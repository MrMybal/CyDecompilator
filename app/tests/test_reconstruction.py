"""Real reconstructed artifacts and bounded repair/validation workflows."""
import ctypes
import hashlib
import json
import os
import sys
from pathlib import Path
import pytest

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from cytools_core import CyToolError
from cydec import service, javascript, workspace, reconstruction, process
from cydec.engines.base import EngineContext
from cydec.project import ProjectStore


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(service,'store',ProjectStore(tmp_path/'projects'))
    return tmp_path,EngineContext(workdir=tmp_path/'work',options={'symbols':False})


def web_project(setup,files):
    root,ctx=setup
    folder=root/'original';folder.mkdir()
    for name,text in files.items():
        path=folder/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')
    project=javascript.open_application(service.store,folder,ctx)
    return project,ctx,folder


def test_javascript_and_typescript_rebuild_and_run(setup):
    project,ctx,original=web_project(setup,{'main.ts':'const value:number=7; console.log(value+3);',
        'package.json':json.dumps({'name':'example','main':'main.ts','version':'1.0.0'})})
    state=service.workspace_create(project.id,context=ctx)
    assert state['kind']=='node'
    built=service.workspace_execute(project.id,'build',ctx)
    assert built['status']=='passed',built['output']
    artifact=Path(built['artifactDirectory'])
    assert (artifact/'main.js.map').is_file()
    assert json.loads((artifact/'package.json').read_text())['main']=='main.js'
    result=service.workspace_execute(project.id,'run',ctx)
    assert result['status']=='passed' and result['output'].strip()=='10'
    assert (original/'main.ts').read_text()=='const value:number=7; console.log(value+3);'
    source=service.workspace_read(project.id,'main.ts')
    service.workspace_save(project.id,'main.ts','const value:number=8;',source['revision'])
    with pytest.raises(CyToolError,match='changed after building'):service.workspace_execute(project.id,'run',ctx)
    rebuilt=service.workspace_execute(project.id,'rebuild',ctx)
    assert rebuilt['artifactDirectory']!=built['artifactDirectory']
    (Path(rebuilt['artifactDirectory'])/'main.js').write_text('console.log(999)')
    with pytest.raises(CyToolError,match='artifact changed'):service.workspace_execute(project.id,'run',ctx)


def test_electron_asar_resource_roundtrip_and_syntax_errors(setup):
    project,ctx,_=web_project(setup,{'main.js':"const {app}=require('electron'); app.whenReady().then(()=>app.quit());",
        'package.json':json.dumps({'main':'main.js'}),'index.html':'<script src="renderer.ts"></script>',
        'renderer.ts':'const n:number=3;','asset.txt':'évidence','unused.node':'native-module-fixture'})
    state=service.workspace_create(project.id,context=ctx)
    assert state['kind']=='electron'
    built=service.workspace_execute(project.id,'build',ctx)
    assert built['status']=='passed',built['output']
    artifact=Path(built['artifactDirectory'])
    recovered,skipped=javascript.read_asar(artifact.with_suffix('.asar'),ctx)
    assert not skipped and recovered['asset.txt']=='évidence'.encode()
    assert b'renderer.js' in recovered['index.html']
    unpacked=Path(built['appArchive']+'.unpacked')/'unused.node'
    unpacked.write_bytes(b'changed native module')
    with pytest.raises(CyToolError,match='unpacked Electron artifacts changed'):
        service.workspace_execute(project.id,'run',ctx)
    source=service.workspace_read(project.id,'main.js')
    service.workspace_save(project.id,'main.js','function invalid( {',source['revision'])
    broken=service.workspace_execute(project.id,'build',ctx)
    assert broken['status']=='failed' and broken['diagnostics']


@pytest.mark.skipif(os.name!='nt',reason='Windows native fixture')
def test_shared_native_reconstruction_exports_and_behavior(setup):
    _,ctx=setup
    project,_=service.store.open(APP/'tests/fixtures/native/funcs_x64_o2.dll')
    state=service.workspace_create(project.id,context=ctx,native_target='shared')
    assert state['reconstruction']['target']=='shared'
    assert not state['reconstruction']['blockers'],state['reconstruction']['blockers']
    built=service.workspace_execute(project.id,'build',ctx)
    assert built['status']=='passed',built['output']
    dll=Path(state['directory'])/'build/x64/Debug/recovered.dll'
    old,new=ctypes.CDLL(str(project.binary)),ctypes.CDLL(str(dll))
    for lib in (old,new):lib.add3.argtypes=[ctypes.c_int]*3;lib.add3.restype=ctypes.c_int
    for args in [(0,0,0),(4,-5,12),(2147483640,2,3),(-789,1,123)]:assert old.add3(*args)==new.add3(*args)
    import pefile
    with pefile.PE(str(project.binary)) as a,pefile.PE(str(dll)) as b:
        assert [(s.name,s.ordinal) for s in a.DIRECTORY_ENTRY_EXPORT.symbols]==[(s.name,s.ordinal) for s in b.DIRECTORY_ENTRY_EXPORT.symbols]


