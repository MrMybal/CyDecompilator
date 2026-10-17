"""Managed method replacement from a rebuilt C# assembly, verified before publishing."""
import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from pathlib import Path

import pefile
from cytools_core import CyToolError

from . import process, workspace
from .paths import APP, ENGINES, read_json, write_json

_tool_lock = threading.Lock()
SOURCE_FILES = ('ManagedPatcher.csproj', 'Program.cs', 'GeneratedImporter.cs', 'NuGet.Config', 'packages.lock.json')


def hash_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tool(context):
    sdk = workspace.dotnet_sdk(context)
    sources = APP / 'managed'
    stamp = hashlib.sha256(b''.join((sources / n).read_bytes() for n in SOURCE_FILES)).hexdigest()
    destination = ENGINES / 'managed-patcher' / '1' / stamp[:16]
    dll = destination / 'ManagedPatcher.dll'
    with _tool_lock:
        if not dll.is_file():
            folder = Path(context.workdir) / ('managed-tool-' + uuid.uuid4().hex)
            folder.mkdir(parents=True)
            for name in SOURCE_FILES:
                shutil.copyfile(sources / name, folder / name)
            packages = (ENGINES / 'managed-patcher/packages').resolve()
            commands = [[sdk, 'restore', str(folder / 'ManagedPatcher.csproj'), '--locked-mode',
                         '--configfile', str(folder / 'NuGet.Config'), '--packages', str(packages)],
                        [sdk, 'build', str(folder / 'ManagedPatcher.csproj'), '--no-restore',
                         '-c', 'Release', '-o', str(folder / 'out'), '--nologo']]
            for index, command in enumerate(commands):
                code, out, err = process.run(command, context=context, timeout=300, log_name='managed-tool-' + str(index))
                if code:
                    raise CyToolError('MissingDependency', 'Managed patch tool build failed:\n' + process.tail(out + '\n' + err))
            context.check()
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(folder / 'out', destination)
    return sdk, dll


def invoke(context, request):
    sdk, dll = tool(context)
    code, out, err = process.run([sdk, '--roll-forward', 'Major', str(dll)], context=context,
                                 stdin_text=json.dumps(request), timeout=300, log_name='managed-' + request['operation'])
    if code:
        raise CyToolError('Unsupported', process.tail(err or out))
    try:
        return json.loads(out)
    except ValueError:
        raise CyToolError('EngineFailed', 'The managed patch tool returned invalid output.')


def validate_original(project):
    if project.meta()['detect']['format'] != 'pe-dotnet':
        raise CyToolError('Unsupported', 'Select a managed .NET assembly.')
    if hash_file(project.binary) != project.meta()['sha256']:
        raise CyToolError('Conflict', 'The cached original changed. Open it again.')
    pe = pefile.PE(str(project.binary), fast_load=True)
    cor = pe.OPTIONAL_HEADER.DATA_DIRECTORY[14]
    header = pe.get_data(cor.VirtualAddress, 72)
    if len(header) < 72 or not int.from_bytes(header[16:20], 'little') & 1:
        raise CyToolError('Unsupported', 'Mixed-mode assemblies require a complete rebuild.')
    if int.from_bytes(header[64:68], 'little'):
        raise CyToolError('Unsupported', 'ReadyToRun assemblies require an IL-only rebuild before method replacement.')


def methods(project, context, type_name=''):
    validate_original(project)
    result = invoke(context, {'operation': 'list', 'original': str(project.binary), 'type': type_name})
    return dict(result, projectId=project.id)


def source_stamp(root):
    digest = hashlib.sha256()
    for directory, folders, names in os.walk(root, followlinks=False):
        folders[:] = sorted(f for f in folders if f not in workspace.EXCLUDED
                            and (Path(directory) / f).resolve().is_relative_to(root))
        for name in sorted(names):
            path = Path(directory) / name
            if path.suffix.lower() in workspace.TEXT_EXTENSIONS and path.resolve().is_relative_to(root):
                digest.update(path.relative_to(root).as_posix().encode())
                digest.update(bytes.fromhex(hash_file(path)))
    return digest.hexdigest()


