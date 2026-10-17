"""Application workflows through actual MCP calls, not direct service mocks."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import time

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from mcp_client import client, payload, run, terminal
from cydec import components, process, workspace
from cydec.engines.base import EngineContext
from test_runtime_observation import CHROME, server  # shared real loopback HTTP fixture


def test_mcp_autonomous_task_and_status(tmp_path):
    original = tmp_path / 'original'
    original.mkdir()
    (original / 'main.js').write_text('console.log(Number(process.argv[2]||4)*3);', encoding='utf-8')
    decisions = [{'tool': 'reconstruction_run', 'arguments': {'maxRounds': 1, 'scenarios': [{'arguments': ['3']}, {'arguments': ['-2']}]}},
                 {'answer': 'The two recorded scenarios matched.', 'status': 'completed'}]

    async def scenario():
        async with client(tmp_path / 'mcp', model_decisions=decisions) as session:
            project = (await run(session, 'application_open', path=str(original)))['projectId']
            report = await run(session, 'ai_agent', projectId=project, objective='Reconstruct and validate the two scenarios.', maxSteps=5)
            assert report['status'] == 'completed' and report['verification']['verified'], report
            assert len(report['steps'][0]['result']['outputs']['attempts'][-1]['comparisons']) == 2
            saved = await run(session, 'ai_agent_status', projectId=project, runId=report['runId'])
            assert saved['runId'] == report['runId'] and saved['status'] == 'completed'
            assert 'messages' not in saved
    asyncio.run(scenario())


def test_mcp_catalog_and_node_reconstruction_history_failures(tmp_path):
    original = tmp_path / 'original'
    original.mkdir()
    (original / 'main.js').write_text('console.log("same behavior");', encoding='utf-8')

    async def scenario():
        async with client(tmp_path / 'mcp') as session:
            catalog = (await session.list_tools()).tools
            operations = json.loads((APP / 'CyTool.json').read_text('utf-8'))['operations']
            assert {t.name for t in catalog if t.name.startswith('op_')} == {'op_' + o['id'] for o in operations} | {'op_installation_storage_status'}
            for operation in operations:
                described = await payload(session, 'cy_describe_operation', {'operationId': operation['id']})
                assert set(described['inputSchema']['properties']) == set(operation['inputSchema']['properties'])
                assert described['inputSchema'].get('required', []) == operation['inputSchema'].get('required', [])
                assert described['outputSchema'] == operation['outputSchema']
            invalid = await session.call_tool('op_workspace_save', {'parameters': {'projectId': 'missing'}})
            assert invalid.isError
            project = (await run(session, 'application_open', path=str(original)))['projectId']
            evidence = await run(session, 'investigation_source', projectId=project, path='main.js')
            assert 'same behavior' in evidence['text']
            report = await run(session, 'reconstruction_run', projectId=project, maxRounds=1)
            assert report['status'] == 'scenarios-matched', report
            assert (await run(session, 'reconstruction_status', projectId=project))['runId'] == report['runId']
            snapshot = await run(session, 'workspace_history', projectId=project, action='snapshot', message='known working')
            source = await run(session, 'workspace_read', projectId=project, path='main.js')
            await run(session, 'workspace_save', projectId=project, path='main.js', text='console.log(2);', revision=source['revision'])
            stale = await terminal(session, await payload(session, 'op_workspace_save', {
                'projectId': project, 'path': 'main.js', 'text': 'console.log(3);', 'revision': source['revision']}))
            assert stale['state'] == 'Failed' and stale['error']['code'] == 'Conflict', stale
            differs = await run(session, 'reconstruction_run', projectId=project, maxRounds=1)
            assert differs['status'] == 'behavior-differs'
            diff = await run(session, 'workspace_history', projectId=project, action='compare', commit=snapshot['head'])
            await run(session, 'workspace_history', projectId=project, action='restore', commit=snapshot['head'], revision=diff['revision'])
            restored = await run(session, 'reconstruction_run', projectId=project, maxRounds=1)
            assert restored['status'] == 'scenarios-matched'
            source = await run(session, 'workspace_read', projectId=project, path='main.js')
            await run(session, 'workspace_save', projectId=project, path='main.js', text='console.log( ;', revision=source['revision'])
            failed = await run(session, 'workspace_execute', projectId=project, action='build')
            assert failed['status'] == 'failed' and failed['exitCode'] != 0
            assert (original / 'main.js').read_text() == 'console.log("same behavior");'
    asyncio.run(scenario())


@pytest.mark.skipif(not CHROME.is_file(), reason='Chrome required for graphical MCP scenario')
def test_mcp_network_graphics_evidence_and_integrity(tmp_path, server):
    original = tmp_path / 'original'
    original.mkdir()
    (original / 'index.html').write_text('<title>Evidence project</title>', encoding='utf-8')
    url, handler = server

    async def scenario():
        async with client(tmp_path / 'mcp') as session:
            project = (await run(session, 'application_open', path=str(original)))['projectId']
            observation = {'driver': 'chromium', 'headless': True, 'network': True, 'url': url, 'settleMs': 200,
                'steps': [{'action': 'fill', 'selector': '#name', 'text': 'sample'},
                          {'action': 'click', 'selector': '#go'},
                          {'action': 'assertText', 'selector': '#result', 'text': 'o'}]}
            first = await run(session, 'behavior_capture', projectId=project, executable=str(CHROME), timeout=40, observation=observation)
            assert first['complete'], first
            request = next(r for r in first['runtime']['gui']['requests'] if '/api/report?' in r['url'])
            assert request['status'] == 200 and request['finished'] and request['step'] == 1
            graph = await run(session, 'investigation_query', projectId=project, query='/api/report')
            assert any(e['kind'] == 'request-during-step' and e['status'] == 'observed' for e in graph['edges'])
            evidence = await run(session, 'behavior_evidence', projectId=project, captureId=first['captureId'])
            assert len(evidence['images']) == 4
            assert all(Path(row['path']).read_bytes().startswith(b'\x89PNG') for row in evidence['images'])
            handler.version = 'two'
            second = await run(session, 'behavior_capture', projectId=project, executable=str(CHROME), timeout=40, observation=observation)
            assert second['complete'], second
            compared = await run(session, 'behavior_compare', projectId=project, left=first['captureId'], right=second['captureId'])
            assert compared['sameScenario'] and not compared['observationsMatch']
            assert not compared['graphics']['states'][-1]['pixelsSame']
            Path(evidence['images'][0]['path']).write_bytes(b'tampered')
            failed = await terminal(session, await payload(session, 'op_behavior_evidence', {'projectId': project, 'captureId': first['captureId']}))
            assert failed['state'] == 'Failed' and failed['error']['code'] == 'IntegrityFailure'
    asyncio.run(scenario())


def test_mcp_native_reconstruct_patch_and_compare(tmp_path):
    binary = APP / 'tests/fixtures/native/funcs_x64_o2.dll'
    before = hashlib.sha256(binary.read_bytes()).hexdigest()
    runner = tmp_path / 'runner.py'
    runner.write_text('import ctypes,sys\nlib=ctypes.CDLL(sys.argv[1])\n'
        'lib.add3.argtypes=[ctypes.c_int]*3\nlib.add3.restype=ctypes.c_int\nprint(lib.add3(2,3,4))\n', encoding='utf-8')

    async def scenario():
        async with client(tmp_path / 'mcp') as session:
            opened = await run(session, 'open_file', path=str(binary), engine='cdec', options={'symbols': False})
            assert opened['name'] == binary.name and opened['sourcePath'] == str(binary), opened
            project = opened['projectId']
            metadata_path = Path(opened['binaryPath']).parent.parent / 'project.json'
            metadata = json.loads(metadata_path.read_text('utf-8'))
            metadata['sourcePath'] = str(tmp_path / 'expired-task/funcs_x64_o2.dll')
            metadata_path.write_text(json.dumps(metadata), encoding='utf-8')
            reopened = await run(session, 'open_file', path=str(binary), analyze=False)
            assert reopened['projectId'] == project and reopened['sourcePath'] == str(binary)
            generated = await run(session, 'workspace_create', projectId=project, nativeTarget='shared')
            assert (await run(session, 'workspace_execute', projectId=project, action='build'))['status'] == 'passed'
            rebuilt = Path(generated['directory']) / 'build/x64/Debug/recovered.dll'
            original = await run(session, 'behavior_capture', projectId=project, executable=sys.executable, arguments=[str(runner), str(binary)])
            recovered = await run(session, 'behavior_capture', projectId=project, executable=sys.executable, arguments=[str(runner), str(rebuilt)])
            comparison = await run(session, 'behavior_compare', projectId=project, left=original['captureId'], right=recovered['captureId'])
            assert comparison['streams']['stdout']['same'], comparison
            plan = await run(session, 'patch_prepare', projectId=project, function='add3', engine='cdec',
                source='int replacement(int a,int b,int c){return a+b+c;}', symbol='replacement')
            patched = await run(session, 'patch_apply', projectId=project, planId=plan['planId'])
            assert patched['originalPreserved'] and Path(patched['path']).is_file()
            changed = await run(session, 'behavior_capture', projectId=project, executable=sys.executable, arguments=[str(runner), patched['path']])
            comparison = await run(session, 'behavior_compare', projectId=project, left=original['captureId'], right=changed['captureId'])
            assert not comparison['streams']['stdout']['same'], comparison
            assert (await run(session, 'patch_outputs', projectId=project))['copies']
            assert hashlib.sha256(binary.read_bytes()).hexdigest() == before
    asyncio.run(scenario())


def test_mcp_dotnet_reconstruction_managed_copy_debug_and_cancel(tmp_path):
    if not components.locate('netcoredbg'):
        pytest.skip('Official netcoredbg component is required')
    ctx = EngineContext(workdir=tmp_path / 'setup')
    sdk = workspace.dotnet_sdk(ctx)
    rc, out, err = process.run([sdk, '--version'], context=ctx)
    assert rc == 0, out + err
    root = tmp_path / 'original-source'
    root.mkdir()
    dependency = tmp_path / 'dependency'
    dependency.mkdir()
    (dependency / 'Local.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        f'<TargetFramework>net{out.split(".")[0]}.0</TargetFramework></PropertyGroup></Project>', encoding='utf-8')
    (dependency / 'Local.cs').write_text('public static class Local {public static int Identity(int v)=>v;}', encoding='utf-8')
    rc, dep_out, err = process.run([sdk, 'build', str(dependency), '-o', str(tmp_path / 'original')], context=ctx)
    assert rc == 0, dep_out + err
    (root / 'Sample.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
        f'<TargetFramework>net{out.split(".")[0]}.0</TargetFramework></PropertyGroup>'
        f'<ItemGroup><Reference Include="Local"><HintPath>{tmp_path / "original/Local.dll"}</HintPath></Reference></ItemGroup></Project>', encoding='utf-8')
    (root / 'Program.cs').write_text('using System; class Program { static int Value(int v)=>Local.Identity(v)+1; '
        'static void Main(){Console.WriteLine("original:"+Value(3));} }', encoding='utf-8')
    rc, out, err = process.run([sdk, 'build', str(root), '-o', str(tmp_path / 'original')], context=ctx)
    assert rc == 0, out + err
    binary = tmp_path / 'original/Sample.dll'
    before = hashlib.sha256(binary.read_bytes()).hexdigest()

    async def scenario():
        async with client(tmp_path / 'mcp') as session:
            opened = await run(session, 'open_file', path=str(binary), engine='ilspy', options={'symbols': False})
            project = opened['projectId']
            assert Path(opened['binaryPath']).name == 'Sample.dll', opened
            await run(session, 'workspace_create', projectId=project)
            assert (await run(session, 'workspace_execute', projectId=project, action='build'))['status'] == 'passed'
            result = await run(session, 'workspace_execute', projectId=project, action='run')
            assert result['status'] == 'passed' and 'original:4' in result['output'], result
            info = await run(session, 'workspace_info', projectId=project)
            source_root = Path(info['directory'])
            source_path = next(p for p in source_root.rglob('Program.cs') if 'obj' not in p.parts)
            source = await run(session, 'workspace_read', projectId=project, path=source_path.relative_to(source_root).as_posix())
            assert (source_root / 'references/Local.dll').is_file()
            assert 'Local.Identity(v) + 1' in source['text'], source
            await run(session, 'workspace_save', projectId=project, path=source['path'], text=source['text'].replace('Local.Identity(v) + 1', 'Local.Identity(v) + 40'), revision=source['revision'])
            listing = await run(session, 'managed_methods', projectId=project)
            method = next(m for m in listing['methods'] if m['name'] == 'Value')
            plan = await run(session, 'managed_patch_prepare', projectId=project, methodId=method['id'], symbols=True)
            patched = await run(session, 'patch_apply', projectId=project, planId=plan['planId'])
            result = await run(session, 'patch_run', projectId=project, receiptId=patched['receiptId'])
            assert result['status'] == 'passed' and 'original:43' in result['output'], result
            owning = await payload(session, 'op_debug_start', {'projectId': project, 'receiptId': patched['receiptId'], 'stopAtEntry': True, 'timeout': 60})
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                state = await run(session, 'debug_status', projectId=project)
                if state['status'] == 'paused':
                    break
                assert state['status'] not in ('failed', 'cancelled'), state
                await asyncio.sleep(.1)
            assert state['status'] == 'paused', state
            inspected = await run(session, 'debug_control', projectId=project, sessionId=state['sessionId'], stopId=state['stopId'], action='inspect')
            assert inspected['frames'], inspected
            await payload(session, 'cy_cancel_job', {'jobId': owning['jobId']})
            cancelled = await terminal(session, owning)
            assert cancelled['state'] == 'Cancelled', cancelled
            assert hashlib.sha256(binary.read_bytes()).hexdigest() == before
    asyncio.run(scenario())
