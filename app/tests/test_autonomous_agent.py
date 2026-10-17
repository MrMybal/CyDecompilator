"""Controlled model decisions; real authenticated jobs, files, compilers and processes."""
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import psutil
import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from cydec import service, workspace
from cydec.ai import agent, assistant
from cydec.engines.base import EngineContext
from cydec.project import ProjectStore
from tool import create_runtime, declared_permissions


@pytest.fixture
def sample(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'store', ProjectStore(tmp_path / 'projects'))
    source = tmp_path / 'original'
    source.mkdir()
    original = 'function compute(v){return v+3;} console.log(compute(7));'
    (source / 'main.js').write_text(original, encoding='utf-8')
    ctx = EngineContext(workdir=tmp_path / 'setup')
    project_id = service.application_open(str(source), ctx)['projectId']
    service.workspace_create(project_id, context=ctx)
    project = service.project_for(project_id)
    with create_runtime(tmp_path / 'jobs') as runtime:
        actor = runtime.authenticate(runtime.create_client('agent-test', declared_permissions(runtime))['token'])
        session = runtime.create_session(actor, temporary=False)['sessionId']
        yield runtime, actor, session, project, ctx, original


def launch(sample, **changes):
    runtime, actor, session, project, _, _ = sample
    parameters = dict(projectId=project.id, objective='Reconstruct the original app and validate its behavior.', maxSteps=12)
    parameters.update(changes)
    return runtime.submit(actor, session, 'ai_agent', parameters)


def reply(value):
    return json.dumps(value), '', 'controlled-model', SimpleNamespace(id='controlled')


def test_agent_repairs_actual_compilation_and_rejects_premature_success(sample, monkeypatch):
    runtime, actor, _, project, ctx, original = sample
    source = service.workspace_read(project.id, 'main.js')
    service.workspace_save(project.id, 'main.js', 'console.log( ;', source['revision'])
    count = 0
    revision = ''

    def model(prompt, **kwargs):
        nonlocal count, revision
        data = json.loads(prompt)
        index, count = count, count + 1
        if index == 0:
            return reply({'answer': 'It is done.', 'status': 'completed'})
        if index == 1:
            assert 'Completion requires actual validation' in data['error']
            return reply({'tool': 'workspace_execute', 'arguments': {'action': 'build'}})
        result = json.loads(data['result'])
        if index == 2:
            assert result['outputs']['status'] == 'failed'
            return reply({'tool': 'workspace_read', 'arguments': {'path': 'main.js'}})
        if index == 3:
            revision = result['outputs']['revision']
            return reply({'tool': 'workspace_history', 'arguments': {'action': 'snapshot', 'message': 'Before autonomous repair'}})
        if index == 4:
            return reply({'tool': 'workspace_save', 'arguments': {'path': 'main.js', 'text': original, 'revision': revision}})
        if index == 5:
            return reply({'tool': 'reconstruction_run', 'arguments': {'maxRounds': 1}})
        assert result['outputs']['status'] == 'scenarios-matched', result
        return reply({'answer': 'Rebuilt and compared the original scenario.', 'status': 'completed'})

    monkeypatch.setattr(assistant, 'call_model', model)
    job = launch(sample)
    result = runtime.wait(actor, job['jobId'], timeout=70)
    assert result['state'] == 'Completed', result
    report = result['outputs']
    assert report['status'] == 'completed' and report['verification']['verified'], report
    assert report['finishedAt'] >= report['startedAt']
    assert report['steps'][0]['status'] == 'error'
    assert count == 7
    assert (Path(project.meta()['sourcePath']) / 'main.js').read_text() == original
    assert service.workspace_read(project.id, 'main.js')['text'] == original
    assert agent.status(project.id, report['runId'])['verification']['jobId']
    assert 'messages' not in agent.status(project.id)
    for child in report['childJobs']:
        row = runtime.get_job(actor, child['jobId'])
        assert row['clientId'] == actor.client_id and row['parameters']['projectId'] == project.id
    assert not agent.verified(report | {'steps': report['steps'] + [{
        'tool': 'workspace_save', 'arguments': {}, 'result': {'state': 'Completed', 'outputs': {}}}]})['verified']
    assert not agent.verified(report | {'steps': report['steps'] + [{
        'tool': 'workspace_save', 'arguments': {}, 'result': {'state': 'Failed'}}]})['verified']


