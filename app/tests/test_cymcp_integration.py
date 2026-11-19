"""Real compiled SDK + business handlers; loopback providers avoid cloud credentials."""
import asyncio
import base64
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest
APP=Path(__file__).resolve().parents[1];ROOT=APP.parent
sys.path.insert(0,str(APP))
from tool import create_runtime,declared_permissions
from cydec import service
from cydec.project import ProjectStore
from cydec.mcp import CyToolError,Native
from cydec.mcp.transport import make_server,HTTPClient

@pytest.fixture
def instance(tmp_path,monkeypatch):
    monkeypatch.setenv('CYTOOLS_TOKEN','explicit-test-identity');monkeypatch.delenv('CYMCP_TOKEN',raising=False)
    monkeypatch.setattr(service,'store',ProjectStore(tmp_path/'projects'))
    runtime=create_runtime(tmp_path/'jobs');runtime.start()
    identity=runtime.create_client('test',declared_permissions(runtime));actor=runtime.authenticate(identity['token'])
    session=runtime.create_session(actor,temporary=False)['sessionId']
    yield runtime,actor,session,identity['token']
    runtime.close(30)

def run(instance,name,**parameters):
    runtime,actor,session,*_=instance
    job=runtime.submit(actor,session,name,parameters)
    result=runtime.wait(actor,job['jobId'],30)
    assert result['state']=='Completed',result.get('error')
    return result

