"""Real Roslyn semantics, unsaved snapshots, scope, definitions and safe editor edits."""
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cytools_core import CyToolError
from cydec import service, workspace, process
from cydec.engines.base import EngineContext
from cydec.project import ProjectStore


@pytest.fixture
def source(tmp_path, monkeypatch):
    ctx = EngineContext(workdir=tmp_path / 'jobs')
    sdk = workspace.dotnet_sdk(ctx)
    _, out, _ = process.run([sdk, '--version'], context=ctx)
    version = int(out.split('.')[0])
    root = tmp_path / 'source'
    root.mkdir()
    (root / 'Demo.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net%d.0</TargetFramework>'
        '<ImplicitUsings>enable</ImplicitUsings></PropertyGroup></Project>' % version, encoding='utf-8')
    (root / 'Counter.cs').write_text('namespace Demo;\npublic class Counter {\n public int Add(int value) => value+1;\n'
        ' private int Secret() => 7;\n public static int Shared() => 1;\n}', encoding='utf-8')
    (root / 'Program.cs').write_text('using Demo; class Program { void M() { var counter=new Counter(); counter.Ad } }', encoding='utf-8')
    monkeypatch.setattr(service, 'store', ProjectStore(tmp_path / 'projects'))
    project, _ = service.store.open(Path(__file__).resolve().parent / 'fixtures/native/funcs_x64_o2.dll')
    service.workspace_open(project.id, str(root))
    return project, root, ctx


def request(source, text, marker, action='complete', extra=()):
    project, _, ctx = source
    position = text.index(marker) + len(marker)
    line = text[:position].count('\n') + 1
    column = len(text[:position].rsplit('\n', 1)[-1]) + 1
    return service.workspace_csharp(project.id, 'Program.cs', action, ctx, line, column,
        [{'path': 'Program.cs', 'text': text}, *extra])


def test_member_completion_scope_and_unicode_edit(source):
    _, root, _ = source
    before = hashlib.sha256((root / 'Program.cs').read_bytes()).hexdigest()
    text = 'using Demo; class Program { void M() { string emoji="😀"; var counter=new Counter(); counter.Ad } }'
    out = request(source, text, 'counter.Ad')
    assert [i['label'] for i in out['items']] == ['Add']
    edit = out['items'][0]['edit']
    assert text[edit['start']['column']-1:edit['end']['column']-1] == 'Ad'
    assert 'Counter.Add' in out['items'][0]['detail']
    out = request(source, text.replace('counter.Ad', 'counter.'), 'counter.')
    names = [i['label'] for i in out['items']]
    assert 'Add' in names and 'Secret' not in names and 'Shared' not in names
    out = request(source, text.replace('counter.Ad', 'Counter.'), 'Counter.')
    names = [i['label'] for i in out['items']]
    assert 'Shared' in names and 'Add' not in names
    out = request(source, text.replace('counter.Ad', 'emoji.Len'), 'emoji.Len')
    assert [i['label'] for i in out['items']] == ['Length']
    assert hashlib.sha256((root / 'Program.cs').read_bytes()).hexdigest() == before


def test_semantic_rename_references_format_and_name_conflicts(source):
    project, root, ctx = source
    text = 'using Demo; class Other { public int Add()=>1; } class Program { int M()=>new Counter().Add(2)+new Other().Add(); }'
    (root / 'Program.cs').write_text(text, encoding='utf-8')
    at = text.index('Counter().Add') + len('Counter().Ad')
    preview = service.workspace_csharp(project.id, 'Program.cs', 'rename', ctx, column=at+1, new_name='Calculate')
    edits = {e['path']: e['text'] for e in preview['edits']}
    assert set(edits) == {'Program.cs', 'Counter.cs'}
    assert 'Counter().Calculate(2)' in edits['Program.cs'] and 'Other().Add()' in edits['Program.cs']
    assert (root / 'Program.cs').read_text() == text
    assert service.workspace_refactor_check(project.id, preview['sourceRevision'])['valid']
    references = service.workspace_csharp(project.id, 'Program.cs', 'references', ctx, column=at+1)
    assert references['references'][0]['path'] == 'Program.cs'
    formatted = service.workspace_csharp(project.id, 'Program.cs', 'format', ctx)
    assert formatted['edits'] and formatted['edits'][0]['text'] != text
    with pytest.raises(CyToolError, match='identifier'):
        service.workspace_csharp(project.id, 'Program.cs', 'rename', ctx, column=at+1, new_name='invalid name')
    (root / 'Other.cs').write_text('class Changed {}', encoding='utf-8')
    with pytest.raises(CyToolError, match='changed'):
        service.workspace_refactor_check(project.id, preview['sourceRevision'])


