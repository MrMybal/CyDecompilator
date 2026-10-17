"""Reconstruct editable Node/web/Electron artifacts and bounded build outputs."""
import hashlib
import json
import os
import shutil
import struct
from pathlib import Path

from cytools_core import CyToolError
from . import components, javascript, process
from .paths import read_json, write_json

CONFIG='cydec.project.json'


def revision(root, context):
    from .history import _capture, _revision
    return _revision(_capture(root, context))


def create(project, root, context):
    manifest=read_json(project.binary)
    artifacts=javascript.artifact_root(project)
    files=[]
    for row in manifest['files']:
        context.check()
        name=javascript.safe_relative(row['path'])
        if name in (CONFIG,'recovered.code-workspace'):
            raise CyToolError('Conflict','The snapshot contains reserved reconstruction files: '+name)
        data=(artifacts/name).read_bytes()
        if hashlib.sha256(data).hexdigest()!=row['sha256']:
            raise CyToolError('IntegrityFailure','The application snapshot has changed; open it again.')
        target=root/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(data)
        files.append(name)
    package=read_json(root/'package.json')
    if not isinstance(package,dict) or any(not isinstance(package.get(k,{}),dict) for k in ('scripts','dependencies','devDependencies')):
        raise CyToolError('InvalidParameters','Invalid package.json project metadata.')
    sources=[p for p in files if Path(p).suffix.lower() in javascript.SOURCE_SUFFIXES]
    electron=any('electron' in package.get(k,{}) for k in ('dependencies','devDependencies'))
    if not electron:
        electron=any("require('electron')" in (root/p).read_text(encoding='utf-8',errors='replace') or
                     'from "electron"' in (root/p).read_text(encoding='utf-8',errors='replace') or
                     'require("electron")' in (root/p).read_text(encoding='utf-8',errors='replace') or
                     "from 'electron'" in (root/p).read_text(encoding='utf-8',errors='replace') for p in sources)
    entry=package.get('main','')
    candidates=[p for p in files if Path(p).name.lower() in ('index.html','index.htm')]
    if not entry:
        if not electron and len(candidates)==1:entry=candidates[0]
        elif len(sources)==1:entry=sources[0]
        elif 'main.js' in files:entry='main.js'
        elif 'index.js' in files:entry='index.js'
    if entry:
        entry=javascript.safe_relative(entry)
        if entry not in files:entry=''
    kind='electron' if electron else 'web' if entry.endswith(('.html','.htm')) else 'node'
    if not package:
        package={'name':'recovered-application','version':'0.0.0','private':True}
        if kind!='web' and entry:package['main']=entry
        write_json(root/'package.json',package)
    blockers=[]
    if not entry:blockers.append({'code':'missing-web-entry','message':'Choose the application entry in cydec.project.json.'})
    dependencies={**package.get('dependencies',{}),**package.get('devDependencies',{})}
    if dependencies:blockers.append({'code':'web-dependencies-not-installed','message':'Install the recovered package dependencies before running.'})
    if any(Path(p).suffix.lower()=='.node' for p in files):
        blockers.append({'code':'native-node-abi','message':'Native Node modules require the matching architecture and Electron/Node ABI.'})
    config={'schemaVersion':1,'kind':kind,'entry':entry,'buildScript':'build' if package.get('scripts',{}).get('build') else '',
        'outputDirectory':'build/app','sourceSha256':project.meta()['sha256'],'dependencies':dependencies,
        'blockers':blockers,'excludedArtifacts':manifest.get('unknowns',[])}
    write_json(root/CONFIG,config)
    (root/'recovered.code-workspace').write_text(json.dumps({'folders':[{'path':'.'}],
        'settings':{'files.exclude':{'**/build':True,'**/node_modules':True}}},indent=2)+'\n',encoding='utf-8')
    return {'kind':kind,'entry':CONFIG,'note':'Recovered JavaScript project. Review its entry, dependencies and build script.',
        'reconstruction':{'family':'javascript','target':kind,'blockers':blockers,'unknowns':manifest.get('unknowns',[])}}


