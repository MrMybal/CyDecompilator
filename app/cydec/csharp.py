"""Roslyn completion, definitions and diagnostics from confined source snapshots."""
import fnmatch
import hashlib
import json
import os
import re
import shutil
import threading
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from cytools_core import CyToolError
from . import process, workspace
from .paths import APP, ENGINES, read_json

_lock = threading.Lock()
SOURCE_FILES = ('CSharpServices.csproj', 'Program.cs', 'NuGet.Config')
SNAPSHOT_LIMIT = 32 * 1024 * 1024


def sdk_info(context):
    host = workspace.dotnet_sdk(context)
    code, version, _ = process.run([host, '--version'], context=context, timeout=30)
    version = version.strip()
    if code or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-+][\w.-]+)?', version) or int(version.split('.')[0]) < 8:
        raise CyToolError('MissingDependency', 'C# editor services require a .NET SDK 8 or later.')
    _, installed, _ = process.run([host, '--list-sdks'], context=context, timeout=30)
    match = next((re.match(r'([^ ]+) \[(.+)\]', line) for line in installed.splitlines() if line.startswith(version + ' ')), None)
    if not match:
        raise CyToolError('MissingDependency', 'Cannot locate the active .NET SDK.')
    sdk = Path(match[2]) / version
    tools = sdk / 'DotnetTools/dotnet-format'
    if not (tools / 'Microsoft.CodeAnalysis.CSharp.Features.dll').is_file():
        raise CyToolError('MissingDependency', 'The installed SDK does not include Roslyn C# editor services.')
    return host, sdk, tools, version


def tool(context, info):
    host, sdk, tools, version = info
    stamp = hashlib.sha256(str(sdk).encode() + b''.join((APP / 'csharp' / n).read_bytes() for n in SOURCE_FILES)).hexdigest()[:16]
    destination = ENGINES / 'csharp-services' / (version + '-' + stamp)
    dll = destination / 'CSharpServices.dll'
    with _lock:
        if not dll.is_file():
            folder = Path(context.workdir) / ('csharp-tool-' + uuid.uuid4().hex)
            folder.mkdir(parents=True)
            for name in SOURCE_FILES:
                shutil.copyfile(APP / 'csharp' / name, folder / name)
            csproj = folder / 'CSharpServices.csproj'
            csproj.write_text(csproj.read_text().replace('<TargetFramework>net8.0</TargetFramework>',
                '<TargetFramework>net' + version.split('.')[0] + '.0</TargetFramework>'), encoding='utf-8')
            command = [host, 'build', str(folder / 'CSharpServices.csproj'), '--nologo', '-c', 'Release',
                       '-o', str(folder / 'out'),
                       '-p:RoslynTools=' + str(tools), '--configfile', str(folder / 'NuGet.Config')]
            code, out, err = process.run(command, context=context, timeout=180, log_name='csharp-tool')
            if code:
                raise CyToolError('MissingDependency', 'C# editor helper compilation failed:\n' + process.tail(out + '\n' + err))
            context.check()
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(folder / 'out', destination)
    return host, dll


def _glob(path, pattern):
    pattern = pattern.replace('\\', '/')
    return fnmatch.fnmatchcase(path, pattern) or (pattern.startswith('**/') and fnmatch.fnmatchcase(path, pattern[3:]))


def _properties(xml, configuration):
    result = {}
    notes = []
    for group in xml.findall('PropertyGroup'):
        if group.get('Condition'):
            notes.append('Conditional project properties require a build for complete diagnostics.')
            continue
        for node in group:
            if not node.get('Condition'):
                result[node.tag] = node.text or ''
    # Configuration defines are part of normal SDK builds even without an explicit property.
    defines = ['TRACE'] + (['DEBUG'] if configuration == 'Debug' else [])
    defines += [d for d in re.split(r'[;, ]+', result.get('DefineConstants', '')) if d.isidentifier()]
    result['_defines'] = list(dict.fromkeys(defines))
    return result, notes


