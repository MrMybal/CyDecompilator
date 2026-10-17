"""Explicit MSBuild evaluation; editor snapshots only read the resulting metadata."""
import hashlib
import json
from pathlib import Path

from cytools_core import CyToolError
from . import process, workspace
from .paths import read_json, write_json


def stamp(root):
    value = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if any(p in workspace.EXCLUDED for p in path.relative_to(root).parts) or not path.is_file():
            continue
        if path.suffix in ('.csproj', '.props', '.targets') or path.name == 'global.json':
            if not path.resolve().is_relative_to(root):
                raise CyToolError('InvalidParameters', 'Project configuration escapes the workspace.')
            value.update(path.relative_to(root).as_posix().encode())
            value.update(path.read_bytes())
        elif path.suffix == '.cs':
            # Default Compile globs must be reevaluated when files are added/removed.
            value.update(path.relative_to(root).as_posix().encode())
    return value.hexdigest()


def evaluate(project, context, configuration='Debug'):
    if configuration not in ('Debug', 'Release'):
        raise CyToolError('InvalidParameters', 'Invalid build configuration.')
    root, _ = workspace.root_for(project)
    before = stamp(root)
    projects = [workspace.confined(root, p['path']) for p in workspace.state(project)['projects'] if p['path'].endswith('.csproj')]
    host = workspace.dotnet_sdk(context)
    models = []
    for path in projects:
        code, out, err = process.run([host, 'msbuild', str(path), '-nologo', '-p:Configuration=' + configuration,
            '-getProperty:TargetFramework,TargetFrameworks'], cwd=root, context=context, timeout=60, log_name='project-framework')
        if code:
            raise CyToolError('EngineFailed', 'Cannot evaluate target frameworks: ' + process.tail(out+err))
        properties = json.loads(out[out.index('{'):])['Properties']
        framework = properties.get('TargetFramework') or properties.get('TargetFrameworks', '').split(';')[0]
        framework_option = ['-p:TargetFramework=' + framework] if framework else []
        code, out, err = process.run([host, 'msbuild', str(path), '-nologo', '-p:Configuration=' + configuration,
            *framework_option,
            '-target:ResolveReferences', '-getProperty:TargetFramework,DefineConstants,LangVersion,Nullable,OutputType,AssemblyName',
            '-getItem:Compile,ReferencePath,ProjectReference,Using'], cwd=root, context=context, timeout=180, log_name='project-model')
        if code:
            raise CyToolError('EngineFailed', 'MSBuild project evaluation failed:\n' + process.tail(out + err))
        try:
            data = json.loads(out[out.index('{'):])
        except (ValueError, KeyError):
            raise CyToolError('EngineFailed', 'MSBuild did not return evaluated project metadata. SDK 8+ is required.')
        props, items = data['Properties'], data['Items']
        def files(name):
            return [Path(i.get('FullPath') or path.parent / i['Identity']).resolve() for i in items.get(name, [])]
        sources = [p for p in files('Compile') if p.is_relative_to(root) and p.is_file() and p.suffix == '.cs']
        references = [str(p) for p in files('ReferencePath') if p.is_file() and p.suffix.lower() in ('.dll', '.exe')]
        models.append({'path': str(path), 'name': props.get('AssemblyName') or path.stem,
            'sources': [str(p) for p in sources], 'references': references,
            'projects': [str(p) for p in files('ProjectReference') if p in projects],
            'defines': [p for p in props.get('DefineConstants', '').split(';') if p.isidentifier()],
            'usings': [i['Identity'] for i in items.get('Using', [])],
            'languageVersion': props.get('LangVersion') or 'default', 'nullable': props.get('Nullable') == 'enable',
            'executable': props.get('OutputType', '').lower() in ('exe', 'winexe')})
    if stamp(root) != before:
        raise CyToolError('Conflict', 'Project configuration changed during evaluation.')
    result = {'directory': str(root), 'configuration': configuration, 'revision': before, 'models': models}
    write_json(project.dir / 'workspace-model.json', result)
    return {'projectId': project.id, 'projects': len(models), 'sources': sum(len(m['sources']) for m in models)}


def cached(project, root, configuration):
    result = read_json(project.dir / 'workspace-model.json', {})
    if result.get('directory') == str(root) and result.get('configuration') == configuration and result.get('revision') == stamp(root):
        return result['models']
    return None
