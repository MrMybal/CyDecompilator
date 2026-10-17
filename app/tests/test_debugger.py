"""Real NetCoreDbg sessions owned by Runtime jobs, with portable source symbols."""
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cytools_core import CyToolError
from cydec import components, debugger, process, service, workspace
from cydec.engines.base import EngineContext
from cydec.project import ProjectStore

SOURCE = '''using System;
class Box { public int Number = 7; }
class Program
{
    static int Compute(int input)
    {
        int local = input + 3;
        Box box = new Box();
        int result = local + box.Number;
        return result;
    }
    static void Main(string[] args)
    {
        Console.WriteLine("pid:" + Environment.ProcessId);
        int answer = Compute(5);
        Console.WriteLine("answer:" + answer + ":" + args[0]);
        System.Threading.Thread.Sleep(60000);
    }
}
'''


@pytest.fixture
def source(tmp_path, monkeypatch):
    if not components.locate('netcoredbg'):
        pytest.skip('Install the official netcoredbg component for debugger integration tests')
    ctx = EngineContext(workdir=tmp_path / 'setup')
    sdk = workspace.dotnet_sdk(ctx)
    _, out, _ = process.run([sdk, '--version'], context=ctx)
    root = tmp_path / 'source'
    root.mkdir()
    (root / 'Demo.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        '<TargetFramework>net%s.0</TargetFramework><OutputType>Exe</OutputType>'
        '</PropertyGroup></Project>' % out.split('.')[0], encoding='utf-8')
    (root / 'Program.cs').write_text(SOURCE, encoding='utf-8')
    monkeypatch.setattr(service, 'store', ProjectStore(tmp_path / 'projects'))
    project, _ = service.store.open(Path(__file__).parent / 'fixtures/native/funcs_x64_o2.dll')
    service.workspace_open(project.id, str(root))
    yield project, root, tmp_path
    session = debugger._sessions.get(debugger._key(project))
    if session and not session.closed:
        session.fatal = CyToolError('Cancelled', 'Test cleanup')
        deadline = time.monotonic() + 15
        while not session.closed and time.monotonic() < deadline:
            time.sleep(.1)


def wait(project, condition, seconds=25, previous_id=''):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = service.debug_status(project.id)
        if condition(result):
            return result
        if result['status'] in ('failed', 'cancelled') and result['sessionId'] != previous_id:
            pytest.fail(str(result))
        time.sleep(.1)
    pytest.fail('Debugger wait timed out: ' + str(service.debug_status(project.id)))


def command(project, ctx, action, state=None, **kw):
    state = state or service.debug_status(project.id)
    return service.debug_control(project.id, state['sessionId'], action, ctx,
                                  stop_id=state.get('stopId', 0), **kw)


def start(project, tmp_path, **kw):
    errors = []
    ctx = EngineContext(workdir=tmp_path / ('job-' + str(time.time_ns())))
    def launch():
        try:
            service.debug_start(project.id, ctx, arguments=['two words'], **kw)
        except BaseException as exc:
            errors.append(exc)
    thread = threading.Thread(target=launch)
    thread.start()
    return thread, ctx, errors


def test_debug_modified_copy_uses_remapped_method_symbols(source):
    _, root, tmp_path = source
    ctx = EngineContext(workdir=tmp_path / 'patch-setup')
    sdk = workspace.dotnet_sdk(ctx)
    text = SOURCE.replace('System.Threading.Thread.Sleep(60000);', '')
    (root / 'Program.cs').write_text(text, encoding='utf-8')
    rc, out, err = process.run([sdk, 'build', str(root), '-o', str(tmp_path / 'original')], context=ctx)
    assert rc == 0, out + err
    project, _ = service.store.open(tmp_path / 'original/Demo.dll')
    service.workspace_open(project.id, str(root))
    method = next(m for m in service.managed_methods(project.id, ctx)['methods'] if m['name'] == 'Compute')
    (root / 'Program.cs').write_text(text.replace('input + 3', 'input + 30').replace('answer:', 'DONOR:'), encoding='utf-8')
    plan = service.managed_patch_prepare(project.id, method['id'], ctx, symbols=True)
    receipt = service.patch_apply(project.id, plan['planId'], context=ctx)
    original = project.binary.read_bytes()
    service.debug_breakpoints(project.id, [{'path': 'Program.cs', 'line': 9}])
    thread, debug_ctx, errors = start(project, tmp_path, receipt_id=receipt['receiptId'])
    try:
        paused = wait(project, lambda s: s['status'] == 'paused')
        inspected = command(project, debug_ctx, 'inspect', paused)
        assert inspected['frames'][0]['path'] == 'Program.cs'
        assert any(v['name'] == 'local' and v['value'] == '35' for v in inspected['variables'])
        command(project, debug_ctx, 'continue', inspected)
        ended = wait(project, lambda s: s['status'] == 'terminated')
        assert 'answer:42:two words' in ended['output'] and 'DONOR:' not in ended['output']
        assert project.binary.read_bytes() == original
    finally:
        if thread.is_alive():
            command(project, debug_ctx, 'stop')
        thread.join(15)
    assert not errors, errors


