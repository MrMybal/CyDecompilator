"""Reconstructed project builds, editor concurrency, and real compiled PE patches."""
import ctypes
import hashlib
import json
import os
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from cytools_core import CyToolError
from cydec import patching, service, workspace
from cydec.engines.base import EngineContext
from cydec.project import ProjectStore

FIXTURE = APP / 'tests/fixtures/native/funcs_x64_o2.dll'


@pytest.fixture
def project(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path / 'projects')
    monkeypatch.setattr(service, 'store', store)
    project, _ = store.open(FIXTURE)
    return project


@pytest.fixture
def ctx(tmp_path):
    return EngineContext(workdir=tmp_path / 'work', options={'symbols': False})


def test_source_edit_conflicts_and_confinement(project, tmp_path):
    folder = tmp_path / 'source'
    folder.mkdir()
    (folder / 'Example.csproj').write_text('<Project/>', encoding='utf-8')
    (folder / 'Program.cs').write_text('class Program {}\n', encoding='utf-8')
    assert service.workspace_open(project.id, str(folder))['kind'] == 'dotnet'
    read = service.workspace_read(project.id, 'Program.cs')
    saved = service.workspace_save(project.id, read['path'], 'class Updated {}\n', read['revision'])
    assert saved['revision'] != read['revision']
    with pytest.raises(CyToolError, match='changed on disk'):
        service.workspace_save(project.id, read['path'], read['text'], read['revision'])
    with pytest.raises(CyToolError):
        service.workspace_read(project.id, '../outside.cs')
    with pytest.raises(CyToolError):
        service.workspace_save(project.id, str(tmp_path / 'outside.cs'), '', '')
    with pytest.raises(CyToolError):
        service.workspace_save(project.id, 'build/output.cs', '', '')
    (folder / 'binary.txt').write_bytes(b'\0\x01')
    with pytest.raises(CyToolError, match='binary file'):
        service.workspace_read(project.id, 'binary.txt')
    service.workspace_save(project.id, 'src/New.cs', 'class New {}', '')
    assert 'src/New.cs' in [row['path'] for row in service.workspace_info(project.id)['files']]
    bom_source = folder / 'Bom.cs'
    bom_source.write_bytes(b'\xef\xbb\xbfclass First {}\r\n')
    read = service.workspace_read(project.id, 'Bom.cs')
    assert read['text'] == 'class First {}\n'
    service.workspace_save(project.id, 'Bom.cs', 'class Second {}\n', read['revision'])
    assert bom_source.read_bytes() == b'\xef\xbb\xbfclass Second {}\r\n'


def test_source_links_cannot_escape(project, tmp_path):
    folder = tmp_path / 'source'
    folder.mkdir()
    (folder / 'CMakeLists.txt').write_text('project(test)', encoding='utf-8')
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        (folder / 'linked').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Symlink creation is unavailable')
    service.workspace_open(project.id, str(folder))
    with pytest.raises(CyToolError):
        service.workspace_save(project.id, 'linked/outside.c', 'escaped', '')
    assert not (outside / 'outside.c').exists()


def test_native_solution_build(project, ctx):
    out = service.workspace_create(project.id, functions=['add3'], context=ctx)
    root = Path(out['directory'])
    assert out['kind'] == 'native'
    assert (root / 'CMakeLists.txt').is_file()
    project_xml = ET.parse(root / out['entry'])
    guid = project_xml.find('.//{*}ProjectGuid').text
    assert guid in (root / (out['name'] + '.sln')).read_text(encoding='utf-8')
    if os.name == 'nt' and workspace.visual_studio_tool('MSBuild/Current/Bin/MSBuild.exe'):
        result = service.workspace_execute(project.id, 'build', ctx)
        assert result['status'] == 'passed', result['output']
        assert list((root / 'build').rglob('*.lib'))
    with pytest.raises(CyToolError, match='already attached'):
        service.workspace_create(project.id, context=ctx)


def test_create_never_overwrites_existing_folder(project, ctx, tmp_path):
    root = tmp_path / 'existing'
    root.mkdir()
    (root / 'keep.txt').write_text('user source', encoding='utf-8')
    with pytest.raises(CyToolError, match='new folder'):
        service.workspace_create(project.id, str(root), context=ctx)
    assert (root / 'keep.txt').read_text() == 'user source'


