"""Xbox input snapshots, ReXGlue projects and cancellable native game jobs.

CPU translation, successful builds and observed gameplay are separate facts.
All external processes belong to the Runtime job. Game data stays outside app/.
"""
from pathlib import Path
import json
import os
import re
import shutil
import sys
import time
import tomllib
import uuid

from cytools_core import CyToolError
from xbox_support.xbox_native import formats
from . import process
from .paths import APP, ROOT, ENGINES, SETTINGS, read_json, write_json
from .project import sha256_file
from .porting import copy_tree, inventory, _copy_file, _relative, _is_link

BUNDLE=APP/'xbox_support'
TOOLS_FILE=SETTINGS/'xbox-native.json'
HALO_SHA='1412845884eba9eb61cdc00213ca3777be19c71f6196faea69e435a350fd3f19'
DEFAULT_LIMIT=64*1024**3
SDK_VERSION='0.10.0'


def fail(message,code='InvalidParameters'):
    raise CyToolError(code,message,recoverable=True)


def _id(value):
    if not re.fullmatch(r'[a-f0-9]{32}',str(value)):fail('Use an identifier returned by the Xbox workflow.')
    return str(value)


def tools(updates=None):
    settings=read_json(TOOLS_FILE,{})
    if updates is not None:
        if set(updates)-{'sdkRoot','gpuPlugin'}:fail('Unknown Xbox tool setting.')
        for key,value in updates.items():
            if not value:settings.pop(key,None);continue
            path=Path(value).expanduser()
            if not path.is_absolute() or not path.exists():fail('Choose an existing absolute Xbox tool path.')
            if key=='sdkRoot' and not (path/'bin/rexglue.exe').is_file():fail('Choose a ReXGlue SDK folder containing bin/rexglue.exe.')
            if key=='gpuPlugin' and (not path.is_file() or path.suffix.lower()!='.dll'):fail('Choose a native GPU plugin DLL.')
            settings[key]=str(path.resolve())
        write_json(TOOLS_FILE,settings)
    default=ENGINES/'rexglue'/SDK_VERSION/'win-amd64'
    if not settings.get('sdkRoot') and (default/'bin/rexglue.exe').is_file():settings['sdkRoot']=str(default)
    return {'settings':settings,'available':{
        'sdkRoot':bool(settings.get('sdkRoot') and (Path(settings['sdkRoot'])/'bin/rexglue.exe').is_file()),
        'gpuPlugin':bool(settings.get('gpuPlugin') and Path(settings['gpuPlugin']).is_file())},
        'sdkVersion':SDK_VERSION,'sdkSource':'https://github.com/rexglue/rexglue-sdk',
        'hostSupported':os.name=='nt','moduleAvailable':(BUNDLE/'scripts/rex_project.py').is_file()}


def install(context):
    if os.name!='nt':fail('The integrated Xbox SDK installer currently supports Windows x64.','Unsupported')
    current=tools()
    if current['available']['sdkRoot']:return dict(current,status='installed')
    # Official pinned archive and SHA-256 live in this shipped installer. The
    # child is job-owned, including downloads; partial installs are never active.
    stage=ENGINES/'rexglue'/('.install-'+uuid.uuid4().hex)
    context.progress(2,'Installing ReXGlue SDK')
    _worker(context,BUNDLE/'scripts/setup_rexglue.py',['--directory',stage],timeout=1800)
    receipt=read_json(stage/'sdk.json',{})
    sdk=Path(receipt.get('executable','')).parent.parent
    if not (sdk/'bin/rexglue.exe').is_file():fail('The SDK installer produced no verified installation.','IntegrityFailure')
    destination=ENGINES/'rexglue'/SDK_VERSION
    if destination.exists():fail('An incomplete SDK directory already exists. Configure another SDK folder.','Conflict')
    relative=sdk.relative_to(stage/SDK_VERSION)
    shutil.move(str(stage/SDK_VERSION),str(destination))
    final=destination/relative
    receipt['executable']=str(final/'bin/rexglue.exe')
    write_json(destination/'installation.json',receipt)
    return dict(tools({'sdkRoot':str(final)}),status='installed')