def test_debug_async_modified_copy_binds_generated_move_next(source):
    _, root, tmp_path = source
    ctx = EngineContext(workdir=tmp_path / 'async-setup')
    sdk = workspace.dotnet_sdk(ctx)
    text = '''using System;
using System.Threading.Tasks;
class Program {
 static async Task<int> Compute(int input) {
  await Task.Delay(10);
  int local = input + 3;
  Console.WriteLine("local:"+local);
  return local;
 }
 static void Main(string[] args) { Console.WriteLine("answer:"+Compute(5).GetAwaiter().GetResult()); }
}
'''
    (root / 'Program.cs').write_text(text, encoding='utf-8')
    rc, out, err = process.run([sdk, 'build', str(root), '-o', str(tmp_path/'original')], context=ctx)
    assert rc == 0, out+err
    project, _ = service.store.open(tmp_path/'original/Demo.dll')
    service.workspace_open(project.id, str(root))
    (root / 'Program.cs').write_text(text.replace('input + 3', 'input + 30'), encoding='utf-8')
    method = next(m for m in service.managed_methods(project.id, ctx)['methods'] if m['name']=='Compute')
    plan = service.managed_patch_prepare(project.id, method['id'], ctx, symbols=True)
    receipt = service.patch_apply(project.id, plan['planId'], context=ctx)
    service.debug_breakpoints(project.id, [{'path':'Program.cs', 'line':7}])
    thread, debug_ctx, errors = start(project, tmp_path, receipt_id=receipt['receiptId'])
    try:
        paused = wait(project, lambda s:s['status']=='paused')
        inspected = command(project, debug_ctx, 'inspect', paused)
        assert inspected['frames'][0]['path']=='Program.cs'
        command(project, debug_ctx, 'continue', inspected)
        ended = wait(project, lambda s:s['status']=='terminated')
        assert 'answer:35' in ended['output']
    finally:
        if thread.is_alive():
            command(project, debug_ctx, 'stop')
        thread.join(15)
    assert not errors, errors


def test_real_breakpoint_stack_locals_children_and_steps(source):
    project, root, tmp_path = source
    original = project.binary.read_bytes()
    saved = service.debug_breakpoints(project.id, [{'path': 'Program.cs', 'line': 9}])
    assert service.debug_breakpoints(project.id) == saved
    thread, ctx, errors = start(project, tmp_path)
    try:
        paused = wait(project, lambda s: s['status'] == 'paused')
        assert paused['reason'] == 'breakpoint'
        snapshot = command(project, ctx, 'inspect', paused)
        assert snapshot['frames'][0]['path'] == 'Program.cs' and snapshot['frames'][0]['line'] == 9
        assert 'Compute' in snapshot['frames'][0]['name'] and any('Main' in f['name'] for f in snapshot['frames'])
        variables = {v['name']: v for v in snapshot['variables']}
        assert 'input' in variables, snapshot
        assert variables['input']['value'] == '5' and variables['local']['value'] == '8'
        children = command(project, ctx, 'variables', snapshot, reference=variables['box']['variablesReference'])
        assert any(v['name'] == 'Number' and v['value'] == '7' for v in children['children'])
        assert snapshot['breakpoints'][0]['verified']
        command(project, ctx, 'next', snapshot)
        stepped = wait(project, lambda s: s['status'] == 'paused' and s['stopId'] > paused['stopId'])
        stepped = command(project, ctx, 'inspect', stepped)
        assert stepped['frames'][0]['line'] == 10
        assert any(v['name'] == 'result' and v['value'] == '15' for v in stepped['variables'])
        with pytest.raises(CyToolError, match='pause changed'):
            command(project, ctx, 'variables', snapshot, reference=variables['box']['variablesReference'])
        command(project, ctx, 'stepOut', stepped)
        outer = wait(project, lambda s: s['status'] == 'paused' and s['stopId'] > stepped['stopId'])
        outer = command(project, ctx, 'inspect', outer)
        assert 'Main' in outer['frames'][0]['name']
        command(project, ctx, 'continue', outer)
        running = wait(project, lambda s: 'answer:15:two words' in s['output'])
        assert running['status'] == 'running'
        pid = int(running['output'].split('pid:')[1].splitlines()[0])
        command(project, ctx, 'pause', running)
        wait(project, lambda s: s['status'] == 'paused')
        command(project, ctx, 'stop')
        thread.join(15)
        assert not thread.is_alive() and not errors
        assert not psutil.pid_exists(pid)
        assert project.binary.read_bytes() == original
    finally:
        if thread.is_alive():
            command(project, ctx, 'stop')
            thread.join(20)


