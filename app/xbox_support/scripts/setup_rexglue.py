"""Install a pinned official ReXGlue SDK release into the separate engine directory."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import urllib.request
import zipfile

VERSION='0.10.0'
FILENAME=f'rexglue-sdk-{VERSION}-win-amd64.zip'
URL=f'https://github.com/rexglue/rexglue-sdk/releases/download/v{VERSION}/{FILENAME}'
SHA256='ad4485da853fbe932e9f5dbb643f9b5fe85dc73775ebbad4df6879fe6df0c11b'


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def install(root:Path):
    root=root.resolve();root.mkdir(parents=True,exist_ok=True)
    archive=root/FILENAME
    if not archive.exists():
        request=urllib.request.Request(URL,headers={'User-Agent':'CyXboxNative/0.1'})
        temporary=root/(FILENAME+'.partial')
        with urllib.request.urlopen(request,timeout=60) as source,temporary.open('wb') as target:
            shutil.copyfileobj(source,target,1024*1024)
        if digest(temporary)!=SHA256:raise ValueError('SDK download SHA-256 mismatch')
        temporary.rename(archive)
    if digest(archive)!=SHA256:raise ValueError('SDK archive SHA-256 mismatch')
    destination=root/VERSION
    if destination.exists():
        raise ValueError('SDK destination already exists; select a new engine root')
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist())>2*1024**3:raise ValueError('Unexpected SDK uncompressed size')
        for item in z.infolist():
            relative=PurePosixPath(item.filename)
            if relative.is_absolute() or '..' in relative.parts or any(':' in part or '\\' in part for part in relative.parts):
                raise ValueError('Unsafe SDK archive path')
            if (item.external_attr>>16)&0o170000==0o120000:raise ValueError('SDK symlinks are not supported')
        destination.mkdir()
        for item in z.infolist():
            output=destination.joinpath(*PurePosixPath(item.filename).parts)
            if item.is_dir():output.mkdir(parents=True,exist_ok=True)
            else:
                output.parent.mkdir(parents=True,exist_ok=True)
                with z.open(item) as source,output.open('xb') as target:shutil.copyfileobj(source,target)
    executables=list(destination.rglob('rexglue.exe'))
    if len(executables)!=1:raise ValueError('Expected one rexglue.exe in SDK')
    receipt=dict(schema_version=1,version=VERSION,url=URL,archive_sha256=SHA256,
                 executable=str(executables[0]),executable_sha256=digest(executables[0]),
                 status='installed',native_game_ready=False)
    (root/'sdk.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    return receipt


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path,default=Path('tools/rexglue'))
    a=p.parse_args();print(json.dumps(install(a.directory),indent=2))


if __name__=='__main__':main()
