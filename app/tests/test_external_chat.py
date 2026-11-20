"""External chats use the real native dispatcher without a window or embedded model."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest
from mcp import ClientSession,StdioServerParameters,types
from mcp.client.stdio import stdio_client

from test_cymcp_integration import APP,ROOT,instance
from cydec import service
from cydec.mcp import Native,CyToolError
from cydec.mcp.instance import automation_identity,client_configuration,discover,MARKER,VAULT,local_url
from cydec.mcp.transport import LiveServer


@asynccontextmanager
async def client(tmp_path,arguments,*,token='',factory='tool.create_runtime'):
    tmp_path.mkdir(parents=True,exist_ok=True)
    script=tmp_path/'client-server.py'
    script.write_text('import sys\n'+f'sys.path.insert(0,{str(APP)!r})\nimport tool\n'+
                      f'raise SystemExit(tool.run_cli({factory},{arguments!r}))\n','utf-8')
    env=dict(os.environ);env.pop('CYTOOLS_TOKEN',None);env.pop('CYMCP_TOKEN',None)
    if token:env['CYMCP_TOKEN']=token
    params=StdioServerParameters(command=sys.executable,args=[str(script)],env=env,cwd=str(ROOT))
    async with stdio_client(params) as (reader,writer):
        async with ClientSession(reader,writer) as session:
            await session.initialize();yield session


async def call(session,name,arguments):
    result=await session.call_tool(name,arguments)
    assert not result.isError,result.content
    return json.loads(result.content[0].text)


def test_auto_attaches_to_actual_instance_without_starting_another_runtime(instance,tmp_path):
    runtime,_,__,___=instance
    async def scenario():
        # A fallback here would fail rather than hide a second store behind the test.
        forbidden='lambda *a,**k: (_ for _ in ()).throw(RuntimeError("Must attach to the owning instance"))'
        async with client(tmp_path/'client',['--data-dir',str(runtime.root),'mcp','--auto','--full'],factory=forbidden) as session:
            catalogue=await session.list_tools();assert 'workspace_execute' in {t.name for t in catalogue.tools}
            opened=await call(session,'open_file',{'path':str(APP/'tests/fixtures/shaders/lit_frag.spv'),'engine':'shader'})
            project=opened['projectId']
            changed=await call(session,'set_notes',{'projectId':project,'text':'External chat operated the live instance'})
            assert service.project_for(project).annotations()['notes']=='External chat operated the live instance'
            actor,_=automation_identity(runtime)
            assert runtime.get_job(actor,changed['_jobId'])['state']=='Completed'
            return project,changed['_jobId']
    with LiveServer(runtime,0,advertise=True):
        endpoint=discover(runtime.root);assert endpoint.instance_id==runtime.instance_id
        project,job=asyncio.run(scenario())
        # A fresh external chat can recover the result under the stable local identity.
        async def resume():
            async with client(tmp_path/'next-client',['--data-dir',str(runtime.root),'mcp','--auto','--full']) as session:
                assert (await call(session,'cy_get_job',{'jobId':job}))['state']=='Completed'
        asyncio.run(resume())
        metadata=(runtime.root/MARKER).read_text('utf-8')
        assert endpoint.token not in metadata and endpoint.token not in json.dumps(client_configuration(runtime.root))
        with pytest.raises(CyToolError) as error:discover(runtime.root,'deliberately-invalid')
        assert error.value.code=='AuthenticationRequired'
    assert not (runtime.root/MARKER).exists()


def test_auto_starts_headless_and_reuses_identity_after_restart(tmp_path):
    jobs=tmp_path/'jobs'
    async def first():
        async with client(tmp_path/'first',['--data-dir',str(jobs),'mcp','--auto','--full']) as session:
            tools=await session.list_tools();assert 'open_file' in {t.name for t in tools.tools}
            result=await call(session,'list_components',{})
            return result['_jobId']
    job=asyncio.run(first());assert not (jobs/MARKER).exists()
    assert not (jobs/VAULT).is_file() # Free headless access needs no generated credential.
    async def second():
        async with client(tmp_path/'second',['--data-dir',str(jobs),'mcp','--auto','--full']) as session:
            result=await call(session,'cy_get_job',{'jobId':job});assert result['state']=='Completed'
    asyncio.run(second())


def test_explicit_proxy_keeps_permissions_and_discovers_full_catalogue(instance,tmp_path):
    runtime,_,__,___=instance;identity=runtime.create_client('restricted external chat',[])
    from mcp.shared.exceptions import McpError
    async def scenario(endpoint):
        async with client(tmp_path/'explicit',['--connect',endpoint,'mcp','--full'],token=identity['token']) as session:
            assert 'install_component' in {t.name for t in (await session.list_tools()).tools}
            try:
                result=await session.call_tool('install_component',{'component':'vineflower'})
                assert result.isError
            except McpError as exc:assert 'permission' in str(exc).lower()
    with LiveServer(runtime,0) as server:
        asyncio.run(scenario('http://127.0.0.1:'+str(server.server.server_port)+'/v1'))


def test_connections_do_not_share_cancellation_ids(instance,tmp_path):
    runtime,_,__,___=instance;entered=[];release=threading.Event()
    def slow(context,arguments):
        entered.append(context.job_id)
        while not release.wait(.02):context.cancellation.check()
        context.cancellation.check();return {'ok':True}
    runtime._handlers['list_projects']=slow
    async def scenario():
        args=['--data-dir',str(runtime.root),'mcp','--auto','--full']
        async with client(tmp_path/'one',args) as first,client(tmp_path/'two',args) as second:
            first_id=first._request_id;assert first_id==second._request_id
            a=asyncio.create_task(first.call_tool('list_projects',{}));b=asyncio.create_task(second.call_tool('list_projects',{}))
            for _ in range(100):
                if len(entered)==2:break
                await asyncio.sleep(.02)
            assert len(entered)==2
            await first.send_notification(types.ClientNotification.model_validate({'method':'notifications/cancelled','params':{'requestId':first_id,'reason':'Cancel only this chat'}}))
            for _ in range(100):
                if any(runtime._jobs[j]['state']=='Cancelled' for j in entered):break
                await asyncio.sleep(.02)
            assert sum(runtime._jobs[j]['state']=='Cancelled' for j in entered)==1
            assert not b.done();release.set();assert not (await b).isError
            from mcp.shared.exceptions import McpError
            try:assert (await a).isError
            except McpError as exc:assert 'cancel' in str(exc).lower()
    try:
        with LiveServer(runtime,0,advertise=True):asyncio.run(scenario())
    finally:release.set()


@pytest.mark.parametrize('url',['http://127.0.0.1:80@evil.example/v1','https://localhost:1/v1','http://localhost:2/v1?token=x','http://example.com:3/v1',None])
def test_instance_credentials_are_confined_to_loopback(url):
    with pytest.raises(CyToolError):local_url(url,'/v1')


def test_sdk_close_waits_for_an_active_external_call(tmp_path):
    entered=threading.Event();release=threading.Event();closed=threading.Event();results=[]
    def host(request):
        if request['type']=='authorize':return {'allowed':True}
        if request['type']=='invoke':entered.set();release.wait(3);return {'ok':True}
        return {}
    native=Native(host,directory=tmp_path)
    native.call('register',operation={'name':'held','description':'Held test operation','inputSchema':{'type':'object'},'outputSchema':{'type':'object'},'readOnly':True})
    worker=threading.Thread(target=lambda:results.append(native.call('invoke',name='held',arguments={})))
    worker.start();assert entered.wait(2)
    closer=threading.Thread(target=lambda:(native.close(),closed.set()));closer.start()
    assert not closed.wait(.1);release.set();worker.join(3);closer.join(3)
    assert results==[{'ok':True}] and closed.is_set()


def test_native_sdk_stdio_client_joins_http_instance_with_modern_headers(instance,tmp_path):
    runtime,_,__,___=instance
    native=Native(directory=tmp_path/'modern-peer')
    try:
        with LiveServer(runtime,0,advertise=True):
            native.call('remoteConnect',id='proxy',config={'executable':sys.executable,'arguments':[str(APP/'tool.py'),'--data-dir',str(runtime.root),'mcp','--auto','--full']})
            result=native.call('remoteCall',id='proxy',name='list_projects',arguments={})
            assert not result.get('isError'),result
            assert 'projects' in json.loads(result['content'][0]['text'])
    finally:native.close()