def test_step_into_entry_and_normal_exit(source):
    project, root, tmp_path = source
    (root / 'Program.cs').write_text(SOURCE.replace('System.Threading.Thread.Sleep(60000);', ''), encoding='utf-8')
    thread, ctx, errors = start(project, tmp_path, rows=[{'path': 'Program.cs', 'line': 15}], stop_at_entry=True)
    try:
        entry = wait(project, lambda s: s['status'] == 'paused')
        assert entry['reason'] == 'entry'
        command(project, ctx, 'continue', entry)
        call = wait(project, lambda s: s['status'] == 'paused' and s['stopId'] > entry['stopId'])
        command(project, ctx, 'stepIn', call)
        inside = wait(project, lambda s: s['status'] == 'paused' and s['stopId'] > call['stopId'])
        inside = command(project, ctx, 'inspect', inside)
        assert 'Compute' in inside['frames'][0]['name']
        command(project, ctx, 'continue', inside)
        thread.join(15)
        assert not thread.is_alive() and not errors
        ended = service.debug_status(project.id)
        assert ended['status'] == 'terminated' and ended['exitCode'] == 0
        assert 'answer:15:two words' in ended['output'] and not ended['frames']
    finally:
        if thread.is_alive():
            command(project, ctx, 'stop')
            thread.join(20)


def test_breakpoint_confinement_and_stale_sessions(source):
    project, _, tmp_path = source
    for rows in ([{'path': '../Program.cs', 'line': 1}], [{'path': 'Program.cs', 'line': 999}],
                 [{'path': 'Program.cs', 'line': True}], [{'path': 'Demo.csproj', 'line': 1}]):
        with pytest.raises(CyToolError):
            service.debug_breakpoints(project.id, rows)
    with pytest.raises(CyToolError, match='session changed'):
        service.debug_control(project.id, 'stale', 'stop', EngineContext(workdir=tmp_path / 'control'))


def test_runtime_controls_cancellation_and_restart(source):
    from tool import create_runtime, declared_permissions
    project, root, tmp_path = source
    with create_runtime(tmp_path / 'runtime') as runtime:
        actor = runtime.authenticate(runtime.create_client('debugger-test', declared_permissions(runtime))['token'])
        owner = runtime.create_session(actor, temporary=False)['sessionId']
        launch = runtime.submit(actor, owner, 'debug_start', {'projectId': project.id,
            'arguments': ['two words'], 'breakpoints': [{'path': 'Program.cs', 'line': 9}]})
        paused = wait(project, lambda s: s['status'] == 'paused')
        pid = int(paused['output'].split('pid:')[1].splitlines()[0])
        control_job = runtime.submit(actor, owner, 'debug_control', {'projectId': project.id,
            'sessionId': paused['sessionId'], 'action': 'inspect', 'stopId': paused['stopId']})
        done = runtime.wait(actor, control_job['jobId'], timeout=20)
        assert done['state'] == 'Completed' and done['outputs']['variables']
        with pytest.raises(CyToolError, match='Stop debugging'):
            service.workspace_save(project.id, 'Program.cs', SOURCE, workspace.read_file(project, 'Program.cs')['revision'])
        with pytest.raises(CyToolError, match='already active'):
            service.debug_start(project.id, EngineContext(workdir=tmp_path / 'other'))
        runtime.cancel(actor, launch['jobId'])
        ended = runtime.wait(actor, launch['jobId'], timeout=20)
        assert ended['state'] == 'Cancelled'
        assert not psutil.pid_exists(pid)
        assert service.debug_status(project.id)['status'] == 'cancelled'
        # A new launch gets a fresh session identity; old clients cannot stop it.
        next_job = runtime.submit(actor, owner, 'debug_start', {'projectId': project.id,
            'arguments': ['two words'], 'stopAtEntry': True})
        next_pause = wait(project, lambda s: s['status'] == 'paused' and s['sessionId'] != paused['sessionId'], previous_id=paused['sessionId'])
        with pytest.raises(CyToolError, match='session changed'):
            command(project, EngineContext(), 'stop', paused)
        runtime.cancel(actor, next_job['jobId'])
        assert runtime.wait(actor, next_job['jobId'], timeout=20)['state'] == 'Cancelled'
        assert next_pause['reason'] == 'entry'


