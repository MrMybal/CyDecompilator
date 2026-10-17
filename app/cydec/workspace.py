"""Persistent source workspaces and cancellable build/test/run jobs for the integrated IDE."""
import hashlib
import os
import re
import shlex
import shutil
import uuid
from pathlib import Path

from cytools_core import CyToolError

from . import components, process
from .paths import read_json, write_json
from .project import safe_name

TEXT_LIMIT = 4 * 1024 * 1024
EXCLUDED = {'.git', '.vs', '__pycache__', 'bin', 'obj', 'build', 'node_modules', '.cydec'}
TEXT_EXTENSIONS = {'.cs', '.csproj', '.sln', '.slnx', '.c', '.cpp', '.h', '.hpp', '.vcxproj',
                   '.props', '.targets', '.json', '.xml', '.config', '.resx', '.txt', '.md',
                   '.py', '.java', '.gradle', '.hlsl', '.glsl', '.cmake', '.xaml',
                   '.js','.cjs','.mjs','.ts','.tsx','.jsx','.html','.htm','.css','.svg','.map','.rc','.def','.code-workspace'}


def parse_arguments(text):
    """Use the platform's command-line quoting without invoking a shell."""
    if os.name != 'nt':
        return shlex.split(text)
    import ctypes
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    count = ctypes.c_int()
    argv = shell.CommandLineToArgvW('program ' + text, ctypes.byref(count))
    if not argv:
        raise ValueError('Invalid command-line arguments')
    try:
        return [argv[i] for i in range(1, count.value)]
    finally:
        kernel.LocalFree(argv)


def confined(root, relative):
    relative = Path(relative)
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if relative.is_absolute() or not relative.parts or path == root or not path.is_relative_to(root):
        raise CyToolError('InvalidParameters', 'Use a relative path inside the source workspace.')
    if any(part in EXCLUDED for part in relative.parts):
        raise CyToolError('InvalidParameters', 'This folder is reserved for build output.')
    return path


def state(project):
    value = read_json(project.dir / 'workspace.json', {})
    if not value:
        return {'projectId': project.id, 'available': False, 'files': []}
    root = Path(value['directory'])
    files = []
    if root.is_dir():
        for directory, folders, names in os.walk(root, followlinks=False):
            folders[:] = sorted(f for f in folders if f not in EXCLUDED and not (Path(directory) / f).is_symlink())
            for name in sorted(names):
                path = Path(directory) / name
                if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                    continue
                if path.suffix.lower() in TEXT_EXTENSIONS or name == 'CMakeLists.txt':
                    files.append({'path': path.relative_to(root).as_posix(), 'size': path.stat().st_size})
    projects = [{'path': row['path'], 'name': Path(row['path']).stem} for row in files
                if Path(row['path']).suffix in ('.csproj', '.vcxproj')]
    return dict(value, projectId=project.id, available=root.is_dir(), files=files, projects=projects,
                lastBuild=read_json(project.dir / 'workspace-build.json', {}))


def root_for(project):
    value = read_json(project.dir / 'workspace.json', {})
    if not value or not Path(value['directory']).is_dir():
        raise CyToolError('NotFound', 'Create or open a source workspace first.')
    return Path(value['directory']).resolve(), value


def read_file(project, relative):
    root, _ = root_for(project)
    path = confined(root, relative)
    if not path.is_file():
        raise CyToolError('NotFound', 'Source file not found: ' + relative)
    if path.stat().st_size > TEXT_LIMIT:
        raise CyToolError('InvalidParameters', 'The editor supports text files up to 4 MiB.')
    raw = path.read_bytes()
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise CyToolError('Unsupported', 'The editor requires UTF-8 text.')
    if '\0' in text:
        raise CyToolError('Unsupported', 'This is a binary file.')
    return {'projectId': project.id, 'path': relative, 'text': text.replace('\r\n', '\n').replace('\r', '\n'),
            'revision': hashlib.sha256(raw).hexdigest()}


def save_file(project, relative, text, revision):
    raw = text.encode('utf-8')
    if len(raw) > TEXT_LIMIT or '\0' in text:
        raise CyToolError('InvalidParameters', 'Use UTF-8 text up to 4 MiB.')
    with project.lock:
        root, _ = root_for(project)
        path = confined(root, relative)
        previous = path.read_bytes() if path.exists() else None
        current = hashlib.sha256(previous).hexdigest() if previous is not None else ''
        if current != revision:
            raise CyToolError('Conflict', 'The file changed on disk. Reload it before saving.')
        normalized = text.replace('\r\n', '\n').replace('\r', '\n')
        raw = normalized.replace('\n', '\r\n').encode('utf-8') if previous and b'\r\n' in previous else normalized.encode('utf-8')
        if previous and previous.startswith(b'\xef\xbb\xbf'):
            raw = b'\xef\xbb\xbf' + raw
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            temp.write_bytes(raw)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
    return read_file(project, relative)


