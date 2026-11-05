"""Adapters to static translation tools. These never start an emulator or game."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
import tomllib
import uuid

from .disc import sha256, write_json
from .formats import FormatError, inspect, span


def workspace(path: Path, console: str | None = None):
    root = path.resolve(strict=True)
    receipt = json.loads((root / 'prepare.json').read_text(encoding='utf-8'))
    if receipt.get('status') != 'prepared':
        raise FormatError('Workspace preparation has not succeeded')
    source = (root / receipt['executable']).resolve(strict=True)
    if root not in source.parents or source.suffix.lower() not in ('.xbe', '.xex'):
        raise FormatError('Executable leaves workspace or has unexpected format')
    report = inspect(source)
    if report['sha256'] != receipt['sha256']:
        raise FormatError('Prepared executable changed; prepare a fresh workspace')
    if console and report['console'] != console:
        raise FormatError(f"Expected {console}, received {report['console']}")
    return root, source, report


def configure(path: Path, profile: Path | None = None) -> dict:
    root, source, report = workspace(path, 'xbox360')
    config = root / 'xenon.toml'
    text = ('# CPU translation only. Complete native runtime/rendering remains title-specific.\n'
            '# Do not use addresses from another game. See docs/RESEARCH.md.\n'
            '[main]\n'
            f'file_path = {json.dumps(source.relative_to(root).as_posix())}\n'
            'out_directory_path = "generated"\n'
            f'switch_table_file_path = {json.dumps("switches.toml" if (root / "switches.toml").exists() else "")}\n'
            'skip_lr = false\nskip_msr = false\nctr_as_local = false\nxer_as_local = false\n'
            'reserved_as_local = false\ncr_as_local = false\n'
            'non_argument_as_local = false\nnon_volatile_as_local = false\n'
            '# Register save/restore helper addresses must be identified for this exact binary.\n'
            '# Missing helpers, jump tables and exception handlers remain translation blockers.\n')
    if profile:
        profile_text = profile.read_text(encoding='utf-8')
        settings = tomllib.loads(profile_text)
        if settings.get('module', {}).get('input_sha256') != report['sha256']:
            raise FormatError('Profile executable SHA-256 does not match this game build')
        if any(k in settings.get('main', {}) for k in ('file_path', 'out_directory_path', 'patch_file_path', 'patched_file_path', 'switch_table_file_path')):
            raise FormatError('Profiles may describe code settings, not workspace paths')
        # Keep the actual profile as evidence; its [main] section extends the generated one.
        marker = re.search(r'^\[main\]\s*$', profile_text, re.M)
        if not marker:
            raise FormatError('Profile needs a [main] table')
        text += '\n' + profile_text[marker.end():].lstrip('\r\n')
        tomllib.loads(text)
    with config.open('x', encoding='utf-8') as f:
        f.write(text)
    return dict(status='configured', config=str(config), sha256=report['sha256'],
                profile_sha256=sha256(profile) if profile else None, native_game_ready=False)


def _stop(process):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait()


def run_tool(command: list[str], cwd: Path, log: Path, timeout: int, env: dict | None = None) -> dict:
    if not 1 <= timeout <= 7200:
        raise FormatError('Timeout must be 1..7200 seconds')
    start = time.monotonic()
    with log.open('xb') as stream:
        process = subprocess.Popen(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=os.name != 'nt', env=env)
        try:
            process.wait(timeout=timeout)
            state = 'exited'
        except subprocess.TimeoutExpired:
            _stop(process)
            state = 'timeout'
        except BaseException:
            _stop(process)
            raise
    return dict(command=command, process_status=state, exit_code=process.returncode,
                elapsed_seconds=round(time.monotonic() - start, 3), log=str(log))


def analyse(path: Path, backend: Path, timeout: int = 600) -> dict:
    root, source, report = workspace(path, 'xbox360')
    target = root / 'switches.toml'
    if target.exists():
        raise FormatError('switches.toml already exists; preserve or rename it before analysing again')
    run = root / 'runs' / ('analyse-' + uuid.uuid4().hex[:12])
    run.mkdir(parents=True)
    receipt = run_tool([str(backend.resolve(strict=True)), str(source), str(run / 'switches.toml')], run, run / 'backend.log', timeout)
    output = run / 'switches.toml'
    if receipt['exit_code'] == 0 and output.is_file():
        tables = tomllib.loads(output.read_text(encoding='utf-8')).get('switch', [])
        with target.open('xb') as f:
            f.write(output.read_bytes())
        receipt.update(status='analysed', detected_switch_tables=len(tables), switch_file=str(target))
    else:
        receipt['status'] = 'analysis-failed'
    receipt.update(schema_version=1, executable_sha256=report['sha256'], backend_sha256=sha256(backend), native_game_ready=False)
    write_json(run / 'receipt.json', receipt)
    return receipt


def _effective_config(root: Path, config: Path, run: Path, output: Path, source: Path) -> str:
    text = config.read_text(encoding='utf-8')
    parsed = tomllib.loads(text)
    main = parsed.get('main', {})
    if (root / main.get('file_path', '')).resolve() != source:
        raise FormatError('Configuration must use this workspace executable')
    # Upstream joins strings to its configuration directory instead of resolving paths.
    # Rebase relative paths into an isolated attempt and prohibit external output paths.
    replacements = dict(file_path=source, out_directory_path=output)
    for key in ('patch_file_path', 'patched_file_path', 'switch_table_file_path'):
        value = main.get(key)
        if value:
            p = (root / value).resolve()
            if root not in p.parents:
                raise FormatError(f'{key} must stay inside workspace')
            if key == 'patched_file_path':
                raise FormatError('Patch output is not supported by this adapter yet; prepare a patched XEX separately')
            if not p.is_file():
                raise FormatError(f'{key} does not exist')
            replacements[key] = p
    lines, in_main, changed = [], False, set()
    for line in text.splitlines():
        if line.strip().startswith('['):
            in_main = line.strip() == '[main]'
        m = re.match(r'^\s*(\w+)\s*=', line) if in_main else None
        if m and m[1] in replacements:
            key = m[1]
            value = os.path.relpath(replacements[key], run).replace('\\', '/')
            line = key + ' = ' + json.dumps(value)
            changed.add(key)
        lines.append(line)
    if changed != replacements.keys():
        raise FormatError('Configuration path keys must be single-line entries in [main]')
    return '\n'.join(lines) + '\n'


def translate(path: Path, backend: Path, context: Path, timeout: int = 1800) -> dict:
    root, source, report = workspace(path, 'xbox360')
    if report.get('module_flags', 0) & 0x70:
        raise FormatError('Prepare a full executable; delta/patch XEX translation is not supported by this adapter')
    backend, context = backend.resolve(strict=True), context.resolve(strict=True)
    config = root / 'xenon.toml'
    run = root / 'runs' / ('translate-' + uuid.uuid4().hex[:12])
    output = run / 'generated'
    run.mkdir(parents=True)
    output.mkdir()
    effective = _effective_config(root, config, run, output, source)
    (run / 'xenon.toml').write_text(effective, encoding='utf-8')
    receipt = run_tool([str(backend), str(run / 'xenon.toml'), str(context)], run, run / 'backend.log', timeout)
    sources = sorted(output.glob('*.cpp'))
    headers = sorted(output.glob('*.h'))
    log = (run / 'backend.log').read_text(encoding='utf-8', errors='replace')
    diagnostics = [line[:1000] for line in log.splitlines() if re.search(r'error|warn|unimplemented|unsupported|invalid|not found|unspecified|unable to decode|unrecognized|no comparison|no switch table', line, re.I)]
    traps, functions = 0, 0
    for p in sources + headers:
        code = p.read_text(encoding='utf-8', errors='replace')
        traps += len(re.findall(r'__builtin_(?:debugtrap|trap)\s*\(|__debugbreak\s*\(', code))
        functions += len(re.findall(r'PPC_FUNC_IMPL\s*\(', code)) if p.suffix == '.cpp' else 0
    produced = bool(sources and (output / 'ppc_config.h').is_file() and (output / 'ppc_context.h').is_file())
    succeeded = receipt['exit_code'] == 0 and receipt['process_status'] == 'exited' and produced
    receipt.update(schema_version=1, status='translated-with-blockers' if succeeded else 'translation-failed',
                   native_game_ready=False, executable_sha256=report['sha256'], backend_sha256=sha256(backend),
                   config_sha256=sha256(run / 'xenon.toml'), context_sha256=sha256(context),
                   generated_directory=str(output), cpp_files=len(sources), header_files=len(headers),
                   translated_function_definitions=functions, explicit_traps=traps,
                   diagnostic_count=len(diagnostics), diagnostics=diagnostics[:200],
                   blockers=['Native kernel/XAM runtime is not implemented by this module',
                             'GPU/shader/audio/input translation is not implemented by this module',
                             'Function boundaries, indirect branches, exceptions and helper addresses require review',
                             'Full native link and game execution have not been validated'])
    write_json(run / 'receipt.json', receipt)
    write_json(root / 'latest-translation.json', receipt)
    return receipt


def export_xbe(path: Path) -> dict:
    root, source, report = workspace(path, 'xbox')
    out = root / 'xbe-sections'
    out.mkdir(exist_ok=False)
    data = source.read_bytes()
    sections = []
    for i, section in enumerate(report['sections']):
        p = out / f'section-{i:04d}.bin'
        p.write_bytes(span(data, section['file_offset'], section['file_size']))
        sections.append(dict(**section, file=p.name, sha256=sha256(p)))
    result = dict(schema_version=1, status='sections-exported', executable_sha256=report['sha256'],
                  image_base=report['image_base'], entry_point=report['entry_point'], sections=sections,
                  native_game_ready=False, blockers=report['blockers'])
    write_json(out / 'sections.json', result)
    return result


def probe(path: Path, backend: Path, timeout: int = 120) -> dict:
    root, source, report = workspace(path, 'xbox360')
    run = root / 'runs' / ('probe-' + uuid.uuid4().hex[:12])
    run.mkdir(parents=True)
    receipt = run_tool([str(backend.resolve(strict=True)), str(source), str(run / 'image.bin'), str(run / 'image.json')],
                       run, run / 'backend.log', timeout)
    receipt.update(schema_version=1, status='probe-failed', native_game_ready=False,
                   executable_sha256=report['sha256'], backend_sha256=sha256(backend))
    if receipt['exit_code'] == 0 and (run / 'image.json').is_file() and (run / 'image.bin').is_file():
        metadata = json.loads((run / 'image.json').read_text(encoding='utf-8'))
        image = (run / 'image.bin').read_bytes()
        if len(image) != metadata['mapped_size'] or metadata['image_base'] != report['image_base']:
            raise FormatError('Backend image does not match XEX metadata')
        patterns = {
            'restgprlr_14_address': 'e9c1ff68', 'savegprlr_14_address': 'f9c1ff68',
            'restfpr_14_address': 'c9ccff70', 'savefpr_14_address': 'd9ccff70',
            'restvmx_14_address': '3960fee07dcb60ce', 'savevmx_14_address': '3960fee07dcb61ce',
            'restvmx_64_address': '3960fc00100b60cb', 'savevmx_64_address': '3960fc00100b61cb',
        }
        candidates = {key: [] for key in patterns}
        for section in metadata['sections']:
            if not section['executable']:
                continue
            start = section['address'] - metadata['image_base']
            code = span(image, start, section['size'])
            for key, signature in patterns.items():
                pattern = bytes.fromhex(signature)
                pos = code.find(pattern)
                while pos >= 0:
                    if not (section['address'] + pos) % 4:
                        candidates[key].append(section['address'] + pos)
                    pos = code.find(pattern, pos + 1)
        imports = [s for s in metadata['symbols'] if s['name'].startswith('__imp__')]
        from .helpers import verify_helpers
        verified = verify_helpers(image, metadata['image_base'], candidates)
        with (run / 'helpers.toml').open('x', encoding='utf-8') as f:
            f.write('# Verified complete routines. Merge these keys into [main] for this exact executable only.\n')
            for name, value in verified.items():
                if value['unique']:
                    f.write(f"{name} = 0x{value['verified'][0]['address']:08X}\n")
        receipt.update(status='image-probed', image=str(run / 'image.bin'), metadata=str(run / 'image.json'),
                       image_sha256=sha256(run / 'image.bin'), helper_candidates=candidates,
                       verified_helpers=verified, helper_config=str(run / 'helpers.toml'),
                       imported_symbol_count=len(imports),
                       note='Only unique complete canonical helper matches are written to helpers.toml. Other signature matches remain candidates.')
    write_json(run / 'receipt.json', receipt)
    write_json(root / 'latest-probe.json', receipt)
    return receipt


def decompile_xbe(path: Path, ghidra: Path, timeout: int = 600) -> dict:
    root, source, report = workspace(path, 'xbox')
    ghidra = ghidra.resolve(strict=True)
    launcher = ghidra / 'support' / ('analyzeHeadless.bat' if os.name == 'nt' else 'analyzeHeadless')
    if not launcher.is_file():
        raise FormatError('Expected a Ghidra installation directory with support/analyzeHeadless')
    scripts = Path(__file__).resolve().parent / 'ghidra'
    run = root / 'runs' / ('ghidra-' + uuid.uuid4().hex[:12])
    run.mkdir(parents=True)
    projects = run / 'project'
    projects.mkdir()
    for directory in ('settings', 'cache', 'temp'):
        (run / directory).mkdir()
    java = Path(os.environ['JAVA_HOME']) / 'bin' / ('java.exe' if os.name == 'nt' else 'java') if os.environ.get('JAVA_HOME') else None
    java_command = str(java) if java and java.is_file() else shutil.which('java')
    utility = ghidra / 'Ghidra/Framework/Utility/lib/Utility.jar'
    if not java_command or not utility.is_file():
        raise FormatError('Ghidra needs a full JDK; set JAVA_HOME to JDK 21+ and use a released Ghidra distribution')
    command = [java_command, '-Djava.awt.headless=true', '-Djava.system.class.loader=ghidra.GhidraClassLoader',
               '-Dfile.encoding=UTF8', '-Duser.language=en', '-Duser.country=US',
               f'-Dapplication.settingsdir={run / "settings"}', f'-Dapplication.cachedir={run / "cache"}',
               f'-Djava.io.tmpdir={run / "temp"}',
               '--enable-native-access=ALL-UNNAMED', '-cp', str(utility),
               'ghidra.Ghidra', 'ghidra.app.util.headless.AnalyzeHeadless',
               str(projects), 'XboxAnalysis', '-import', str(source),
               '-loader', 'BinaryLoader', '-processor', 'x86:LE:32:default',
               '-scriptPath', str(scripts), '-preScript', 'LoadXboxXbe.java', str(source),
               '-postScript', 'ExportXboxFunctions.java', str(run / 'pseudocode'),
               '-analysisTimeoutPerFile', str(min(timeout, 3600)), '-deleteProject']
    receipt = run_tool(command, run, run / 'backend.log', timeout)
    exported = run / 'pseudocode/export.json'
    if receipt['exit_code'] == 0 and exported.is_file():
        receipt.update(json.loads(exported.read_text(encoding='utf-8')))
        receipt['status'] = 'pseudocode-exported'
    else:
        receipt['status'] = 'decompilation-failed'
    receipt.update(schema_version=1, native_game_ready=False, executable_sha256=report['sha256'],
                   output=str(run / 'pseudocode'),
                   note='Analysis pseudocode. Full x86 static recompilation and native Xbox APIs are not implemented.')
    write_json(run / 'receipt.json', receipt)
    write_json(root / 'latest-decompilation.json', receipt)
    return receipt