def test_reconstruct_repair_compile_and_compare_real_node(setup,monkeypatch):
    from cydec.ai import assistant
    project,ctx,original=web_project(setup,{'main.js':'console.log("same behavior");'})
    service.workspace_create(project.id,context=ctx)
    source=service.workspace_read(project.id,'main.js')
    service.workspace_save(project.id,'main.js','console.log( ;',source['revision'])
    def model(prompt,**kw):
        facts=json.loads(prompt)
        source=next(s for s in facts['sources'] if s['path']=='main.js')
        assert facts['build']['status']=='failed'
        original=next(s for s in facts['originalEvidence'] if s['path']=='main.js')
        assert original['code']=='console.log("same behavior");'
        from types import SimpleNamespace
        return json.dumps({'reason':'Restore the malformed call syntax.','edits':[dict(source,text=original['code'])]}),'','test',SimpleNamespace(id='fixture')
    monkeypatch.setattr(assistant,'call_model',model)
    report=service.reconstruction_run(project.id,ctx,{'repair':True,'maxRounds':2})
    assert report['status']=='scenarios-matched',report
    assert len(report['attempts'])==2
    assert report['attempts'][0]['repair']['changedFiles']==['main.js']
    assert report['attempts'][0]['repairCommit']!=report['initialCommit']
    assert report['attempts'][1]['comparisons'][0]['complete']
    assert service.reconstruction_status(project.id)['runId']==report['runId']
    assert (original/'main.js').read_text()=='console.log("same behavior");'


def test_repair_batch_revisions_confinement_and_rollback(setup,monkeypatch):
    project,ctx,_=web_project(setup,{'main.js':'console.log(1);','helper.js':'const n=1;'})
    service.workspace_create(project.id,context=ctx)
    root,_=workspace.root_for(project)
    before=reconstruction.history._capture(root,ctx)
    revision=reconstruction.history._revision(before)
    edits=[{'path':'main.js','beforeSha256':hashlib.sha256(before['main.js']).hexdigest(),'text':'console.log(2);'},
           {'path':'../escape.js','beforeSha256':'','text':'throw 0;'}]
    with pytest.raises(CyToolError):reconstruction.apply_edits(project,{'edits':edits},revision,ctx)
    assert (root/'main.js').read_bytes()==before['main.js']
    edits[1]={'path':'helper.js','beforeSha256':hashlib.sha256(before['helper.js']).hexdigest(),'text':'const n=2;'}
    save=workspace.save_file
    def fail_second(project,path,*a):
        if path=='helper.js':raise OSError('simulated write failure')
        return save(project,path,*a)
    monkeypatch.setattr(workspace,'save_file',fail_second)
    with pytest.raises(OSError):reconstruction.apply_edits(project,{'edits':edits},revision,ctx)
    assert (root/'main.js').read_bytes()==before['main.js']


def test_no_fake_validation_without_runner_and_no_unbounded_repair(setup,monkeypatch):
    project,ctx,_=web_project(setup,{'main.ts':'console.log(1);'})
    result=service.reconstruction_run(project.id,ctx,{'maxRounds':1})
    assert result['status']=='compiled-unverified'
    assert result['unknowns'][-1]['code']=='NeedsScenario'
    with pytest.raises(CyToolError):service.reconstruction_run(project.id,ctx,{'maxRounds':11})


def test_reconstruction_records_actual_behavior_difference(setup):
    project,ctx,_=web_project(setup,{'main.js':'console.log(1);'})
    service.workspace_create(project.id,context=ctx)
    read=service.workspace_read(project.id,'main.js')
    service.workspace_save(project.id,'main.js','console.log(2);',read['revision'])
    report=service.reconstruction_run(project.id,ctx,{'maxRounds':1})
    assert report['status']=='behavior-differs'
    comparison=report['attempts'][0]['comparisons'][0]
    assert comparison['sameScenario'] and comparison['complete']
    assert not comparison['streams']['stdout']['same']


