"""Build complete Windows x64 portable/installer artifacts from a verified source tree.

Uses a fresh relocatable Python distribution and hash-locked wheels, never the
developer's venv, data, caches, optional engines or unrelated module checkouts.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'
CONFIG = APP / 'packaging/windows-runtime.json'
LOCK = APP / 'packaging/windows-requirements.lock'
WORK = ROOT / 'runtime/build/windows-packaging'
DIST = ROOT / 'dist'


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def run(command, **options):
    return subprocess.run([str(c) for c in command], check=True, **options)


def git(*args):
    return run(['git', '-c', 'safe.directory=' + ROOT.as_posix(), *args], cwd=ROOT,
               capture_output=True, text=True).stdout.strip()


def reset_owned(path, parent):
    path, parent = Path(path).absolute(), Path(parent).resolve()
    def linked(p):
        return p.is_symlink() or p.exists() and bool(getattr(p.lstat(), 'st_file_attributes', 0) & 0x400)
    if linked(path) or not path.resolve().is_relative_to(parent) or path.resolve() == parent:
        raise ValueError('Refusing linked or external packaging path')
    if path.exists():
        for directory, folders, files in os.walk(path, followlinks=False):
            for name in folders + files:
                child = Path(directory)/name
                if linked(child) or not child.resolve().is_relative_to(path.resolve()):
                    raise ValueError('Refusing linked packaging child')
        shutil.rmtree(path)
    path.mkdir(parents=True)


def download(row, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_file():
        temporary = destination.with_suffix(destination.suffix + '.part')
        request = urllib.request.Request(row['url'], headers={'User-Agent':'CyDecompilator-packaging'})
        with urllib.request.urlopen(request, timeout=120) as source, temporary.open('wb') as out:
            shutil.copyfileobj(source, out)
        os.replace(temporary, destination)
    if destination.stat().st_size != row['size'] or digest(destination) != row['sha256']:
        raise ValueError('Packaging download failed size/SHA-256 verification: ' + destination.name)
    return destination


def extract_python(archive, destination):
    destination.mkdir(parents=True)
    with tarfile.open(archive, 'r:gz') as source:
        for member in source:
            parts = Path(member.name).parts
            if not parts or parts[0] != 'python' or '..' in parts or member.issym() or member.islnk():
                raise ValueError('Unexpected Python archive entry')
            if not (member.isfile() or member.isdir()):
                raise ValueError('Non-regular Python archive entry')
            target = destination.joinpath(*parts[1:])
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError('Python archive escaped its destination')
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as incoming, target.open('wb') as out:
                    shutil.copyfileobj(incoming, out)


def source_files():
    paths = git('ls-files', '-z').split('\0')
    roots = {'README.md','README.fr.md','LISEZ-MOI.md','CHANGELOG.md','CHANGELOG.en.md','LICENSE'}
    pictures = {'workspace.png','project.png','history.png','investigation.png'}
    for name in sorted(p for p in paths if p):
        if (name in roots or name.startswith('app/') and not name.startswith(('app/tests/','app/.CyDocBuild/'))
                or name.startswith('website/assets/') and Path(name).name in pictures):
            if Path(name).suffix not in {'.pyc','.pyo'} and '__pycache__' not in Path(name).parts:
                yield name


def build_payload(allow_working_tree=False):
    if os.name != 'nt':
        raise SystemExit('Windows x64 packaging must run on Windows.')
    dirty = git('status','--porcelain','--untracked-files=no')
    if dirty and not allow_working_tree:
        raise SystemExit('Commit packaging inputs first; --allow-working-tree is for local validation only.')
    config = json.loads(CONFIG.read_text('utf-8'))
    version = json.loads((APP/'CyTool.json').read_text('utf-8'))['version']
    if shutil.disk_usage(ROOT).free < 2 * 1024**3:
        raise SystemExit('Packaging requires at least 2 GiB free space; no files have been staged.')
    from scripts import build_documentation
    build_documentation.check_current()
    stage = WORK/'payload'
    reset_owned(stage, WORK)
    for name in source_files():
        source = ROOT/name
        if source.is_symlink() or not source.resolve().is_relative_to(ROOT):
            raise ValueError('Refusing linked source input')
        target = stage/name; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)
    if not (stage/'app/packaging/vendor'/config['sdk']['wheel']).is_file():
        raise SystemExit('Add the packaging inputs to Git before building a local candidate.')
    python_archive = download(config['python'],WORK/'downloads'/config['python']['name'])
    home = stage/'runtime/python'
    extract_python(python_archive,home)
    interpreter = home/'python.exe'
    wheels = WORK/'wheels'; wheels.mkdir(parents=True,exist_ok=True)
    sdk = APP/'packaging/vendor'/config['sdk']['wheel']
    if digest(sdk) != config['sdk']['sha256']:
        raise ValueError('Vendored SDK wheel hash mismatch')
    shutil.copy2(sdk,wheels/sdk.name)
    env = {**os.environ,'PIP_CONFIG_FILE':os.devnull,'PIP_DISABLE_PIP_VERSION_CHECK':'1',
           'PIP_CACHE_DIR':str(WORK/'pip-cache'),'TEMP':str(WORK/'tmp'),'TMP':str(WORK/'tmp')}
    (WORK/'tmp').mkdir(exist_ok=True)
    # Download resolution is fully locked; cached artifacts are hash-checked again by pip.
    run([interpreter,'-E','-s','-m','pip','download','--only-binary=:all:','--no-cache-dir',
         '--find-links',wheels,'--require-hashes','-r',LOCK,'--dest',wheels],env=env)
    run([interpreter,'-E','-s','-m','pip','install','--no-index','--find-links',wheels,
         '--no-cache-dir','--no-compile','--no-warn-script-location','--require-hashes','-r',LOCK],env=env)
    run([interpreter,'-E','-s','-m','pip','check'],env=env)
    # pip-generated console scripts contain absolute build paths. Modules remain usable
    # through python -m; the native proxy below preserves existing MCP configurations.
    for path in (home/'Scripts').glob('*.exe'):
        path.unlink()
    for path in (home/'Scripts').glob('*.py'):
        content = path.read_bytes()
        if content.startswith(b'#!'):
            path.write_bytes(b'#!python\n' + content.split(b'\n', 1)[1])
    for path in home.rglob('direct_url.json'):
        path.unlink()
    for path in home.rglob('*.pyc'):
        path.unlink()
    native = WORK/'native'
    run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',APP/'build_launcher.ps1',
         '-OutputDirectory',native,'-BuildDirectory',WORK/'native-objects'])
    for name in ['CyDecompilator.exe','CyDecompilatorCLI.exe']:
        shutil.copy2(native/name,stage/name)
    (home/'Scripts').mkdir(exist_ok=True)
    shutil.copy2(native/'python-proxy.exe',home/'Scripts/python.exe')
    # Native DLLs ship in their official wheels and Python distribution, without registry setup.
    metadata = {'version':version,'runtimeAbi':'python311-cytools010-imgui192-cydec01',
                'repository':'MrMybal/CyDecompilator','commit':git('rev-parse','HEAD'),
                'distribution':'windows-x64-full','python':config['python'],'sdk':config['sdk'],
                'requirementsSha256':digest(LOCK),'workingTreeCandidate':bool(dirty)}
    (stage/'app/release.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
    # Only data created after deployment belongs beside the portable installation.
    if (stage/'data').exists() or any((stage/'runtime'/n).exists() for n in ['engines','downloads','updates']):
        raise ValueError('Local application data entered the distribution')
    return stage,version,metadata


def archive_payload(stage,version):
    if (stage/'data').exists():
        raise ValueError('Refusing a payload that has been run or contains user data')
    DIST.mkdir(exist_ok=True)
    target = DIST/f'CyDecompilator-{version}-windows-x64-portable.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in sorted(stage.rglob('*')):
            if path.is_file():
                archive.write(path,'CyDecompilator/'+path.relative_to(stage).as_posix())
    return target


def compile_installer(stage,version,iscc):
    if not Path(iscc).is_file():
        raise SystemExit('Supply --iscc with the installed Inno Setup 7 compiler.')
    run([iscc,'/Qp','/DPackageRoot='+str(stage),'/DAppVersion='+version,
         '/DArtifactDirectory='+str(DIST),APP/'packaging/CyDecompilator.iss'])
    result = DIST/f'CyDecompilator-{version}-windows-x64-setup.exe'
    if not result.is_file():
        raise ValueError('Installer compiler produced no artifact')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iscc',type=Path,default=WORK/'inno/ISCC.exe')
    parser.add_argument('--allow-working-tree',action='store_true')
    parser.add_argument('--reuse-payload',action='store_true',help='Rearchive an already validated payload')
    parser.add_argument('--portable-only',action='store_true')
    args=parser.parse_args()
    if args.reuse_payload:
        stage=WORK/'payload'; metadata=json.loads((stage/'app/release.json').read_text('utf-8'));version=metadata['version']
        if (metadata['commit'] != git('rev-parse','HEAD') or metadata['workingTreeCandidate']
                or git('status','--porcelain','--untracked-files=no')):
            raise SystemExit('Refusing to reuse a payload from other or uncommitted sources.')
    else:
        stage,version,metadata=build_payload(args.allow_working_tree)
    artifacts=[archive_payload(stage,version)]
    if not args.portable_only:
        artifacts.append(compile_installer(stage,version,args.iscc))
    report=[]
    for path in artifacts:
        sha=digest(path)
        path.with_name(path.name+'.sha256').write_text(f'{sha}  {path.name}\n',encoding='ascii')
        report.append({'name':path.name,'size':path.stat().st_size,'sha256':sha})
    (WORK/'artifacts.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    sys.path.insert(0,str(APP))
    main()
