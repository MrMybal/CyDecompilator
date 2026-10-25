"""Real input snapshots, hostile-container boundaries and receipt-verified execution.

The adapter contract uses a controlled converter; real AnyPS5 checks are recorded
separately and are not inferred from these tests.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import sys
import zipfile

import pytest

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from cytools_core import CyToolError
from cydec import porting,service,process
from cydec.engines.base import EngineContext
from cydec.project import ProjectStore


def elf_bytes(code=b'\x31\xc0\xc3'):
    data=bytearray(0x1000+len(code))
    struct.pack_into('<16sHHIQQQIHHHHHH',data,0,b'\x7fELF\x02\x01\x01'+bytes(9),0xfe10,62,1,
                     0x401000,64,0,0,64,56,1,0,0,0)
    struct.pack_into('<IIQQQQQQ',data,64,1,5,0x1000,0x401000,0x401000,len(code),len(code),0x1000)
    data[0x1000:]=code
    return bytes(data)


def self_bytes(elf):
    result=bytearray(0x400+len(elf)-0x1000)
    result[:4]=porting.SELF_MAGIC
    struct.pack_into('<QQQQ',result,0x40,0x800,0x400,len(elf)-0x1000,len(elf)-0x1000)
    header_size=64+56*struct.unpack_from('<H',elf,56)[0]
    result[0x200:0x200+header_size]=elf[:header_size]
    result[0x400:]=elf[0x1000:]
    return bytes(result)


def test_kernel_self_subranges_and_opaque_signed_metadata(setup,tmp_path):
    store,ctx,source=setup
    elf=bytearray(elf_bytes(bytes(128)))
    struct.pack_into('<H',elf,56,2)
    struct.pack_into('<IIQQQQQQ',elf,120,2,4,0x1040,0x401040,0x401040,32,32,8)
    wrapped=bytearray(self_bytes(elf));wrapped[:4]=porting.SELF_MAGICS[1]
    (source/'eboot.bin').write_bytes(wrapped)
    metadata=source/'sce_sys/about';metadata.mkdir()
    opaque=bytearray(self_bytes(elf_bytes(bytes(range(256))*32)))
    opaque[:4]=porting.SELF_MAGICS[1]
    (metadata/'right.sprx').write_bytes(opaque)
    opened=porting.open_input(store,source,ctx)
    assert (Path(opened['directory'])/'eboot.bin').read_bytes()==elf
    assert len(opened['unwrapped'])==1 and opened['unpreparedSelf'][0]['path']=='sce_sys/about/right.sprx'
    assert (Path(opened['directory'])/'sce_sys/about/right.sprx').read_bytes()==opaque
    # The same unresolved payload is not allowed in a runtime module directory.
    modules=source/'sce_module';modules.mkdir()
    (modules/'required.prx').write_bytes(opaque)
    with pytest.raises(CyToolError):porting.open_input(store,source,ctx)


def test_self_nonload_metadata_memsz_and_explicitly_omitted_notes(setup):
    store,ctx,source=setup
    elf=bytearray(elf_bytes(bytes(128)))
    struct.pack_into('<H',elf,56,3)
    # Mapped SCE version data may have memsz=0: it is not a PT_LOAD.
    struct.pack_into('<IIQQQQQQ',elf,120,0x6fffff00,0,0x1040,0,0,32,0,1)
    # A debug note with no SELF mapping may be omitted, not synthesized.
    struct.pack_into('<IIQQQQQQ',elf,176,4,0,0x3000,0,0,64,0,4)
    wrapped=self_bytes(elf)
    (source/'eboot.bin').write_bytes(wrapped)
    opened=porting.open_input(store,source,ctx)
    assert opened['unwrapped'][0]['omittedMetadata']==[{
        'index':2,'type':'0x4','reason':'No explicit readable segment mapping.'}]
    result=Path(opened['directory'])/'eboot.bin'
    info=porting.elf_info(result)
    assert info['segments'][1]['memorySize']==0 and info['segments'][1]['fileSize']==32
    assert info['segments'][2]['fileSize']==0
    assert (source/'eboot.bin').read_bytes()==wrapped
    # Dynamic-link data is essential and cannot be silently omitted.
    struct.pack_into('<I',elf,176,2)
    (source/'eboot.bin').write_bytes(self_bytes(elf))
    with pytest.raises(CyToolError,match='mapping is incomplete'):porting.open_input(store,source,ctx)


@pytest.fixture
def setup(tmp_path,monkeypatch):
    store=ProjectStore(tmp_path/'projects')
    monkeypatch.setattr(service,'store',store)
    monkeypatch.setattr(porting,'TOOLS_FILE',tmp_path/'settings/porting.json')
    ctx=EngineContext(workdir=tmp_path/'job')
    Path(ctx.workdir).mkdir()
    source=tmp_path/'original'
    source.mkdir()
    (source/'eboot.bin').write_bytes(elf_bytes())
    (source/'sce_sys').mkdir()
    (source/'sce_sys/param.json').write_text(json.dumps({'titleId':'PPSA00000','localizedParameters':{
        'defaultLanguage':'en-US','en-US':{'titleName':'Own test application'}}}),'utf-8')
    (source/'resource.txt').write_text('original resource')
    return store,ctx,source


def test_folder_zip_and_plaintext_self_are_persistent_and_preserve_originals(setup,tmp_path):
    store,ctx,source=setup
    before={p.relative_to(source).as_posix():p.read_bytes() for p in source.rglob('*') if p.is_file()}
    first=porting.open_input(store,source,ctx)
    assert first['title']['name']=='Own test application' and first['status']=='prepared'
    assert porting.info(store.get(first['projectId']))['importId']==first['importId']
    archive=tmp_path/'application.zip'
    with zipfile.ZipFile(archive,'w') as bundle:
        for relative,data in before.items():bundle.writestr('nested/app0/'+relative,data)
    zipped=porting.open_input(store,archive,ctx)
    assert zipped['entry']=='nested/app0/eboot.bin'
    assert Path(zipped['directory'],'nested/app0/resource.txt').read_text()=='original resource'
    wrapped=tmp_path/'plaintext.self'
    wrapped.write_bytes(self_bytes(elf_bytes()))
    digest=hashlib.sha256(wrapped.read_bytes()).hexdigest()
    unwrapped=porting.open_input(store,wrapped,ctx)
    assert unwrapped['unwrapped'][0]['sourceSha256']==digest
    assert (Path(unwrapped['directory'])/unwrapped['entry']).read_bytes()==elf_bytes()
    assert hashlib.sha256(wrapped.read_bytes()).hexdigest()==digest
    assert before=={p.relative_to(source).as_posix():p.read_bytes() for p in source.rglob('*') if p.is_file()}
    # Stable saved inputs survive deletion of the temporary job workspace.
    saved=Path(first['directory'])
    shutil.rmtree(ctx.workdir)
    assert (saved/'resource.txt').read_text()=='original resource'


@pytest.mark.parametrize('name',['../escape.bin','/absolute.bin','C:/drive.bin','a/../../escape','file:stream','NUL','foo.','a\\..\\escape'])
def test_hostile_zip_names_cannot_escape_or_alias(setup,tmp_path,name):
    store,ctx,_=setup
    archive=tmp_path/'hostile.zip'
    with zipfile.ZipFile(archive,'w') as bundle:bundle.writestr(name,elf_bytes())
    with pytest.raises(CyToolError):porting.open_input(store,archive,ctx)
    assert not (tmp_path/'escape.bin').exists()
    assert not store.list()


def test_zip_links_duplicates_limits_and_multiple_entries(setup,tmp_path):
    store,ctx,_=setup
    archive=tmp_path/'input.zip'
    symlink=zipfile.ZipInfo('eboot.bin')
    symlink.create_system=3
    symlink.external_attr=(stat.S_IFLNK|0o777)<<16
    with zipfile.ZipFile(archive,'w') as bundle:bundle.writestr(symlink,'outside')
    with pytest.raises(CyToolError):porting.open_input(store,archive,ctx)
    with zipfile.ZipFile(archive,'w') as bundle:
        bundle.writestr('eboot.bin',elf_bytes())
        bundle.writestr('EBOOT.BIN',elf_bytes())
    with pytest.raises(CyToolError):porting.open_input(store,archive,ctx)
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:bundle.writestr('eboot.bin',elf_bytes()+bytes(200000))
    with pytest.raises(CyToolError):porting.open_input(store,archive,ctx,limit=10000)
    with zipfile.ZipFile(archive,'w') as bundle:
        bundle.writestr('a/eboot.bin',elf_bytes())
        bundle.writestr('b/eboot.bin',elf_bytes())
    with pytest.raises(CyToolError):porting.open_input(store,archive,ctx)
    assert porting.open_input(store,archive,ctx,entry='b/eboot.bin')['entry']=='b/eboot.bin'


def test_bad_self_and_elf_are_refused(setup,tmp_path):
    _,ctx,_=setup
    wrapped=tmp_path/'bad.self'
    data=bytearray(self_bytes(elf_bytes()))
    struct.pack_into('<Q',data,0x40+24,999999)
    wrapped.write_bytes(data)
    with pytest.raises(CyToolError):porting.unwrap_self(wrapped,tmp_path/'out.elf',ctx)
    bad=tmp_path/'bad.elf'
    data=bytearray(elf_bytes())
    struct.pack_into('<Q',data,24,0x90000000)
    bad.write_bytes(data)
    with pytest.raises(CyToolError):porting.elf_info(bad)
    assert not (tmp_path/'out.elf').exists()


@pytest.mark.parametrize('embedded_zip',[False,True])
def test_ultrapack_receives_a_private_container_copy_without_mutating_source(setup,tmp_path,monkeypatch,embedded_zip):
    store,ctx,_=setup
    source=tmp_path/'own.pkg'
    source.write_bytes(b'own package fixture')
    if embedded_zip:
        with zipfile.ZipFile(source,'a') as archive:archive.writestr('metadata.json','{}')
    original=source.read_bytes()
    cli=tmp_path/'cli.py'
    cli.write_text('# controlled adapter contract')
    porting.tools({'ultrapackCli':str(cli)})
    def extract(command,**kwargs):
        assert command[-2:]==['--to','folder']
        assert Path(command[2])!=source
        assert Path(command[2]).read_bytes()==source.read_bytes()
        output=Path(command[3]);output.mkdir()
        (output/'eboot.bin').write_bytes(elf_bytes())
        return 0,'extracted',''
    monkeypatch.setattr(process,'run',extract)
    opened=porting.open_input(store,source,ctx)
    assert opened['entry']=='eboot.bin' and source.read_bytes()==original
    assert not (Path(opened['directory']).parent/source.name).exists()
    assert opened['container']['sha256']==hashlib.sha256(original).hexdigest()


def test_extraction_monitor_tolerates_disappearing_backend_scratch_files(setup,tmp_path,monkeypatch):
    store,ctx,_=setup
    source=tmp_path/'input.pkg';source.write_bytes(b'controlled package')
    cli=tmp_path/'cli.py';cli.write_text('controlled extraction backend')
    porting.tools({'ultrapackCli':str(cli)})
    original=porting._is_link
    def transient(path):
        if path.name=='transient-file':raise FileNotFoundError(str(path))
        return original(path)
    monkeypatch.setattr(porting,'_is_link',transient)
    def extract(command,**kwargs):
        destination=Path(command[3])
        scratch=destination.parent/'temp/transient-file';scratch.write_bytes(b'scratch')
        kwargs['on_tick'](None)
        scratch.unlink()
        destination.mkdir();(destination/'eboot.bin').write_bytes(elf_bytes())
        return 0,'extracted',''
    monkeypatch.setattr(process,'run',extract)
    assert porting.open_input(store,source,ctx)['status']=='prepared'


@pytest.fixture
def native_executable(tmp_path):
    from cydec.ai.verify import msvc_vcvars
    source=tmp_path/'application.c'
    source.write_text('#include <stdio.h>\n#include <stdlib.h>\nint main(int argc,char**argv){ puts("port-test");if(getenv("APS5_NO_PAD_INPUT"))return 91;return argc>1?7:0;}\n')
    result=tmp_path/('application.exe' if os.name=='nt' else 'application.elf')
    ctx=EngineContext(workdir=tmp_path/'compiler');Path(ctx.workdir).mkdir()
    if os.name=='nt':
        vcvars=msvc_vcvars()
        if not vcvars:pytest.skip('MSVC required for the native porting execution test')
        script=tmp_path/'compile.cmd'
        script.write_text('@echo off\ncall "'+str(vcvars)+'" >nul\ncl /nologo /O2 /MT "'+str(source)+'" /Fe:"'+str(result)+'"\n')
        code,out,err=process.run(['cmd.exe','/c',script],cwd=tmp_path,context=ctx,timeout=90)
    else:
        compiler=shutil.which('cc')
        if not compiler:pytest.skip('C compiler required')
        code,out,err=process.run([compiler,source,'-o',result],cwd=tmp_path,context=ctx,timeout=90)
    assert code==0,(out,err)
    return result


def test_conversion_receipts_execution_assertions_and_tamper_refusal(setup,tmp_path,monkeypatch,native_executable):
    store,ctx,source=setup
    imported=porting.open_input(store,source,ctx)
    project=store.get(imported['projectId'])
    target='windows' if os.name=='nt' else 'linux'
    assert porting.plan(project,target)['status']=='blocked'
    tool=tmp_path/'controlled-converter';tool.write_text('controlled converter contract')
    libraries=tmp_path/'libraries';libraries.mkdir();(libraries/'libc.prx').write_bytes(b'controlled libraries')
    porting.tools({'relinker':str(tool),target+'Libraries':str(libraries)})
    original_run=process.run
    def convert(command,**kwargs):
        if str(command[0])==str(tool):
            if '--help' in command:return 0,'--windows --registry --sce-module-path --module-dir --no-patches',''
            assert '--no-patches' in command and '--autorun' not in command
            assert Path(command[-2]).is_relative_to(Path(ctx.workdir))
            assert not (Path(command[-2]).parent/'resource.txt').exists()
            shutil.copyfile(native_executable,command[-1])
            return 0,'controlled conversion',''
        return original_run(command,**kwargs)
    monkeypatch.setattr(process,'run',convert)
    converted=porting.convert(project,target,ctx)
    assert converted['status']=='converted-unverified'
    stdout='port-test'+os.linesep
    result=porting.run(project,ctx,scenarios=[{'expectedExitCode':0,'expectedStdout':stdout},
                     {'arguments':['value'],'expectedExitCode':7,'expectedStdout':stdout}])
    assert result['status']=='scenarios-passed'
    assert porting.run(project,ctx,scenarios=[{'arguments':['value'],'expectedExitCode':7},{}])['status']=='executed-unverified'
    assert porting.run(project,ctx)['status']=='executed-unverified'
    assert porting.run(project,ctx,scenarios=[{'expectedExitCode':99}])['status']=='execution-failed'
    # A model cannot turn a successful conversion alone into a verified port.
    from types import SimpleNamespace
    from cydec.ai import agent,assistant
    from tool import create_runtime,declared_permissions
    calls=iter([{'tool':'porting_diagnose','arguments':{'engine':'cdec'}},
                {'answer':'Diagnosed, therefore done.','status':'completed'},
                {'tool':'porting_run','arguments':{'scenarios':[{'expectedStdout':stdout,'expectedExitCode':0}]}},
                {'answer':'The explicit output scenario passed.','status':'completed'}])
    monkeypatch.setattr(assistant,'call_model',lambda *a,**k:(json.dumps(next(calls)),'','controlled',SimpleNamespace(id='controlled')))
    with create_runtime(tmp_path/'agent-jobs') as runtime:
        actor=runtime.authenticate(runtime.create_client('port-test',declared_permissions(runtime))['token'])
        session=runtime.create_session(actor,temporary=False)['sessionId']
        job=runtime.submit(actor,session,'ai_agent',{'projectId':project.id,'workflow':'port',
            'objective':'Test the converted application against its expected stdout.','maxSteps':5})
        completed=runtime.wait(actor,job['jobId'],timeout=30)
        assert completed['state']=='Completed',completed.get('error')
        report=completed['outputs']
    assert report['status']=='completed' and report['verification']['verified'],report
    assert [s['tool'] for s in report['steps']]==['porting_diagnose','porting_run']
    for state in ('Failed','Cancelled'):
        stale=report|{'steps':report['steps']+[{'tool':'porting_run','result':{'state':state}}]}
        assert not agent.verified(stale)['verified']
    assert not agent.verified(report|{'steps':[]})['verified']
    (Path(converted['directory'])/'app0/resource.txt').write_text('changed')
    with pytest.raises(CyToolError):porting.run(project,ctx)
    assert not agent.verified(report,SimpleNamespace(workdir=ctx.workdir,cancellation=ctx.cancellation,
        log=lambda *a:None,emit=lambda *a:None,path=lambda p:Path(ctx.workdir)/p))['verified']
    assert (source/'resource.txt').read_text()=='original resource'


@pytest.mark.skipif(os.name!='nt',reason='AnyPS5 Windows instrumentation contract')
def test_diagnostics_trace_capabilities_and_run_environment(setup,tmp_path,monkeypatch,native_executable):
    store,ctx,source=setup
    imported=porting.open_input(store,source,ctx)
    project=store.get(imported['projectId'])
    tool=tmp_path/'converter';tool.write_text('controlled tool')
    libs=tmp_path/'libs';libs.mkdir()
    porting.tools({'relinker':str(tool),'windowsLibraries':str(libs)})
    original=process.run
    commands=[]
    capability='--windows --registry --sce-module-path --module-dir --windows-diagnostics --trace-imports'
    def execute(command,**kwargs):
        if str(command[0])==str(tool):
            if '--help' in command:return 0,capability,''
            commands.append(command)
            shutil.copyfile(native_executable,command[-1])
            return 0,'controlled converter',''
        assert kwargs['env']['APS5_TRACE_CALLS']=='all'
        assert kwargs['env']['APS5_NO_PAD_INPUT'] is None
        return original(command,**kwargs)
    monkeypatch.setattr(process,'run',execute)
    converted=porting.convert(project,'windows',ctx,diagnostics=True,trace_imports=True)
    assert '--windows-diagnostics' in commands[-1] and '--trace-imports' in commands[-1]
    monkeypatch.setenv('APS5_NO_PAD_INPUT','1')
    result=porting.run(project,ctx,scenarios=[{'expectedExitCode':0}],trace_libraries='all')
    assert result['status']=='scenarios-passed' and result['traceLibraries']=='all'
    assert (project.dir/'porting/runs'/(result['runId']+'.json')).is_file()
    with pytest.raises(CyToolError):porting.run(project,ctx,trace_libraries='libc;evil')
    plain=porting.convert(project,'windows',ctx)
    with pytest.raises(CyToolError,match='traceImports'):porting.run(project,ctx,trace_libraries='all')
    capability=capability.replace('--trace-imports','')
    with pytest.raises(CyToolError,match='required command-line'):
        porting.convert(project,'windows',ctx,trace_imports=True)
    with pytest.raises(CyToolError):porting.convert(project,'linux',ctx,diagnostics=True)
    assert plain['options']['traceImports'] is False and converted['options']['traceImports'] is True


def test_secondary_programs_are_not_shared_modules_and_all_outputs_are_validated(setup,tmp_path,monkeypatch,native_executable):
    store,ctx,source=setup
    (source/'codmp.elf').write_bytes(elf_bytes(b'\x31\xc0\xc3'))
    (source/'codzm.elf').write_bytes(elf_bytes(b'\xb8\x07\0\0\0\xc3'))
    (source/'sce_module').mkdir()
    imported=porting.open_input(store,source,ctx)
    project=store.get(imported['projectId'])
    target='windows' if os.name=='nt' else 'linux'
    tool=tmp_path/'converter';tool.write_text('controlled converter')
    libraries=tmp_path/'libs';libraries.mkdir()
    porting.tools({'relinker':str(tool),target+'Libraries':str(libraries)})
    capabilities='--windows --registry --sce-module-path'
    commands=[]
    def convert(command,**kwargs):
        if '--help' in command:return 0,capabilities,''
        commands.append(command)
        assert '--module-dir' not in command
        root=Path(command[-1]).parent
        shutil.copyfile(native_executable,command[-1])
        for index,value in enumerate(command):
            if value=='--executable':
                name=command[index+1]
                shutil.copyfile(native_executable,root/(name+Path(command[-1]).suffix))
                write_json(root/(name+'.registry.json'),[])
        return 0,'controlled multi-program conversion',''
    from cydec.paths import write_json
    monkeypatch.setattr(process,'run',convert)
    with pytest.raises(CyToolError,match='required command-line'):
        porting.convert(project,target,ctx)
    capabilities+=' --executable'
    result=porting.convert(project,target,ctx)
    assert result['status']=='converted-unverified'
    assert result['secondaryExecutables']==['codmp.elf','codzm.elf']
    assert [commands[-1][i+1] for i,v in enumerate(commands[-1]) if v=='--executable']==['codmp.elf','codzm.elf']
    assert {r['source'] for r in result['additionalExecutables']}=={'codmp.elf','codzm.elf'}
    assert {r['source'] for r in result['registries']}=={'codmp.elf','codzm.elf'}
    assert (Path(result['directory'])/'app0/resource.txt').read_text()=='original resource'
    # A missing secondary result cannot create a successful receipt.
    monkeypatch.setattr(process,'run',lambda command,**kw:(0,capabilities,'') if '--help' in command else (
        shutil.copyfile(native_executable,command[-1]) and (0,'only primary written','')))
    with pytest.raises(CyToolError,match='secondary executable'):porting.convert(project,target,ctx)
    # Root executables mixed with loose root libraries need an explicit layout.
    module=bytearray(elf_bytes());struct.pack_into('<H',module,16,0xfe18)
    (source/'loose.prx').write_bytes(module)
    imported=porting.open_input(store,source,ctx)
    with pytest.raises(CyToolError,match='loose root modules'):porting.convert(project,target,ctx)


def test_failed_or_missing_converter_output_never_creates_a_success_receipt(setup,tmp_path,monkeypatch):
    store,ctx,source=setup
    imported=porting.open_input(store,source,ctx)
    project=store.get(imported['projectId'])
    target='windows' if os.name=='nt' else 'linux'
    tool=tmp_path/'converter';tool.write_text('fake')
    libraries=tmp_path/'libs';libraries.mkdir()
    porting.tools({'relinker':str(tool),target+'Libraries':str(libraries)})
    help_text='--windows --registry --sce-module-path --module-dir --no-patches'
    monkeypatch.setattr(process,'run',lambda command,**k:(0,help_text,'') if '--help' in command else (4,'unsupported import',''))
    failure=porting.convert(project,target,ctx)
    assert failure['status']=='conversion-failed' and failure['diagnosis']['engine']=='cdec'
    from cydec.porting_analysis import _saved
    assert _saved(project,'attempt')['exitCode']==4
    assert not porting.conversion(project)['available']
    monkeypatch.setattr(process,'run',lambda command,**k:(0,help_text if '--help' in command else 'no artifact',''))
    with pytest.raises(CyToolError):porting.convert(project,target,ctx)
    assert not porting.conversion(project)['available']


def test_mcp_import_preserves_provenance_and_discoverable_contract(tmp_path):
    import asyncio
    from mcp_client import client,run as mcp_run
    source=tmp_path/'own.elf'
    source.write_bytes(elf_bytes())
    async def scenario():
        async with client(tmp_path/'server') as session:
            names={tool.name for tool in (await session.list_tools()).tools}
            assert {'op_porting_open','op_porting_plan','op_porting_convert','op_porting_run','op_porting_diagnose'}<=names
            opened=await mcp_run(session,'porting_open',file=str(source))
            assert opened['source']==str(source)
            info=await mcp_run(session,'porting_info',projectId=opened['projectId'])
            assert Path(info['directory'],info['entry']).read_bytes()==source.read_bytes()
            diagnosis=await mcp_run(session,'porting_diagnose',projectId=opened['projectId'])
            assert diagnosis['coverage']['discoveredFunctions']==1 and diagnosis['samples'][0]['decompiled']['code']
    asyncio.run(scenario())
