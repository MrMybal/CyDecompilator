import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from cytools_core import CyToolError
from cydec import components, javascript, service
from cydec.engines.base import EngineContext
from cydec.project import ProjectStore


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'store', ProjectStore(tmp_path / 'projects'))
    return tmp_path, EngineContext(workdir=tmp_path / 'jobs')


@pytest.mark.skipif(not shutil.which('node') or not components.locate('typescript'), reason='Node.js and parser required')
def test_electron_feature_ipc_preload_web_har_and_snapshot(setup):
    root, ctx = setup
    app = root / 'electron'
    app.mkdir()
    (app / 'main.js').write_text("""
const { ipcMain: ipc, BrowserWindow } = require('electron');
const path = require('path');
const win = new BrowserWindow({webPreferences:{preload:path.join(__dirname,'preload.js'),contextIsolation:true}});
win.loadFile('index.html');
ipc.handle('export-report', async (event,name) => { return 'report:'+name; });
function shadow(ipc) { ipc.handle('false-handler',()=>1); }
""", encoding='utf-8')
    (app / 'preload.js').write_text("""
const {contextBridge,ipcRenderer} = require('electron');
contextBridge.exposeInMainWorld('reports',{export: (name)=>ipcRenderer.invoke('export-report', name)});
""", encoding='utf-8')
    (app / 'renderer.ts').write_text("""
import {helper} from './helper';
function exportReport(name:string) { fetch('/api/report'); return window.reports.export(name); }
const label = 'Exporter le rapport';
""", encoding='utf-8')
    (app / 'helper.ts').write_text('export const helper = 1;', encoding='utf-8')
    (app / 'renderer.ts').write_text((app / 'renderer.ts').read_text() + "\ndocument.getElementById('export').addEventListener('click',exportReport);", encoding='utf-8')
    (app / 'index.html').write_text('<button id="export">Exporter le rapport</button><script src="renderer.ts"></script>', encoding='utf-8')
    (app / 'node_modules').mkdir()
    (app / 'node_modules/ignored.js').write_text('throw new Error("must not run")')
    project = service.application_open(str(app), ctx)
    pid = project['projectId']
    report = service.investigation_query(pid, 'export', 4, 1000)
    assert any(r['kind'] == 'bridge' for r in report['nodes'])
    assert any(e['kind'] == 'resolves-to' for e in report['edges'])
    assert any(e['kind'] == 'bridge-api-candidate' for e in report['edges'])
    assert any(e['kind'] == 'event-callback-candidate' for e in report['edges'])
    # Receiver shadowing prevents false attribution, including top-level ambiguity.
    assert not any(r['kind'] == 'ipc' and r['label'] == 'false-handler' for r in report['nodes'])
    assert any(u['code'] == 'excluded-directory' for u in report['unknowns'])
    original = service.investigation_source(pid, 'renderer.ts')
    (app / 'renderer.ts').write_text('changed externally')
    assert service.investigation_source(pid, 'renderer.ts') == original
    source = service.decompile(pid, 'renderer.ts', 'javascript', ctx)
    assert 'exportReport' in source['code']
    har = root / 'recording.har'
    har.write_text(json.dumps({'log':{'entries':[{'request':{'method':'GET','url':'https://example.test/api/report','headers':[{'name':'Cookie','value':'secret'}]},'response':{'status':200},'time':12}]}}))
    service.investigation_har(pid, str(har), ctx)
    report = service.investigation_query(pid, '/api/report', 1, 200)
    assert any(e['kind'] == 'network-candidate' and e['status'] == 'inferred' for e in report['edges'])
    assert any(r['status'] == 'observed' for r in report['nodes'])
    assert 'secret' not in json.dumps(report)
    snapshot = service.store.get(pid)
    (javascript.artifact_root(snapshot) / 'renderer.ts').write_text('tampered')
    with pytest.raises(CyToolError) as error:
        service.investigation_source(pid, 'renderer.ts')
    assert error.value.code == 'IntegrityFailure'


def asar_bytes(files):
    offset, entries, payload = 0, {}, b''
    for name, data in files.items():
        entries[name] = {'size':len(data),'offset':str(offset),
                         'integrity':{'algorithm':'SHA256','hash':hashlib.sha256(data).hexdigest()}}
        offset += len(data)
        payload += data
    header = json.dumps({'files':entries}).encode()
    padded = header + b'\0' * ((-len(header)) % 4)
    pickle = struct.pack('<II',4+len(padded),len(header)) + padded
    return struct.pack('<II',4,len(pickle)) + pickle + payload