def _framework_references(sdk, framework, props):
    target = re.match(r'(net(?:standard)?[0-9]+\.[0-9]+)', framework)
    target = target[1] if target else ''
    refs, notes = [], []
    pack_names = ['NETStandard.Library.Ref' if target.startswith('netstandard') else 'Microsoft.NETCore.App.Ref']
    if props.get('UseWPF', '').lower() == 'true' or props.get('UseWindowsForms', '').lower() == 'true':
        pack_names.append('Microsoft.WindowsDesktop.App.Ref')
    for name in pack_names:
        packs = sdk.parent.parent / 'packs' / name
        versions = sorted(packs.glob('*/ref/' + target), key=lambda p: tuple(int(v) for v in re.findall(r'\d+', p.parent.parent.name)), reverse=True) if target else []
        if not versions and name == 'Microsoft.NETCore.App.Ref':
            versions = sorted(packs.glob('*/ref/net*'), key=lambda p: tuple(int(v) for v in re.findall(r'\d+', p.parent.parent.name)), reverse=True)
            notes.append('Target framework reference pack is unavailable; editor analysis uses an installed framework.')
        if versions:
            refs.extend(str(p.resolve()) for p in versions[0].glob('*.dll'))
        else:
            notes.append('A framework reference pack is missing: ' + name)
    return refs, notes