@contextmanager
def provider(project_id):
    entered=threading.Event();release=threading.Event();requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            data=json.dumps({'data':[{'id':'fixture-model','object':'model'}]}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_POST(self):
            request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(request)
            messages=request.get('messages',[]);text=json.dumps(messages)
            if 'slow-turn' in text:
                entered.set();release.wait(5)
            used=any(m.get('role')=='tool' for m in messages)
            if not used and ('change-notes' in text or 'remote-edit' in text or 'remote-error' in text):
                names=[t['function']['name'] for t in request.get('tools',[])]
                compact='cy_tools_call' in names
                args={'projectId':project_id,'text':'SDK business mutation verified'}
                operation='set_notes'
                if 'remote-edit' in text or 'remote-error' in text:
                    if 'remote-error' in text:args['projectId']='missing'
                    operation='remote_call';args={'server':'application-b','tool':'set_notes','arguments':args}
                function={'name':'cy_tools_call' if compact else operation,'arguments':json.dumps({'name':operation,'arguments':args} if compact else args)}
                deltas=[{'tool_calls':[{'index':0,'id':'tool-1','type':'function','function':function}]}];finish='tool_calls'
            else:deltas=[{'content':'Streamed '},{'content':'SDK answer.'}];finish='stop'
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            try:
                for delta in deltas:
                    value={'id':'fixture','choices':[{'index':0,'delta':delta,'finish_reason':None}]}
                    self.wfile.write(('data: '+json.dumps(value)+'\n\n').encode());self.wfile.flush();time.sleep(.5 if 'ui-stream-demo' in text else .02)
                self.wfile.write(('data: '+json.dumps({'choices':[{'index':0,'delta':{},'finish_reason':finish}]})+'\n\ndata: [DONE]\n\n').encode());self.wfile.flush()
            except (ConnectionError,OSError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield 'http://127.0.0.1:'+str(server.server_port)+'/v1',entered,release,requests
    finally:release.set();server.shutdown();server.server_close();thread.join(3)

def configure_provider(monkeypatch,tmp_path,url):
    from cydec.ai import assistant
    path=tmp_path/'ai-settings.json';path.write_text(json.dumps({'provider':'openai-compatible','model':'fixture-model','providers':{'openai-compatible':{'base_url':url}}}),'utf-8')
    monkeypatch.setattr(assistant,'SETTINGS_FILE',path)

def test_sdk_chat_streams_calls_real_tool_and_restores(instance,tmp_path,monkeypatch):
    runtime,actor,session,_=instance
    project=run(instance,'open_file',path=str(APP/'tests/fixtures/shaders/lit_frag.spv'))['outputs']['projectId']
    with provider(project) as (url,_,__,requests):
        configure_provider(monkeypatch,tmp_path,url)
        job=run(instance,'assistant_send',text='change-notes',projectId=project,allowEdits=True)
        out=job['outputs'];assert out['answer']=='Streamed SDK answer.'
        assert service.project_for(project).annotations()['notes']=='SDK business mutation verified'
        events=runtime.events(actor)['events'];assert any(e['type']=='AiDelta' and 'Streamed' in e['data']['text'] for e in events)
        assert any(e['type']=='AiTool' for e in events)
        assert any(j.get('parentJobId')==job['jobId'] and j['operationId']=='set_notes' and j['state']=='Completed' for j in runtime.list_jobs(actor))
        identifier=out['conversationId'];before=runtime.assistant.history(actor,identifier)['history']
        assert any(m['role']=='tool' for m in before)
        runtime.assistant.native.call('conversationClose',id=identifier);runtime.assistant.opened.clear()
        out2=run(instance,'assistant_send',text='Continue.',conversationId=identifier,projectId=project)['outputs']
        after=runtime.assistant.history(actor,identifier)['history'];assert len(after)>len(before)
        assert out2['conversationId']==identifier and requests[-1]['messages'][0]['role']=='system'

def test_chat_cancellation_and_read_only_grant(instance,tmp_path,monkeypatch):
    runtime,actor,session,_=instance
    project=run(instance,'open_file',path=str(APP/'tests/fixtures/shaders/lit_vs.cso'))['outputs']['projectId']
    with provider(project) as (url,entered,release,requests):
        configure_provider(monkeypatch,tmp_path,url)
        result=run(instance,'assistant_send',text='change-notes',projectId=project,allowEdits=False)
        assert service.project_for(project).annotations().get('notes','')!='SDK business mutation verified'
        assert 'set_notes' not in [t['function']['name'] for t in requests[0].get('tools',[])]
        job=runtime.submit(actor,session,'assistant_send',{'text':'slow-turn'})
        assert entered.wait(5);runtime.cancel(actor,job['jobId']);release.set()
        result=runtime.wait(actor,job['jobId'],10)
        assert result['state']=='Cancelled',result

def test_live_instance_cli_and_mcp_share_rights(instance,tmp_path):
    runtime,actor,session,token=instance
    server=make_server(runtime,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        url='http://127.0.0.1:'+str(server.server_port)+'/v1';client=HTTPClient(url,token)
        assert client.call('SDKInfo')['version']=='0.7.0'
        params=tmp_path/'read.json';params.write_text('{}','utf-8')
        env={**os.environ,'CYMCP_TOKEN':token}
        proc=subprocess.run([sys.executable,str(APP/'tool.py'),'--connect',url,'invoke','list_projects','--params-file',str(params)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=15)
        assert proc.returncode==0,proc.stderr;assert json.loads(proc.stdout)['state']=='Completed'
        restricted=runtime.create_client('restricted',[]);other=HTTPClient(url,restricted['token'])
        denied=other.call('CreateSession',temporary=False)
        with pytest.raises(CyToolError,match='permissions'):other.call('SubmitJob',sessionId=denied['sessionId'],operationId='install_component',parameters={'component':'vineflower'})
        initialized=runtime.native.call('mcp',principal=restricted['clientId'],request={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'rights-test','version':'1'}}})
        assert initialized.get('result',{}).get('protocolVersion')
        response=runtime.native.call('mcp',principal=restricted['clientId'],request={'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'install_component','arguments':{'component':'vineflower'}}})
        assert response.get('result',{}).get('isError') or response.get('error')
        with pytest.raises(CyToolError,match='confirm'):client.call('SubmitJob',sessionId=session,operationId='delete_project',parameters={'projectId':'anything'})
    finally:server.shutdown();server.server_close();thread.join(3)

def test_results_survive_restart_and_chunk_reads(instance,tmp_path):
    runtime,actor,session,token=instance
    job=run(instance,'list_projects');root=runtime.root;runtime.close()
    restarted=create_runtime(root);restarted.start()
    try:
        same=restarted.authenticate(token);assert restarted.get_job(same,job['jobId'])['outputs']==job['outputs']
        from cydec.mcp.api import LocalClient
        part=LocalClient(restarted,same).call('ReadResult',jobId=job['jobId'],offset=0,length=65536)
        assert json.loads(base64.b64decode(part['data']))==job['outputs']
    finally:restarted.close()

def test_private_large_results_expire_without_replay(tmp_path):
    n=Native(lambda request:{'allowed':True},directory=tmp_path,options={'spoolRoot':str(tmp_path/'chosen-spool'),'retentionSeconds':1,'memoryBytes':1024**2,'diskBytes':8*1024**2,'chunkBytes':8192})
    try:
        text='unique retained text\n'*100000
        result=n.call('store',text=text,principal='alice')
        assert n.call('stats')['storage']
        assert any((tmp_path/'chosen-spool').iterdir())
        uri=result.get('uri') or result.get('firstUri')
        assert uri,result
        with pytest.raises(CyToolError):n.call('read',uri=uri,principal='bob')
        first=n.call('read',uri=uri,principal='alice')
        manifest=json.loads(first['contents'][0]['text']);next_uri=manifest['firstUri'];pieces=[]
        while next_uri:
            page=n.call('read',uri=next_uri,principal='alice')
            pieces.append(page['contents'][0]['text'])
            next_uri=page['_meta']['com.cymcp/chunk'].get('nextUri')
        assert ''.join(pieces)==text
        time.sleep(1.1)
        with pytest.raises(CyToolError):n.call('read',uri=uri,principal='alice')
    finally:n.close()

def test_external_mcp_client_uses_real_tools_and_errors(instance,tmp_path):
    runtime,actor,session,token=instance
    project=run(instance,'open_file',path=str(APP/'tests/fixtures/shaders/lit_frag.spv'))['outputs']['projectId']
    bootstrap=tmp_path/'remote-server.py'
    bootstrap.write_text('import sys\nfrom pathlib import Path\n'+f'sys.path.insert(0,{str(APP)!r})\n'+'import tool\nfrom cydec.project import ProjectStore\n'+f'tool.service.store=ProjectStore(Path({str(tmp_path/"projects")!r}))\n'+f'raise SystemExit(tool.run_cli(tool.create_runtime,["--data-dir",{str(tmp_path/"remote-jobs")!r},"mcp"]))\n','utf-8')
    config={'servers':{'application-b':{'executable':sys.executable,'arguments':[str(bootstrap)],'allowedTools':['list_projects','set_notes']}}}
    runtime.assistant.config_file.parent.mkdir(parents=True,exist_ok=True);runtime.assistant.config_file.write_text(json.dumps(config),'utf-8')
    tools=run(instance,'remote_tools',server='application-b')['outputs']['tools'];assert {t['name'] for t in tools}=={'list_projects','set_notes'}
    out=run(instance,'remote_call',server='application-b',tool='set_notes',arguments={'projectId':project,'text':'External SDK tool changed real notes'})
    assert service.project_for(project).annotations()['notes']=='External SDK tool changed real notes'
    denied=runtime.submit(actor,session,'remote_call',{'server':'application-b','tool':'delete_project','arguments':{'projectId':project}})
    assert runtime.wait(actor,denied['jobId'],10)['error']['code']=='AccessDenied'
    failure=runtime.submit(actor,session,'remote_call',{'server':'application-b','tool':'set_notes','arguments':{'projectId':'missing','text':'no'}})
    assert runtime.wait(actor,failure['jobId'],10)['error']['code']=='RemoteToolFailed'

    # The same approved remote tool must also be callable by the actual chat loop.
    from unittest.mock import patch
    from cydec.ai import assistant
    with provider(project) as (url,_,__,requests):
        settings=tmp_path/'remote-ai.json'
        settings.write_text(json.dumps({'provider':'openai-compatible','model':'fixture-model','providers':{'openai-compatible':{'base_url':url}}}),'utf-8')
        with patch.object(assistant,'SETTINGS_FILE',settings):
            result=run(instance,'assistant_send',text='remote-edit',projectId=project)
        assert result['outputs']['answer']=='Streamed SDK answer.'
        assert service.project_for(project).annotations()['notes']=='SDK business mutation verified'
        assert any(j['operationId']=='remote_call' and j.get('parentJobId')==result['jobId'] for j in runtime.list_jobs(actor))
        with patch.object(assistant,'SETTINGS_FILE',settings):
            run(instance,'assistant_send',text='remote-error')
        assert 'RemoteToolFailed' in json.dumps(requests[-1]['messages'])


def test_temperature_discovery_and_host_deadline(instance,tmp_path,monkeypatch):
    runtime,actor,session,_=instance
    with provider('unused') as (url,entered,release,requests):
        configure_provider(monkeypatch,tmp_path,url)
        native=Native(directory=tmp_path/'api')
        try:
            native.call('conversationOpen',id='sampling',provider='openai-compatible',model='fixture-model',settings={'base_url':url,'temperature':.25})
            native.call('conversationSend',id='sampling',content='sampling-test')
            assert requests[-1]['temperature']==.25
            found=native.call('discover',configured={'openai-compatible':{'settings':{'base_url':url}}})
            assert isinstance(found,list) and any(p['id']=='openai-compatible' for p in found)
        finally:native.close()
        job=runtime.submit(actor,session,'assistant_send',{'text':'slow-turn'},execution_timeout=.2)
        assert entered.wait(5)
        result=runtime.wait(actor,job['jobId'],5);release.set()
        assert result['state']=='Failed' and result['error']['code']=='Timeout',result

def test_context_projection_preserves_history_and_metrics_omit_content(tmp_path):
    with provider('unused') as (url,_,__,requests):
        n=Native(directory=tmp_path/'sdk',options={'telemetry':True})
        history=[]
        for index in range(30):history.extend([{'role':'user','content':'old question '+str(index)},{'role':'assistant','content':'private-canary-'+('answer '*500)}])
        try:
            n.call('conversationOpen',id='context-test',provider='openai-compatible',model='fixture-model',system='Pinned system instruction',settings={'base_url':url},history=history,contextBytes=4096,recentTurns=2)
            n.call('conversationSend',id='context-test',content='Active user question')
            snapshot=n.call('conversationCheckpoint',id='context-test')
            assert len(snapshot['messages'])==len(history)+3
            sent=requests[-1]['messages'];assert len(sent)<len(snapshot['messages'])
            assert sent[0]['content']=='Pinned system instruction' and sent[-1]['content']=='Active user question'
        finally:n.close()
        metrics=(tmp_path/'sdk/metrics.jsonl').read_text('utf-8')
        assert 'private-canary' not in metrics and 'Active user question' not in metrics


def test_native_cache_notifications_invalidate_before_ttl(tmp_path):
    bootstrap=tmp_path/'change-server.py'
    bootstrap.write_text('''import sys
from pathlib import Path
sys.path.insert(0, APP_PATH)
from cydec.mcp import Native
from cydec.mcp.runtime import Principal
from cydec.mcp.transport import serve_stdio
class Host:
    def __init__(self):
        self._notification_sinks={};self._transport_sessions={};self.count=0
        self.native=Native(self.callback,directory=Path(__file__).parent/'child-sdk')
    def callback(self,r):
        if r['type']=='authorize':return {'allowed':True}
        if r['type']=='notification':
            sink=self._notification_sinks.get(r['principal'])
            if sink:sink(r['payload'])
        if r['type']=='invoke':
            self.count+=1
            self.native.call('resource',uri='fixture://state',text=str(self.count))
            return {'count':self.count}
        return {}
h=Host()
h.native.call('register',operation={'name':'mutate','description':'Change fixture state.','inputSchema':{'type':'object','properties':{},'additionalProperties':False},'outputSchema':{'type':'object'},'readOnly':False})
h.native.call('resource',uri='fixture://state',text='0')
try:serve_stdio(h,Principal('peer',frozenset()))
finally:h.native.close()
'''.replace('APP_PATH',repr(str(APP))),'utf-8')
    n=Native(directory=tmp_path/'client')
    try:
        n.call('remoteConnect',id='peer',config={'executable':sys.executable,'arguments':[str(bootstrap)]})
        def read():return n.call('remoteRead',id='peer',uri='fixture://state')['contents'][0]['text']
        assert read()=='0' and read()=='0'
        assert n.call('remoteCacheStats',id='peer')['hits']>=1
        n.call('remoteNotifications',id='peer',start=True)
        # Subscription setup is asynchronous; wait for its acknowledged state.
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            status=n.call('remoteNotifications',id='peer')
            if status['status'].get('state')=='active':break
            time.sleep(.02)
        a=n.call('remoteCall',id='peer',name='mutate',arguments={})
        b=n.call('remoteCall',id='peer',name='mutate',arguments={})
        assert a!=b  # Mutations never reuse a cached result.
        deadline=time.monotonic()+3;events=[]
        while time.monotonic()<deadline:
            events+=n.call('remoteNotifications',id='peer')['events']
            if events:break
            time.sleep(.02)
        assert events and read()=='2'
    finally:n.close()


def test_conversation_delegation_is_scoped_and_revocable(instance):
    runtime,actor,session,_=instance
    project=run(instance,'open_file',path=str(APP/'tests/fixtures/shaders/lit_frag.spv'))['outputs']['projectId']
    unrelated=run(instance,'list_projects')
    identifier='delegation-fixture'
    runtime.assistant._mcp_route(actor,identifier,['set_notes','cy_list_jobs','cy_get_job'],project)
    client=runtime.assistant.delegations[identifier];delegate=client['clientId'];grant=runtime._delegations[delegate]
    initialized=runtime.native.call('mcp',principal=delegate,request={'jsonrpc':'2.0','id':0,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'delegation-test','version':'1'}}})
    assert initialized.get('result',{}).get('protocolVersion')
    def call(name,args):
        response=runtime.native.call('mcp',principal=delegate,request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}})
        return response.get('result') or {'isError':True,'error':response.get('error')}
    assert call('set_notes',{'projectId':project,'text':'no-active-turn'}).get('isError')
    grant['parentJobId']=unrelated['jobId']
    assert not call('set_notes',{'projectId':project,'text':'Delegated mutation verified'}).get('isError')
    assert service.project_for(project).annotations()['notes']=='Delegated mutation verified'
    assert call('set_notes',{'projectId':'another-project','text':'denied'}).get('isError')
    assert call('delete_project',{'projectId':project}).get('isError')
    assert call('cy_get_job',{'jobId':unrelated['jobId']}).get('isError')
    runtime._delegations.pop(delegate)
    assert call('set_notes',{'projectId':project,'text':'revoked'}).get('isError')