def test_build_failure_has_diagnostics(project, tmp_path, ctx, monkeypatch):
    folder = tmp_path / 'source'
    folder.mkdir()
    (folder / 'Example.csproj').write_text('<Project/>', encoding='utf-8')
    service.workspace_open(project.id, str(folder))
    monkeypatch.setattr(workspace, 'dotnet_sdk', lambda context: 'dotnet')
    calls = []

    def run(command, **kw):
        calls.append(command)
        return 1, str(folder / 'Program.cs') + '(4,9): error CS1002: ; expected', ''
    monkeypatch.setattr(workspace.process, 'run', run)
    result = service.workspace_execute(project.id, 'build', ctx)
    assert result['status'] == 'failed'
    assert result['diagnostics'][0]['line'] == 4 and result['diagnostics'][0]['column'] == 9
    assert calls[0][1] == 'build'


def test_no_tests_is_not_a_pass(project, tmp_path, ctx, monkeypatch):
    folder = tmp_path / 'source'
    folder.mkdir()
    (folder / 'Example.csproj').write_text('<Project/>', encoding='utf-8')
    service.workspace_open(project.id, str(folder))
    monkeypatch.setattr(workspace, 'dotnet_sdk', lambda context: 'dotnet')
    monkeypatch.setattr(workspace.process, 'run', lambda *args, **kw: (0, 'Build succeeded.', ''))
    assert service.workspace_execute(project.id, 'test', ctx)['status'] == 'no-tests'
    monkeypatch.setattr(workspace.process, 'run', lambda *args, **kw: (1, 'Compilation failed before tests', ''))
    assert service.workspace_execute(project.id, 'test', ctx)['status'] == 'failed'


def test_dotnet_build_and_run(project, tmp_path, ctx):
    try:
        exe = workspace.dotnet_sdk(ctx)
    except CyToolError:
        pytest.skip('No .NET SDK installed')
    from cydec import process
    folder = tmp_path / 'source'
    result = process.run([exe, 'new', 'console', '-o', str(folder), '--no-restore'], context=ctx, timeout=120)
    assert result[0] == 0, result
    service.workspace_open(project.id, str(folder))
    result = service.workspace_execute(project.id, 'build', ctx)
    assert result['status'] == 'passed', result['output']
    result = service.workspace_execute(project.id, 'run', ctx)
    assert result['status'] == 'passed' and 'Hello, World!' in result['output']


def test_dotnet_decompile_edit_rebuild_roundtrip(tmp_path, ctx, monkeypatch):
    from cydec import components, process
    if not components.locate('ilspycmd'):
        pytest.skip('ILSpy not installed')
    try:
        dotnet = workspace.dotnet_sdk(ctx)
    except CyToolError:
        pytest.skip('No .NET SDK installed')
    original = tmp_path / 'original'
    status, out, err = process.run([dotnet, 'new', 'console', '-o', str(original), '--no-restore'], context=ctx)
    assert status == 0, out + err
    (original / 'Program.cs').write_text('using System; class Program { static int Value() => 7; '
                                        'static void Main() { Console.WriteLine(Value()); } }', encoding='utf-8')
    status, out, err = process.run([dotnet, 'build', str(original), '-o', str(tmp_path / 'compiled')], context=ctx)
    assert status == 0, out + err
    store = ProjectStore(tmp_path / 'projects')
    monkeypatch.setattr(service, 'store', store)
    project, _ = store.open(tmp_path / 'compiled/original.dll')
    exported = service.workspace_create(project.id, context=ctx)
    assert exported['kind'] == 'dotnet'
    paths = [f['path'] for f in exported['files'] if f['path'].endswith('.cs')]
    changed = False
    for path in paths:
        file = service.workspace_read(project.id, path)
        if 'return 7;' in file['text']:
            service.workspace_save(project.id, path, file['text'].replace('return 7;', 'return 42;'), file['revision'])
            changed = True
    assert changed, paths
    result = service.workspace_execute(project.id, 'build', ctx)
    assert result['status'] == 'passed', result['output']
    result = service.workspace_execute(project.id, 'run', ctx)
    assert result['status'] == 'passed' and '42' in result['output'], result['output']
    method = next(m for m in service.managed_methods(project.id, ctx)['methods'] if m['name'] == 'Value')
    plan = service.managed_patch_prepare(project.id, method['id'], ctx, build=False)
    receipt = service.patch_apply(project.id, plan['planId'], context=ctx)
    status, out, err = process.run([dotnet, receipt['path']], context=ctx)
    assert status == 0 and out.strip() == '42', out + err