@pytest.mark.skipif(os.name!='nt',reason='Windows MSVC and resource compiler')
def test_native_executable_entry_resources_and_observed_exit(setup):
    from cydec.ai.verify import msvc_vcvars
    root,ctx=setup
    source=root/'original';source.mkdir()
    (source/'entry.c').write_text('int main(void){return 7;}',encoding='utf-8')
    (source/'data.bin').write_bytes(b'original resource\0\x01')
    (source/'resource.rc').write_text('LANGUAGE 12, 1\n101 10 "data.bin"\n',encoding='utf-8')
    script=source/'compile.cmd'
    script.write_text('@echo off\ncall "'+str(msvc_vcvars())+'" >nul\nrc /nologo resource.rc\nif errorlevel 1 exit /b 1\n'
        'cl /nologo /O2 /GS- entry.c resource.res /link /NODEFAULTLIB /ENTRY:main /EXPORT:main /SUBSYSTEM:CONSOLE /OUT:original.exe\n',encoding='utf-8')
    code,out,err=process.run(['cmd.exe','/d','/c',script],cwd=source,context=ctx,timeout=90)
    assert code==0,out+err
    project,_=service.store.open(source/'original.exe')
    report=service.reconstruction_run(project.id,ctx,{'nativeTarget':'executable','maxRounds':1})
    assert report['status']=='scenarios-matched',report
    assert report['attempts'][0]['comparisons'][0]['exitCodes']==[7,7]
    assert report['reconstruction']['entryFunction']=='main'
    row=report['reconstruction']['resources'][0]
    assert row['type']=='10' and row['name']=='101' and row['language']==1036
    import pefile
    dll=Path(report['directory'])/'build/x64/Debug/recovered.exe'
    with pefile.PE(str(dll)) as pe:
        resource=pe.DIRECTORY_ENTRY_RESOURCE.entries[0].directory.entries[0].directory.entries[0].data.struct
        assert pe.get_data(resource.OffsetToData,resource.Size)==(source/'data.bin').read_bytes()


def test_web_reconstruction_real_browser_scenario(setup):
    root,ctx=setup
    project,ctx,_=web_project(setup,{'index.html':'<!doctype html><title>Reconstruction</title><button id="go">Click</button>'
        '<p id="result">Ready</p><script>document.querySelector("#go").onclick=()=>document.querySelector("#result").textContent="Done";</script>'})
    scenario={'checks':{'stderr':False},'observation':{'headless':True,'network':False,'settleMs':200,'steps':[
        {'action':'click','selector':'#go'},{'action':'assertText','selector':'#result','text':'Done'},{'action':'snapshot'}]},'timeout':40}
    report=service.reconstruction_run(project.id,ctx,{'maxRounds':1,'scenarios':[scenario]})
    assert report['status']=='scenarios-matched',report
    comparison=report['attempts'][0]['comparisons'][0]
    assert comparison['graphics']['same'] and comparison['sameScenario'] and comparison['complete']


def test_build_script_cannot_reuse_stale_artifact(setup):
    project,ctx,_=web_project(setup,{'main.js':'console.log(1);','package.json':json.dumps({'main':'main.js',
        'scripts':{'build':'node -e "process.exit(0)"'}})})
    state=service.workspace_create(project.id,context=ctx)
    root=Path(state['directory']);stale=root/'build/app';stale.mkdir(parents=True)
    (stale/'main.js').write_text('console.log(999);')
    result=service.workspace_execute(project.id,'build',ctx)
    assert result['status']=='failed'
    assert list((root/'build').glob('app-previous-*/main.js'))


def test_cancelled_reconstruction_retains_durable_report(setup):
    project,ctx,_=web_project(setup,{'main.js':'console.log(1);'})
    service.workspace_create(project.id,context=ctx)
    class Cancellation:
        def check(self):raise CyToolError('Cancelled','Cancelled')
    ctx.cancellation=Cancellation()
    with pytest.raises(CyToolError,match='Cancelled'):service.reconstruction_run(project.id,ctx)
    report=service.reconstruction_status(project.id)
    assert report['status']=='cancelled' and report['finishedAt']