def test_refactoring_editor_changes_are_undoable_and_stale_preview_applies_nothing(source):
    from imgui_bundle import imgui, imgui_color_text_edit as ed
    from project_ui import ProjectIDE
    from types import SimpleNamespace
    project, root, ctx = source
    text = 'using Demo; class Program { int M()=>new Counter().Add(2); }'
    (root/'Program.cs').write_text(text, encoding='utf-8')
    at = text.index('Counter().Add')+len('Counter().Ad')
    result = service.workspace_csharp(project.id, 'Program.cs', 'rename', ctx, column=at+1, new_name='Calculate')
    context = imgui.create_context()
    try:
        ide = ProjectIDE(SimpleNamespace(), None, None, None, None)
        ide.debug = SimpleNamespace(active=lambda pid: False)
        tabs = {}
        for path in ('Program.cs', 'Counter.cs'):
            editor = ed.TextEditor(); editor.set_text((root/path).read_text())
            tabs[path] = {'editor':editor, 'saved':editor.get_text(), 'revision':'unchanged'}
        result.update(buffers=ide.csharp_buffers({'tabs':tabs}), configuration='Debug')
        state = {'tabs':tabs, 'configuration':0, 'csharp_rename':result}
        ide.sessions[project.id] = state
        ide.submit = lambda pid, operation, params, done: done(service.workspace_refactor_check(pid, params['revision']))
        ide.apply_refactoring(project.id, 'rename')
        for tab in tabs.values():
            assert 'Calculate' in tab['editor'].get_text() and tab['editor'].can_undo()
            tab['editor'].undo(); assert tab['editor'].get_text()==tab['saved']
        state['csharp_rename']=result
        tabs['Program.cs']['editor'].set_text(text+'// unsaved')
        before = {p:t['editor'].get_text() for p,t in tabs.items()}
        ide.apply_refactoring(project.id, 'rename')
        assert {p:t['editor'].get_text() for p,t in tabs.items()}==before
        assert state['csharp_error']
    finally:
        imgui.destroy_context(context)


def test_evaluated_msbuild_model_honors_imports_configuration_and_compile_items(source):
    project, root, ctx = source
    (root / 'Program.cs').write_text('class Program { int M()=>new Conditional().FromProps(); }', encoding='utf-8')
    (root / 'Excluded.cs').write_text('class BAD { invalid syntax }', encoding='utf-8')
    (root / 'Conditional.cs').write_text('#if FROM_PROPS\nclass Conditional { public int FromProps()=>3; }\n#endif', encoding='utf-8')
    (root / 'Directory.Build.props').write_text('<Project><PropertyGroup Condition="\'$(Configuration)\' == \'Debug\'">'
        '<DefineConstants>FROM_PROPS</DefineConstants></PropertyGroup><ItemGroup><Compile Remove="Excluded.cs" /></ItemGroup></Project>', encoding='utf-8')
    # Remove is applied after the SDK's implicit includes via Directory.Build.targets.
    (root / 'Directory.Build.targets').write_text('<Project><ItemGroup><Compile Remove="Excluded.cs" /></ItemGroup></Project>', encoding='utf-8')
    rc, out, err = process.run([workspace.dotnet_sdk(ctx), 'restore', str(root)], context=ctx)
    assert rc == 0, out + err
    result = service.workspace_evaluate(project.id, ctx)
    assert result['projects'] == 1
    diagnostics = service.workspace_csharp(project.id, 'Program.cs', 'diagnostics', ctx)
    assert not diagnostics['diagnostics'], diagnostics