def test_agent_checkpoint_resume_and_fresh_source_verification(sample, monkeypatch):
    runtime, actor, _, project, _, _ = sample
    monkeypatch.setattr(assistant, 'call_model', lambda *a, **k: reply({'tool': 'workspace_read', 'arguments': {'path': 'main.js'}}))
    job = launch(sample, maxSteps=1)
    first = runtime.wait(actor, job['jobId'], timeout=20)['outputs']
    assert first['status'] == 'budget-exhausted' and len(first['steps']) == 1
    calls = iter([{'tool': 'reconstruction_run', 'arguments': {'maxRounds': 1}}, {'answer': 'Validated.', 'status': 'completed'}])
    monkeypatch.setattr(assistant, 'call_model', lambda *a, **k: reply(next(calls)))
    job = launch(sample, runId=first['runId'])
    resumed = runtime.wait(actor, job['jobId'], timeout=70)['outputs']
    assert resumed['status'] == 'completed' and resumed['runId'] == first['runId']
    source = service.workspace_read(project.id, 'main.js')
    service.workspace_save(project.id, 'main.js', 'console.log(99);', source['revision'])
    # A checkpoint cannot reuse old successful evidence after external source edits.
    monkeypatch.setattr(assistant, 'call_model', lambda *a, **k: reply({'answer': 'Done.', 'status': 'completed'}))
    job = launch(sample, runId=first['runId'], maxSteps=1)
    rejected = runtime.wait(actor, job['jobId'], timeout=20)['outputs']
    assert rejected['status'] == 'budget-exhausted' and not rejected['verification']['verified']


def test_agent_scope_modes_and_foreign_jobs_are_enforced(sample, monkeypatch):
    runtime, actor, session, project, _, _ = sample
    foreign = runtime.submit(actor, session, 'workspace_info', {'projectId': project.id})
    calls = iter([
        {'tool': [], 'arguments': {}},
        {'tool': 'workspace_history', 'arguments': []},
        {'tool': 'workspace_save', 'arguments': {'path': 'main.js', 'text': 'bad'}},
        {'tool': 'get_job', 'arguments': {'jobId': foreign['jobId']}},
        {'tool': 'workspace_read', 'arguments': {'projectId': 'some-other-project', 'path': 'main.js'}},
        {'tool': 'install_component', 'arguments': {'component': 'ghidra'}},
        {'tool': 'ai_configure', 'arguments': {'provider': 'ollama'}},
        {'tool': 'workspace_read', 'arguments': {'path': 'main.js'}},
        {'answer': 'Read the original source without editing or executing it.', 'status': 'completed'}])
    monkeypatch.setattr(assistant, 'call_model', lambda *a, **k: reply(next(calls)))
    job = launch(sample, workflow='investigate', allowInstall=False)
    report = runtime.wait(actor, job['jobId'], timeout=30)['outputs']
    assert report['status'] == 'completed'
    assert [s['status'] for s in report['steps']] == ['error'] * 5 + ['ok']
    assert len(report['childJobs']) == 1


def test_cancelling_agent_stops_running_child_process_and_saves_checkpoint(sample, monkeypatch, tmp_path):
    runtime, actor, _, project, ctx, _ = sample
    pid_path = tmp_path / 'child-pid.txt'
    source = service.workspace_read(project.id, 'main.js')
    service.workspace_save(project.id, 'main.js',
        'require("fs").writeFileSync(' + json.dumps(str(pid_path)) + ',String(process.pid));setTimeout(()=>{},60000);', source['revision'])
    assert service.workspace_execute(project.id, 'build', ctx)['status'] == 'passed'
    monkeypatch.setattr(assistant, 'call_model', lambda *a, **k: reply({'tool': 'workspace_execute', 'arguments': {'action': 'run'}}))
    job = launch(sample)
    deadline = time.monotonic() + 20
    while not pid_path.exists() and time.monotonic() < deadline:
        time.sleep(.05)
    assert pid_path.is_file()
    pid = int(pid_path.read_text())
    runtime.cancel(actor, job['jobId'])
    cancelled = runtime.wait(actor, job['jobId'], timeout=20)
    assert cancelled['state'] == 'Cancelled', cancelled
    assert not psutil.pid_exists(pid)
    report = agent.status(project.id)
    assert report['status'] == 'cancelled' and report['childJobs']
    assert all(runtime.get_job(actor, j['jobId'])['state'] in ('Completed', 'Cancelled', 'Failed') for j in report['childJobs'])