def _worker(context,script,arguments,timeout=7200,progress_root=None):
    log_cursor={}
    def tick(_process):
        if not progress_root:return
        logs=list((Path(progress_root)/'logs').glob('*.log'))
        if not logs:return
        latest=max(logs,key=lambda p:p.stat().st_mtime_ns)
        size=latest.stat().st_size
        if log_cursor.get(str(latest))==size:return
        log_cursor[str(latest)]=size
        with latest.open('rb') as stream:
            stream.seek(max(0,size-8192));tail=stream.read().decode('utf-8','replace')
        steps=re.findall(r'\[(\d+)/(\d+)\]\s*([^\r\n]+)',tail)
        if steps:
            done,total,label=steps[-1]
            context.progress(5+90*int(done)/max(1,int(total)),label[:160])
    code,out,err=process.run([sys.executable,'-u',script,*map(str,arguments)],context=context,
        cwd=ROOT,timeout=timeout,log_name='xbox-'+Path(script).stem,own_children=True,
        output_limit=2*1024**2,on_tick=tick)
    if code:
        details=err or out
        if progress_root:
            logs=list((Path(progress_root)/'logs').glob('*.log'))
            if logs:
                latest=max(logs,key=lambda p:p.stat().st_mtime_ns)
                with latest.open('rb') as stream:
                    stream.seek(max(0,latest.stat().st_size-8192));details=stream.read().decode('utf-8','replace')
        fail('Xbox backend failed. See the job log for details.\n'+process.tail(details,16),'EngineError')
    return out


def _metadata(project,report):
    console=report['console']
    title=report.get('title') or project.meta()['name']
    if report['sha256']==HALO_SHA:title='Halo: Combat Evolved Anniversary (Xbox 360)'
    project.update_meta(name=title,detect={'format':'xbox-xex2' if console=='xbox360' else 'xbox-xbe',
        'formatName':'Xbox 360 XEX2' if console=='xbox360' else 'Xbox XBE',
        'arch':report['architecture'],'bits':32,'engines':[],
        'details':{'titleId':report.get('title_id'),'console':console}})


def open_input(store,source,context,entry='',original='',limit=DEFAULT_LIMIT):
    source=Path(source).expanduser()
    if not source.is_absolute() or not source.exists():fail('Choose an existing Xbox game file or folder.')
    if _is_link(source):fail('Game links and reparse points are not imported.','IntegrityFailure')
    source=source.resolve()
    limit=max(1024,min(int(limit),256*1024**3))
    if source.is_file() and source.stat().st_size>limit:fail('The game exceeds the configured byte limit.','ResourceLimit')
    work=Path(context.workdir)/('xbox-import-'+uuid.uuid4().hex)
    work.mkdir(parents=True)
    staged=source
    context.progress(2,'Preparing Xbox input')
    if source.is_dir():
        staged=work/'snapshot'
        copy_tree(source,staged,context,limit)
    prepared=work/'prepared'
    _worker(context,BUNDLE/'scripts/disc_worker.py',[staged,prepared,'--entry',entry,
            '--max-bytes',limit],timeout=7200)
    record=read_json(prepared/'worker.json',{})
    if source.is_dir():
        shutil.move(str(staged),str(prepared/'game'))
        selected=Path(record['selected_executable']).relative_to(staged).as_posix()
    elif record.get('disc_image'):
        selected=_relative(record['selected_executable'])
    else:
        selected=Path(record['executable']).name
        (prepared/'game').mkdir()
        _copy_file(prepared/'probe'/record['executable'],prepared/'game'/selected,context)
    selected=_relative(selected)
    rows=inventory(prepared/'game',context,limit)
    executable=prepared/'game'/selected
    description=formats.inspect(executable)
    project,_=store.open(executable,source_path=str(original or source),cancellation=context.cancellation)
    _metadata(project,description)
    import_id=uuid.uuid4().hex
    final=project.dir/'xbox/inputs'/import_id
    final.parent.mkdir(parents=True,exist_ok=True)
    context.check()
    shutil.move(str(prepared),str(final))
    description['source']=str(final/'game'/selected)
    # Worker paths are temporary provenance, never the persistent launch paths.
    saved={'schemaVersion':1,'projectId':project.id,'importId':import_id,'status':'prepared',
        'directory':str(final/'game'),'entry':selected,'source':str(original or source),
        'sha256':description['sha256'],'console':description['console'],'inspection':description,
        'files':rows,'assetsComplete':source.is_dir() or bool(record.get('disc_image')),
        'nativeGameReady':False,'createdAt':time.time()}
    write_json(final/'input.json',saved)
    write_json(project.dir/'xbox/latest-input.json',{'importId':import_id})
    context.progress(100,'Xbox input prepared')
    return saved


