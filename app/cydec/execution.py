"""Launch an explicitly selected, recorded modified copy through a cancellable job."""
import hashlib
import os
import re
import shutil
import threading
import uuid
from pathlib import Path

import pefile
from cytools_core import CyToolError

from . import components, process
from .paths import read_json, write_json

OUTPUT_LIMIT = 200000


def output_events(context):
    """Bound live output events; the full streams remain in the job's log files."""
    remaining = OUTPUT_LIMIT
    lock = threading.Lock()

    def line(stream, text):
        nonlocal remaining
        if context is None:
            return
        with lock:
            if remaining <= 0:
                return
            value = (text + '\n')[:min(8192, remaining)]
            remaining -= len(value)
            context.emit('ProcessOutput', {'stream': stream, 'text': value})
    return line


def launch_kind(path):
    """Inspect PE metadata without loading the application or a native DLL."""
    with pefile.PE(str(path), fast_load=True) as pe:
        directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY
        if len(directory) > 14 and directory[14].VirtualAddress:
            header = pe.get_data(directory[14].VirtualAddress, 72)
            if len(header) < 72 or not int.from_bytes(header[20:24], 'little'):
                return 'library'
            return 'managed'
        return 'library' if pe.FILE_HEADER.Characteristics & 0x2000 else 'native'


def save_receipt(project, receipt):
    receipt = dict(receipt, receiptId=uuid.uuid4().hex, launchKind=launch_kind(receipt['path']))
    from .history import matching_commit
    receipt['sourceCommit'] = matching_commit(project, receipt.get('sourceDirectory'), receipt.get('sourceRevision'))
    write_json(project.dir / 'patches/receipts' / (receipt['receiptId'] + '.json'), receipt)
    return receipt


def outputs(project):
    rows = []
    folder = project.dir / 'patches/receipts'
    for path in sorted(folder.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        if not re.fullmatch(r'[0-9a-f]{32}', path.stem):
            continue
        row = read_json(path, {})
        if row.get('projectId') == project.id and row.get('path'):
            # Older receipts also have a stable filename identifier.
            row = dict(row, receiptId=path.stem,
                       launchKind=row.get('launchKind') or launch_kind(project.binary))
            rows.append(row)
    return {'projectId': project.id, 'copies': rows, 'lastRun': read_json(project.dir / 'patch-run.json', {})}


def _runtime():
    candidates = [shutil.which('dotnet')]
    if os.name == 'nt':
        candidates.append(str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'dotnet/dotnet.exe'))
    located = components.locate('dotnet')
    if located and located.get('dotnet'):
        candidates.append(located['dotnet'])
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise CyToolError('MissingDependency', 'Install the .NET runtime required by this application.')


def verified_copy(project, receipt_id):
    if not re.fullmatch(r'[0-9a-f]{32}', receipt_id):
        raise CyToolError('InvalidParameters', 'Choose a saved modified copy.')
    with project.lock:
        receipt = read_json(project.dir / 'patches/receipts' / (receipt_id + '.json'), {})
        if not receipt or receipt.get('projectId') != project.id:
            raise CyToolError('NotFound', 'Modified copy receipt not found.')
        path = Path(receipt['path'])
        if not path.is_absolute() or path.resolve() in (project.binary.resolve(), Path(project.meta()['sourcePath']).resolve()):
            raise CyToolError('InvalidParameters', 'Run a separate modified copy; the original is protected.')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != receipt['sha256']:
            raise CyToolError('Conflict', 'The modified copy is missing or changed. Write a new verified copy.')
        for row in receipt.get('companionHashes', []):
            companion = Path(row['path'])
            if not companion.is_file() or hashlib.sha256(companion.read_bytes()).hexdigest() != row['sha256']:
                raise CyToolError('Conflict', 'A runtime dependency changed. Write a new verified copy.')
        return path, receipt


def run_copy(project, receipt_id, context, arguments=(), timeout=60):
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 900:
        raise CyToolError('InvalidParameters', 'Run timeout must be between 1 and 900 seconds.')
    if not isinstance(arguments, (list, tuple)) or any(not isinstance(a, str) or '\0' in a for a in arguments):
        raise CyToolError('InvalidParameters', 'Use an array of string arguments.')
    with project.lock:
        path, receipt = verified_copy(project, receipt_id)
        kind = launch_kind(path)
        if kind == 'library':
            raise CyToolError('Unsupported', 'This copy is a library. Run it through a source project test harness.')
        if kind == 'managed' and path.with_suffix('.runtimeconfig.json').is_file():
            command = [_runtime(), str(path), *arguments]
        elif kind == 'managed' and path.suffix.lower() != '.exe':
            raise CyToolError('MissingDependency', 'The runtime configuration is missing. Keep the original filename in a new output folder.')
        else:
            command = [str(path), *arguments]
    # Do not hold the project lock while application code is running.
    code, out, err = process.run(command, cwd=path.parent, context=context, timeout=timeout,
                                 log_name='modified-copy', on_output=output_events(context))
    result = {'projectId': project.id, 'receiptId': receipt_id, 'path': str(path), 'action': 'patch-run',
              'status': 'passed' if code == 0 else 'failed', 'exitCode': code,
              'output': (out + '\n' + err).strip()[-OUTPUT_LIMIT:], 'diagnostics': []}
    with project.lock:
        write_json(project.dir / 'patch-run.json', result)
    return result