def test_native_test_harness(project, ctx):
    out = service.workspace_create(project.id, functions=['add3'], context=ctx)
    root = Path(out['directory'])
    if not (workspace.visual_studio_tool('Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe')
            or __import__('shutil').which('cmake')):
        pytest.skip('No CMake installed')
    service.workspace_save(project.id, 'tests/check.c', 'extern long long add3(long long, long long, long long);\n'
                           'int main(void) { return add3(1, 2, 3) != 0; }\n', '')
    file = service.workspace_read(project.id, 'CMakeLists.txt')
    service.workspace_save(project.id, file['path'], file['text'] +
                           'add_executable(check tests/check.c)\ntarget_link_libraries(check recovered)\n'
                           'add_test(NAME arithmetic COMMAND check)\n', file['revision'])
    result = service.workspace_execute(project.id, 'test', ctx)
    assert result['status'] == 'passed', result['output']
    assert '100% tests passed' in result['output']


def test_solution_build_and_startup_project(project, tmp_path, ctx):
    from cydec import process
    sdk = workspace.dotnet_sdk(ctx)
    root = tmp_path / 'solution'
    root.mkdir()
    for template, name in [('classlib', 'Library'), ('console', 'Runner')]:
        rc, out, err = process.run([sdk, 'new', template, '-o', str(root / name), '--no-restore'], context=ctx)
        assert rc == 0, out + err
    rc, out, err = process.run([sdk, 'new', 'sln', '-n', 'Demo', '-o', str(root)], context=ctx)
    assert rc == 0, out + err
    entry = next(iter([*root.glob('*.sln'), *root.glob('*.slnx')]))
    rc, out, err = process.run([sdk, 'sln', str(entry), 'add', str(root / 'Library/Library.csproj'),
                              str(root / 'Runner/Runner.csproj')], context=ctx)
    assert rc == 0, out + err
    out = service.workspace_open(project.id, str(root))
    assert out['entry'] == entry.name and len(out['projects']) == 2
    built = service.workspace_execute(project.id, 'build', ctx)
    assert built['status'] == 'passed', built['output']
    with pytest.raises(CyToolError, match='startup'):
        service.workspace_execute(project.id, 'run', ctx)
    ran = service.workspace_execute(project.id, 'run', ctx, target_project='Runner/Runner.csproj')
    assert ran['status'] == 'passed' and 'Hello, World!' in ran['output']
    with pytest.raises(CyToolError):
        service.workspace_execute(project.id, 'build', ctx, target_project='../outside.csproj')


def test_real_native_patch_preserves_original_and_changes_execution(project, ctx, tmp_path):
    service.analyze(project.id, 'cdec', ctx)
    original = project.binary.read_bytes()
    source = 'int add3(int a, int b, int c) { return a + b * c; }'
    plan = service.patch_prepare(project.id, 'add3', source, 'add3', ctx, 'cdec')
    assert plan['size'] <= plan['capacity'] and plan['disassembly']
    result = service.patch_apply(project.id, plan['planId'], str(tmp_path / 'patched.dll'), ctx)
    assert result['launchKind'] == 'library'
    with pytest.raises(CyToolError, match='library'):
        service.patch_run(project.id, result['receiptId'], ctx)
    patched = Path(result['path']).read_bytes()
    assert project.binary.read_bytes() == original
    assert hashlib.sha256(patched).hexdigest() == result['sha256']
    offset, capacity = plan['offset'], plan['capacity']
    # Only the chosen function and PE checksum may differ.
    import pefile
    check = pefile.PE(data=original).OPTIONAL_HEADER.get_field_absolute_offset('CheckSum')
    differences = [i for i, pair in enumerate(zip(original, patched)) if pair[0] != pair[1]]
    assert all(offset <= i < offset + capacity or check <= i < check + 4 for i in differences)
    if os.name == 'nt':
        old, new = ctypes.CDLL(str(project.binary)), ctypes.CDLL(str(result['path']))
        for dll, expected in ((old, 1 + 2 * 3 - 7), (new, 1 + 2 * 3)):
            dll.add3.argtypes = [ctypes.c_int] * 3
            dll.add3.restype = ctypes.c_int
            assert dll.add3(1, 2, 3) == expected
        # Explicitly release DLL handles so pytest can remove the temporary workspace.
        import _ctypes
        _ctypes.FreeLibrary(old._handle)
        _ctypes.FreeLibrary(new._handle)
    with pytest.raises(CyToolError, match='already exists'):
        service.patch_apply(project.id, plan['planId'], result['path'], ctx)
    with pytest.raises(CyToolError, match='original'):
        service.patch_apply(project.id, plan['planId'], str(project.binary), ctx)