def input_info(project,import_id=''):
    if not import_id:import_id=read_json(project.dir/'xbox/latest-input.json',{}).get('importId','')
    if not import_id:return {'available':False,'projectId':project.id,'build':build_info(project)}
    value=read_json(project.dir/'xbox/inputs'/_id(import_id)/'input.json',{})
    if not value:fail('The Xbox input receipt is missing.','NotFound')
    return dict(value,available=True,build=build_info(project))


def _input(project,import_id,context):
    value=input_info(project,import_id)
    if not value.get('available'):fail('Prepare Xbox input before creating a native project.','NotFound')
    root=(project.dir/'xbox/inputs'/value['importId']/'game').resolve(strict=True)
    if Path(value['directory']).resolve()!=root:fail('The Xbox input receipt changed.','IntegrityFailure')
    selected=(root/_relative(value['entry'])).resolve(strict=True)
    if not selected.is_relative_to(root) or sha256_file(selected,context.cancellation)!=value['sha256']:
        fail('The Xbox executable changed. Prepare it again.','IntegrityFailure')
    return value,root,selected


def build_info(project,build_id=''):
    if not build_id:build_id=read_json(project.dir/'xbox/latest-build.json',{}).get('buildId','')
    if not build_id:return {'available':False,'projectId':project.id}
    record=read_json(project.dir/'xbox/builds'/(_id(build_id)+'.json'),{})
    if not record:fail('The Xbox native project receipt is missing.','NotFound')
    return dict(record,available=True)


def _save_build(project,record):
    write_json(project.dir/'xbox/builds'/(record['buildId']+'.json'),record)
    write_json(project.dir/'xbox/latest-build.json',{'buildId':record['buildId']})
    return record


def _manifest(directory):
    found=list(directory.glob('*_manifest.toml'))
    if len(found)!=1:fail('Choose a native project containing one ReXGlue manifest.')
    if found[0].stat().st_size>1024**2:fail('The ReXGlue manifest is too large.','ResourceLimit')
    return found[0],tomllib.loads(found[0].read_text('utf-8'))


def attach(store,directory,context):
    directory=Path(directory).expanduser()
    if not directory.is_absolute() or not directory.is_dir():fail('Choose an existing absolute ReXGlue project folder.')
    directory=directory.resolve()
    manifest,config=_manifest(directory)
    info=read_json(directory/'native-project.json',{})
    previous=read_json(directory/'native-build.json',{})
    guest=(directory/config['entrypoint']['file_path']).resolve(strict=True)
    description=formats.inspect(guest)
    expected=info.get('executable_sha256') or previous.get('guest_sha256') or description['sha256']
    if description['console']!='xbox360' or description['sha256']!=expected:
        fail('The native project does not match its Xbox executable.','IntegrityFailure')
    game=(Path(info['game']) if info.get('game') else directory/config['project'].get('game_root',str(guest.parent))).resolve(strict=True)
    if not game.is_dir() or not guest.is_relative_to(game):fail('The game data folder does not match the native project.','IntegrityFailure')
    project,_=store.open(guest,source_path=str(guest),cancellation=context.cancellation)
    _metadata(project,description)
    record={'schemaVersion':1,'projectId':project.id,'buildId':uuid.uuid4().hex,
        'status':'native-project','directory':str(directory),'gameDirectory':str(game),
        'entry':guest.relative_to(game).as_posix(),'guestSha256':description['sha256'],
        'manifestSha256':sha256_file(manifest,context.cancellation),'attached':True,
        'sdkRoot':info.get('sdk',''),'nativeGameReady':False,'createdAt':time.time()}
    _read_build(record,context,required=False)
    plugin=directory/'build/rexgpu-xenos-occlusion.dll'
    if plugin.is_file():record['gpuPluginSha256']=sha256_file(plugin,context.cancellation)
    return _save_build(project,record)