def test_ui_saves_and_freezes_source_before_autonomous_changes():
    from desktop import App
    app = App.__new__(App)
    calls = []
    state = {'tabs': {'dirty.cs': {}}, 'active': 'dirty.cs'}
    def save_all(pid, after):
        calls.append('save')
        assert not state.get('reconstruction_busy')
        after()
    def submit(operation, parameters, **kwargs):
        calls.append(operation)
        assert state['reconstruction_busy']
        kwargs['done']({'projectId': 'p', 'objective': 'fix', 'workflow': 'reconstruct',
                        'status': 'completed', 'answer': 'Built and validated.', 'runId': 'run'})
    app.ide = SimpleNamespace(sessions={'p': state}, save_all=save_all, refresh=lambda pid: calls.append('refresh'))
    app.jobs = SimpleNamespace(submit=submit)
    app.ai_editor = SimpleNamespace(set_text=lambda text: None)
    app.ai_language = lambda: 'fr'
    app.start_agent('p', 'fix', 'reconstruct')
    assert calls == ['save', 'ai_agent', 'refresh']
    assert not state['reconstruction_busy'] and state['tabs'] == {}


def test_agent_native_dll_patch_is_validated_with_real_harness(sample, monkeypatch, tmp_path):
    runtime, actor, session, _, _, _ = sample
    binary = APP / 'tests/fixtures/native/funcs_x64_o2.dll'
    project, _ = service.store.open(binary)
    ctx = EngineContext(workdir=tmp_path / 'native', options={'symbols': False})
    service.analyze(project.id, 'cdec', ctx)
    runner = tmp_path / 'runner.py'
    runner.write_text('import ctypes,sys\nlib=ctypes.CDLL(sys.argv[1])\n'
        'lib.add3.argtypes=[ctypes.c_int]*3\nlib.add3.restype=ctypes.c_int\nv=lib.add3(2,3,4)\n'
        'print(v)\nassert v==int(sys.argv[2])\n', encoding='utf-8')
    count, plan_id, output, capture_id = 0, '', '', ''
    def model(prompt, **kwargs):
        nonlocal count, plan_id, output, capture_id
        data = json.loads(prompt)
        index, count = count, count + 1
        result = json.loads(data['result'])['outputs'] if 'result' in data else {}
        if index == 0:
            return reply({'tool': 'patch_prepare', 'arguments': {'function': 'add3', 'engine': 'cdec',
                'source': 'int replacement(int a,int b,int c){return a+b+c;}', 'symbol': 'replacement'}})
        if index == 1:
            plan_id = result['planId']
            return reply({'tool': 'patch_apply', 'arguments': {'planId': plan_id}})
        if index == 2:
            output = result['path']
            return reply({'tool': 'behavior_capture', 'arguments': {'executable': sys.executable,
                'arguments': [str(runner), str(binary), '7']}})
        if index == 3:
            assert result['complete'] and result['exitCode'] == 0, result
            capture_id = result['captureId']
            return reply({'tool': 'behavior_capture', 'arguments': {'executable': sys.executable,
                'arguments': [str(runner), output, '9']}})
        if index == 4:
            assert result['complete'] and result['exitCode'] == 0, result
            return reply({'tool': 'behavior_compare', 'arguments': {'left': capture_id, 'right': result['captureId']}})
        assert result['complete'] and not result['streams']['stdout']['same']
        return reply({'answer': 'The original produced 7 and the modified function produced the requested 9.', 'status': 'completed'})
    monkeypatch.setattr(assistant, 'call_model', model)
    job = runtime.submit(actor, session, 'ai_agent', {'projectId': project.id, 'workflow': 'patch',
        'objective': 'Change add3 to sum all three arguments, then test original and modified copies.', 'maxSteps': 10})
    result = runtime.wait(actor, job['jobId'], timeout=80)
    assert result['state'] == 'Completed', result
    assert result['outputs']['status'] == 'completed' and result['outputs']['verification']['verified']


def test_agent_cannot_attach_or_export_over_original_application(sample, monkeypatch):
    runtime, actor, _, project, _, original = sample
    source = Path(project.meta()['sourcePath'])
    calls = iter([{'tool': 'workspace_open', 'arguments': {'directory': str(source)}},
                  {'tool': 'export_sources', 'arguments': {'destination': str(source)}},
                  {'answer': 'The original is protected; choose a separate reconstruction.', 'status': 'blocked'}])
    monkeypatch.setattr(assistant, 'call_model', lambda *a, **k: reply(next(calls)))
    job = launch(sample)
    report = runtime.wait(actor, job['jobId'], timeout=20)['outputs']
    assert report['status'] == 'blocked' and not report['childJobs']
    assert all(step['result']['error']['code'] == 'AccessDenied' for step in report['steps'])
    assert (source / 'main.js').read_text() == original
