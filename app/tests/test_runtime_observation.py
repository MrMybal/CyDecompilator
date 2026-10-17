import json
import os
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cytools_core import CyToolError
from cydec import process, service
from cydec.engines.base import EngineContext
from cydec.project import ProjectStore
from cydec.runtime_observation import validate


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'store', ProjectStore(tmp_path / 'projects'))
    source = tmp_path / 'input.bin'
    source.write_bytes(b'runtime-observation-project')
    ctx = EngineContext(workdir=tmp_path / 'jobs')
    return tmp_path, ctx, service.open_file(source, ctx)['projectId']


@pytest.fixture
def server():
    class Handler(BaseHTTPRequestHandler):
        version = 'one'
        def do_GET(self):
            if self.path.startswith('/api/report'):
                body = self.version.encode()
                mime = 'text/plain'
            elif self.path == '/':
                body = b'''<!doctype html><title>Capture fixture</title><style>*{font-family:Arial}</style>
                <input id="name" aria-label="Name"><button id="go">Export report</button><p id="result">Ready</p>
                <script>document.getElementById('go').onclick=async function exportReport(){
                const r=await fetch('/api/report?name='+document.getElementById('name').value);
                document.getElementById('result').innerText=await r.text();console.log('export completed');};</script>'''
                mime = 'text/html'
            else:
                body, mime = b'', 'text/plain'
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:%d/' % http.server_port, Handler
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


CHROME = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')


@pytest.mark.skipif(not CHROME.is_file() or not shutil.which('node'), reason='Chrome and Node 22 required')
def test_real_renderer_network_graphics_and_integrity(setup, server):
    root, ctx, pid = setup
    url, handler = server
    observation = {'driver':'chromium', 'headless':True, 'network':True, 'url':url, 'settleMs':200,
        'steps':[{'action':'fill','selector':'#name','text':'sample'},
                 {'action':'click','selector':'#go'}, {'action':'assertText','selector':'#result','text':'o'}]}
    a = service.behavior_capture(pid, ctx, str(CHROME), timeout=40, observation=observation)
    assert a['complete'], a['runtime']
    evidence = service.behavior_evidence(pid, a['captureId'])
    assert len(evidence['images']) == 4
    assert all(Path(r['path']).read_bytes().startswith(b'\x89PNG') for r in evidence['images'])
    gui = a['runtime']['gui']
    assert all(r['status']=='passed' for r in gui['steps'])
    request = next(r for r in gui['requests'] if '/api/report?' in r['url'])
    assert request['method']=='GET' and request['status']==200 and request['finished']
    assert request['step']==1
    assert any(r['functionName']=='exportReport' for r in request['initiator'])
    assert gui['states'][-1]['state']['elements'][-1]['text']=='one'
    assert not any(k in request for k in ('headers','postData','body'))
    report=service.investigation_query(pid,'/api/report',2,200)
    assert any(r['kind']=='request-during-step' and r['status']=='observed' for r in report['edges'])
    c = service.behavior_capture(pid, ctx, str(CHROME), timeout=40, observation=observation)
    same = service.behavior_compare(pid, a['captureId'], c['captureId'])
    assert same['graphics']['same'], same
    # External browser/provider traffic can legitimately vary between executions.
    # The fixture's own HTTP observations must match exactly.
    from cydec.behavior import compare_network
    def local_http(record):
        return {'gui':{'requests':[r for r in record['runtime']['gui']['requests'] if r['url'].startswith(url)]}}
    assert compare_network(local_http(a),local_http(c))['same']
    handler.version = 'two'
    b = service.behavior_capture(pid, ctx, str(CHROME), timeout=40, observation=observation)
    assert b['complete'], b['runtime']
    diff = service.behavior_compare(pid, a['captureId'], b['captureId'])
    assert diff['sameScenario'] and not diff['observationsMatch']
    assert not diff['graphics']['states'][-1]['stateSame']
    assert not diff['graphics']['states'][-1]['pixelsSame']
    image = Path(evidence['images'][0]['path'])
    image.write_bytes(b'tampered')
    with pytest.raises(CyToolError) as error:
        service.behavior_evidence(pid, a['captureId'])
    assert error.value.code == 'IntegrityFailure'


@pytest.mark.skipif(not CHROME.is_file() or not shutil.which('node'), reason='Chrome and Node 22 required')
def test_renderer_failed_step_is_partial_and_stops_target(setup, server):
    root, ctx, pid = setup
    result = service.behavior_capture(pid, ctx, str(CHROME), timeout=30,
        observation={'driver':'chromium','headless':True,'url':server[0],'settleMs':0,
                     'steps':[{'action':'click','selector':'#absent'}]})
    assert not result['complete']
    assert result['runtime']['gui']['steps'][0]['status']=='failed'
    assert 'exactly one' in result['runtime']['gui']['error']
    assert result['runtime']['termination']=='scenario-failed'