def create(project,context,import_id='',name=''):
    value,game,guest=_input(project,import_id,context)
    if value['console']!='xbox360':fail('Original Xbox XBE inspection is available; native XBE recompilation is not implemented.','Unsupported')
    sdk=tools()['settings'].get('sdkRoot','')
    if not sdk:fail('Install or configure the ReXGlue SDK first.','MissingDependency')
    name=name or 'XboxGame_'+value['sha256'][:8]
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',name):fail('Use a short ASCII C++ project identifier.')
    build_id=uuid.uuid4().hex
    directory=project.dir/'xbox/builds'/build_id/'native'
    directory.parent.mkdir(parents=True)
    context.progress(5,'Creating native Xbox project')
    _worker(context,BUNDLE/'scripts/rex_project.py',['init','--sdk',sdk,'--game',game,
        '--project',directory,'--name',name,'--entry',value['entry']],progress_root=directory)
    manifest,_=_manifest(directory)
    record={'schemaVersion':1,'projectId':project.id,'buildId':build_id,'importId':value['importId'],
        'status':'native-project','directory':str(directory),'gameDirectory':str(game),
        'entry':value['entry'],'guestSha256':value['sha256'],
        'manifestSha256':sha256_file(manifest,context.cancellation),'attached':False,'sdkRoot':sdk,
        'nativeGameReady':False,'createdAt':time.time()}
    context.progress(100,'Native Xbox project created')
    return _save_build(project,record)


def _verify(project,build_id,context):
    record=build_info(project,build_id)
    if not record.get('available'):fail('Create or attach a native Xbox project first.','NotFound')
    directory=Path(record['directory']).resolve(strict=True)
    if not record['attached'] and not directory.is_relative_to(project.dir.resolve()):
        fail('The native project directory changed.','IntegrityFailure')
    manifest,config=_manifest(directory)
    if sha256_file(manifest,context.cancellation)!=record['manifestSha256']:
        fail('The native project manifest changed. Attach or create the project again.','IntegrityFailure')
    guest=(directory/config['entrypoint']['file_path']).resolve(strict=True)
    game=Path(record['gameDirectory']).resolve(strict=True)
    if guest!=(game/_relative(record['entry'])).resolve() or sha256_file(guest,context.cancellation)!=record['guestSha256']:
        fail('The Xbox executable changed. Prepare it again.','IntegrityFailure')
    return record,directory,config


def _read_build(record,context,required=True):
    directory=Path(record['directory']).resolve()
    native=read_json(directory/'native-build.json',{})
    if not native:
        if required:fail('Build the native Xbox project before launching it.','NotFound')
        return
    executable=Path(native.get('executable','')).resolve(strict=True)
    if (executable.parent!=directory/'build' or native.get('guest_sha256')!=record['guestSha256']
            or sha256_file(executable,context.cancellation)!=native.get('sha256')):
        fail('The compiled Xbox executable does not match its build receipt.','IntegrityFailure')
    record.update(status='built',executable=str(executable),executableSha256=native['sha256'],buildLog=native.get('build_log',''))
    log=Path(record['buildLog']).resolve()
    if log.is_file() and log.is_relative_to(directory/'logs'):
        with log.open('rb') as stream:
            stream.seek(max(0,log.stat().st_size-16384))
            record['output']=process.tail(stream.read().decode('utf-8','replace'),35)


