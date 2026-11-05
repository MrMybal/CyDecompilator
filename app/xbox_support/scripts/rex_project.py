"""Build and run an isolated, statically recompiled Xbox 360 project with ReXGlue.

The SDK is external and pinned by setup_rexglue.py. Game assets are local inputs.
Compilation success is recorded separately from observed gameplay compatibility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tomllib
import uuid

from setup_backend import toolchain

MODULE = Path(__file__).resolve().parents[1]
HALO_SHA = '1412845884eba9eb61cdc00213ca3777be19c71f6196faea69e435a350fd3f19'


def runtime_options(defaults, overrides):
    """CLI11 rejects duplicate options rather than taking the last value."""
    result = {}
    for option in [*defaults, *overrides]:
        match = re.fullmatch(r'--([a-zA-Z_][a-zA-Z0-9_]*)=(.*)', option, flags=re.S)
        if not match:
            raise ValueError('Runtime options must use --name=value: ' + option)
        result[match[1]] = option
    return list(result.values())


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def execute(command, cwd, label, env=None):
    logs = cwd / 'logs'
    logs.mkdir(exist_ok=True)
    log = logs / (label + '-' + uuid.uuid4().hex[:10] + '.log')
    with log.open('w', encoding='utf-8') as output:
        result = subprocess.run([str(x) for x in command], cwd=cwd, env=env,
                                stdout=output, stderr=subprocess.STDOUT)
    print(str(log), flush=True)
    if result.returncode:
        raise RuntimeError(f'{label} failed ({result.returncode}); see {log}')
    return str(log)


def init(sdk, game, project, name, entry='default.xex'):
    if not name.isascii() or not name.isidentifier():
        raise ValueError('Project name must be an ASCII identifier')
    if project.exists():
        raise ValueError('Choose a fresh project directory')
    if game == project or game in project.parents or project in game.parents:
        raise ValueError('Project and game assets must be separate directories')
    xex = (game / entry).resolve(strict=True)
    if game not in xex.parents:
        raise ValueError('Executable must stay inside the game directory')
    subprocess.run([str(sdk / 'bin/rexglue.exe'), 'init', '--project-name', name,
                    '--xex-path', str(xex), '--game-root', str(game),
                    '--project-root', str(project)], check=True)
    manifests = list(project.glob('*_manifest.toml'))
    if len(manifests) != 1:
        raise ValueError('Expected one generated manifest')
    manifest = manifests[0]
    identity = digest(xex)
    if identity == HALO_SHA:
        profile = MODULE / 'profiles/halo-rex-14128458.toml'
        # ReXGlue resolves includes relative to the manifest.
        relative = os.path.relpath(profile, project).replace('\\', '/')
        contents = manifest.read_text(encoding='utf-8')
        manifest.write_text(contents.replace('includes = []', 'includes = [' + json.dumps(relative) + ']'),
                            encoding='utf-8', newline='\n')
    cmake = project / 'CMakeLists.txt'
    contents = cmake.read_text(encoding='utf-8')
    actual_name = tomllib.loads(manifest.read_text(encoding='utf-8'))['project']['name']
    contents = contents.replace(f'rexglue_setup_target({actual_name})',
                                f'rexglue_setup_target({actual_name} GPU_PLUGINS xenos)')
    seh_header = (MODULE / 'native/rex_seh.h').as_posix()
    contents += (f'\nif(TARGET {actual_name}_recomp)\n'
                 f'    target_precompile_headers({actual_name}_recomp PRIVATE "{seh_header}")\n'
                 'endif()\n')
    if identity == HALO_SHA:
        guard_script = (MODULE / 'scripts/rex_guard_branches.py').as_posix()
        python = Path(sys.executable).as_posix()
        contents += (f'\nadd_custom_command(TARGET {actual_name}_codegen POST_BUILD\n'
                     f'    COMMAND "{python}" "{guard_script}" --project "${{CMAKE_CURRENT_SOURCE_DIR}}"\n'
                     '    VERBATIM)\n')
        contents += f'\ntarget_sources({actual_name} PRIVATE "{(MODULE / "native/rex_test_flags.cpp").as_posix()}")\n'
        contents += f'\ntarget_sources({actual_name} PRIVATE "{(MODULE / "native/rex_menu_bridge.cpp").as_posix()}")\n'
        contents += f'\ntarget_sources({actual_name} PRIVATE "{(MODULE / "native/rex_animation.cpp").as_posix()}")\n'
        contents += f'\ntarget_sources({actual_name} PRIVATE "{(MODULE / "native/rex_physics.cpp").as_posix()}")\n'
        contents += f'\ntarget_compile_definitions({actual_name} PRIVATE XBOX_NATIVE_HALO=1 XBOX_NATIVE_PCH="{actual_name}_pch.h")\n'
        contents += f'\ninclude("{(MODULE / "native/rex_controls_checks.cmake").as_posix()}")\nxbox_native_controls_checks({actual_name})\n'
    if identity == HALO_SHA:
        contents += f'\ntarget_sources({actual_name} PRIVATE "{(MODULE / "native/rex_controls.cpp").as_posix()}")\n'
    cmake.write_text(contents, encoding='utf-8')
    app_header = project / 'src' / (actual_name + '_app.h')
    if identity == HALO_SHA and app_header.is_file():
        contents = app_header.read_text(encoding='utf-8')
        diagnostics = (MODULE / 'native/rex_diagnostics.h').as_posix()
        contents = contents.replace('#include <rex/rex_app.h>', f'#include "{diagnostics}"')
        contents = contents.replace('public rex::ReXApp', 'public XboxNativeApp')
        contents = contents.replace('using rex::ReXApp::ReXApp;', 'using XboxNativeApp::XboxNativeApp;')
        app_header.write_text(contents, encoding='utf-8')
    write(project / 'native-project.json', dict(schema_version=1, sdk=str(sdk),
          executable_sha256=identity, game=str(game), name=actual_name,
          manifest=manifest.name, native_game_ready=False))


def build(sdk, project, jobs):
    manifests = list(project.glob('*_manifest.toml'))
    if len(manifests) != 1:
        raise ValueError('Expected one manifest')
    config = tomllib.loads(manifests[0].read_text(encoding='utf-8'))
    xex = (project / config['entrypoint']['file_path']).resolve(strict=True)
    known_profile = MODULE / 'profiles/halo-rex-14128458.toml'
    includes = [(project / p).resolve() for p in config['entrypoint'].get('includes', [])]
    if known_profile in includes and digest(xex) != HALO_SHA:
        raise ValueError('Halo analysis hints require the exact supported executable SHA-256')
    # The SDK stamps manifests using LF. Normalize before its input fingerprint
    # so a first Windows build does not invalidate itself after generation.
    contents = manifests[0].read_text(encoding='utf-8')
    if manifests[0].read_bytes() != contents.encode('utf-8'):
        manifests[0].write_text(contents, encoding='utf-8', newline='\n')
    log = execute([sdk / 'bin/rexglue.exe', 'codegen', manifests[0]], project, 'codegen')
    if known_profile in includes:
        # Ninja decides which generated C++ files are dirty before executing
        # target commands. Apply local hooks now, before it reads that graph;
        # patching only in the codegen POST_BUILD may miss this build's objects.
        from rex_guard_branches import guard
        guard(project)
    cmake, env, options = toolchain()
    if os.name == 'nt':
        # SDK consumer presets use the GNU-style Clang driver with MSVC libraries.
        options = [x.replace('clang-cl.exe', 'clang.exe') if x.startswith('-DCMAKE_C_COMPILER=')
                   else x.replace('clang-cl.exe', 'clang++.exe') if x.startswith('-DCMAKE_CXX_COMPILER=')
                   else x for x in options]
    directory = project / 'build'
    configure = execute([cmake, '-S', project, '-B', directory, *options,
                         '-DCMAKE_PREFIX_PATH=' + str(sdk), '-DCMAKE_BUILD_TYPE=Release'], project, 'configure', env)
    compilation = execute([cmake, '--build', directory, '--parallel', str(jobs)], project, 'build', env)
    # The application installs its explicitly configured GPU plugin after the
    # build. Never depend on a private research work/ directory in the app.
    executable = directory / (config['project']['name'] + '.exe')
    write(project / 'native-build.json', dict(schema_version=1, status='built',
          executable=str(executable), sha256=digest(executable),
          guest_sha256=digest(xex), codegen_log=log,
          configure_log=configure, build_log=compilation, native_game_ready=False))


def launch(project, game, extra, wait=False):
    build_info = json.loads((project / 'native-build.json').read_text(encoding='utf-8'))
    executable = Path(build_info['executable']).resolve(strict=True)
    if project not in executable.parents or digest(executable) != build_info['sha256']:
        raise ValueError('Executable is outside the project or differs from the recorded build')
    if digest(game / 'default.xex') != build_info['guest_sha256']:
        raise ValueError('Game executable differs from the statically recompiled image')
    run = project / 'runs' / uuid.uuid4().hex[:12]
    run.mkdir(parents=True)
    data = project / 'data'
    for name in ('user', 'cache', 'metadata'):
        (data / name).mkdir(parents=True, exist_ok=True)
    options = ['--game_data_root=' + str(game), '--gpu_plugin=xenos',
               '--user_data_root=' + str(data / 'user'), '--cache_root=' + str(data / 'cache'),
               '--metadata_root=' + str(data / 'metadata'), '--log_file=' + str(run / 'runtime.log'),
               '--log_level=debug', '--log_flush_interval=1']
    command = [str(executable), *runtime_options(options, extra)]
    with (run / 'console.log').open('wb') as output:
        process = subprocess.Popen(command, cwd=executable.parent, stdout=output,
                                   stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    receipt = dict(schema_version=1, status='started', pid=process.pid, command=command,
                   directory=str(run), native_game_ready=False)
    write(run / 'launch.json', receipt)
    write(project / 'latest-run.json', receipt)
    print(json.dumps(receipt, indent=2), flush=True)
    if wait:
        code = process.wait()
        receipt.update(status='exited' if code == 0 else 'failed', exit_code=code)
        write(run / 'launch.json', receipt)
        write(project / 'latest-run.json', receipt)
        print(json.dumps(dict(status=receipt['status'], exit_code=code, directory=str(run))), flush=True)
        return code
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('init', 'build', 'run'))
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--sdk', type=Path)
    parser.add_argument('--game', type=Path)
    parser.add_argument('--name', default='XboxNativeGame')
    parser.add_argument('--entry', default='default.xex')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--wait', action='store_true', help='Record the game process exit status')
    args, extra = parser.parse_known_args()
    if extra and args.action != 'run': parser.error('Unexpected arguments: ' + ' '.join(extra))
    project = args.project.resolve()
    sdk = args.sdk.resolve(strict=True) if args.sdk else None
    game = args.game.resolve(strict=True) if args.game else None
    if args.action == 'init':
        if not sdk or not game: parser.error('init requires --sdk and --game')
        init(sdk, game, project, args.name, args.entry)
    elif args.action == 'build':
        if not sdk: parser.error('build requires --sdk')
        if args.jobs < 1 or args.jobs > 32: parser.error('--jobs must be between 1 and 32')
        build(sdk, project, args.jobs)
    else:
        if not game: parser.error('run requires --game')
        code = launch(project, game, extra, args.wait)
        if code: raise SystemExit(1)


if __name__ == '__main__':
    main()
