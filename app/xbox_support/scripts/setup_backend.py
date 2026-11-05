"""Fetch the pinned upstream CPU translator and build it locally, without app changes.

Usage: python scripts/setup_backend.py --directory tools/xenonrecomp [--build]
Requires Git, CMake 3.20+, Clang 18+ and Windows SDK/MSVC or a Linux toolchain.
No compiled dependency is bundled into this module.
"""
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

REVISION = "ddd128bcca99fe8bfbb99bea583c972351fa6ace"
URL = "https://github.com/hedge-dev/XenonRecomp.git"


def run(args, **kw):
    print(subprocess.list2cmdline([str(a) for a in args]), flush=True)
    subprocess.run([str(a) for a in args], check=True, **kw)


def git(path, *args):
    # Per-command trust for only this selected local checkout; no global config edits.
    return subprocess.check_output(['git', '-c', 'safe.directory=' + str(path), '-C', str(path), *args], text=True).strip()


def checkout(url, revision, path):
    if not path.exists() or not any(path.iterdir()):
        run(['git', 'clone', '--no-checkout', url, path])
    actual = git(path, 'remote', 'get-url', 'origin')
    if actual.rstrip('/') != url.rstrip('/'):
        raise ValueError(f"Unexpected origin at {path}: {actual}")
    if git(path, 'status', '--porcelain', '--untracked-files=no'):
        raise ValueError(f"Refusing to change modified backend checkout: {path}")
    try:
        git(path, 'cat-file', '-e', revision + '^{commit}')
    except subprocess.CalledProcessError:
        run(['git', '-c', 'safe.directory=' + str(path), '-C', path, 'fetch', 'origin', revision])
    run(['git', '-c', 'safe.directory=' + str(path), '-C', path, 'checkout', '--detach', revision])


def toolchain():
    env = os.environ.copy()
    cmake = shutil.which('cmake')
    if os.name == 'nt':
        vswhere = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
        vs = Path(subprocess.check_output([str(vswhere), '-latest', '-products', '*', '-property', 'installationPath'], text=True).strip())
        # Resolve the toolchain without running vendor shell scripts or changing the host.
        msvc = sorted((vs / 'VC/Tools/MSVC').iterdir(), key=lambda p: tuple(int(n) for n in p.name.split('.')))[-1]
        kits = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Windows Kits/10'
        sdk = sorted((kits / 'Include').iterdir(), key=lambda p: tuple(int(n) for n in p.name.split('.')))[-1].name
        env = {k.upper(): v for k, v in env.items()}
        env['INCLUDE'] = ';'.join(str(p) for p in [msvc / 'include', *[kits / 'Include' / sdk / n for n in ('ucrt', 'shared', 'um', 'winrt')]])
        env['LIB'] = ';'.join(str(p) for p in [msvc / 'lib/x64', kits / 'Lib' / sdk / 'ucrt/x64', kits / 'Lib' / sdk / 'um/x64'])
        clang = vs / 'VC/Tools/Llvm/x64/bin/clang-cl.exe'
        cmake = cmake or str(vs / 'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe')
        ninja = vs / 'Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja/ninja.exe'
        env['PATH'] = os.pathsep.join(str(p) for p in [clang.parent, ninja.parent, msvc / 'bin/Hostx64/x64', kits / 'bin' / sdk / 'x64']) + os.pathsep + env['PATH']
        options = ['-G', 'Ninja', '-DCMAKE_C_COMPILER=' + str(clang), '-DCMAKE_CXX_COMPILER=' + str(clang), '-DCMAKE_MAKE_PROGRAM=' + str(ninja)]
    else:
        options = ['-DCMAKE_C_COMPILER=clang', '-DCMAKE_CXX_COMPILER=clang++']
    if not cmake:
        raise ValueError('CMake was not found')
    return cmake, env, options


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory', type=Path, default=Path('tools/xenonrecomp'))
    p.add_argument('--build', action='store_true')
    p.add_argument('--probe', action='store_true', help='Also build the local image inspection bridge')
    p.add_argument('--overlay', action='store_true', help='Build reviewed local control-flow fixes without editing upstream checkout')
    args = p.parse_args()
    root = args.directory.resolve()
    source = root / 'source'
    root.mkdir(parents=True, exist_ok=True)
    checkout(URL, REVISION, source)
    config = configparser.ConfigParser()
    config.read(source / '.gitmodules')
    paths = [config[s]['path'] for s in config.sections()]
    tree = git(source, 'ls-tree', 'HEAD', *paths)
    pins = {line.split('\t')[1]: line.split()[2] for line in tree.splitlines()}
    for s in config.sections():
        path, url = config[s]['path'], config[s]['url']
        if not url.startswith('https://github.com/') or '..' in Path(path).parts or Path(path).is_absolute():
            raise ValueError('Unexpected backend submodule source')
        checkout(url, pins[path], source / path)
    receipt = dict(repository=URL, revision=REVISION, dependencies=pins, status='sources-ready')
    if args.build:
        cmake, env, options = toolchain()
        build = root / 'build-clang'
        with (root / 'build.log').open('w', encoding='utf-8') as log:
            run([cmake, '-S', source, '-B', build, *options, '-DCMAKE_BUILD_TYPE=Release'], env=env, stdout=log, stderr=subprocess.STDOUT)
            run([cmake, '--build', build, '--config', 'Release', '--target', 'XenonRecomp', 'XenonAnalyse', '--parallel', '4'], env=env, stdout=log, stderr=subprocess.STDOUT)
        receipt['status'] = 'built'
        receipt['executables'] = [str(p) for p in build.rglob('XenonRecomp.exe' if os.name == 'nt' else 'XenonRecomp') if p.is_file()]
        if args.overlay:
            from backend_overlay import generate
            overlay = generate(source, root / 'overlay')
            overlay_build = root / 'overlay-build'
            with (root / 'overlay-build.log').open('w', encoding='utf-8') as log:
                run([cmake, '-S', Path(__file__).resolve().parents[1] / 'native', '-B', overlay_build,
                     *options, '-DCMAKE_BUILD_TYPE=Release', '-DXENONRECOMP_SOURCE=' + str(source),
                     '-DXBOX_NATIVE_PATCHED_RECOMPILER=' + overlay['source']], env=env, stdout=log, stderr=subprocess.STDOUT)
                run([cmake, '--build', overlay_build, '--target', 'XenonRecomp', '--parallel', '4'], env=env, stdout=log, stderr=subprocess.STDOUT)
            overlay['executable'] = str(overlay_build / 'upstream/XenonRecomp' / ('XenonRecomp.exe' if os.name == 'nt' else 'XenonRecomp'))
            with Path(overlay['executable']).open('rb') as stream:
                overlay['executable_sha256'] = hashlib.file_digest(stream,'sha256').hexdigest()
            receipt['overlay'] = overlay
        if args.probe:
            probe_build = root / 'probe-build'
            with (root / 'probe-build.log').open('w', encoding='utf-8') as log:
                run([cmake, '-S', Path(__file__).resolve().parents[1] / 'native', '-B', probe_build,
                     *options, '-DCMAKE_BUILD_TYPE=Release', '-DXENONRECOMP_SOURCE=' + str(source)], env=env, stdout=log, stderr=subprocess.STDOUT)
                run([cmake, '--build', probe_build, '--target', 'xbox-image-probe', '--parallel', '4'], env=env, stdout=log, stderr=subprocess.STDOUT)
            receipt['probe'] = str(probe_build / ('xbox-image-probe.exe' if os.name == 'nt' else 'xbox-image-probe'))
    (root / 'backend.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