def test_definition_resolves_unsaved_own_type_not_same_named_method(source):
    _, root, _ = source
    text = 'using Demo; class Other { public void Add() {} } class Program { void M() { new Counter().Add(1); } }'
    counter = '\n\n' + (root / 'Counter.cs').read_text()
    out = request(source, text, 'Counter().Ad', 'definition', [{'path': 'Counter.cs', 'text': counter}])
    assert out['definitions'] == [{'path': 'Counter.cs', 'point': {'line': 5, 'column': 13}}]
    assert 'Add(int value)' in out['symbol']
    out = request(source, 'class Program { void M(){ string s=""; s.Length.ToString(); } }', 's.Leng', 'definition')
    assert out['symbol'] and out['definitions'] == []  # Framework symbols have no source in this project.


def test_diagnostics_and_declarations_use_unsaved_buffers(source):
    project, root, ctx = source
    text = 'class Program { void M() { Console.WriteLine(missingName); } }'
    out = request(source, text, 'missingName', 'diagnostics')
    assert any(i['code'] == 'CS0103' and i['location']['path'] == 'Program.cs' for i in out['diagnostics'])
    assert not any('Console' in i['message'] for i in out['diagnostics'])  # SDK implicit usings/ref pack.
    fixed = text.replace('missingName', '42')
    out = request(source, fixed, '42', 'diagnostics')
    assert out['diagnostics'] == []
    out = service.workspace_csharp(project.id, 'Program.cs', 'symbols', ctx, buffers=[{'path': 'Program.cs', 'text': fixed}])
    assert any(s['name'] == 'Counter' and s['location']['path'] == 'Counter.cs' for s in out['symbols'])
    assert any('Add(int' in s['name'] for s in out['symbols'])
    assert (root / 'Program.cs').read_text() != fixed


def test_cross_project_semantics_without_running_build_targets(source):
    project, root, ctx = source
    library = root / 'Library'
    library.mkdir()
    (library / 'Library.csproj').write_text((root / 'Demo.csproj').read_text().replace('</Project>',
        '<Target Name="NeverRun" BeforeTargets="Build"><Error Text="MUST NOT EXECUTE" /></Target></Project>'), encoding='utf-8')
    (library / 'Library.cs').write_text('namespace Tools; public class Worker { public int Compute(int x)=>x+1; }', encoding='utf-8')
    csproj = root / 'Demo.csproj'
    csproj.write_text(csproj.read_text().replace('</Project>', '<ItemGroup><ProjectReference Include="Library/Library.csproj" /></ItemGroup></Project>'), encoding='utf-8')
    text = 'class Program { void M() { var w=new Tools.Worker(); w.Comp } }'
    out = request(source, text, 'w.Comp')
    assert [i['label'] for i in out['items']] == ['Compute']
    text = text.replace('w.Comp', 'w.Compute(1);')
    out = request(source, text, 'w.Comp', 'definition')
    assert out['definitions'][0]['path'] == 'Library/Library.cs'


def test_excluded_sources_and_escaping_buffers_refused(source):
    project, root, ctx = source
    for path in ('../outside.cs', 'obj/Generated.cs'):
        with pytest.raises(CyToolError, match='relative|reserved'):
            service.workspace_csharp(project.id, 'Program.cs', 'diagnostics', ctx, buffers=[{'path': path, 'text': 'class Escape {}'}])
    csproj = root / 'Demo.csproj'
    csproj.write_text(csproj.read_text().replace('</Project>', '<ItemGroup><Compile Remove="Program.cs" /></ItemGroup></Project>'), encoding='utf-8')
    with pytest.raises(CyToolError, match='excluded'):
        service.workspace_csharp(project.id, 'Program.cs', 'diagnostics', ctx)