def test_patch_rejects_external_references_and_tampering(project, ctx):
    service.analyze(project.id, 'cdec', ctx)
    with pytest.raises(CyToolError, match='relocation'):
        service.patch_prepare(project.id, 'add3', 'extern int other(int); int add3(int a) { return other(a); }', 'add3', ctx)
    plan = service.patch_prepare(project.id, 'add3', 'int add3(int a, int b, int c) { return 42; }', 'add3', ctx)
    path = project.dir / 'patches/plans' / (plan['planId'] + '.json')
    plan['replacementBytes'] = 'c3'
    path.write_text(json.dumps(plan), encoding='utf-8')
    with pytest.raises(CyToolError, match='changed'):
        service.patch_apply(project.id, plan['planId'], context=ctx)


@pytest.mark.parametrize('filename', ['funcs_x64_o2.dll', 'funcs_x64_od.dll', 'funcs_x86_o2.dll'])
def test_extended_native_patch_calls_original_and_links_unwind_aslr(tmp_path, ctx, monkeypatch, filename):
    store = ProjectStore(tmp_path / 'projects')
    monkeypatch.setattr(service, 'store', store)
    project, _ = store.open(APP / 'tests/fixtures/native' / filename)
    service.analyze(project.id, 'cdec', ctx)
    before = project.binary.read_bytes()
    source = ('extern int mul_add(int,int,int); '
              '__attribute__((noinline)) static int helper(int a){ volatile int local[10]; local[0]=a; return local[0]+20; } '
              'static volatile int extra=5; static volatile int * volatile pointer=&extra; '
              'int add3(int a,int b,int c){ return mul_add(a,b,c)+helper(a)+*pointer; }')
    # Use an original exported function with a known ABI as the external call target.
    original_name = next(f['name'] for f in project.functions('cdec') if f['name'] == 'add3')
    functions = [f for f in project.functions('cdec') if f.get('exported') and f['name'] != original_name]
    # The original add3 is intentionally not bound to avoid recursion. Use our
    # existing three-argument fixture's exported arithmetic function, when available.
    extern = next((f for f in functions if f['name'] == 'mul_add'), None)
    if extern is None:
        # Replace external call with original one-argument sum_to, preserving its ABI.
        source = source.replace('extern int mul_add(int,int,int);', 'extern int sum_to(int);').replace('mul_add(a,b,c)', 'sum_to(a)')
    plan = service.patch_prepare(project.id, 'add3', source, 'add3', ctx, 'cdec', extended=True)
    assert plan['kind'] == 'native-linked' and plan['loaderRelocations'] >= 1
    if 'x64' in filename:
        assert plan['unwindEntries'] > 0
    receipt = service.patch_apply(project.id, plan['planId'], context=ctx)
    assert project.binary.read_bytes() == before
    import pefile
    modified = pefile.PE(receipt['path'])
    modified.parse_data_directories()
    assert modified.sections[-1].Name.startswith(b'.cydec')
    if 'x64' in filename and os.name == 'nt':
        old, new = ctypes.CDLL(str(project.binary)), ctypes.CDLL(receipt['path'])
        try:
            new.add3.argtypes = [ctypes.c_int] * 3
            new.add3.restype = ctypes.c_int
            if extern:
                old.mul_add.argtypes = [ctypes.c_int] * 3
                expected = old.mul_add(3, 2, 1)+3+20+5
            else:
                old.sum_to.argtypes = [ctypes.c_int]
                expected = old.sum_to(3)+3+20+5
            assert new.add3(3, 2, 1) == expected
            image_base = ctypes.c_ulonglong()
            lookup = ctypes.windll.kernel32.RtlLookupFunctionEntry
            lookup.argtypes = [ctypes.c_ulonglong, ctypes.POINTER(ctypes.c_ulonglong), ctypes.c_void_p]
            lookup.restype = ctypes.c_void_p
            assert lookup(new._handle + plan['replacementRva'], ctypes.byref(image_base), None)
            assert image_base.value == new._handle
        finally:
            import _ctypes
            _ctypes.FreeLibrary(old._handle)
            _ctypes.FreeLibrary(new._handle)
    if 'x86' in filename:
        import faulthandler
        # Unicorn handles Windows guard-page exceptions itself; Python's handler
        # would print a false fatal-exception banner before native code handles it.
        handler = faulthandler.is_enabled()
        faulthandler.disable()
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
        from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EAX
        import struct
        emu = Uc(UC_ARCH_X86, UC_MODE_32)
        image_base = modified.OPTIONAL_HEADER.ImageBase
        emu.mem_map(image_base, (modified.OPTIONAL_HEADER.SizeOfImage+0xfff)&~0xfff)
        emu.mem_write(image_base, modified.get_memory_mapped_image())
        stack, stop = 0x70000000, 0x71000000
        emu.mem_map(stack, 0x10000); emu.mem_map(stop, 0x1000)
        emu.mem_write(stack+0x8000, struct.pack('<IIII', stop, 3, 2, 1))
        emu.reg_write(UC_X86_REG_ESP, stack+0x8000)
        export = next(e for e in modified.DIRECTORY_ENTRY_EXPORT.symbols if e.name == b'add3')
        emu.emu_start(image_base+export.address, stop, count=100000)
        assert emu.reg_read(UC_X86_REG_EAX) == 6+3+20+5
        if handler:
            faulthandler.enable()


