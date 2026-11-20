"""Actual native HTTP, registry validation and host business mutations across access profiles."""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest
from test_cymcp_integration import APP,ROOT
from tool import create_runtime,declared_permissions
from cydec import service
from cydec.project import ProjectStore
from cydec.mcp import Native,CyToolError
from cydec.mcp.configuration import ACCESS_PROFILES,load_options,validate_options
from cydec.mcp.transport import LiveServer,HTTPClient


def test_default_migration_preserves_options_and_explicit_choices(tmp_path):
    path=tmp_path/'settings/mcp.json';path.parent.mkdir()
    path.write_text(json.dumps({'cache':False,'contextBytes':8192}),'utf-8')
    options=load_options(path)
    assert options['accessProfile']=='free' and not options['cache'] and options['contextBytes']==8192
    assert json.loads(path.read_text())['accessProfile']=='free'
    for profile in ACCESS_PROFILES:
        path.write_text(json.dumps({'accessProfile':profile,'cache':False}),'utf-8')
        before=path.read_bytes()
        assert load_options(path)['accessProfile']==profile and path.read_bytes()==before
    for value in ('invalid',None,True):
        with pytest.raises(CyToolError):validate_options({'accessProfile':value})


@pytest.mark.parametrize('profile',ACCESS_PROFILES)
def test_native_http_access_matrix_and_argument_validation(profile,tmp_path,monkeypatch):
    monkeypatch.setenv('CYTOOLS_TOKEN','test-bootstrap');monkeypatch.delenv('CYMCP_TOKEN',raising=False)
    monkeypatch.setattr(service,'store',ProjectStore(tmp_path/'projects'))
    settings=tmp_path/'settings/mcp.json';settings.parent.mkdir()
    settings.write_text(json.dumps({'accessProfile':profile,'compactDiscovery':False}),'utf-8')
    with create_runtime(tmp_path/'jobs') as runtime:
        identity=runtime.create_client('limited',[])
        required,controlled=ACCESS_PROFILES[profile]
        with LiveServer(runtime,0,advertise=True,require_token=False) as live:
            url='http://127.0.0.1:'+str(live.server.server_port)
            client=HTTPClient(url+'/v1')
            if required:
                with pytest.raises(CyToolError,match='401'):client.call('ListOperations')
                with pytest.raises(CyToolError):HTTPClient(url+'/v1','invalid-token').call('ListOperations')
                client=HTTPClient(url+'/v1',identity['token'])
                with _native(tmp_path/'no-token') as native:
                    with pytest.raises(CyToolError):native.call('remoteConnect',id='blocked',config={'url':url+'/mcp'})
            assert {o['id'] for o in client.call('ListOperations')}=={o['id'] for o in runtime.descriptor['operations']}
            session=client.call('CreateSession',temporary=False)['sessionId']
            # Controlled profiles still require confirmation even on an otherwise allowed action.
            if controlled:
                with pytest.raises(CyToolError,match='confirm'):client.call('SubmitJob',sessionId=session,operationId='delete_project',parameters={'projectId':'absent'})
            else:
                job=client.call('SubmitJob',sessionId=session,operationId='delete_project',parameters={'projectId':'absent'})
                assert job['state'] in ('Queued','Running','Failed')
            with pytest.raises(CyToolError):client.call('SubmitJob',sessionId=session,operationId='set_notes',parameters={'projectId':1,'text':False})
            with _native(tmp_path/'peer') as native:
                native.call('remoteConnect',id='app',config={'url':url+'/mcp'},token=identity['token'] if required else '')
                tools=native.call('remoteTools',id='app')
                assert 'set_notes' in {t['name'] for t in tools['tools']}
                # No fake handler: open, mutate, read and delete a real shader project.
                if profile=='protected_access':
                    denied=native.call('remoteCall',id='app',name='open_file',arguments={'path':str(APP/'tests/fixtures/shaders/lit_frag.spv')})
                    assert denied['isError']
                else:
                    opened=native.call('remoteCall',id='app',name='open_file',arguments={'path':str(APP/'tests/fixtures/shaders/lit_frag.spv'),'engine':'shader'})
                    assert not opened.get('isError'),opened
                    project=json.loads(opened['content'][0]['text'])['projectId']
                    changed=native.call('remoteCall',id='app',name='set_notes',arguments={'projectId':project,'text':'Address-only MCP edit'})
                    assert not changed.get('isError'),changed
                    assert service.project_for(project).annotations()['notes']=='Address-only MCP edit'
                    if not controlled:
                        removed=native.call('remoteCall',id='app',name='delete_project',arguments={'projectId':project})
                        assert not removed.get('isError'),removed
            # SDK loopback Host/Origin protections apply in Free as well.
            for headers in ({'Host':'evil.example'},{'Origin':'https://evil.example'}):
                request=urllib.request.Request(url+'/v1',data=b'{}',headers={'Content-Type':'application/json',**headers})
                with pytest.raises(urllib.error.HTTPError) as error:urllib.request.urlopen(request,timeout=2)
                assert error.value.code==403