def test_native_workspace_search_confines_and_checks_revisions(tmp_path):
    import shutil
    if not shutil.which('rg'):pytest.skip('ripgrep is an optional host dependency')
    root=tmp_path/'workspace';root.mkdir();text=root/'sample.txt';text.write_bytes(b'needle\nunchanged\n')
    n=Native(lambda r:{'allowed':True},directory=tmp_path/'sdk',options={'ripgrep':True,'workspaceRoot':str(root)})
    try:
        found=n.call('fileGrep',arguments={'pattern':'needle'})
        assert 'sample.txt' in json.dumps(found)
        part=n.call('fileRead',arguments={'path':'sample.txt','length':7})
        assert part['text']=='needle\n'
        with pytest.raises(CyToolError):n.call('fileRead',arguments={'path':'../outside.txt'})
        text.write_text('different text\n','utf-8')
        with pytest.raises(CyToolError,match='changed'):n.call('fileRead',arguments={'path':'sample.txt','revision':part['revision']})
    finally:n.close()


def test_direct_mcp_cancellation_stops_the_business_handler(instance):
    runtime,actor,_,__=instance;entered=threading.Event();response=[]
    def slow(context,arguments):
        entered.set();context.cancellation.sleep(10)
        pytest.fail('Cancelled native MCP work must not reach this point')
    runtime._handlers['list_projects']=slow
    def request(value):return runtime.native.call('mcp',principal=actor.client_id,scope='cancel-test',request=value)
    initialized=request({'jsonrpc':'2.0','id':0,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'cancel-test','version':'1'}}})
    assert initialized.get('result')
    worker=threading.Thread(target=lambda:response.append(request({'jsonrpc':'2.0','id':'slow-call','method':'tools/call','params':{'name':'list_projects','arguments':{}}})))
    worker.start();assert entered.wait(3)
    request({'jsonrpc':'2.0','method':'notifications/cancelled','params':{'requestId':'slow-call','reason':'User cancelled'}})
    worker.join(3);assert not worker.is_alive()
    assert 'Cancelled' in json.dumps(response)
    assert any(j['operationId']=='list_projects' and j['state']=='Cancelled' for j in runtime.list_jobs(actor))


def test_function_assistance_adapter_preserves_options_and_history(tmp_path):
    from cydec.ai.providers.sdk import Registry
    from cydec.ai.providers.base import ChatRequest
    with provider('unused') as (url,_,__,requests):
        registry=Registry({'openai-compatible':{'base_url':url}},tmp_path/'function-ai',options={'contextBytes':4096,'recentTurns':2})
        history=[m for i in range(20) for m in ({'role':'user','content':'previous question '+str(i)},{'role':'assistant','content':'long previous answer '*200})]
        deltas=[]
        try:
            result=registry.get('openai-compatible').chat(ChatRequest(prompt='Current function question',messages=history,system_prompt='Pinned function instruction',model='fixture-model',settings={'temperature':.3}),lambda *d:deltas.append(d))
            assert result['text']=='Streamed SDK answer.' and deltas
            sent=requests[-1]
            assert sent['temperature']==.3 and 2<len(sent['messages'])<len(history)
            assert sent['messages'][0]['content']=='Pinned function instruction'
            assert sent['messages'][-1]['content']=='Current function question'
            assert len(history)==40
        finally:registry.close()