def test_extended_native_import_call_and_tampering(project, ctx, tmp_path):
    service.analyze(project.id, 'cdec', ctx)
    source = ('extern __declspec(dllimport) unsigned long __stdcall GetCurrentProcessId(void); '
              'int add3(int a,int b,int c){return (int)GetCurrentProcessId()+a+b+c;}')
    plan = service.patch_prepare(project.id, 'add3', source, 'add3', ctx, 'cdec', extended=True)
    receipt = service.patch_apply(project.id, plan['planId'], context=ctx)
    if os.name == 'nt':
        dll = ctypes.CDLL(receipt['path'])
        try:
            dll.add3.argtypes = [ctypes.c_int] * 3
            dll.add3.restype = ctypes.c_int
            assert dll.add3(1, 2, 3) == os.getpid()+6
        finally:
            import _ctypes
            _ctypes.FreeLibrary(dll._handle)
    candidate = project.dir / 'patches/native' / plan['planId'] / 'candidate.bin'
    candidate.write_bytes(candidate.read_bytes()+b'tamper')
    with pytest.raises(CyToolError, match='changed'):
        service.patch_apply(project.id, plan['planId'], str(tmp_path/'other.dll'), ctx)
    with pytest.raises(CyToolError, match='Unresolved'):
        service.patch_prepare(project.id, 'add3', 'extern int Unknown(); int add3(){return Unknown();}', 'add3', ctx, extended=True)


def test_x86_patch_and_unwind_refusal(tmp_path, ctx, monkeypatch):
    store = ProjectStore(tmp_path / 'projects')
    monkeypatch.setattr(service, 'store', store)
    x86_project, _ = store.open(APP / 'tests/fixtures/native/funcs_x86_o2.dll')
    service.analyze(x86_project.id, 'cdec', ctx)
    plan = service.patch_prepare(x86_project.id, 'add3', 'int add3(int a,int b,int c){return 42;}', 'add3', ctx)
    assert plan['bits'] == 32 and plan['size'] <= plan['capacity']
    result = service.patch_apply(x86_project.id, plan['planId'], context=ctx)
    assert Path(result['path']).is_file()
    debug_project, _ = store.open(APP / 'tests/fixtures/native/funcs_x64_od.dll')
    service.analyze(debug_project.id, 'cdec', ctx)
    with pytest.raises(CyToolError, match='unwind metadata'):
        service.patch_prepare(debug_project.id, 'sum_to', 'int sum_to(int a){return 42;}', 'sum_to', ctx)


def test_workspace_operations_through_runtime(project, tmp_path):
    from tool import create_runtime, declared_permissions
    folder = tmp_path / 'source'
    folder.mkdir()
    (folder / 'Example.csproj').write_text('<Project/>', encoding='utf-8')
    with create_runtime(tmp_path / 'jobs') as runtime:
        actor = runtime.authenticate(runtime.create_client('ide-test', declared_permissions(runtime))['token'])
        session = runtime.create_session(actor, temporary=False)['sessionId']
        def invoke(operation, parameters):
            job = runtime.submit(actor, session, operation, dict(parameters, projectId=project.id))
            result = runtime.wait(actor, job['jobId'], timeout=30)
            assert result['state'] == 'Completed', result
            return result['outputs']
        assert invoke('workspace_open', {'directory': str(folder)})['kind'] == 'dotnet'
        out = invoke('workspace_save', {'path': 'Example.cs', 'text': 'class Example {}', 'revision': ''})
        assert invoke('workspace_read', {'path': 'Example.cs'})['revision'] == out['revision']
        assert invoke('workspace_info', {})['available']
        assert invoke('workspace_search', {'query': 'Example', 'wholeWord': True})['matches'][0]['path'] == 'Example.cs'