def build(project,context,build_id='',jobs=4):
    record,directory,_=_verify(project,build_id,context)
    if os.name!='nt':fail('This integrated native Xbox build profile currently supports Windows x64.','Unsupported')
    sdk=tools()['settings'].get('sdkRoot') or record.get('sdkRoot')
    if not sdk or not (Path(sdk)/'bin/rexglue.exe').is_file():fail('Install or configure the ReXGlue SDK first.','MissingDependency')
    record['status']='building';_save_build(project,record)
    try:
        _worker(context,BUNDLE/'scripts/rex_project.py',['build','--sdk',sdk,'--project',directory,
            '--jobs',max(1,min(16,int(jobs)))],progress_root=directory)
        _read_build(record,context)
        plugin=tools()['settings'].get('gpuPlugin')
        if record['guestSha256']==HALO_SHA and plugin:
            destination=directory/'build/rexgpu-xenos-occlusion.dll'
            if Path(plugin).resolve()!=destination.resolve():shutil.copy2(plugin,destination)
            record['gpuPluginSha256']=sha256_file(destination,context.cancellation)
        record['sdkRoot']=sdk
        record['builtAt']=time.time()
    except BaseException:
        record['status']='build-failed';_save_build(project,record);raise
    context.progress(100,'Native Xbox build completed')
    return _save_build(project,record)


def _halo_flags(directory,coop,fullscreen):
    plugin=directory/'build/rexgpu-xenos-occlusion.dll'
    return {'mnk_mode':'true','mnk_mouse':'true','mnk_sensitivity':'1.0',
        'gpu_plugin':'xenos-occlusion' if plugin.is_file() else 'xenos',
        'gpu_allow_invalid_fetch_constants':'true','query_occlusion_fake_sample_count':'0',
          'native_querybatch_range':'256','readback_resolve':'full',
          'gamma_render_target_as_unorm16':'false',
        'occlusion_query_enable':'true','vsync':'false','fullscreen':str(fullscreen).lower(),
        'present_letterbox':'false','window_width':'1152','window_height':'648',
        'keybind_lstick_up':'W','keybind_lstick_down':'S','keybind_lstick_left':'A','keybind_lstick_right':'D',
        'keybind_a':'Space','keybind_b':'F,Backspace','keybind_x':'R,E','keybind_y':'Q',
        'keybind_right_trigger':'LMB','keybind_left_trigger':'G','keybind_rstick_press':'RMB',
        'keybind_lstick_press':'C','keybind_left_shoulder':'1','keybind_right_shoulder':'3',
        'keybind_rstick_up':'','keybind_rstick_down':'','keybind_rstick_left':'','keybind_rstick_right':'',
        'keybind_dpad_up':'Up','keybind_dpad_down':'Down','keybind_dpad_left':'Left','keybind_dpad_right':'Right',
        'keybind_start':'Return','keybind_back':'Tab','native_local_players':'2' if coop else '1',
        'native_keyboard_player_one':'true','log_max_file_size_mb':'20','log_max_files':'4'}


def _halo_player_settings(user_root,coop):
    """Older native builds load this profile after CLI flags; keep the UI choice effective."""
    path=user_root/'campaign-coop.toml'
    if path.exists() and path.stat().st_size>65536:fail('The local campaign profile is too large.','IntegrityFailure')
    text=path.read_text('utf-8') if path.exists() else ''
    if len(text)>65536:fail('The local campaign profile is too large.','IntegrityFailure')
    parsed=tomllib.loads(text)
    boundary=re.search(r'(?m)^\s*\[',text)
    head,tail=(text[:boundary.start()],text[boundary.start():]) if boundary else (text,'')
    for key,value in [('local_players','2' if coop else '1'),('keyboard_player_one','true')]:
        pattern=re.compile(r'(?m)^[ \t]*(?:'+key+r'|"'+key+r'"|\''+key+r"\')[ \t]*=.*$")
        if pattern.search(head):head=pattern.sub(key+' = '+value,head,count=1)
        elif key in parsed:fail('The local campaign profile must use ordinary root settings.','IntegrityFailure')
        else:head+=(('' if not head or head.endswith('\n') else '\n')+key+' = '+value+'\n')
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(head+tail,encoding='utf-8')
    os.replace(temporary,path)