@pytest.mark.skipif(not CHROME.is_file() or not shutil.which('node'), reason='Chrome and Node 22 required')
def test_renderer_timeout_stops_the_observer_and_owned_target(setup,server,monkeypatch):
    import psutil
    root,ctx,pid=setup
    launched=[]
    original=process.run
    def record_launch(command,**kwargs):
        callback=kwargs.get('on_started')
        def started(target):
            launched.append((str(command[0]),target.pid))
            if callback:callback(target)
        return original(command,**{**kwargs,'on_started':started})
    monkeypatch.setattr(process,'run',record_launch)
    record=service.behavior_capture(pid,ctx,str(CHROME),timeout=3,
        observation={'driver':'chromium','headless':True,'url':server[0],'settleMs':0,
                     'steps':[{'action':'wait','ms':10000}]})
    assert not record['complete'] and record['failure']=='Timeout'
    assert len(launched)>=2
    assert all(not psutil.pid_exists(p) for _,p in launched),launched


@pytest.mark.skipif(os.name!='nt', reason='Windows UI Automation required')
def test_real_windows_controls_and_screenshots(setup):
    root, ctx, pid = setup
    framework = Path(os.environ['SystemRoot'])/'Microsoft.NET/Framework64/v4.0.30319'
    source, executable = root/'Fixture.cs', root/'Fixture.exe'
    source.write_text('''using System;using System.Windows.Forms;using System.IO;
    class QuietForm:Form{protected override bool ShowWithoutActivation{get{return true;}}}
    class QuietInput:TextBox{protected override void WndProc(ref Message m){if(m.Msg==0x102)return;base.WndProc(ref m);}}
    class Fixture{[STAThread]static void Main(){var f=new QuietForm{Text="CyDecompilator capture fixture",Width=480,Height=220};
    var input=new QuietInput{Name="input",AccessibleName="Name",Top=20,Left=20,Width=200};
    var output=new Label{Name="result",AccessibleName="Ready",Top=100,Left=20,Width=300};
    var button=new Button{Name="go",AccessibleName="Export report",Text="Export report",Top=55,Left=20,Width=200};
    button.Click+=(s,e)=>{output.Text="Hello "+input.Text;output.AccessibleName=output.Text;File.WriteAllText("result.txt",output.Text);};
    f.Controls.AddRange(new Control[]{input,button,output});Application.Run(f);}}''', encoding='utf-8')
    code, out, err = process.run([framework/'csc.exe','/nologo','/target:winexe','/out:'+str(executable),
        '/reference:'+str(framework/'System.Windows.Forms.dll'),'/reference:'+str(framework/'System.Drawing.dll'),source],context=ctx,timeout=30)
    assert code==0, out+err
    result = service.behavior_capture(pid, ctx, str(executable), timeout=40,
        observation={'driver':'windows','settleMs':200,'steps':[
            {'action':'fill','selector':{'name':'Name'},'text':'sample'},
            {'action':'click','selector':{'name':'Export report'}},
            {'action':'assertText','selector':{'name':'Hello sample'},'text':'Hello sample'}]})
    assert result['complete'], result['runtime']
    assert result['runtime']['termination']=='scenario-complete'
    assert all(r['status']=='passed' for r in result['runtime']['gui']['steps'])
    evidence = service.behavior_evidence(pid, result['captureId'])
    assert len(evidence['images'])==4
    assert (service.store.get(pid).dir/'investigation/captures'/result['captureId']/'working/result.txt').read_text()=='Hello sample'


@pytest.mark.parametrize('options',[
    {'driver':'none','steps':[{'action':'click','selector':'#go'}]},
    {'driver':'chromium','steps':[{'action':'evaluate','text':'process.exit()'}]},
    {'driver':'chromium','steps':[{'action':'navigate','url':'javascript:alert(1)'}]},
    {'driver':'chromium','network':'true'},
    {'driver':'windows','steps':[{'action':'click','selector':{'pid':1}}]},
])
def test_scenario_rejects_unbounded_or_unsupported_actions(options):
    with pytest.raises(CyToolError):
        validate(options)


def test_passive_tcp_capture_is_scoped_to_owned_processes(setup):
    import socket
    root,ctx,pid=setup
    listener=socket.socket()
    listener.bind(('127.0.0.1',0))
    listener.listen()
    port=listener.getsockname()[1]
    def accept():
        client,_=listener.accept()
        client.recv(1)
        client.close()
    thread=threading.Thread(target=accept,daemon=True)
    thread.start()
    try:
        code="import socket,time;s=socket.create_connection(('127.0.0.1',%d));time.sleep(1);s.send(b'x');s.close()" % port
        record=service.behavior_capture(pid,ctx,sys.executable,['-c',code],observation={'network':True})
        assert record['complete']
        assert record['runtime']['connections']
        assert all(r['remotePort']==port for r in record['runtime']['connections'])
        assert all(r['pid']!=os.getpid() for r in record['runtime']['connections'])
        graph=service.investigation_query(pid,str(port),1,200)
        assert any(n['kind']=='tcp-connection' and n['status']=='observed' for n in graph['nodes'])
    finally:
        listener.close()
        thread.join(timeout=3)