def search(project, query, context=None, case_sensitive=False, whole_word=False, limit=100):
    """Literal source search with bounded results, excluding generated/binary files."""
    if not isinstance(query, str) or not query or len(query) > 256 or '\n' in query or '\r' in query:
        raise CyToolError('InvalidParameters', 'Use a nonempty single-line search up to 256 characters.')
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise CyToolError('InvalidParameters', 'Search limit must be between 1 and 500.')
    root_for(project)
    expression = re.escape(query)
    if whole_word:
        expression = r'(?<!\w)' + expression + r'(?!\w)'
    pattern = re.compile(expression, 0 if case_sensitive else re.IGNORECASE)
    matches, skipped, scanned, total_bytes = [], [], 0, 0
    truncated = False
    for row in state(project)['files']:
        if context:
            context.check()
        if row['size'] > TEXT_LIMIT:
            skipped.append(row['path'])
            continue
        total_bytes += row['size']
        if total_bytes > 128 * 1024 * 1024:
            truncated = True
            break
        try:
            text = read_file(project, row['path'])['text']
        except CyToolError as error:
            if error.code not in ('Unsupported', 'InvalidParameters', 'NotFound'):
                raise
            skipped.append(row['path'])
            continue
        scanned += 1
        for line_number, line in enumerate(text.splitlines(), 1):
            if context and line_number % 1024 == 0:
                context.check()
            for match in pattern.finditer(line):
                if len(matches) == limit:
                    truncated = True
                    break
                start = max(0, match.start() - 80)
                matches.append({'path': row['path'], 'line': line_number, 'column': match.start() + 1,
                                'text': line[start:start + 400]})
            if truncated:
                break
        if truncated:
            break
    return {'projectId': project.id, 'query': query, 'matches': matches, 'truncated': truncated,
            'scannedFiles': scanned, 'skippedFiles': skipped}


def _solution(root, name, project_file, native=False, guid=None):
    type_id = 'BC8A1FFA-BEE3-4634-8014-F334798102B3' if native else 'FAE04EC0-301F-11D3-BF4B-00C04F79EFBC'
    guid = guid or str(uuid.uuid4()).upper()
    platforms = ['Win32', 'x64', 'ARM64'] if native else ['Any CPU']
    configs = [c + '|' + p for c in ('Debug', 'Release') for p in platforms]
    lines = ['Microsoft Visual Studio Solution File, Format Version 12.00', '# Visual Studio Version 17',
             'Project("{%s}") = "%s", "%s", "{%s}"' % (type_id, name, project_file, guid),
             'EndProject', 'Global', '\tGlobalSection(SolutionConfigurationPlatforms) = preSolution']
    lines += ['\t\t%s = %s' % (c, c) for c in configs]
    lines += ['\tEndGlobalSection', '\tGlobalSection(ProjectConfigurationPlatforms) = postSolution']
    for c in configs:
        lines += ['\t\t{%s}.%s.%s = %s' % (guid, c, action, c) for action in ('ActiveCfg', 'Build.0')]
    lines += ['\tEndGlobalSection', 'EndGlobal', '']
    (root / (name + '.sln')).write_text('\n'.join(lines), encoding='utf-8')