def snapshot(project, context, info, path, buffers, target_project, configuration):
    root, _ = workspace.root_for(project)
    selected = workspace.confined(root, path)
    if selected.suffix.lower() != '.cs':
        raise CyToolError('Unsupported', 'Choose a C# source file for editor analysis.')
    if configuration not in ('Debug', 'Release'):
        raise CyToolError('InvalidParameters', 'Invalid C# project configuration.')
    overlays = {}
    if not isinstance(buffers, (list, tuple)) or len(buffers) > 200:
        raise CyToolError('InvalidParameters', 'Provide at most 200 edited source buffers.')
    for row in buffers:
        if not isinstance(row, dict) or not isinstance(row.get('path'), str) or not isinstance(row.get('text'), str):
            raise CyToolError('InvalidParameters', 'A source buffer requires path and text.')
        absolute = workspace.confined(root, row['path'])
        if absolute.suffix.lower() != '.cs' or len(row['text'].encode()) > workspace.TEXT_LIMIT or '\0' in row['text']:
            raise CyToolError('InvalidParameters', 'Use C# text buffers up to 4 MiB.')
        if absolute in overlays:
            raise CyToolError('InvalidParameters', 'Duplicate edited source buffer.')
        overlays[absolute] = row['text'].replace('\r\n', '\n').replace('\r', '\n')
    state = workspace.state(project)
    from . import project_model
    evaluated = project_model.cached(project, root, configuration)
    if evaluated is not None:
        models, size = [], 0
        for model in evaluated:
            rows = []
            for filename in model['sources']:
                source = Path(filename).resolve()
                if not source.is_relative_to(root) or not source.is_file():
                    raise CyToolError('Conflict', 'An evaluated source disappeared. Evaluate the project again.')
                if source.stat().st_size > workspace.TEXT_LIMIT:
                    raise CyToolError('Unsupported', 'An evaluated source exceeds the editor size limit.')
                text = overlays.get(source) if source in overlays else source.read_text('utf-8-sig').replace('\r\n', '\n')
                size += len(text.encode())
                rows.append({'path': str(source), 'text': text})
            if model['usings'] and not any(p['path'].endswith('GlobalUsings.g.cs') for p in rows):
                rows.append({'path': str(Path(model['path']).parent / '.cydec-global-usings.cs'),
                             'text': '\n'.join('global using ' + u + ';' for u in model['usings'])})
            models.append(dict(model, sources=rows))
        if size > SNAPSHOT_LIMIT or sum(len(m['sources']) for m in models) > 2000:
            raise CyToolError('Unsupported', 'Evaluated source model exceeds editor limits.')
        owner = next((m for m in models if any(s['path'] == str(selected) for s in m['sources']) and
                      (not target_project or m['path'] == str(workspace.confined(root, target_project)))), None)
        if owner is None:
            raise CyToolError('InvalidParameters', 'This source file is excluded from the evaluated C# project.')
        return root, str(selected), owner['path'], models, []
    project_paths = [workspace.confined(root, row['path']) for row in state['projects'] if row['path'].endswith('.csproj')]
    if not project_paths:
        raise CyToolError('Unsupported', 'Attach a C# project before using editor services.')
    sources = [workspace.confined(root, row['path']) for row in state['files'] if row['path'].endswith('.cs')]
    sources += [p for p in overlays if p not in sources]
    models, notes, used, size = [], [], set(), 0
    for csproj in project_paths:
        context.check()
        try:
            xml = ET.fromstring(csproj.read_bytes())
        except (ET.ParseError, OSError):
            raise CyToolError('InvalidParameters', 'Cannot read the C# project: ' + str(csproj))
        for node in xml.iter():
            node.tag = node.tag.rsplit('}', 1)[-1]
        props, project_notes = _properties(xml, configuration)
        notes += project_notes
        if xml.findall('Import') or xml.findall('.//Analyzer'):
            notes.append('Imported targets, analyzers and generated sources require a build for complete diagnostics.')
        framework = props.get('TargetFramework') or props.get('TargetFrameworks', '').split(';')[0]
        refs, framework_notes = _framework_references(info[1], framework, props)
        notes += framework_notes
        includes = [(node.get('Include', ''), node.get('Exclude', '')) for node in xml.findall('.//Compile') if node.get('Include')]
        removes = [pattern for node in xml.findall('.//Compile') for pattern in node.get('Remove', '').split(';') if pattern]
        project_sources = []
        for source in sources:
            relative = Path(os.path.relpath(source, csproj.parent)).as_posix()
            owners = [p for p in project_paths if source.is_relative_to(p.parent)]
            default = bool(owners) and max(owners, key=lambda p: len(p.parent.parts)) == csproj and props.get('EnableDefaultCompileItems', 'true').lower() != 'false'
            included = default or any(any(_glob(relative, p) for p in pattern.split(';')) and
                not any(_glob(relative, p) for p in exclude.split(';') if p) for pattern, exclude in includes)
            if not included or any(_glob(relative, p) for p in removes):
                continue
            context.check()
            text = overlays[source] if source in overlays else workspace.read_file(project, source.relative_to(root).as_posix())['text']
            size += len(text.encode())
            used.add(source)
            if size > SNAPSHOT_LIMIT or len(used) > 2000:
                raise CyToolError('InvalidParameters', 'C# editor analysis supports source snapshots up to 32 MiB and 2000 files.')
            project_sources.append({'path': str(source), 'text': text})
        linked = []
        for reference in xml.findall('.//ProjectReference'):
            value = reference.get('Include', '')
            destination = (csproj.parent / value.replace('\\', '/')).resolve()
            if destination in project_paths:
                linked.append(str(destination))
            else:
                notes.append('A project reference outside the source workspace is unavailable to editor analysis.')
        for reference in xml.findall('.//Reference'):
            hint = reference.findtext('HintPath')
            if hint and '$(' not in hint:
                destination = (csproj.parent / hint.replace('\\', '/')).resolve()
                if destination.is_file():
                    refs.append(str(destination))
                else:
                    notes.append('A referenced assembly is missing: ' + reference.get('Include', ''))
        assets = read_json(csproj.parent / 'obj/project.assets.json', {})
        for name, target in assets.get('targets', {}).items():
            if name != framework and name != framework.split('-')[0]:
                continue
            for key, package in target.items():
                if package.get('type') != 'package':
                    continue
                library = assets.get('libraries', {}).get(key, {}).get('path', '')
                for asset in package.get('compile', {}):
                    if not asset.endswith('.dll'):
                        continue
                    candidates = [(Path(folder) / library / asset).resolve() for folder in assets.get('packageFolders', {})]
                    found = next((p for p in candidates if p.is_file()), None)
                    if found:
                        refs.append(str(found))
        if xml.findall('.//PackageReference') and not assets:
            notes.append('Build or restore this project to make package reference metadata available.')
        usings = []
        if props.get('ImplicitUsings', '').lower() in ('enable', 'true'):
            usings = ['System', 'System.Collections.Generic', 'System.IO', 'System.Linq', 'System.Net.Http', 'System.Threading', 'System.Threading.Tasks']
            project_sources.append({'path': str(csproj.parent / '.cydec-global-usings.cs'),
                                    'text': '\n'.join('global using ' + name + ';' for name in usings)})
        models.append({'path': str(csproj), 'name': props.get('AssemblyName') or csproj.stem,
                       'sources': project_sources, 'references': sorted(set(refs)), 'projects': linked,
                       'defines': props['_defines'], 'usings': usings,
                       'languageVersion': props.get('LangVersion', 'default'), 'nullable': props.get('Nullable') == 'enable',
                       'executable': props.get('OutputType', '').lower() in ('exe', 'winexe')})
    if selected not in used:
        raise CyToolError('InvalidParameters', 'This source file is excluded from the C# project.')
    selected_project = workspace.confined(root, target_project) if target_project else next(
        Path(model['path']) for model in models if any(row['path'] == str(selected) for row in model['sources']))
    if not any(model['path'] == str(selected_project) and any(row['path'] == str(selected) for row in model['sources']) for model in models):
        raise CyToolError('InvalidParameters', 'The selected project does not own this source file.')
    return root, str(selected), str(selected_project), models, sorted(set(notes))


