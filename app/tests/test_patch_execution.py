"""Real copy execution, live console events, receipt integrity and cancellation."""
import json
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest

from test_managed_patching import sample, edit, value_method  # fixture shared with managed patch tests
from cytools_core import CyToolError
from cydec import execution, process, service
from cydec.engines.base import EngineContext


def prepare(sample, body):
    project, source, ctx, _ = sample
    method = value_method(project, ctx)
    edit(source, 'static int Value(int v) { ' + body + ' }')
    plan = service.managed_patch_prepare(project.id, method['id'], ctx)
    return service.patch_apply(project.id, plan['planId'], context=ctx)


def test_run_modified_copy_streams_arguments_and_failure(sample):
    project, _, ctx, _ = sample
    receipt = prepare(sample, 'Console.WriteLine("arg:"+Environment.GetCommandLineArgs()[1]); '
        'Console.Error.WriteLine("stderr-marker"); System.Threading.Thread.Sleep(500); Environment.ExitCode=7; return 42;')
    events = []
    ctx._emit = lambda kind, data: events.append((kind, data, time.monotonic()))
    result = service.patch_run(project.id, receipt['receiptId'], ctx, ['two words'])
    finished = time.monotonic()
    assert result['status'] == 'failed' and result['exitCode'] == 7
    assert 'arg:two words' in result['output'] and 'original:42' in result['output']
    assert any(data['stream'] == 'stderr' and 'stderr-marker' in data['text'] for kind, data, _ in events if kind == 'ProcessOutput')
    assert any('arg:two words' in data['text'] and finished-stamp > .3 for kind, data, stamp in events if kind == 'ProcessOutput')
    saved = service.patch_outputs(project.id)
    assert saved['copies'][0]['receiptId'] == receipt['receiptId']
    assert saved['lastRun'] == result
    assert project.meta()['sha256'] == execution.hashlib.sha256(project.binary.read_bytes()).hexdigest()


def test_run_refuses_changed_files_and_original(sample):
    project, _, ctx, _ = sample
    receipt = prepare(sample, 'return 42;')
    for timeout in (0, 901, True):
        with pytest.raises(CyToolError, match='timeout'):
            service.patch_run(project.id, receipt['receiptId'], ctx, timeout=timeout)
    with pytest.raises(CyToolError, match='arguments'):
        service.patch_run(project.id, receipt['receiptId'], ctx, 'shell string')
    with pytest.raises(CyToolError, match='saved'):
        service.patch_run(project.id, '../escape', ctx)
    companion = Path(receipt['companionHashes'][0]['path'])
    old = companion.read_bytes()
    companion.write_bytes(old + b'changed')
    with pytest.raises(CyToolError, match='dependency changed'):
        service.patch_run(project.id, receipt['receiptId'], ctx)
    companion.write_bytes(old)
    output = Path(receipt['path'])
    old = output.read_bytes()
    output.write_bytes(old + b'changed')
    with pytest.raises(CyToolError, match='missing or changed'):
        service.patch_run(project.id, receipt['receiptId'], ctx)
    output.write_bytes(old)
    path = project.dir / 'patches/receipts' / (receipt['receiptId'] + '.json')
    receipt['path'] = str(project.binary)
    receipt['sha256'] = project.meta()['sha256']
    path.write_text(json.dumps(receipt), encoding='utf-8')
    with pytest.raises(CyToolError, match='original is protected'):
        service.patch_run(project.id, receipt['receiptId'], ctx)


def test_modified_copy_timeout_and_runtime_cancellation(sample, tmp_path):
    from tool import create_runtime, declared_permissions
    project, _, ctx, _ = sample
    receipt = prepare(sample, 'Console.WriteLine("ready:"+Environment.ProcessId); '
                            'System.Threading.Thread.Sleep(60000); return 42;')
    with pytest.raises(CyToolError, match='did not finish'):
        service.patch_run(project.id, receipt['receiptId'], ctx, timeout=1)
    assert 'ready:' in (ctx.workdir / 'modified-copy.stdout.log').read_text()
    with create_runtime(tmp_path / 'jobs') as runtime:
        actor = runtime.authenticate(runtime.create_client('copy-test', declared_permissions(runtime))['token'])
        session = runtime.create_session(actor, temporary=False)['sessionId']
        job = runtime.submit(actor, session, 'patch_run', {'projectId': project.id, 'receiptId': receipt['receiptId']})
        deadline, cursor, pid = time.monotonic()+15, 0, None
        while time.monotonic() < deadline and pid is None:
            events = runtime.events(actor, cursor)
            cursor = events['cursor']
            for event in events['events']:
                if event.get('jobId') == job['jobId'] and event.get('type') == 'ProcessOutput':
                    text = event['data']['text']
                    if text.startswith('ready:'):
                        pid = int(text.split(':')[1])
            time.sleep(.05)
        try:
            assert pid is not None, runtime.get_job(actor, job['jobId'])
            assert psutil.pid_exists(pid)
        finally:
            runtime.cancel(actor, job['jobId'])
        result = runtime.wait(actor, job['jobId'], timeout=20)
        assert result['state'] == 'Cancelled', result
        assert not psutil.pid_exists(pid)


def test_process_cancel_stops_descendants_and_preserves_live_output(tmp_path):
    class Token:
        cancelled = False
        def check(self):
            if self.cancelled:
                raise CyToolError('Cancelled', 'Cancelled')
    token = Token()
    ctx = EngineContext(workdir=tmp_path, cancellation=token)
    pids = []
    def output(stream, text):
        if text.startswith('ready:'):
            pids.extend(int(v) for v in text.removeprefix('ready:').split(','))
            token.cancelled = True
    program = ('import os,subprocess,sys,time; '
        'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]); '
        'print("ready:"+str(os.getpid())+","+str(child.pid),flush=True); time.sleep(60)')
    with pytest.raises(CyToolError, match='Cancelled'):
        process.run([sys.executable, '-c', program], context=ctx, on_output=output)
    assert len(pids) == 2 and all(not psutil.pid_exists(pid) for pid in pids)
    assert 'ready:' in (tmp_path / 'process.stdout.log').read_text()


def test_live_output_is_bounded_and_contains_stderr(tmp_path):
    events = []
    ctx = EngineContext(workdir=tmp_path, emit=lambda kind, data: events.append(data))
    process.run([sys.executable, '-c', 'import sys;print("x"*250000);print("err",file=sys.stderr)'],
                context=ctx, on_output=execution.output_events(ctx))
    assert sum(len(item['text']) for item in events) <= execution.OUTPUT_LIMIT
    assert max(len(item['text']) for item in events) <= 8192
    assert len((tmp_path / 'process.stdout.log').read_text()) == 250000