def test_asar_bounds_integrity_traversal_and_unpacked(setup):
    root, ctx = setup
    path = root / 'app.asar'
    path.write_bytes(asar_bytes({'main.js':b'const x=1;'}))
    assert javascript.read_asar(path, ctx)[0]['main.js'] == b'const x=1;'
    bad = bytearray(path.read_bytes())
    bad[-1] ^= 1
    path.write_bytes(bad)
    with pytest.raises(CyToolError) as error:
        javascript.read_asar(path, ctx)
    assert error.value.code == 'IntegrityFailure'
    path.write_bytes(asar_bytes({'../escape.js':b'bad'}))
    with pytest.raises(CyToolError):
        javascript.read_asar(path, ctx)
    path.write_bytes(asar_bytes({'main.js':b'x'})[:-1])
    with pytest.raises(CyToolError):
        javascript.read_asar(path, ctx)
    assert not (root / 'escape.js').exists()


@pytest.mark.skipif(not shutil.which('node') or not components.locate('typescript'), reason='Node.js and parser required')
def test_ipc_uniqueness_source_maps_and_dynamic_unknowns(setup):
    root, ctx = setup
    app = root / 'source'
    app.mkdir()
    (app / 'main.js').write_text("const {ipcMain,BrowserWindow}=require('electron');const win=new BrowserWindow({});ipcMain.handle('save',()=>1);win.webContents.send('refresh');",encoding='utf-8')
    (app / 'preload.js').write_text("const {ipcRenderer}=require('electron');ipcRenderer.invoke('save');ipcRenderer.on('save',()=>0);ipcRenderer.on('refresh',()=>1);ipcRenderer.invoke(channel);\n//# sourceMappingURL=preload.js.map",encoding='utf-8')
    (app / 'preload.js.map').write_text(json.dumps({'version':3,'sources':['original.ts'],'sourcesContent':['const first = 1;'],
        'names':['originalName'],'mappings':'AAAAA','file':'preload.js'}))
    pid = service.application_open(str(app),ctx)['projectId']
    report = service.investigation_query(pid,'',0,1000)
    assert any(e['kind']=='ipc-channel-candidate' for e in report['edges'])
    ipc_nodes={n['id']:n for n in report['nodes'] if n['kind']=='ipc'}
    ipc_edges=[e for e in report['edges'] if e['kind']=='ipc-channel-candidate']
    assert len(ipc_edges)==2
    assert all(ipc_nodes[e['source']]['details']['direction']==ipc_nodes[e['target']]['details']['direction'] for e in ipc_edges)
    assert any(e['kind']=='source-map-position' for e in report['edges'])
    assert any(n['details'].get('mappedName')=='originalName' for n in report['nodes'])
    assert any(u['code']=='dynamic-ipc' for u in report['unknowns'])
    (app / 'second.js').write_text("const {ipcMain}=require('electron');ipcMain.handle('save',()=>2);",encoding='utf-8')
    pid2 = service.application_open(str(app),ctx)['projectId']
    assert pid2 != pid
    ambiguous = service.investigation_query(pid2,'',0,1000)
    ambiguous_nodes={n['id']:n for n in ambiguous['nodes']}
    assert not any(e['kind']=='ipc-channel-candidate' and ambiguous_nodes[e['source']]['label']=='save' for e in ambiguous['edges'])
    assert any(u['code']=='ambiguous-or-missing-ipc-handler' and u['handlers']==2 for u in ambiguous['unknowns'])


def test_source_map_vlq_invalid_positions_and_unmapped_segments():
    from cydec.source_maps import decode, lookup
    decoded=decode('AAAA,K;AACA',1,0)
    assert lookup(decoded,1,1)['line']==0
    assert lookup(decoded,1,6) is None
    assert lookup(decoded,2,1)['line']==1
    for value in ('g','AACA!','ACAA','D','AAAAAA'):
        with pytest.raises(ValueError):
            decode(value,1,0)


def test_capture_closes_owned_children(setup):
    import psutil
    root,ctx=setup
    source=root/'input.bin'
    source.write_bytes(b'child-project')
    pid=service.open_file(source,ctx)['projectId']
    code="import subprocess,sys,time;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);print(p.pid,flush=True);time.sleep(.3)"
    capture=service.behavior_capture(pid,ctx,sys.executable,['-c',code])
    child_pid=int(capture['stdout'].strip())
    assert not psutil.pid_exists(child_pid)