def prepare(project, method_id, context, donor='', configuration='Debug', build=True, remove_strong_name=False, target_project='', allow_new_members=False, symbols=False):
    validate_original(project)
    if not re.fullmatch(r'0x06[0-9a-fA-F]{6}', method_id):
        raise CyToolError('InvalidParameters', 'Use a method id returned by managed_methods.')
    with project.lock:
        root, info = workspace.root_for(project)
        if info['kind'] != 'dotnet':
            raise CyToolError('Unsupported', 'Attach or reconstruct a C# project before replacing a .NET method.')
        before = source_stamp(root)
        if build:
            result = workspace.execute(project, 'build', context, configuration, target_project=target_project, debug_symbols=symbols)
            if result['status'] != 'passed':
                raise CyToolError('EngineFailed', 'The source project must compile first:\n' + process.tail(result['output'], 50))
        listing = methods(project, context)
        token = int(method_id, 16)
        method = next((m for m in listing['methods'] if m['token'] == token), None)
        if method is None or not method['editable']:
            raise CyToolError('Unsupported', 'Select an editable source method with an IL body instead of a generated helper.')
        if donor:
            donor_path = (root / donor).resolve()
            if Path(donor).is_absolute() or not donor_path.is_relative_to(root) or not donor_path.is_file():
                raise CyToolError('InvalidParameters', 'Choose a rebuilt assembly relative to the source workspace.')
        else:
            module_name = Path(listing['module']).name
            candidates = [p for p in root.rglob(module_name) if p.is_file() and
                          ('bin', configuration) in list(zip(p.relative_to(root).parts, p.relative_to(root).parts[1:]))]
            if len(candidates) != 1:
                raise CyToolError('InvalidParameters', 'Choose the rebuilt assembly explicitly; none or multiple matching outputs were found.')
            donor_path = candidates[0]
        folder = Path(context.workdir) / ('managed-patch-' + uuid.uuid4().hex)
        folder.mkdir(parents=True)
        candidate = folder / 'candidate.dll'
        donor_hash = hash_file(donor_path)
        report = invoke(context, {'operation': 'patch', 'original': str(project.binary), 'donor': str(donor_path),
                                 'output': str(candidate), 'token': token, 'removeStrongName': remove_strong_name,
                                 'allowNewMembers': allow_new_members, 'symbols': symbols})
        if source_stamp(root) != before or hash_file(donor_path) != donor_hash:
            raise CyToolError('Conflict', 'Source or build output changed while preparing the patch. Prepare it again.')
        context.check()
        plan_id = uuid.uuid4().hex
        saved = project.dir / 'patches/managed' / plan_id
        saved.mkdir(parents=True)
        shutil.copyfile(candidate, saved / 'candidate.dll')
        companions = []
        # Keep runtime configuration available for testing a modern managed executable.
        companion_paths = [donor_path.with_name(donor_path.stem + suffix) for suffix in ('.runtimeconfig.json', '.deps.json')]
        companion_paths += [p for p in donor_path.parent.glob('*.dll') if p.resolve() != donor_path.resolve()]
        (saved / 'companions').mkdir()
        if symbols:
            pdb_name = project.binary.stem + '.pdb'
            shutil.copyfile(candidate.with_suffix('.pdb'), saved / 'companions' / pdb_name)
            companions.append({'name': pdb_name, 'sha256': hash_file(saved / 'companions' / pdb_name)})
        for path in companion_paths:
            if path.is_file():
                shutil.copyfile(path, saved / 'companions' / path.name)
                companions.append({'name': path.name, 'sha256': hash_file(path)})
        value = {'kind': 'managed', 'projectId': project.id, 'planId': plan_id, 'methodId': method_id,
                 'function': report['method'], 'originalHash': hash_file(project.binary),
                 'candidateHash': hash_file(candidate), 'donorHash': donor_hash,
                 'sourceDirectory': str(root), 'sourceRevision': before, 'companions': companions,
                 'size': report['newSize'], 'capacity': report['oldSize'], 'disassembly': report['il'],
                 'unchangedMethods': report['unchangedMethods'], 'strongNameRemoved': report['strongNameRemoved'],
                 'generatedTypes': report['generatedTypes'], 'generatedMethods': report['generatedMethods'],
                 'addedTypes': report['addedTypes'], 'addedMethods': report['addedMethods'], 'addedFields': report['addedFields'],
                 'symbols': symbols,
                 'note': 'The selected method and reviewed dependencies are imported. Other existing method bodies and tokens are verified unchanged. Portable symbols map imported methods to matching sources. Test the modified copy before use.'}
        write_json(project.dir / 'patches/plans' / (plan_id + '.json'), value)
        return value


