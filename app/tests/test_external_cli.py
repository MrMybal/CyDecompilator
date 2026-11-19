"""An external agent drives CyMCPSDK CLI/JSONL without any model or MCP client."""
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys

from test_cymcp_integration import APP,ROOT,instance
from cydec import service
from cydec.mcp.transport import LiveServer,HTTPClient
from cydec.mcp.instance import automation_identity


def runner(directory,jobs=None,*,factory='tool.create_runtime',setup=''):
    directory.mkdir(parents=True,exist_ok=True);jobs=jobs or directory/'jobs'
    script=directory/'cli.py'
    script.write_text('import sys\nfrom pathlib import Path\n'+f'sys.path.insert(0,{str(APP)!r})\n'+
        'import tool\nfrom cydec.project import ProjectStore\n'+f'tool.service.store=ProjectStore(Path({str(directory/"projects")!r}))\n'+setup+
        f'raise SystemExit(tool.run_cli({factory},["--data-dir",{str(jobs)!r},"--auto",*sys.argv[1:]]))\n','utf-8')
    env=dict(os.environ);env.pop('CYTOOLS_TOKEN',None);env.pop('CYMCP_TOKEN',None)
    command=[sys.executable,str(script)]
    def run(*arguments,input=None,expected=0):
        result=subprocess.run([*command,*arguments],input=input,capture_output=True,text=True,encoding='utf-8',env=env,timeout=40)
        assert result.returncode==expected,result.stderr
        return json.loads(result.stdout)
    return run,command,env