def test_source_search_coordinates_filters_and_limits(project, tmp_path, ctx):
    root = tmp_path / 'search-source'
    root.mkdir()
    (root / 'Example.csproj').write_text('<Project/>', encoding='utf-8')
    (root / 'Example.cs').write_bytes('  Value(); ValueOther(); value();\r\n  éValue();\r\n  // a+b literal\r\n'.encode())
    (root / 'bad.txt').write_bytes(b'\x00Value')
    (root / 'invalid.txt').write_bytes(b'\xffValue')
    (root / 'large.txt').write_bytes(b'V' * (workspace.TEXT_LIMIT + 1))
    (root / 'obj').mkdir()
    (root / 'obj/generated.cs').write_text('Value();', encoding='utf-8')
    service.workspace_open(project.id, str(root))
    out = service.workspace_search(project.id, 'Value', ctx, whole_word=True)
    assert [(m['path'], m['line'], m['column']) for m in out['matches']] == [('Example.cs', 1, 3), ('Example.cs', 1, 26)]
    assert set(out['skippedFiles']) == {'bad.txt', 'invalid.txt', 'large.txt'}
    assert not out['truncated']
    out = service.workspace_search(project.id, 'Value', ctx, case_sensitive=True, whole_word=True)
    assert len(out['matches']) == 1
    assert service.workspace_search(project.id, 'a+b', ctx)['matches'][0]['line'] == 3
    out = service.workspace_search(project.id, 'Value', ctx, limit=1)
    assert len(out['matches']) == 1 and out['truncated']
    for query in ('', 'multi\nline', 'x'*257):
        with pytest.raises(CyToolError, match='single-line'):
            service.workspace_search(project.id, query, ctx)
    with pytest.raises(CyToolError, match='limit'):
        service.workspace_search(project.id, 'Value', ctx, limit=0)


def test_search_cancellation(project, tmp_path):
    from cydec.engines.base import EngineContext
    root = tmp_path / 'search-cancel'
    root.mkdir()
    (root / 'Example.csproj').write_text('<Project/>', encoding='utf-8')
    service.workspace_open(project.id, str(root))
    class Token:
        def check(self):
            raise CyToolError('Cancelled', 'Cancelled')
    with pytest.raises(CyToolError, match='Cancelled'):
        service.workspace_search(project.id, 'Value', EngineContext(cancellation=Token()))


def test_editor_reload_preserves_edits_made_during_read(project, tmp_path):
    from project_ui import ProjectIDE
    from types import SimpleNamespace
    class Editor:
        def __init__(self, text=''):
            self.text = text
        def get_text(self):
            return self.text
        def set_text(self, text):
            self.text = text
    class Jobs:
        def submit(self, operation, parameters, **options):
            self.done = options['done']
            return 'reload'
    jobs = Jobs()
    ide = ProjectIDE(SimpleNamespace(jobs=jobs), None, None, None, None)
    tab = {'editor': Editor('unsaved'), 'saved': 'old', 'revision': 'old'}
    state = {'tabs': {'Program.cs': tab}, 'output': Editor(), 'result': {}, 'output_busy': False}
    ide.sessions[project.id] = state
    ide.reload_file(project.id, 'Program.cs')
    tab['editor'].set_text('new edit while reading')
    jobs.done({'text': 'disk content', 'revision': 'disk-revision'})
    assert tab['editor'].get_text() == 'new edit while reading' and tab['revision'] == 'old'
    assert state['result']['status'] == 'failed'
    ide.reload_file(project.id, 'Program.cs')
    jobs.done({'text': 'disk content', 'revision': 'disk-revision'})
    assert tab['editor'].get_text() == tab['saved'] == 'disk content'
    assert tab['revision'] == 'disk-revision'


@pytest.mark.parametrize('hexcode', ['4883ec08c3', '48b80000000000000000ffe0', '8b0500000000c3', 'e900100000c3'])
def test_patch_rejects_stack_frames_and_unbound_references(hexcode):
    with pytest.raises(CyToolError):
        patching.validate_code(bytes.fromhex(hexcode), 64)