def test_timeout_and_protocol_failure_kill_debuggee(source, monkeypatch):
    project, _, tmp_path = source
    original_run = process.run
    def short_run(command, **kw):
        if kw.get('protocol'):
            kw['timeout'] = 1
        return original_run(command, **kw)
    monkeypatch.setattr(process, 'run', short_run)
    thread, ctx, errors = start(project, tmp_path, rows=[{'path': 'Program.cs', 'line': 9}])
    paused = wait(project, lambda s: s['status'] == 'paused')
    pid = int(paused['output'].split('pid:')[1].splitlines()[0])
    thread.join(15)
    assert not thread.is_alive() and len(errors) == 1 and 'did not finish' in str(errors[0])
    assert not psutil.pid_exists(pid)
    # A broken adapter protocol is also handled by process.run's tree cleanup.
    monkeypatch.setattr(process, 'run', original_run)
    thread, ctx, errors = start(project, tmp_path, rows=[{'path': 'Program.cs', 'line': 9}])
    paused = wait(project, lambda s: s['status'] == 'paused', previous_id=paused['sessionId'])
    pid = int(paused['output'].split('pid:')[1].splitlines()[0])
    debugger._sessions[debugger._key(project)].fatal = CyToolError('EngineFailed', 'Protocol test failure')
    thread.join(15)
    assert not thread.is_alive() and errors and 'Protocol test failure' in str(errors[0])
    assert not psutil.pid_exists(pid)


def test_runtime_shutdown_kills_debuggee_and_descendants(source):
    from tool import create_runtime, declared_permissions
    project, root, tmp_path = source
    # Spawn a long-lived child through the test app, without opening a window.
    child_source = SOURCE.replace('int answer = Compute(5);',
        'var child = System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo { '
        'FileName = "' + sys.executable.replace('\\', '\\\\') + '", '
        'Arguments = "-c \\\"import time; time.sleep(60)\\\"", UseShellExecute = false, CreateNoWindow = true });\n'
        '        Console.WriteLine("child:" + child.Id);\n        int answer = Compute(5);')
    (root / 'Program.cs').write_text(child_source, encoding='utf-8')
    with create_runtime(tmp_path / 'runtime') as runtime:
        actor = runtime.authenticate(runtime.create_client('shutdown-test', declared_permissions(runtime))['token'])
        owner = runtime.create_session(actor, temporary=False)['sessionId']
        runtime.submit(actor, owner, 'debug_start', {'projectId': project.id, 'arguments': ['two words']})
        running = wait(project, lambda s: 'answer:15:two words' in s.get('output', ''))
        pid = int(running['output'].split('pid:')[1].splitlines()[0])
        child = int(running['output'].split('child:')[1].splitlines()[0])
        assert psutil.pid_exists(pid) and psutil.pid_exists(child)
    assert not psutil.pid_exists(pid) and not psutil.pid_exists(child)


def test_decompile_reconstruct_and_debug_with_new_symbols(source):
    project, root, tmp_path = source
    if not components.locate('ilspycmd'):
        pytest.skip('ILSpy is required for the complete decompile/debug roundtrip')
    ctx = EngineContext(workdir=tmp_path / 'roundtrip', options={'symbols': False})
    sdk = workspace.dotnet_sdk(ctx)
    (root / 'Program.cs').write_text(SOURCE.replace('System.Threading.Thread.Sleep(60000);', ''), encoding='utf-8')
    rc, out, err = process.run([sdk, 'build', str(root), '-o', str(tmp_path / 'original')], context=ctx, timeout=120)
    assert rc == 0, out + err
    managed, _ = service.store.open(tmp_path / 'original/Demo.dll')
    original = managed.binary.read_bytes()
    service.analyze(managed.id, 'ilspy', ctx)
    exported = service.workspace_create(managed.id, str(tmp_path / 'reconstructed'), context=ctx)
    assert exported['kind'] == 'dotnet'
    file = next(f['path'] for f in exported['files'] if Path(f['path']).name == 'Program.cs')
    code = service.workspace_read(managed.id, file)['text']
    line = next(i for i, text in enumerate(code.splitlines(), 1) if 'Compute(5)' in text)
    thread, launch_ctx, errors = start(managed, tmp_path, rows=[{'path': file, 'line': line}])
    try:
        paused = wait(managed, lambda s: s['status'] == 'paused')
        state = command(managed, launch_ctx, 'inspect', paused)
        assert state['frames'][0]['path'] == file and state['frames'][0]['line'] == line
        assert 'Main' in state['frames'][0]['name'] and state['breakpoints'][0]['verified']
        command(managed, launch_ctx, 'stepIn', state)
        inside = wait(managed, lambda s: s['status'] == 'paused' and s['stopId'] > paused['stopId'])
        inside = command(managed, launch_ctx, 'inspect', inside)
        assert 'Compute' in inside['frames'][0]['name']
        command(managed, launch_ctx, 'continue', inside)
        thread.join(15)
        assert not thread.is_alive() and not errors
        assert service.debug_status(managed.id)['exitCode'] == 0
        assert 'answer:15:two words' in service.debug_status(managed.id)['output']
        assert managed.binary.read_bytes() == original
    finally:
        if thread.is_alive():
            command(managed, launch_ctx, 'stop')
            thread.join(20)
