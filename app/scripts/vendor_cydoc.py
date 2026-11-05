"""Package a pinned clean CyDoc source with existing build dependencies, without editing it."""
from pathlib import Path
import argparse,hashlib,io,json,os,shutil,subprocess,tarfile,zipfile

ROOT=Path(__file__).resolve().parents[2]
REVISION='774f2a7eabf7dd181a98ffc5add115b580b67f42'
REPOSITORY='https://github.com/MrMybal/CyDoc'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path,help='Clean CyDoc checkout with its existing npm build dependencies')
    args=parser.parse_args();source=args.source.resolve()
    git=['git','-c','safe.directory='+source.as_posix(),'-C',str(source)]
    if subprocess.check_output(git+['rev-parse','HEAD'],text=True).strip()!=REVISION:
        raise SystemExit('CyDoc checkout must match the pinned revision')
    if subprocess.check_output(git+['status','--porcelain','--untracked-files=no'],text=True).strip():
        raise SystemExit('CyDoc has tracked changes; refusing to package a dirty dependency')
    work=ROOT/'runtime/build/cydoc-vendor/source'
    if work.exists():raise SystemExit('Remove the previous generated vendor source before repackaging')
    work.mkdir(parents=True)
    raw=subprocess.check_output(git+['archive','--format=zip',REVISION])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:archive.extractall(work)
    deps=source/'node_modules'
    compiler=deps/'typescript/bin/tsc'
    if not compiler.is_file():raise SystemExit('Build dependencies are missing; prepare CyDoc using its official guide first')
    link=work/'node_modules'
    if os.name=='nt':
        subprocess.run(['powershell.exe','-NoProfile','-Command',
            'New-Item -ItemType Junction -Path $env:CYDOC_BUILD_LINK -Target $env:CYDOC_BUILD_DEPS | Out-Null'],
            env=dict(os.environ,CYDOC_BUILD_LINK=str(link),CYDOC_BUILD_DEPS=str(deps)),check=True)
    else:link.symlink_to(deps,target_is_directory=True)
    try:
        subprocess.run(['node',str(compiler),'-p',str(work/'tsconfig.json')],cwd=work,check=True)
        shutil.copyfile(work/'src/viewer.css',work/'dist/viewer.css')
        destination=ROOT/'docs/cydoc/vendor';destination.mkdir(parents=True,exist_ok=True)
        npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
        result=subprocess.check_output([npm,'pack','--ignore-scripts','--json','--pack-destination',str(destination)],
            cwd=work,text=True,env=dict(os.environ,npm_config_cache=str(ROOT/'runtime/cache/npm')))
        filename=json.loads(result)[0]['filename'];package=destination/filename
        with tarfile.open(package) as archive:
            names=set(archive.getnames())
            assert 'package/tools/cli.mjs' in names and 'package/dist/viewer.js' in names
            assert not any('/node_modules/' in name for name in names)
        license_text=(work/'LICENSE').read_bytes()
        (destination/'CyDoc-LICENSE.txt').write_bytes(license_text)
        metadata={'library':'CyDoc','version':'0.1.0','repository':REPOSITORY,'revision':REVISION,
            'package':package.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(package.read_bytes()).hexdigest(),
            'license':'MIT','licenseUrl':REPOSITORY+'/blob/'+REVISION+'/LICENSE','modules':['image']}
        (ROOT/'app/vendor/cydoc-source.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(metadata,indent=2))
    finally:
        if link.exists():
            assert link.resolve()==deps.resolve()
            if os.name=='nt':os.rmdir(link)
            else:link.unlink()

if __name__=='__main__':main()