def create(project, destination, context, functions=(), native_target='library', entry_function=''):
    from . import service
    with project.lock:
        if read_json(project.dir / 'workspace.json', {}):
            raise CyToolError('Conflict', 'A source workspace is already attached. Open it or attach another folder.')
        final_root = Path(destination).resolve() if destination else project.dir.resolve() / 'source'
        if destination and not Path(destination).is_absolute():
            raise CyToolError('InvalidParameters', 'destination must be an absolute folder path.')
        # Never export over an existing user's tree, even if an earlier export failed.
        if final_root.exists():
            raise CyToolError('Conflict', 'Choose a new folder for the reconstructed project.')
        fmt = project.meta()['detect']['format']
        if fmt not in ('pe-dotnet', 'pe', 'elf','javascript-app'):
            raise CyToolError('Unsupported', 'Source projects support .NET, native PE/ELF and JavaScript/Electron/web applications.')
        if context is None or not context.workdir:
            raise CyToolError('InvalidParameters', 'Source reconstruction requires a job workdir.')
        root = Path(context.workdir) / ('source-export-' + uuid.uuid4().hex)
        root.mkdir(parents=True)
        name = safe_name(project.binary.stem)
        extra={}
        if fmt=='javascript-app':
            from . import web_workspace
            extra=web_workspace.create(project,root,context)
            kind,entry,note=extra['kind'],extra['entry'],extra['note']
        elif fmt in ('pe','elf') and native_target!='library':
            from . import native_workspace
            extra=native_workspace.create(project,root,context,functions,native_target,entry_function)
            kind,entry,note=extra['kind'],extra['entry'],extra['note']
            name='recovered'
        elif fmt == 'pe-dotnet':
            from .engines import get
            # ILSpy's default language can be newer than the installed C# compiler.
            language_version = 'CSharp12_0'
            try:
                sdk = dotnet_sdk(context)
            except CyToolError:
                sdk = None
            if sdk:
                status, out, _ = process.run([sdk, '--version'], context=context, timeout=30, log_name='sdk-version')
                if status == 0 and re.match(r'^\d+\.', out.strip()):
                    major = int(out.strip().split('.')[0])
                    language_version = 'CSharp%d_0' % min(13, major + 4) if major >= 5 else 'CSharp7_3'
            get('ilspy').export_project(project, root, context, language_version=language_version)
            projects = sorted(root.glob('*.csproj'))
            if len(projects) != 1:
                raise CyToolError('EngineFailed', 'ILSpy did not produce exactly one C# project.')
            entry = projects[0].name
            _solution(root, name, entry)
            kind = 'dotnet'
            note = 'Recovered C# project. Missing references, resources or obfuscated source may require repairs.'
        elif fmt in ('pe', 'elf'):
            code = service.c_module(project.id, functions, context=context)['code']
            (root / 'src').mkdir()
            (root / 'src/recovered.c').write_text(code, encoding='utf-8')
            (root / 'CMakeLists.txt').write_text(
                'cmake_minimum_required(VERSION 3.20)\nproject(%s LANGUAGES C)\n'
                'set(CMAKE_C_STANDARD 17)\nadd_library(recovered STATIC src/recovered.c)\n'
                'include(CTest)\n' % name.replace('.', '_').replace('-', '_'), encoding='utf-8')
            configs = ''.join('<ProjectConfiguration Include="%s|%s"><Configuration>%s</Configuration>'
                              '<Platform>%s</Platform></ProjectConfiguration>' % (c, p, c, p)
                              for c in ('Debug', 'Release') for p in ('Win32', 'x64', 'ARM64'))
            guid = str(uuid.uuid4()).upper()
            xml = ('<Project DefaultTargets="Build" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">'
                   '<ItemGroup Label="ProjectConfigurations">%s</ItemGroup>'
                   '<PropertyGroup Label="Globals"><ProjectGuid>{%s}</ProjectGuid></PropertyGroup>'
                   '<Import Project="$(VCTargetsPath)\\Microsoft.Cpp.Default.props" />'
                   '<PropertyGroup Label="Configuration"><ConfigurationType>StaticLibrary</ConfigurationType>'
                   '<PlatformToolset>v143</PlatformToolset></PropertyGroup>'
                   '<Import Project="$(VCTargetsPath)\\Microsoft.Cpp.props" />'
                   '<PropertyGroup><OutDir>build\\$(Platform)\\$(Configuration)\\</OutDir>'
                   '<IntDir>build\\obj\\$(Platform)\\$(Configuration)\\</IntDir></PropertyGroup>'
                   '<ItemDefinitionGroup><ClCompile><LanguageStandard_C>stdc17</LanguageStandard_C>'
                   '</ClCompile></ItemDefinitionGroup><ItemGroup><ClCompile Include="src\\recovered.c" />'
                   '</ItemGroup><Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" /></Project>'
                   % (configs, guid))
            entry = name + '.vcxproj'
            (root / entry).write_text(xml, encoding='utf-8')
            _solution(root, name, entry, True, guid)
            kind = 'native'
            note = ('Recovered native functions form a static library. Reconstruct the entry point, '
                    'import bindings, resources and application framework to build the complete application.')
        if context:
            context.check()
        final_root.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(root, final_root)
        except FileExistsError:
            raise CyToolError('Conflict', 'The destination was created during reconstruction. Choose a new folder.')
        write_json(project.dir / 'workspace.json', {'directory': str(final_root), 'kind': kind, 'entry': entry,
                   **extra,'name': name, 'note': note, 'platform': {'x86': 'Win32', 'arm64': 'ARM64'}.get(
                       project.meta()['detect'].get('arch'), 'x64')})
        return state(project)


