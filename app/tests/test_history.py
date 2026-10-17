"""Real local Git history, exact-byte restores and user-repository isolation."""
import hashlib
import shutil
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from cytools_core import CyToolError
from cydec import history, process, service
from cydec.engines.base import EngineContext
from cydec.project import ProjectStore


@pytest.fixture
def sample(tmp_path, monkeypatch):
    if not shutil.which('git'):
        pytest.skip('Git is required')
    store = ProjectStore(tmp_path / 'projects')
    monkeypatch.setattr(service, 'store', store)
    project, _ = store.open(APP / 'tests/fixtures/native/funcs_x64_o2.dll')
    root = tmp_path / 'source'
    root.mkdir()
    (root / 'Sample.csproj').write_text('<Project/>', encoding='utf-8')
    (root / 'Program.cs').write_bytes(b'\xef\xbb\xbfclass First {}\r\n')
    (root / 'references').mkdir()
    (root / 'references/library.dll').write_bytes(bytes(range(256)))
    (root / 'bin').mkdir()
    (root / 'bin/generated.dll').write_bytes(b'ignore output')
    service.workspace_open(project.id, str(root))
    ctx = EngineContext(workdir=tmp_path / 'jobs')
    return project, root, ctx


def test_git_versions_diff_restore_and_recover_unsaved_disk_version(sample):
    project, root, ctx = sample
    initial = service.workspace_history(project.id, 'status', ctx)
    assert initial['head'] == '' and initial['commits'] == []
    first = service.workspace_history(project.id, 'snapshot', ctx, 'Version initiale')
    assert first['created'] and not first['dirty']
    original = (root / 'Program.cs').read_bytes()
    (root / 'Program.cs').write_text('class Second {}\n', encoding='utf-8')
    (root / 'New.cs').write_text('class New {}', encoding='utf-8')
    (root / 'references/library.dll').write_bytes(b'\0changed')
    preview = service.workspace_history(project.id, 'compare', ctx, commit=first['commit'])
    changes = {row['path']: row for row in preview['changes']}
    assert '+class Second' in changes['Program.cs']['diff']
    assert changes['New.cs']['kind'] == 'added'
    assert changes['references/library.dll']['binary']
    assert 'bin/generated.dll' not in changes
    restored = service.workspace_history(project.id, 'restore', ctx, commit=first['commit'], revision=preview['revision'])
    assert (root / 'Program.cs').read_bytes() == original
    assert not (root / 'New.cs').exists()
    assert (root / 'references/library.dll').read_bytes() == bytes(range(256))
    assert (root / 'bin/generated.dll').read_bytes() == b'ignore output'
    assert restored['backupCommit'] != first['commit'] and len(restored['commits']) == 3
    back = service.workspace_history(project.id, 'compare', ctx, commit=restored['backupCommit'])
    service.workspace_history(project.id, 'restore', ctx, commit=restored['backupCommit'], revision=back['revision'])
    assert (root / 'New.cs').read_text() == 'class New {}'
    assert (root / 'references/library.dll').read_bytes() == b'\0changed'
    again = service.workspace_history(project.id, 'snapshot', ctx, 'No duplicate')
    assert not again['created']