def apply(project, plan, destination='', context=None):
    validate_original(project)
    root, _ = workspace.root_for(project)
    if str(root) != plan['sourceDirectory'] or source_stamp(root) != plan['sourceRevision']:
        raise CyToolError('Conflict', 'The source project changed. Prepare the method patch again.')
    saved = project.dir / 'patches/managed' / plan['planId']
    candidate = saved / 'candidate.dll'
    if hash_file(candidate) != plan['candidateHash'] or hash_file(project.binary) != plan['originalHash']:
        raise CyToolError('Conflict', 'The verified patch or original changed. Prepare it again.')
    path = Path(destination) if destination else project.dir / 'patches/output' / plan['planId'] / project.binary.name
    if not path.is_absolute():
        raise CyToolError('InvalidParameters', 'destination must be an absolute file path.')
    if path.resolve() in (project.binary.resolve(), Path(project.meta()['sourcePath']).resolve()):
        raise CyToolError('InvalidParameters', 'Choose a separate output copy; the original cannot be overwritten.')
    for row in plan['companions']:
        if Path(row['name']).name != row['name'] or hash_file(saved / 'companions' / row['name']) != row['sha256']:
            raise CyToolError('Conflict', 'Runtime configuration changed. Prepare the patch again.')
    if plan.get('symbols') and path.stem == project.binary.stem:
        pdb = path.with_suffix('.pdb')
        row = next(c for c in plan['companions'] if c['name'] == project.binary.stem + '.pdb')
        if pdb.exists() and hash_file(pdb) != row['sha256']:
            raise CyToolError('Conflict', 'Existing debug symbols do not match this copy. Choose a new output folder.')
    if context:
        context.check()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as output:
            output.write(candidate.read_bytes())
    except FileExistsError:
        raise CyToolError('Conflict', 'The output already exists. Choose a new filename.')
    companions = []
    companion_hashes = []
    if path.stem == project.binary.stem:
        for row in plan['companions']:
            output = path.parent / row['name']
            if not output.exists():
                with output.open('xb') as file:
                    file.write((saved / 'companions' / row['name']).read_bytes())
                companions.append(str(output))
            companion_hashes.append({'path': str(output), 'sha256': hash_file(output)})
    receipt = {'projectId': project.id, 'planId': plan['planId'], 'path': str(path), 'sha256': plan['candidateHash'],
               'originalHash': plan['originalHash'], 'function': plan['function'], 'originalPreserved': True,
               'unchangedMethods': plan['unchangedMethods'], 'strongNameRemoved': plan['strongNameRemoved'],
               'generatedTypes': plan.get('generatedTypes', []), 'generatedMethods': plan.get('generatedMethods', []),
               'addedTypes': plan.get('addedTypes', []), 'addedMethods': plan.get('addedMethods', []), 'addedFields': plan.get('addedFields', []),
               'symbols': bool(plan.get('symbols')) and path.stem == project.binary.stem,
               'sourceDirectory': str(root), 'sourceRevision': plan['sourceRevision'],
               'companions': companions, 'companionHashes': companion_hashes}
    from .execution import save_receipt
    return save_receipt(project, receipt)