def attach(project, directory):
    root = Path(directory)
    if not root.is_absolute() or not root.is_dir():
        raise CyToolError('InvalidParameters', 'Choose an existing absolute project folder.')
    root = root.resolve()
    csharp, native = sorted(root.glob('*.csproj')), sorted(root.glob('*.vcxproj'))
    solutions = sorted([*root.glob('*.sln'), *root.glob('*.slnx')])
    projects = []
    if len(solutions) == 1:
        for directory_path, folders, names in os.walk(root, followlinks=False):
            folders[:] = [f for f in folders if f not in EXCLUDED and (Path(directory_path) / f).resolve().is_relative_to(root)]
            projects.extend(Path(directory_path) / n for n in names if n.endswith(('.csproj', '.vcxproj')))
    if len(solutions) == 1 and len(projects) > 1:
        kind = 'native' if any(p.suffix == '.vcxproj' for p in projects) else 'dotnet'
        entry = solutions[0].name
    elif len(csharp) == 1:
        kind, entry = 'dotnet', csharp[0].name
    elif len(native) == 1:
        kind, entry = 'native', native[0].name
    elif (root / 'cydec.project.json').is_file():
        kind=read_json(root/'cydec.project.json').get('kind')
        if kind not in ('node','web','electron'):raise CyToolError('InvalidParameters','Invalid JavaScript project kind.')
        entry='cydec.project.json'
    elif (root / 'CMakeLists.txt').is_file():
        kind, entry = 'cmake', 'CMakeLists.txt'
    else:
        if len(solutions) != 1:
            raise CyToolError('Unsupported', 'Choose a folder with one project, one solution or CMakeLists.txt.')
        if not projects:
            raise CyToolError('Unsupported', 'No source projects were found inside the solution folder.')
        kind = 'native' if any(p.suffix == '.vcxproj' for p in projects) else 'dotnet'
        entry = solutions[0].name
    confined(root, entry)
    with project.lock:
        write_json(project.dir / 'workspace.json', {'directory': str(root), 'kind': kind, 'entry': entry,
                   'name': root.name, 'note': '', 'platform': 'x64'})
        (project.dir / 'workspace-build.json').unlink(missing_ok=True)
    return state(project)


def visual_studio_tool(relative):
    from .ai.verify import msvc_vcvars
    vcvars = msvc_vcvars()
    if vcvars:
        path = Path(vcvars).parents[3] / relative
        if path.is_file():
            return str(path)
    return None


def dotnet_sdk(context):
    # The private engine ships a runtime; building requires an SDK.
    candidates = [shutil.which('dotnet')]
    if os.name == 'nt':
        candidates += [str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'dotnet/dotnet.exe')]
    located = components.locate('dotnet')
    candidates += [located.get('dotnet') if located else None]
    for exe in dict.fromkeys(p for p in candidates if p and Path(p).is_file()):
        code, out, _ = process.run([exe, '--list-sdks'], context=context, timeout=30, log_name='sdk')
        if code == 0 and out.strip():
            return exe
    raise CyToolError('MissingDependency', 'Install a .NET SDK for project builds. The ILSpy runtime alone cannot compile.')


def diagnostics(output):
    result = []
    patterns = [re.compile(r'^(.+?)\((\d+)(?:,(\d+))?\)\s*:\s*(?:fatal )?(error|warning)\s*([^:]*):\s*(.*)'),
                re.compile(r'^(.+?):(\d+)(?::(\d+))?:\s*(?:fatal )?(error|warning):\s*(.*)')]
    for line in output.splitlines():
        for index, pattern in enumerate(patterns):
            m = pattern.match(line.strip())
            if m:
                groups = m.groups()
                result.append({'file': groups[0], 'line': int(groups[1]), 'column': int(groups[2] or 1),
                               'severity': groups[3], 'message': (groups[4] + ': ' + groups[5]) if index == 0 else groups[4]})
                break
    return result