def analyze(project, path, action, context, line=1, column=1, buffers=(), target_project='', configuration='Debug', limit=60, new_name=''):
    if action not in ('complete', 'definition', 'diagnostics', 'symbols', 'rename', 'references', 'format'):
        raise CyToolError('InvalidParameters', 'Unknown C# editor action.')
    if any(not isinstance(v, int) or isinstance(v, bool) or v < 1 for v in (line, column)) or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
        raise CyToolError('InvalidParameters', 'Use positive editor coordinates and a result limit up to 200.')
    info = sdk_info(context)
    from .managed_patching import source_stamp
    initial_root, _ = workspace.root_for(project)
    before_revision = source_stamp(initial_root) if action in ('rename', 'format') else ''
    root, file, owner, projects, notes = snapshot(project, context, info, path, buffers, target_project, configuration)
    host, dll = tool(context, info)
    request = {'action': action, 'file': file, 'project': owner, 'line': line, 'column': column,
               'projects': projects, 'limit': limit, 'newName': new_name}
    code, out, err = process.run([host, str(dll)], context=context, stdin_text=json.dumps(request), timeout=120, log_name='csharp-' + action)
    if code:
        raise CyToolError('EngineFailed', 'C# editor analysis failed:\n' + process.tail(err or out))
    result = json.loads(out)
    allowed = {Path(s['path']) for p in projects for s in p['sources'] if not s['path'].endswith('.cydec-global-usings.cs')
               and not any(v in workspace.EXCLUDED for v in Path(s['path']).relative_to(root).parts)}
    if action in ('rename', 'format') and any(Path(e['path']).resolve() not in allowed for e in result['edits']):
        raise CyToolError('Unsupported', 'This refactoring changes generated files. Modify the source generator input and rebuild.')
    def locations(value):
        if isinstance(value, dict):
            if 'path' in value:
                absolute = Path(value['path']).resolve()
                if not absolute.is_relative_to(root) or absolute not in allowed:
                    return None
                value['path'] = absolute.relative_to(root).as_posix()
            return {key: locations(v) for key, v in value.items()}
        if isinstance(value, list):
            return [mapped for v in value if (mapped := locations(v)) is not None]
        return value
    result = locations(result)
    if action in ('rename', 'format'):
        if len(result['edits']) > 200 or any(p['before'] is None or len(p['text'].encode()) > workspace.TEXT_LIMIT for p in result['edits']):
            raise CyToolError('Unsupported', 'Refactoring exceeds the editor buffer limits.')
        if source_stamp(root) != before_revision:
            raise CyToolError('Conflict', 'Sources changed while preparing the refactoring. Request it again.')
        result['sourceRevision'] = before_revision
    for key in ('diagnostics', 'symbols'):
        if key in result:
            result[key] = [row for row in result[key] if row.get('location')]
    return dict(result, projectId=project.id, path=path, action=action, notes=notes)
