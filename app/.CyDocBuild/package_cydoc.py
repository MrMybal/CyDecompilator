"""Create the documented npm archive from a clean pinned CyDoc Git checkout.

The dependency checkout remains read-only. Its existing build dependencies are
temporarily linked into an exact Git archive inside this private workspace.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

WORKSPACE = Path(__file__).resolve().parent
REVISION = '6ddf9a582defb2f11fbb3f992afef6f98dcadc93'
REPOSITORY = 'https://github.com/MrMybal/CyDoc'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    source = parser.parse_args().source.resolve()
    git = ['git', '-c', 'safe.directory=' + source.as_posix(), '-C', str(source)]
    if subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip() != REVISION:
        raise SystemExit('CyDoc checkout does not match the pinned revision')
    if subprocess.check_output(git + ['status', '--porcelain', '--untracked-files=no'], text=True).strip():
        raise SystemExit('CyDoc has tracked changes')
    work = WORKSPACE / '.work/vendor-source'
    work.mkdir(parents=True, exist_ok=False)
    raw = subprocess.check_output(git + ['archive', '--format=zip', REVISION])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        archive.extractall(work)
    dependencies = source / 'node_modules'
    if not (dependencies / 'typescript/bin/tsc').is_file():
        raise SystemExit('Prepare the upstream build dependencies using its integration guide')
    link = work / 'node_modules'
    if os.name == 'nt':
        subprocess.run(['powershell.exe', '-NoProfile', '-Command',
            'New-Item -ItemType Junction -Path $env:CYDOC_LINK -Target $env:CYDOC_DEPENDENCIES | Out-Null'],
            env={**os.environ, 'CYDOC_LINK': str(link), 'CYDOC_DEPENDENCIES': str(dependencies)}, check=True)
    else:
        link.symlink_to(dependencies, target_is_directory=True)
    vendor = WORKSPACE / 'vendor'
    vendor.mkdir(exist_ok=True)
    try:
        npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
        result = subprocess.run([npm, 'pack', '--json', '--pack-destination', str(vendor)],
            cwd=work, env={**os.environ, 'npm_config_cache': str(WORKSPACE / '.work/npm-cache')},
            check=True, capture_output=True, text=True)
        # npm lifecycle build output may precede the JSON array.
        output = result.stdout
        start = output.rfind('\n[')
        packed = json.loads(output[start + 1:] if start >= 0 else output)
        archive = vendor / packed[0]['filename']
        shutil.copy2(work / 'LICENSE', vendor / 'CyDoc-LICENSE.txt')
        version = json.loads((work / 'package.json').read_text('utf-8'))['version']
        metadata = {'library': 'CyDoc', 'version': version, 'repository': REPOSITORY,
            'revision': REVISION, 'package': archive.relative_to(WORKSPACE).as_posix(),
            'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'license': 'MIT',
            'licenseUrl': REPOSITORY + '/blob/' + REVISION + '/LICENSE', 'modules': ['image']}
        (vendor / 'cydoc-source.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8', newline='\n')
        print(json.dumps(metadata, indent=2))
    finally:
        if link.exists():
            if link.resolve() != dependencies.resolve():
                raise ValueError('Unexpected dependency link')
            if os.name == 'nt':
                os.rmdir(link)
            else:
                link.unlink()


if __name__ == '__main__':
    main()