def execute(project, action, context, configuration='Debug', executable='', arguments=(), target_project='', debug_symbols=False):
    from .execution import output_events
    if action not in ('build', 'rebuild', 'test', 'run') or configuration not in ('Debug', 'Release'):
        raise CyToolError('InvalidParameters', 'Invalid build action or configuration.')
    with project.lock:
        root, value = root_for(project)
        if value['kind'] in ('node','web','electron'):
            from .web_workspace import execute as execute_web
            if target_project:raise CyToolError('InvalidParameters','JavaScript projects use cydec.project.json as their build configuration.')
            return execute_web(project,action,context,executable,arguments)
        entry = confined(root, value['entry'])
        if target_project:
            entry = confined(root, target_project)
            if not entry.is_file() or entry.suffix not in ('.csproj', '.vcxproj'):
                raise CyToolError('InvalidParameters', 'Select a source project inside the solution folder.')
            value = dict(value, kind='dotnet' if entry.suffix == '.csproj' else 'native')
        commands = []
        if value['kind'] == 'dotnet':
            if action == 'run' and entry.suffix != '.csproj':
                raise CyToolError('InvalidParameters', 'Select the startup C# project before running a solution.')
            dotnet = dotnet_sdk(context)
            if action == 'rebuild':
                commands.append([dotnet, 'clean', str(entry), '-c', configuration, '--nologo'])
            verb = 'build' if action == 'rebuild' else action
            command = [dotnet, verb, '--project', str(entry)] if verb == 'run' else [dotnet, verb, str(entry)]
            command += ['-c', configuration]
            if debug_symbols and verb == 'build':
                command += ['-p:DebugType=portable', '-p:DebugSymbols=true', '-p:Optimize=false', '-p:PublishReadyToRun=false']
            if verb != 'run':
                command += ['--nologo', '-v', 'minimal']
            if verb == 'run' and arguments:
                command += ['--', *arguments]
            commands.append(command)
        elif action == 'run':
            # Executing a program is always an explicit UI/MCP action.
            path = (root / executable).resolve() if executable else None
            if path is None or not path.is_relative_to(root) or not path.is_file():
                raise CyToolError('InvalidParameters', 'Choose a built executable inside the source workspace.')
            commands.append([str(path), *arguments])
        elif value['kind'] == 'native' and action != 'test' and os.name == 'nt':
            msbuild = shutil.which('MSBuild') or visual_studio_tool('MSBuild/Current/Bin/MSBuild.exe')
            if not msbuild:
                raise CyToolError('MissingDependency', 'Install Visual Studio C++ Build Tools to build the native solution.')
            commands.append([msbuild, str(entry), '/nologo', '/m', '/t:' + ('Rebuild' if action == 'rebuild' else 'Build'),
                             '/p:Configuration=' + configuration, '/p:Platform=' + value.get('platform', 'x64')])
        else:
            cmake = shutil.which('cmake') or visual_studio_tool('Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe')
            if not cmake:
                raise CyToolError('MissingDependency', 'Install CMake for native builds and tests.')
            commands = [[cmake, '-S', str(root), '-B', str(root / 'build'), '-DCMAKE_BUILD_TYPE=' + configuration],
                        [cmake, '--build', str(root / 'build'), '--config', configuration]]
            if action == 'rebuild':
                commands[1].append('--clean-first')
            if action == 'test':
                ctest = str(Path(cmake).with_name('ctest.exe' if os.name == 'nt' else 'ctest'))
                commands.append([ctest, '--test-dir', str(root / 'build'), '-C', configuration,
                                 '--output-on-failure', '--no-tests=error'])
        outputs, exit_code = [], 0
        live_output = output_events(context)
        for index, command in enumerate(commands):
            if context:
                context.progress(index * 100 / len(commands), action)
            exit_code, out, err = process.run(command, cwd=root, context=context, timeout=900,
                                             log_name='workspace-' + action + '-' + str(index), on_output=live_output)
            outputs.append(out + '\n' + err)
            if exit_code:
                break
        output = '\n'.join(outputs)
        status = 'passed' if exit_code == 0 else 'failed'
        if action == 'test' and value['kind'] == 'dotnet' and exit_code == 0:
            # dotnet test may return 0 on a library with no test runner.
            if not re.search(r'(Passed!|Failed!|Total tests:|Test summary:|total:\s*\d+)', output, re.I):
                status = 'no-tests'
        result = {'projectId': project.id, 'action': action, 'configuration': configuration,
                  'status': status, 'exitCode': exit_code, 'output': output[-200000:],
                  'diagnostics': diagnostics(output), 'directory': str(root)}
        if action in ('build', 'rebuild'):
            write_json(project.dir / 'workspace-build.json', result)
        return result