@pytest.mark.skipif(sys.platform!='win32',reason='Windows native process')
def test_short_native_windows_captures(setup):
    import os
    root,ctx=setup
    source=root/'input.bin'
    source.write_bytes(b'native-capture-project')
    pid=service.open_file(source,ctx)['projectId']
    executable=Path(os.environ['SystemRoot'])/'System32/cmd.exe'
    for _ in range(3):
        result=service.behavior_capture(pid,ctx,str(executable),['/d','/c','echo native-capture'])
        assert result['complete'] and result['exitCode']==0
        assert result['stdout'].strip()=='native-capture'


def test_captures_compare_exact_outputs_input_exit_and_files(setup):
    root, ctx = setup
    source = root / 'input.bin'
    source.write_bytes(b'capture-project')
    project = service.open_file(source, ctx)
    pid = project['projectId']
    code = "import sys,pathlib;value=sys.stdin.read();print('version:',sys.argv[1],value,end='');pathlib.Path('result.txt').write_text(sys.argv[1]);pathlib.Path('seed.txt').unlink()"
    first, second = root / 'v1.py', root / 'v2.py'
    first.write_text(code.replace('sys.argv[1]', "'one'"))
    second.write_text(code.replace('sys.argv[1]', "'two'"))
    a = service.behavior_capture(pid, ctx, sys.executable, [str(first)], 'interaction\n', seed_files={'seed.txt':'seed'})
    b = service.behavior_capture(pid, ctx, sys.executable, [str(second)], 'interaction\n', seed_files={'seed.txt':'seed'})
    diff = service.behavior_compare(pid, a['captureId'], b['captureId'])
    assert diff['sameScenario'] and diff['complete'] and not diff['observationsMatch']
    assert '-version: one interaction' in diff['streams']['stdout']['diff']
    assert diff['fileChanges'][0]['path'] == 'result.txt'
    assert {r['kind'] for r in a['changes']} == {'added','deleted'}
    assert a['stdout'].endswith('\n')
    c = service.behavior_capture(pid, ctx, sys.executable, [str(first)], 'interaction\n', seed_files={'seed.txt':'seed'})
    same = service.behavior_compare(pid, a['captureId'], c['captureId'])
    assert same['observationsMatch']
    assert len(service.behavior_captures(pid)['captures']) == 3
    assert source.read_bytes() == b'capture-project'
    with pytest.raises(CyToolError):
        service.behavior_compare(pid, '../escape', c['captureId'])


def test_capture_timeout_and_output_limits_are_partial_evidence(setup):
    root, ctx = setup
    source = root / 'input.bin'
    source.write_bytes(b'timeout-project')
    pid = service.open_file(source, ctx)['projectId']
    result = service.behavior_capture(pid, ctx, sys.executable, ['-c',"import time;print('before timeout',flush=True);time.sleep(20)"], timeout=1)
    assert not result['complete'] and result['failure'] == 'Timeout'
    assert result['stdout'] in ('before timeout\n', 'before timeout\r\n')
    limited = service.behavior_capture(pid, ctx, sys.executable, ['-c',"import sys;sys.stdout.write('x'*3000000)"])
    assert not limited['complete'] and limited['failure'] == 'ExecutionOutputLimit'
    assert len(limited['stdout']) <= 1024 ** 2


@pytest.mark.skipif(not components.locate('ghidra') or not components.locate('jdk'), reason='Ghidra/JDK required')
def test_real_ghidra_types_calls_and_value_dependencies(setup):
    root, ctx = setup
    fixture = APP / 'tests/fixtures/native/funcs_x64_o2.dll'
    project = service.open_file(fixture, ctx)
    pid = project['projectId']
    ctx.options = {'maxDecompile':0}
    service.analyze(pid, 'ghidra', ctx)
    functions = service.list_functions(pid, 'ghidra')['functions']
    selected = next(f for f in functions if 'add' in f['name'].lower())
    result = service.investigation_native(pid, selected['id'], ctx)
    dossier = result['dossier']
    assert dossier['instructions'] and dossier['operations'] and dossier['values']
    assert dossier['returnType']['name'] and dossier['targetSha256'] == project['sha256']
    report = service.investigation_query(pid, selected['name'], 4, 1000)
    assert any(e['kind'] == 'defines' for e in report['edges'])
    assert any(n['kind'] == 'signature' for n in report['nodes'])