def run(project,context,build_id='',coop=False,fullscreen=False,timeout=14400):
    record,directory,_=_verify(project,build_id,context)
    if record.get('status')!='built':fail('Build the native Xbox project before launching it.','NotFound')
    _read_build(record,context)
    if record['executableSha256']!=build_info(project,record['buildId']).get('executableSha256'):
        fail('The Xbox build changed. Refresh or rebuild it before launching.','IntegrityFailure')
    if os.name!='nt':fail('The compiled Xbox application requires Windows.','Unsupported')
    if coop and record['guestSha256']!=HALO_SHA:fail('The local coop profile is available only for the verified Halo build.','Unsupported')
    plugin=directory/'build/rexgpu-xenos-occlusion.dll'
    expected=record.get('gpuPluginSha256')
    if expected and (not plugin.is_file() or sha256_file(plugin,context.cancellation)!=expected):
        fail('The native GPU plugin changed. Rebuild or attach the project again.','IntegrityFailure')
    if not record.get('attached'):
        imported=input_info(project,record['importId'])
        if inventory(Path(record['gameDirectory']),context,DEFAULT_LIMIT)!=imported['files']:
            fail('The saved game data changed. Prepare the input again.','IntegrityFailure')
    data=directory/'data'
    for name in ('user','cache','metadata'):(data/name).mkdir(parents=True,exist_ok=True)
    if record['guestSha256']==HALO_SHA:_halo_player_settings(data/'user',coop)
    flags=_halo_flags(directory,coop,fullscreen) if record['guestSha256']==HALO_SHA else {'gpu_plugin':'xenos','fullscreen':str(fullscreen).lower()}
    flags.update(game_data_root=record['gameDirectory'],user_data_root=str(data/'user'),cache_root=str(data/'cache'),
        metadata_root=str(data/'metadata'),log_file=str(Path(context.workdir)/'xbox-game.log'),log_level='info')
    saved={'runId':uuid.uuid4().hex,'buildId':record['buildId'],'status':'running',
        'executableSha256':record['executableSha256'],'nativeGameReady':False,'createdAt':time.time()}
    run_receipt=project.dir/'xbox/runs'/(saved['runId']+'.json')
    write_json(run_receipt,saved)
    context.progress(1,'Native Xbox game running; cancel this job to stop it')
    try:
        code,out,err=process.run([record['executable'],*[f'--{k}={v}' for k,v in flags.items()]],
            context=context,cwd=directory/'build',timeout=max(1,min(int(timeout),28800)),
            log_name='xbox-game',own_children=True,output_limit=8*1024**2)
        saved.update(status='executed-unverified' if code==0 else 'execution-failed',exitCode=code,output=process.tail(err or out,25))
    except BaseException:
        saved['status']='interrupted';write_json(run_receipt,saved);raise
    saved['finishedAt']=time.time();write_json(run_receipt,saved)
    return saved


def guide(language='en'):
    document=APP/('Docs/XboxPorting.fr.md' if language=='fr' else 'Docs/XboxPorting.md')
    return {'path':str(document),'documentation':document.read_text('utf-8'),
        'method':'Static CPU recompilation plus a console compatibility runtime and graphics translation.',
        'scope':{'xbox':'XBE inspection and asset preparation; no native XBE runtime.',
                 'xbox360':'ReXGlue native projects; title-specific compatibility.',
                 'haloCoop':'Local two-player profile; gameplay validation pending.',
                 'directIp':'Campaign session integration incomplete.',
                 'rayTracing':'Experimental; not a complete material/light renderer.'},
        'rules':['Bind every code patch to an exact executable SHA-256.',
                 'Keep original inputs and SDK sources unchanged.',
                 'Distinguish translation, compilation, linking and gameplay validation.',
                 'Keep simulation timing separate from unlocked presentation FPS.',
                 'Handle per-view interpolation history and rendering for split screen.',
                 'Audit console imports, PowerPC register arguments, stack arguments and endianness.',
                 'Never report stubbed network calls as an established campaign connection.']}
