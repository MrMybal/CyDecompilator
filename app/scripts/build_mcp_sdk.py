"""Compile the selected CyMCPSDK modules and the application's C ABI from source."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile
import re

ROOT=Path(__file__).resolve().parents[2]
APP=ROOT/'app'

def git(source,*args):
    return subprocess.check_output(['git','-c','safe.directory='+source.as_posix(),'-C',str(source),*args],text=True).strip()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT.parent/'CyMCPSDK')
    parser.add_argument('--output',type=Path,default=ROOT/'runtime/native/CyMCPSDK')
    parser.add_argument('--jobs',type=int,default=3)
    parser.add_argument('--archive-source',action='store_true')
    parser.add_argument('--bundled',action='store_true',help='Build the hash-verified SDK source archive pinned by this application.')
    args=parser.parse_args()
    source=args.source.resolve()
    if args.bundled or not source.is_dir():
        archive=APP/'native/vendor/CyMCPSDK-source.zip'
        source=ROOT/'runtime/build/cymcpsdk/sources'
        if args.bundled and not archive.is_file():raise RuntimeError('The pinned SDK source archive is missing.')
        if archive.is_file():
            expected=json.loads((APP/'native/cymcpsdk-source.json').read_text('utf-8')).get('archiveSha256')
            if expected and hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:raise RuntimeError('SDK source archive hash mismatch.')
            source.mkdir(parents=True,exist_ok=True)
            with zipfile.ZipFile(archive) as package: package.extractall(source)
        else:
            subprocess.run(['git','clone','--depth','1','https://github.com/MrMybal/CyMCPSDK.git',str(source)],check=True)
    provenance_path=APP/'native/cymcpsdk-source.json'
    if (source/'.git').exists():
        revision=git(source,'rev-parse','HEAD')
        if git(source,'status','--porcelain'): raise RuntimeError('SDK has local changes; commit them before recording a reproducible source revision.')
    else: revision=json.loads(provenance_path.read_text('utf-8'))['revision']
    cmake=shutil.which('cmake')
    if not cmake and os.name=='nt':
        vswhere=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Microsoft Visual Studio/Installer/vswhere.exe'
        vs=subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],text=True).strip()
        cmake=str(Path(vs)/'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe')
    if not cmake: raise RuntimeError('Install CMake 3.24+ and a C++20 compiler.')
    import importlib.util
    spec=importlib.util.spec_from_file_location('sdk_overlay',APP/'native/sdk_overlay.py');overlay=importlib.util.module_from_spec(spec);spec.loader.exec_module(overlay)
    compiled_source,extensions=overlay.prepare(source,ROOT/'runtime/build/cymcpsdk/sdk-source')
    build=ROOT/'runtime/build/cymcpsdk/native'
    configuration=[cmake,'-S',str(APP/'native'),'-B',str(build),'-DCYDEC_SDK_SOURCE='+str(compiled_source),'-DCYDEC_SDK_REVISION='+revision,'-DCMAKE_BUILD_TYPE=Release']
    if os.name=='nt': configuration+=['-G','Visual Studio 17 2022','-A','x64']
    subprocess.run(configuration,check=True)
    subprocess.run([cmake,'--build',str(build),'--config','Release','--target','cydec_mcp','--parallel',str(args.jobs)],check=True)
    binary=next(build.rglob('cydec_mcp.dll' if os.name=='nt' else 'libcydec_mcp.so'))
    args.output.mkdir(parents=True,exist_ok=True)
    target=args.output/binary.name
    # An already loaded Windows DLL may still be reused when its bytes match.
    if not target.is_file() or hashlib.sha256(target.read_bytes()).digest()!=hashlib.sha256(binary.read_bytes()).digest():
        shutil.copy2(binary,target)
    files={}
    for folder in ('include','src','cmake','third_party'):
        for path in (source/folder).rglob('*'):
            if path.is_file(): files[path.relative_to(source).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ('CMakeLists.txt','LICENSE','README.md','README.fr.md','VERSION.md','VERSION.fr.md','THIRD_PARTY_NOTICES.md'):
        files[name]=hashlib.sha256((source/name).read_bytes()).hexdigest()
    version=re.search(r'const char\* version = "([^"]+)"',(source/'include/cymcp/core.hpp').read_text('utf-8')).group(1)
    metadata={'repository':'https://github.com/MrMybal/CyMCPSDK','version':version,'revision':revision,'modules':['Core','Platform','Http','MCP','AI'],'files':files}
    if args.archive_source:
        vendor=APP/'native/vendor';vendor.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(vendor/'CyMCPSDK-source.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(files):
                item=zipfile.ZipInfo(name,date_time=(2026,1,1,0,0,0));item.compress_type=zipfile.ZIP_DEFLATED
                archive.writestr(item,(source/name).read_bytes())
        metadata['archiveSha256']=hashlib.sha256((vendor/'CyMCPSDK-source.zip').read_bytes()).hexdigest()
        provenance_path.write_text(json.dumps(metadata,indent=2)+'\n','utf-8')
        for src,dst in [('LICENSE','CyMCPSDK-MIT.txt'),('THIRD_PARTY_NOTICES.md','CyMCPSDK-NOTICES.md'),('third_party/nlohmann/LICENSE.MIT','nlohmann-MIT.txt'),('third_party/httplib/LICENSE','httplib-MIT.txt'),('third_party/picosha2/LICENSE','picosha2-MIT.txt')]:shutil.copy2(source/src,vendor/dst)
    receipt={**metadata,'hostExtensions':extensions,'binary':binary.name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'hostSources':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (APP/'native/bridge.cpp',APP/'native/CMakeLists.txt',APP/'native/sdk_overlay.py')}}
    (args.output/'build.json').write_text(json.dumps(receipt,indent=2)+'\n','utf-8')
    print(json.dumps({'version':metadata['version'],'revision':revision,'binary':str(target),'bytes':target.stat().st_size}))
if __name__=='__main__': main()