@pytest.mark.skipif(os.name!='nt' or not (ROOT/'CyDecompilator.exe').is_file(),reason='Windows native application required')
@pytest.mark.parametrize('profile',['free','protected_access'])
def test_native_desktop_address_only_and_protected(profile,tmp_path,monkeypatch):
    """Launch the real desktop executable, not a mocked server or replacement GUI."""
    jobs=tmp_path/'jobs';settings=tmp_path/'settings/mcp.json';settings.parent.mkdir()
    # Missing profile exercises migration inside the actual desktop process.
    settings.write_text(json.dumps({'compactDiscovery':False,**({'accessProfile':profile} if profile!='free' else {})}),'utf-8')
    token=''
    if profile=='protected_access':
        with create_runtime(jobs) as runtime:token=runtime.create_client('desktop-check',declared_permissions(runtime))['token']
    env=dict(os.environ)
    for key in ('CYMCP_TOKEN','CYTOOLS_TOKEN'):env.pop(key,None)
    source=tmp_path/('access-'+tmp_path.name+'.spv');shutil.copy2(APP/'tests/fixtures/shaders/lit_frag.spv',source)
    screenshot=tmp_path/'desktop.png'
    with (tmp_path/'desktop.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen([str(ROOT/'CyDecompilator.exe'),'--data-dir',str(jobs),'--smoke-test','--ui-test-tab=assistant','--ui-test-frames=180','--screenshot='+str(screenshot)],env=env,stdout=log,stderr=log)
        try:
            marker=jobs/'mcp-instance.json';deadline=time.monotonic()+20
            while not marker.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.05)
            assert marker.exists(),'Desktop did not publish its native HTTP endpoint'
            endpoint=json.loads(marker.read_text('utf-8'))['mcpUrl'];url=endpoint.removesuffix('/mcp')+'/v1'
            if token:
                with pytest.raises(CyToolError):HTTPClient(url).call('SDKInfo')
            with _native(tmp_path/'desktop-peer') as native:
                if token:
                    with pytest.raises(CyToolError):native.call('remoteConnect',id='blocked',config={'url':endpoint})
                native.call('remoteConnect',id='desktop',config={'url':endpoint},token=token)
                def call(name,arguments):
                    result=native.call('remoteCall',id='desktop',name=name,arguments=arguments)
                    assert not result.get('isError'),result
                    return json.loads(result['content'][0]['text'])
                assert call('cy_sdk_info',{})['revision']=='e562c731a146d599e3404718ea8414bb5b96b66d'
                if not token:
                    opened=call('open_file',{'path':str(source),'engine':'shader'});project=opened['projectId']
                    assert call('set_notes',{'projectId':project,'text':'Real desktop Free MCP mutation'})['notes']=='Real desktop Free MCP mutation'
                    info=call('project_info',{'projectId':project})
                    assert 'Real desktop Free MCP mutation' in json.dumps(info)
                    invalid=native.call('remoteCall',id='desktop',name='set_notes',arguments={'projectId':1,'text':False})
                    assert invalid.get('isError')
                    assert call('delete_project',{'projectId':project})['deleted']
                    cli=subprocess.run([str(ROOT/'CyDecompilatorCLI.exe'),'--connect',url,'list-operations'],env=env,capture_output=True,text=True,encoding='utf-8',timeout=10)
                    assert cli.returncode==0,cli.stderr
                    exposed={o['id'] for o in json.loads(cli.stdout)}
                    assert {o['id'] for o in json.loads((APP/'CyTool.json').read_text('utf-8'))['operations']}<=exposed
            assert process.wait(timeout=55)==0
            assert screenshot.is_file()
            assert json.loads(settings.read_text('utf-8'))['accessProfile']==profile
        finally:
            if process.poll() is None:
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=5)
                process.wait(timeout=5)


from contextlib import contextmanager
@contextmanager
def _native(path):
    native=Native(directory=path)
    try:yield native
    finally:native.close()