def node():
    path=shutil.which('node')
    if not path:raise CyToolError('MissingDependency','Install Node.js and add it to PATH.')
    return path


def npm_command():
    runtime=Path(node())
    cli=runtime.parent/'node_modules/npm/bin/npm-cli.js'
    if not cli.is_file():
        command=shutil.which('npm')
        if command and Path(command).suffix not in ('.cmd','.bat'):return [command]
        raise CyToolError('MissingDependency','Install npm next to Node.js.')
    return [str(runtime),str(cli)]


def output_root(root, config):
    from . import workspace
    relative=config.get('outputDirectory','build/app')
    # Build outputs are separate from source files; never clean or overwrite a user tree.
    name=javascript.safe_relative(relative)
    target=(root/name).resolve()
    if not target.is_relative_to((root/'build').resolve()) or target==root/'build':
        raise CyToolError('InvalidParameters','JavaScript build output must be a subfolder of build.')
    if any(javascript.is_link(p) for p in (root,*[root/Path(*Path(name).parts[:i]) for i in range(1,len(Path(name).parts)+1)]) if p.exists()):
        raise CyToolError('InvalidParameters','Build output cannot follow links.')
    return target


def pack_asar(folder,destination,context):
    files,total={},0
    for directory,dirs,names in os.walk(folder,followlinks=False):
        context.check()
        for name in dirs+names:
            path=Path(directory)/name
            if javascript.is_link(path):raise CyToolError('IntegrityFailure','Electron packaging cannot follow links.')
        for name in names:
            path=Path(directory)/name
            size=path.stat().st_size
            if len(files)>=javascript.MAX_FILES or size>javascript.MAX_FILE or total+size>javascript.MAX_BYTES:
                raise CyToolError('Unsupported','Electron package exceeds reconstruction limits.')
            files[javascript.safe_relative(path.relative_to(folder).as_posix())]=path.read_bytes();total+=size
    offset,header,payload=0,{'files':{}},[]
    for name,data in sorted(files.items()):
        branch=header['files']
        parts=name.split('/')
        if len(parts)>64:raise CyToolError('Unsupported','Electron artifact directory nesting exceeds archive limits.')
        for part in parts[:-1]:branch=branch.setdefault(part,{'files':{}})['files']
        branch[parts[-1]]={'size':len(data),'offset':str(offset),'integrity':{
            'algorithm':'SHA256','hash':hashlib.sha256(data).hexdigest(),'blockSize':4*1024*1024,
            'blocks':[hashlib.sha256(data[i:i+4*1024*1024]).hexdigest() for i in range(0,len(data),4*1024*1024)]}}
        if Path(name).suffix.lower() in ('.node','.dll','.exe'):
            branch[parts[-1]].pop('offset')
            branch[parts[-1]]['unpacked']=True
            path=Path(str(destination)+'.unpacked')/name
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        else:
            payload.append(data);offset+=len(data)
    encoded=json.dumps(header,separators=(',',':'),ensure_ascii=False).encode()
    padded=encoded+b'\0'*((-len(encoded))%4)
    pickle=struct.pack('<II',4+len(padded),len(encoded))+padded
    destination.write_bytes(struct.pack('<II',4,len(pickle))+pickle+b''.join(payload))