def test_history_ignores_user_git_config_index_hooks_and_attributes(sample, monkeypatch):
    project, root, ctx = sample
    git = shutil.which('git')
    assert process.run([git, 'init', str(root)], context=ctx)[0] == 0
    (root / '.gitignore').write_text('Program.cs\nreferences/\n', encoding='utf-8')
    (root / '.gitattributes').write_text('* text eol=lf\nProgram.cs export-ignore\n', encoding='utf-8')
    assert process.run([git, '-C', str(root), 'add', 'Sample.csproj'], context=ctx)[0] == 0
    index = (root / '.git/index').read_bytes()
    config = (root / '.git/config').read_bytes()
    hook = root / '.git/hooks/post-commit'
    hook.write_text('#!/bin/sh\ntouch SHOULD_NOT_EXIST\n', encoding='utf-8')
    hook.chmod(0o755)
    monkeypatch.setenv('GIT_DIR', str(root / '.git'))
    monkeypatch.setenv('GIT_INDEX_FILE', str(root / '.git/index'))
    monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
    monkeypatch.setenv('GIT_CONFIG_KEY_0', 'core.hooksPath')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', str(root / '.git/hooks'))
    first = service.workspace_history(project.id, 'snapshot', ctx, 'Exact bytes')
    (root / 'Program.cs').write_bytes(b'changed\n')
    preview = service.workspace_history(project.id, 'compare', ctx, commit=first['commit'])
    service.workspace_history(project.id, 'restore', ctx, commit=first['commit'], revision=preview['revision'])
    assert (root / 'Program.cs').read_bytes() == b'\xef\xbb\xbfclass First {}\r\n'
    assert (root / '.git/index').read_bytes() == index
    assert (root / '.git/config').read_bytes() == config
    assert not (root / 'SHOULD_NOT_EXIST').exists()


def test_stale_preview_and_foreign_workspace_commit_refused(sample, tmp_path):
    project, root, ctx = sample
    first = service.workspace_history(project.id, 'snapshot', ctx, 'First')
    preview = service.workspace_history(project.id, 'compare', ctx, commit=first['commit'])
    (root / 'Program.cs').write_bytes(b'external edit')
    with pytest.raises(CyToolError, match='changed since'):
        service.workspace_history(project.id, 'restore', ctx, commit=first['commit'], revision=preview['revision'])
    assert (root / 'Program.cs').read_bytes() == b'external edit'
    other = tmp_path / 'other'
    other.mkdir()
    (other / 'Other.csproj').write_text('<Project/>')
    service.workspace_open(project.id, str(other))
    assert not service.workspace_history(project.id, 'status', ctx)['commits']
    with pytest.raises(CyToolError, match='not found'):
        service.workspace_history(project.id, 'compare', ctx, commit=first['commit'])
    service.workspace_open(project.id, str(root))
    assert service.workspace_history(project.id, 'status', ctx)['head'] == first['commit']
    with pytest.raises(CyToolError):
        service.workspace_history(project.id, 'compare', ctx, commit='HEAD~1')


def test_restore_protects_original_and_receipt_links_saved_sources(sample):
    from cydec.execution import save_receipt
    from cydec.managed_patching import source_stamp
    project, root, ctx = sample
    first = service.workspace_history(project.id, 'snapshot', ctx, 'Sources')
    copied = root.parent / 'copy.dll'
    copied.write_bytes(project.binary.read_bytes())
    receipt = save_receipt(project, {'projectId': project.id, 'path': str(copied),
                                    'sha256': hashlib.sha256(copied.read_bytes()).hexdigest(),
                                    'sourceDirectory': str(root), 'sourceRevision': source_stamp(root)})
    assert receipt['sourceCommit'] == first['commit']
    (root / 'Program.cs').write_bytes(b'changed')
    assert not history.matching_commit(project, str(root), source_stamp(root))
    original = root / 'original.dll'
    original.write_bytes(b'first original')
    version = service.workspace_history(project.id, 'snapshot', ctx, 'With original')
    original.write_bytes(b'second original')
    metadata = project.meta()
    metadata['sourcePath'] = str(original)
    from cydec.paths import write_json
    write_json(project.dir / 'project.json', metadata)
    preview = service.workspace_history(project.id, 'compare', ctx, commit=version['commit'])
    with pytest.raises(CyToolError, match='original application'):
        service.workspace_history(project.id, 'restore', ctx, commit=version['commit'], revision=preview['revision'])
    assert original.read_bytes() == b'second original'


def test_cancel_and_unsupported_snapshot_keep_sources(sample):
    project, root, ctx = sample
    first = service.workspace_history(project.id, 'snapshot', ctx, 'First')
    (root / 'huge.bin').write_bytes(b'large')
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(history, 'MAX_FILE', 2)
        with pytest.raises(CyToolError, match='32 MiB'):
            service.workspace_history(project.id, 'snapshot', ctx, 'Too large')
    with pytest.MonkeyPatch.context() as patch:
        def cancel():
            raise CyToolError('Cancelled', 'cancelled')
        patch.setattr(ctx, 'check', cancel)
        with pytest.raises(CyToolError, match='cancelled'):
            service.workspace_history(project.id, 'restore', ctx, commit=first['commit'], revision=first['revision'])
    assert (root / 'huge.bin').read_bytes() == b'large'