def test_real_electron_reconstruction_run_and_graphical_ipc(setup):
    from cydec import components
    if not components.locate('electron'):pytest.skip('Private Electron runtime required')
    project,ctx,_=web_project(setup,{'main.js':"""const {app,BrowserWindow,ipcMain}=require('electron');
      const path=require('path');let win;
      ipcMain.handle('report',()=> 'Done');
      app.whenReady().then(async()=>{win=new BrowserWindow({show:false,width:640,height:480,
        webPreferences:{preload:path.join(__dirname,'preload.js'),backgroundThrottling:false}});await win.loadFile('index.html');win.showInactive();});""",
      'preload.js':"const {contextBridge,ipcRenderer}=require('electron'); contextBridge.exposeInMainWorld('report',()=>ipcRenderer.invoke('report'));",
      'renderer.js':"document.querySelector('#go').onclick=async()=>document.querySelector('#result').textContent=await window.report();",
      'index.html':'<!doctype html><title>Recovered Electron</title><button id="go">Export</button><p id="result">Ready</p><script src="renderer.js"></script>',
      'package.json':json.dumps({'name':'recovered-electron','version':'1.0.0','main':'main.js'})})
    scenario={'checks':{'stderr':False},'timeout':40,'observation':{'driver':'electron','settleMs':200,'steps':[
      {'action':'click','selector':'#go'},{'action':'assertText','selector':'#result','text':'Done'},{'action':'snapshot'}]}}
    report=service.reconstruction_run(project.id,ctx,{'maxRounds':1,'scenarios':[scenario]})
    comparison=report['attempts'][0]['comparisons'][0]
    assert report['status']=='scenarios-matched',comparison
    assert comparison['graphics']['same'] and comparison['applicationPathsNormalized']
    assert not comparison['rawGraphics']['same']
    assert comparison['complete'] and comparison['sameScenario']
    assert comparison['commands'][1][1].endswith('.asar')
    build=service.workspace_info(project.id)['lastBuild']
    Path(build['appArchive']).write_bytes(b'tampered archive')
    with pytest.raises(CyToolError,match='archive changed'):service.workspace_execute(project.id,'run',ctx)


def test_reconstruction_dotnet_console_roundtrip(setup):
    root,ctx=setup
    sdk=workspace.dotnet_sdk(ctx)
    source=root/'managed';source.mkdir()
    code,out,err=process.run([sdk,'new','console','--no-restore','-o',source],context=ctx,timeout=90)
    assert code==0,out+err
    (source/'Program.cs').write_text('System.Console.WriteLine("Managed reconstruction");',encoding='utf-8')
    output=root/'output'
    code,out,err=process.run([sdk,'build',source,'-o',output,'--nologo'],context=ctx,timeout=180)
    assert code==0,out+err
    project,_=service.store.open(output/'managed.dll')
    report=service.reconstruction_run(project.id,ctx,{'maxRounds':1})
    assert report['status']=='scenarios-matched',report
    assert report['attempts'][0]['comparisons'][0]['streams']['stdout']['same']


def test_reconstruction_operations_through_real_runtime(setup):
    from tool import create_runtime,declared_permissions
    root,ctx=setup
    project,_,_=web_project(setup,{'main.js':'console.log("Runtime reconstruction");'})
    with create_runtime(root/'jobs') as runtime:
        actor=runtime.authenticate(runtime.create_client('reconstruction-test',declared_permissions(runtime))['token'])
        session=runtime.create_session(actor,temporary=False)['sessionId']
        job=runtime.submit(actor,session,'reconstruction_run',{'projectId':project.id,'maxRounds':1})
        result=runtime.wait(actor,job['jobId'],timeout=60)
        assert result['state']=='Completed',result
        assert result['outputs']['status']=='scenarios-matched'
        job=runtime.submit(actor,session,'reconstruction_status',{'projectId':project.id})
        result=runtime.wait(actor,job['jobId'],timeout=30)
        assert result['outputs']['status']=='scenarios-matched'


def test_asar_unpacked_native_resources_and_typescript_output_collision(setup):
    from cydec import web_workspace
    root,ctx=setup
    folder=root/'packed';folder.mkdir()
    (folder/'native.node').write_bytes(b'native resource bytes')
    (folder/'main.js').write_text('console.log(1);')
    archive=root/'app.asar'
    web_workspace.pack_asar(folder,archive,ctx)
    recovered,skipped=javascript.read_asar(archive,ctx)
    assert not skipped and recovered['native.node']==b'native resource bytes'
    assert (root/'app.asar.unpacked/native.node').read_bytes()==recovered['native.node']
    project,ctx,_=web_project(setup,{'main.ts':'console.log(1);','main.js':'console.log(2);',
        'package.json':json.dumps({'main':'main.ts'})})
    service.workspace_create(project.id,context=ctx)
    result=service.workspace_execute(project.id,'build',ctx)
    assert result['status']=='failed' and 'conflicts with main.js' in result['output']


def test_reconstruction_does_not_hide_project_test_failures(setup):
    project,ctx,_=web_project(setup,{'main.js':'console.log(1);','package.json':json.dumps({'main':'main.js',
        'scripts':{'test':'node -e "console.error(\'test failed\');process.exit(3)"'}})})
    report=service.reconstruction_run(project.id,ctx,{'runTests':True,'maxRounds':1})
    assert report['status']=='tests-failed'
    assert report['attempts'][0]['build']['status']=='passed'
    assert report['attempts'][0]['tests']['exitCode']==3
    assert 'test failed' in report['output']
    assert not report['attempts'][0]['comparisons']