def test_csharp_services_through_runtime(source, tmp_path):
    from tool import create_runtime, declared_permissions
    project, _, _ = source
    with create_runtime(tmp_path / 'runtime') as runtime:
        actor = runtime.authenticate(runtime.create_client('csharp-test', declared_permissions(runtime))['token'])
        session = runtime.create_session(actor, temporary=False)['sessionId']
        job = runtime.submit(actor, session, 'workspace_csharp', {'projectId': project.id, 'path': 'Program.cs',
            'action': 'diagnostics', 'buffers': [{'path': 'Program.cs', 'text': 'class Program {}'}]})
        result = runtime.wait(actor, job['jobId'], timeout=60)
        assert result['state'] == 'Completed', result
        assert result['outputs']['diagnostics'] == []


def test_completion_insertion_is_undoable_and_refuses_stale_edits(source):
    from imgui_bundle import imgui, imgui_color_text_edit as ed
    from project_ui import ProjectIDE
    from types import SimpleNamespace
    project, root, _ = source
    text = (root / 'Program.cs').read_text()
    out = request(source, text, 'counter.Ad')
    context = imgui.create_context()
    try:
        editor = ed.TextEditor()
        editor.set_text(text)
        point = text.index('counter.Ad') + len('counter.Ad')
        editor.set_cursor(ed.TextEditor.DocPos(0, point))
        ide = ProjectIDE(SimpleNamespace(), None, None, None, None)
        original = dict(out, buffers=[{'path': 'Program.cs', 'text': text}], configuration='Debug',
                        requestPosition={'line': 0, 'index': point})
        session = {'tabs': {'Program.cs': {'editor': editor, 'saved': text, 'revision': 'original'}},
                   'configuration': 0, 'active': 'Program.cs', 'csharp_completion': original}
        ide.sessions[project.id] = session
        ide.apply_completion(project.id, original['items'][0])
        assert 'counter.Add' in editor.get_text() and editor.can_undo()
        assert session['tabs']['Program.cs']['saved'] == text
        editor.undo()
        assert editor.get_text() == text
        editor.set_text(text + '// new unsaved edit')
        latest = editor.get_text()
        session['csharp_completion'] = original
        ide.apply_completion(project.id, original['items'][0])
        assert editor.get_text() == latest and session['csharp_completion'] is None
        editor.set_text(text)
        editor.set_cursor(ed.TextEditor.DocPos(0, 1))
        session['csharp_completion'] = original
        ide.apply_completion(project.id, original['items'][0])
        assert editor.get_text() == text and session['csharp_completion'] is None
    finally:
        imgui.destroy_context(context)


def test_async_editor_result_does_not_replace_newer_buffer(source):
    from project_ui import ProjectIDE
    from types import SimpleNamespace
    project, _, _ = source
    class Editor:
        text = 'class Program {}'
        def get_text(self):
            return self.text
        def get_main_cursor_position(self):
            return SimpleNamespace(line=0, index=0)
    class Jobs:
        def busy(self, tag):
            return False
        def submit(self, operation, parameters, **options):
            self.done = options['done']
    jobs = Jobs()
    editor = Editor()
    ide = ProjectIDE(SimpleNamespace(jobs=jobs), None, None, None, None)
    session = {'tabs': {'Program.cs': {'editor': editor}}, 'configuration': 0,
               'active': 'Program.cs', 'csharp_diagnostics': None}
    ide.sessions[project.id] = session
    ide.csharp_request(project.id, 'diagnostics')
    editor.text = 'class Program { int newer; }'
    jobs.done({'notes': [], 'diagnostics': [{'code': 'old diagnostic'}]})
    assert session['csharp_diagnostics'] is None