def test_write_failure_rolls_back_with_git_backup(sample, monkeypatch):
    project, root, ctx = sample
    first = service.workspace_history(project.id, 'snapshot', ctx, 'First')
    (root / 'Program.cs').write_bytes(b'newer program')
    (root / 'Sample.csproj').write_bytes(b'newer project')
    preview = service.workspace_history(project.id, 'compare', ctx, commit=first['commit'])
    replace = history.os.replace
    failed = [False]
    def fail_one(source, destination):
        if Path(destination) == root / 'Sample.csproj' and not failed[0]:
            failed[0] = True
            raise OSError('Simulated disk write failure')
        return replace(source, destination)
    monkeypatch.setattr(history.os, 'replace', fail_one)
    with pytest.raises(OSError, match='Simulated'):
        service.workspace_history(project.id, 'restore', ctx, commit=first['commit'], revision=preview['revision'])
    assert (root / 'Program.cs').read_bytes() == b'newer program'
    assert (root / 'Sample.csproj').read_bytes() == b'newer project'
    state = service.workspace_history(project.id, 'status', ctx)
    assert len(state['commits']) == 2 and not state['dirty']


def test_history_through_runtime(sample, tmp_path):
    from tool import create_runtime, declared_permissions
    project, _, _ = sample
    with create_runtime(tmp_path / 'runtime') as runtime:
        actor = runtime.authenticate(runtime.create_client('history-test', declared_permissions(runtime))['token'])
        session = runtime.create_session(actor, temporary=False)['sessionId']
        job = runtime.submit(actor, session, 'workspace_history', {'projectId': project.id, 'action': 'snapshot', 'message': 'Runtime version'})
        result = runtime.wait(actor, job['jobId'], timeout=60)
        assert result['state'] == 'Completed', result
        assert result['outputs']['created']


def test_editor_restore_freezes_buffers_and_reloads_only_surviving_files(sample):
    from imgui_bundle import imgui, imgui_color_text_edit as ed
    from project_ui import ProjectIDE
    from types import SimpleNamespace
    project, root, ctx = sample
    first = service.workspace_history(project.id, 'snapshot', ctx, 'First')
    (root / 'New.cs').write_text('class New {}')
    preview = service.workspace_history(project.id, 'compare', ctx, commit=first['commit'])
    context = imgui.create_context()
    try:
        ide = ProjectIDE(SimpleNamespace(jobs=SimpleNamespace(busy=lambda tag: False)), None, None, None, None)
        editor, output = ed.TextEditor(), ed.TextEditor()
        editor.set_text('class New {}')
        state = {'info': service.workspace_info(project.id), 'tabs': {'New.cs': {'editor': editor, 'saved': editor.get_text()}},
                 'history_commit': first['commit'], 'history_preview': preview, 'history_restoring': False, 'output': output,
                 'debug': {'status': 'idle'}}
        ide.sessions[project.id] = state
        calls = []
        ide.submit = lambda pid, operation, parameters, done, failed: calls.append((operation, parameters, done, failed))
        ide.refresh = lambda pid: None
        ide.open_file = lambda pid, path: pytest.fail('Deleted file should not be reopened')
        ide.history_request(project.id, 'restore')
        assert state['history_restoring'] and editor.is_read_only_enabled()
        operation, parameters, done, failed = calls.pop()
        result = service.workspace_history(project.id, parameters['action'], ctx, commit=parameters['commit'], revision=parameters['revision'])
        done(result)
        assert not state['history_restoring'] and not editor.is_read_only_enabled()
        assert state['tabs'] == {} and state['history_preview'] is None
    finally:
        imgui.destroy_context(context)