def execute(project,action,context,executable='',arguments=()):
    from . import workspace
    from .execution import output_events
    root,_=workspace.root_for(project)
    source_revision=revision(root,context)
    config=read_json(root/CONFIG)
    if config.get('kind') not in ('node','web','electron'):
        raise CyToolError('InvalidParameters','Choose a JavaScript application kind in cydec.project.json.')
    runtime=node()
    package=read_json(root/'package.json')
    output,code,mode=[],0,''
    artifact=output_root(root,config)
    commands=[]
    if action=='install':
        if not (root/'package-lock.json').is_file():
            raise CyToolError('MissingDependency','A package-lock.json is required for reproducible dependency installation.')
        commands=[npm_command()+['ci','--ignore-scripts','--no-audit','--no-fund']]
        mode='dependencies'
    elif action in ('build','rebuild'):
        script=config.get('buildScript','')
        if script:
            if not isinstance(script,str) or script not in package.get('scripts',{}):
                raise CyToolError('InvalidParameters','The selected npm build script is absent.')
            commands=[npm_command()+['run',script]]
            mode='project-build-script'
            if artifact.exists():
                import uuid
                os.replace(artifact,artifact.with_name(artifact.name+'-previous-'+uuid.uuid4().hex[:12]))
        else:
            parser=components.locate('typescript')
            if not parser:raise CyToolError('MissingDependency','Install the private TypeScript parser for JavaScript reconstruction.')
            files,excluded=javascript.read_tree(root,context,excluded_directories=('build',))
            if excluded and any(r['code']=='snapshot-limit' for r in excluded):
                raise CyToolError('InvalidParameters','The source workspace exceeds JavaScript build limits.')
            # A fresh immutable build avoids stale outputs after deleted source files.
            import uuid
            artifact=artifact.parent/('app-'+uuid.uuid4().hex[:12])
            artifact.mkdir(parents=True)
            for name,data in files.items():
                target=artifact/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            request=Path(context.workdir)/'web-build.json'
            write_json(request,{'directory':str(artifact),'files':list(files)})
            helper=Path(__file__).resolve().parents[1]/'javascript/rebuild.cjs'
            commands=[[runtime,helper,parser['parser'],request]]
            mode='syntax-and-transpile'
    elif action=='test':
        if not package.get('scripts',{}).get('test'):
            return {'projectId':project.id,'action':action,'status':'no-tests','exitCode':0,'output':'No test script is configured.','diagnostics':[]}
        commands=[npm_command()+['run','test','--',*arguments]];mode='project-test-script'
    elif action=='run':
        previous=read_json(project.dir/'workspace-build.json')
        if previous.get('status')!='passed' or not previous.get('artifactDirectory'):
            raise CyToolError('InvalidParameters','Build the JavaScript project before running it.')
        artifact=Path(previous['artifactDirectory']).resolve()
        if not artifact.is_relative_to(root/'build') or any(javascript.is_link(p) for p in (artifact,*artifact.parents)):
            raise CyToolError('IntegrityFailure','The build artifact escapes its workspace.')
        if previous.get('sourceRevision')!=source_revision:
            raise CyToolError('Conflict','Sources changed after building. Build again before running.')
        if previous.get('artifactRevision')!=artifact_revision(artifact,context):
            raise CyToolError('IntegrityFailure','The build artifact changed. Build again before running.')
        entry=javascript.safe_relative(config.get('entry',''))
        if config['kind']=='web':
            helper=Path(__file__).resolve().parents[1]/'javascript/serve.cjs'
            commands=[[runtime,helper,artifact,*arguments]]
        elif config['kind']=='electron':
            installed=components.locate('electron') if not executable else None
            path=Path(executable or installed['exe']) if executable or installed else None
            if not path or not path.is_absolute() or not path.is_file():
                raise CyToolError('MissingDependency','Select an absolute Electron runtime executable to run this project.')
            archive=Path(previous.get('appArchive',''))
            if not archive.is_file() or not archive.resolve().is_relative_to(root/'build') or hashlib.sha256(archive.read_bytes()).hexdigest()!=previous.get('archiveSha256'):
                raise CyToolError('IntegrityFailure','The rebuilt Electron archive changed. Build again.')
            if artifact_revision(Path(str(archive)+'.unpacked'),context)!=previous.get('unpackedRevision'):
                raise CyToolError('IntegrityFailure','The unpacked Electron artifacts changed. Build again.')
            commands=[[str(path),str(archive),*arguments]]
        else:
            path=(artifact/entry).with_suffix('.js') if entry.endswith(('.ts','.tsx','.jsx')) else artifact/entry
            if not path.is_file():raise CyToolError('NotFound','The rebuilt JavaScript entry is absent.')
            commands=[[runtime,path,*arguments]]
        mode='run'
    else:raise CyToolError('InvalidParameters','Invalid JavaScript workspace action.')
    for index,command in enumerate(commands):
        context.check()
        code,out,err=process.run(command,cwd=root,context=context,timeout=900,log_name='web-'+action+'-'+str(index),
            on_output=output_events(context),env={'NODE_OPTIONS':None,'NODE_PATH':None},output_limit=2*1024*1024)
        output.append(out+'\n'+err)
        if code:break
    status='passed' if code==0 else 'failed'
    if status=='passed' and action in ('build','rebuild'):
        if not artifact.is_dir():
            status='failed';output.append('The build script did not produce the configured output directory.')
        elif revision(root,context)!=source_revision:
            raise CyToolError('Conflict','Sources changed while building. Build again.')
        else:
            for name in package.get('dependencies',{}):
                if name=='electron':continue
                source=root/'node_modules'/javascript.safe_relative(name)
                if not source.is_dir():
                    status='failed';output.append('Missing runtime dependency: '+name)
            if status=='passed' and config['kind']=='electron':
                # Preserve installed modules, including transitive packages; omit the runtime itself.
                modules=root/'node_modules'
                if modules.is_dir():
                    for item in modules.iterdir():
                        if item.name in ('electron','.bin','.package-lock.json'):continue
                        if javascript.is_link(item):raise CyToolError('Unsupported','Linked dependencies require an explicit build script.')
                        target=artifact/'node_modules'/item.name
                        target.parent.mkdir(parents=True,exist_ok=True)
                        if not target.exists():
                            if item.is_dir():
                                # Validate the complete tree before copytree can follow links.
                                artifact_revision(item,context)
                                shutil.copytree(item,target,symlinks=True)
                            else:shutil.copy2(item,target)
                pack_asar(artifact,artifact.parent/(artifact.name+'.asar'),context)
    result={'projectId':project.id,'action':action,'status':status,'exitCode':code,
        'output':'\n'.join(output)[-200000:],'diagnostics':workspace.diagnostics('\n'.join(output)),
        'directory':str(root),'artifactDirectory':str(artifact) if action in ('build','rebuild') and status=='passed' else '',
        'buildMode':mode,'typeChecked':False,'sourceRevision':source_revision,
        'artifactRevision':artifact_revision(artifact,context) if status=='passed' and action in ('build','rebuild') else ''}
    if status=='passed' and action in ('build','rebuild') and config['kind']=='electron':
        archive=artifact.parent/(artifact.name+'.asar')
        result.update(appArchive=str(archive),archiveSha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            unpackedRevision=artifact_revision(Path(str(archive)+'.unpacked'),context))
    if action in ('build','rebuild'):write_json(project.dir/'workspace-build.json',result)
    return result


def artifact_revision(folder,context):
    if any(javascript.is_link(p) for p in (folder,*folder.parents) if p.exists()):
        raise CyToolError('IntegrityFailure','Build artifacts cannot follow links.')
    digest=hashlib.sha256();total=0;count=0
    for directory,dirs,names in os.walk(folder,followlinks=False):
        context.check();dirs.sort()
        for name in dirs+names:
            if javascript.is_link(Path(directory)/name):raise CyToolError('IntegrityFailure','Build artifacts cannot contain links.')
        for name in sorted(names):
            path=Path(directory)/name;size=path.stat().st_size
            total+=size;count+=1
            if size>javascript.MAX_FILE or total>javascript.MAX_BYTES or count>javascript.MAX_FILES:
                raise CyToolError('Unsupported','Build artifact exceeds reconstruction limits.')
            digest.update(path.relative_to(folder).as_posix().encode());digest.update(b'\0');digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()
