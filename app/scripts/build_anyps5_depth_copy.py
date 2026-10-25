"""Build a pinned, hash-verified AnyPS5 compatibility profile without changing settings."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from cydec import process
from cydec.engines.base import EngineContext
from cydec.paths import write_json


def digest(path):
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--toolchain-bin', type=Path, required=True)
    parser.add_argument('--validation-layer-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, default=APP/'engine-patches/anyps5-depth-copy.json')
    args = parser.parse_args()
    source, build, output = (p.resolve() for p in (args.source, args.build, args.output))
    if output == source or output.is_relative_to(source) or output == build or output.is_relative_to(build):
        parser.error('The output profile must be outside the source and build directories.')
    if output.exists():
        parser.error('Use a new output directory to preserve earlier profiles.')
    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text('utf-8'))
    patch = manifest_path.with_suffix('.patch')
    if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest['patchSha256']:
        raise RuntimeError('Profile patch checksum mismatch.')
    layer = args.validation_layer_dir.resolve()
    if not (layer/'VkLayer_khronos_validation.json').is_file():
        parser.error('The Khronos Vulkan validation-layer manifest is required.')
    tools = args.toolchain_bin.resolve()
    env = {'PATH': str(tools)+os.pathsep+os.environ['PATH'],
           'VK_LAYER_PATH': str(layer), 'VK_INSTANCE_LAYERS': 'VK_LAYER_KHRONOS_validation',
           'ANYPS5_REQUIRE_VULKAN': '1', 'ANYPS5_NO_SHADER_CACHE': '1',
           'APS5_NO_SHARED_PREPARED_STATE': None, 'APS5_NO_PERSISTENT_DRAW_SLICES': None,
           'APS5_NO_NATIVE_ABI_STATE': None, 'APS5_NO_NATIVE_ABI_READERS': None,
           'APS5_NO_NATIVE_ABI_INPUT_CACHE': None,
           'APS5_NO_RESIDENT_DRAW_SNAPSHOTS': None,
           'APS5_NO_DRAW_SET_REUSE': None,
           'APS5_NO_PERSISTENT_DRAW_SETS': None,
           'APS5_NO_MOVED_BUFFER_RECYCLING': None,
           'APS5_NO_RESIDENT_DRAW_UPDATES': None,
           'APS5_NO_DRAW_SNAPSHOT_ROTATION': None,
           'APS5_NO_LARGE_HOST_CLASSES': None,
           'APS5_NO_DEVICE_PARAMETERS': None,
           'APS5_NO_FINE_DRAW_UPDATES': None,
           'APS5_NO_NATIVE_DESCRIPTOR_PLAN': None,
           'APS5_NO_SRT_REPLAY': None,
           'APS5_TRACE_SRT_REPLAY': None,
           'APS5_NO_SRT_FRAME_REUSE': None,
           'APS5_VERIFY_SRT_TAPE': None,
           'APS5_NO_NATIVE_DRAW_SCRATCH': None,
           'APS5_NO_NATIVE_PREPARED_LOOKUPS': None,
           'APS5_CHECK_NATIVE_ABI_KEYS': None,
           'APS5_PROFILE_ABI': None}
    logs = build/(manifest_path.stem+'-logs')
    logs.mkdir(parents=True, exist_ok=True)
    context = EngineContext(workdir=logs)

    def run(command, name, timeout=1800, stdout_only=False):
        code, out, err = process.run(command, context=context, cwd=source, env=env,
                                    timeout=timeout, log_name=name, own_children=True,
                                    output_limit=8*1024**2)
        if code:
            raise RuntimeError(f'{name} failed; see {logs}:\n'+process.tail(out+err, 20))
        return out if stdout_only else out+'\n'+err

    git = ['git', '-c', 'safe.directory='+source.as_posix(), '-C', str(source)]
    if run(git+['rev-parse', 'HEAD'], 'revision', 30, stdout_only=True).strip() != manifest['baseCommit']:
        raise RuntimeError('The source checkout does not match the pinned commit.')
    changed = set(run(git+['diff', 'HEAD', '--name-only'], 'source-diff', 30, stdout_only=True).splitlines())
    changed.update(run(git+['ls-files', '--others', '--exclude-standard'], 'source-added', 30, stdout_only=True).splitlines())
    unexpected = changed - {row['path'] for row in manifest['files']}
    if unexpected:
        raise RuntimeError('Source changes are missing from the profile manifest: '+', '.join(sorted(unexpected)))
    states = []
    for row in manifest['files']:
        path = (source/row['path']).resolve()
        if not path.is_relative_to(source):
            raise RuntimeError('Patch path leaves the source checkout.')
        current = digest(path) if path.is_file() else None
        states.append('before' if current == row['beforeSha256'] else 'after' if current == row['afterSha256'] else 'unknown')
    if all(state == 'before' for state in states):
        run(git+['apply', '--check', str(patch)], 'patch-check', 30)
        run(git+['apply', str(patch)], 'patch-apply', 30)
    elif not all(state == 'after' for state in states):
        raise RuntimeError('The source has partial or conflicting changes; use a separate checkout.')
    run([tools/'cmake.exe', '-S', source, '-B', build, '-G', 'Ninja',
         '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_TESTING=ON', '-DANYPS5_ENABLE_SPIRV_TOOLS=ON',
         '-DCMAKE_C_COMPILER='+str(tools/'gcc.exe'), '-DCMAKE_CXX_COMPILER='+str(tools/'g++.exe'),
         '-DCMAKE_MAKE_PROGRAM='+str(tools/'ninja.exe'), '-DPython3_EXECUTABLE='+sys.executable], 'configure')
    run([tools/'cmake.exe', '--build', build, '--target', 'libs', 'relinker',
         'agc_driver_tests', 'agc_driver_graphics_tests', 'agc_driver_depth_copy_tests',
         'agc_driver_depth_storage_tests', 'agc_driver_depth_range_remap_draw_tests',
         'agc_driver_recorder_tests',
         *manifest.get('additionalBuildTargets', []),
         '--parallel', '12'], 'build', 3600)
    command = [tools/'ctest.exe', '--test-dir', build, '-R', manifest['testPattern'], '-V', '--no-tests=error']
    modes = ('standard', 'without-pipeline-libraries')
    if manifest.get('keyVerificationEnvironment'):
        modes += ('key-verification',)
    extra_modes = manifest.get('additionalValidationEnvironments', {})
    modes += tuple(extra_modes)
    extra_keys = {key for values in extra_modes.values() for key in values}
    for mode in modes:
        env.update({key: extra_modes.get(mode, {}).get(key) for key in extra_keys})
        env['APS5_NO_GPL'] = '1' if mode == 'without-pipeline-libraries' else None
        env.update({key: value if mode == 'key-verification' else None
                    for key, value in manifest.get('keyVerificationEnvironment', {}).items()})
        result = run(command, 'validation-'+mode, 300)
        if manifest.get('expectedTestCount') and f"100% tests passed, 0 tests failed out of {manifest['expectedTestCount']}" not in result:
            raise RuntimeError('The focused validation suite was incomplete; inspect '+str(logs))
        if 'VUID-' in result or 'was not found but was requested by env var VK_INSTANCE_LAYERS' in result or '***Skipped' in result or '[srt-tape] verify: shader ' in result:
            raise RuntimeError('Vulkan validation failed or was skipped; inspect '+str(logs))
        if any(message not in result for message in [*manifest.get('requiredTestMessages', []), *manifest.get('modeRequiredTestMessages', {}).get(mode, [])]):
            raise RuntimeError('A required GPU check did not run; inspect '+str(logs))
        if mode == 'key-verification' and any(message not in result for message in manifest.get('keyVerificationMessages', [])):
            raise RuntimeError('Native graphics ABI verification did not run; inspect '+str(logs))
    for row in manifest['files']:
        if digest(source/row['path']) != row['afterSha256']:
            raise RuntimeError('Source changed during compilation or validation; rebuild from the current manifest.')
    output.mkdir(parents=True)
    libs = output/'libs'
    libs.mkdir()
    engine_root = APP.parent/'runtime/engines/anyps5'
    previous = None
    previous_hashes = {}
    try:
        settings = json.loads((APP.parent/'data/settings/porting.json').read_text('utf-8'))
        candidate = Path(settings.get('windowsLibraries', '')).resolve()
        if candidate.is_relative_to(engine_root.resolve()) and candidate != libs and candidate.name == 'libs':
            previous_build = json.loads((candidate.parent/'build.json').read_text('utf-8'))
            if previous_build.get('buildKind', '').startswith('cydecompilator-'):
                previous, previous_hashes = candidate, previous_build.get('libraries', {})
    except (OSError, ValueError, TypeError):
        pass
    library_hashes = {}
    storage = {'linkedFiles':0, 'linkedBytes':0, 'copiedFiles':0, 'copiedBytes':0,
               'baseProfile':str(previous.parent) if previous else None}
    sources = [path for path in (build/'core/libs/libs').iterdir() if path.is_file()]
    sources += [tools/name for name in ('libgcc_s_seh-1.dll', 'libstdc++-6.dll', 'libwinpthread-1.dll')]
    for path in sources:
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        destination = libs/path.name
        linked = False
        if previous is not None and previous_hashes.get(path.name) == checksum:
            shared = previous/path.name
            if shared.is_file() and not shared.is_symlink() and hashlib.sha256(shared.read_bytes()).hexdigest() == checksum:
                try:
                    os.link(shared, destination)
                    linked = True
                except OSError:
                    pass
        if not linked:
            shutil.copy2(path, destination)
        library_hashes[path.name] = checksum
        storage['linkedFiles' if linked else 'copiedFiles'] += 1
        storage['linkedBytes' if linked else 'copiedBytes'] += path.stat().st_size
    shutil.copy2(build/'core/relinker/relinker.exe', output/'relinker.exe')
    write_json(output/'build.json', {**manifest, 'validationLogs': str(logs),
               'library': str(libs/'libSceVoice.prx'),
               'sha256': hashlib.sha256((libs/'libSceVoice.prx').read_bytes()).hexdigest(),
               'buildKind': manifest.get('profileId', 'cydecompilator-depth-copy'),
               'status': 'experimental-unverified-gameplay',
               'libraryStorage': storage, 'libraries': library_hashes})
    print(json.dumps({'windowsLibraries': str(libs), 'relinker': str(output/'relinker.exe'),
                      'status': 'experimental-unverified-gameplay'}))


if __name__ == '__main__':
    main()