@contextmanager
def jsonl(directory,*,setup='',factory='tool.create_runtime'):
    run,command,env=runner(directory,setup=setup,factory=factory)
    with (directory/'stderr.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen([*command,'jsonl'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,encoding='utf-8',env=env)
        reader=ThreadPoolExecutor(max_workers=1)
        def request(method,name=None,arguments=None):
            value={'method':method}
            if name:value.update(name=name,arguments=arguments or {})
            process.stdin.write(json.dumps(value)+'\n');process.stdin.flush()
            line=reader.submit(process.stdout.readline).result(timeout=35)
            assert line,'CLI closed without a JSON response'
            result=json.loads(line);assert not result.get('error') or 'jobId' in result,result
            return result
        try:yield request,run
        finally:
            process.stdin.close()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
            process.stdout.close();reader.shutdown()
        assert process.returncode==0,(directory/'stderr.log').read_text('utf-8')


def test_native_sdk_jsonl_reconstructs_edits_builds_and_runs_without_a_chat(tmp_path):
    original=tmp_path/'original';original.mkdir();(original/'main.js').write_text('console.log("original CLI behavior");','utf-8')
    with jsonl(tmp_path/'agent') as (sdk,run):
        described=sdk('describe')
        assert described['sdkVersion']=='0.7.0'
        assert {'application_open','workspace_execute'}<={o['name'] for o in described['operations']}
        project=sdk('invoke','application_open',{'path':str(original)})['projectId']
        rebuilt=sdk('invoke','reconstruction_run',{'projectId':project,'maxRounds':1})
        assert rebuilt['status']=='scenarios-matched'
        sdk('invoke','workspace_history',{'projectId':project,'action':'snapshot','message':'Before external CLI edit'})
        source=sdk('invoke','workspace_read',{'projectId':project,'path':'main.js'})
        sdk('invoke','workspace_save',{'projectId':project,'path':'main.js','revision':source['revision'],'text':'console.log("EXTERNAL_CLI_BUILT_OK");'})
        built=sdk('invoke','workspace_execute',{'projectId':project,'action':'build'})
        assert built['status']=='passed' and built['exitCode']==0
        executed=sdk('invoke','workspace_execute',{'projectId':project,'action':'run'})
        assert 'EXTERNAL_CLI_BUILT_OK' in json.dumps(executed)
        # Another CLI process attaches to the same owner while JSONL stays open.
        assert run('job',executed['_jobId'])['state']=='Completed'
    assert (original/'main.js').read_text()=='console.log("original CLI behavior");'


def test_cli_keeps_identity_and_results_between_processes(tmp_path):
    run,_,__=runner(tmp_path/'agent')
    source=tmp_path/'input.json';source.write_text(json.dumps({'path':str(APP/'tests/fixtures/shaders/lit_frag.spv'),'engine':'shader'}),'utf-8')
    opened=run('invoke','open_file',str(source))
    assert opened['state']=='Completed'
    assert run('job',opened['jobId'])['outputs']==opened['outputs']
    encoded=run('result',opened['jobId']);assert json.loads(base64.b64decode(encoded['data']))==opened['outputs']
    assert run('wait',opened['jobId'],'--timeout','1')['state']=='Completed'
    assert any(j['jobId']==opened['jobId'] for j in run('jobs'))


def test_sdk_cli_can_modify_the_open_instance_without_a_second_runtime(instance,tmp_path):
    runtime,_,__,___=instance
    factory='lambda *a,**k: (_ for _ in ()).throw(RuntimeError("Must use live instance"))'
    run,_,__=runner(tmp_path/'agent',runtime.root,factory=factory)
    params=tmp_path/'open.json';params.write_text(json.dumps({'path':str(APP/'tests/fixtures/shaders/lit_frag.spv')}),'utf-8')
    with LiveServer(runtime,0,advertise=True):
        opened=run('sdk','invoke','open_file','--params-file',str(params));project=opened['projectId']
        change=tmp_path/'notes.json';change.write_text(json.dumps({'projectId':project,'text':'SDK CLI acted on the live application'}),'utf-8')
        run('sdk','invoke','set_notes','--params-file',str(change))
        assert service.project_for(project).annotations()['notes']=='SDK CLI acted on the live application'


def test_cli_controls_an_async_job_while_sdk_jsonl_owns_the_engine(tmp_path):
    setup='def factory(path):\n r=tool.create_runtime(path)\n r._handlers["list_projects"]=lambda context,arguments: context.cancellation.sleep(20) or {"ok":True}\n return r\n'
    with jsonl(tmp_path/'agent',setup=setup,factory='factory') as (sdk,run):
        job=sdk('invoke','op_list_projects',{'parameters':{}})
        run('cancel',job['jobId'])
        assert run('wait',job['jobId'],'--timeout','5',expected=1)['state']=='Cancelled'
        assert sdk('invoke','cy_get_job',{'jobId':job['jobId']})['state']=='Cancelled'


def test_sdk_jsonl_reports_failure_without_losing_the_stream(tmp_path):
    _,command,env=runner(tmp_path/'agent')
    result=subprocess.run([*command,'jsonl'],input='{"method":"not-a-method"}\n{"method":"describe"}\n',capture_output=True,text=True,encoding='utf-8',env=env,timeout=15)
    assert result.returncode==1
    lines=[json.loads(v) for v in result.stdout.splitlines()]
    assert lines[0]['error']['code']=='UnknownMethod' and lines[1]['sdkVersion']=='0.7.0'


def test_sdk_cli_connections_have_independent_temporary_tasks(instance):
    runtime,_,__,___=instance
    with LiveServer(runtime,0,advertise=True) as server:
        actor,token=automation_identity(runtime)
        endpoint='http://127.0.0.1:'+str(server.server.server_port)+'/v1'
        first,second=HTTPClient(endpoint,token),HTTPClient(endpoint,token)
        def sdk(client,name,arguments):return client.call('SDKDispatch',request={'method':'invoke','name':name,'arguments':arguments})
        a=sdk(first,'list_projects',{});b=sdk(second,'list_projects',{})
        first_job=runtime.get_job(actor,a['_jobId']);second_job=runtime.get_job(actor,b['_jobId'])
        assert first_job['sessionId']!=second_job['sessionId']
        sdk(first,'cy_finish_task',{})
        assert Path(second_job['workspace']).is_dir()
        assert runtime.get_job(actor,b['_jobId'])['state']=='Completed'
