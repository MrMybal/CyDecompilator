"""Job-owned NetCoreDbg DAP sessions for reconstructed .NET projects.

The launch job owns the adapter and debuggee for their entire lifetime. Controls use
separate short Runtime jobs; cancellation/timeout/Runtime shutdown kills the tree.
No process survives the launch job, and no target assembly is loaded into Python.
"""
import copy
import json
import threading
import time
import uuid
from pathlib import Path

from cytools_core import CyToolError

from . import components, process, workspace
from .execution import output_events
from .managed_patching import source_stamp
from .paths import read_json, write_json

_sessions = {}
_lock = threading.RLock()
TERMINAL = {'terminated', 'failed', 'cancelled'}


def _key(project):
    return str(project.dir.resolve())


def ensure_editable(project):
    with _lock:
        session = _sessions.get(_key(project))
        if session and not session.closed:
            raise CyToolError('Busy', 'Stop debugging before changing or rebuilding the source workspace.')


def _validate_breakpoints(root, rows):
    if not isinstance(rows, (list, tuple)) or len(rows) > 200:
        raise CyToolError('InvalidParameters', 'Use at most 200 source breakpoints.')
    result = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('path'), str):
            raise CyToolError('InvalidParameters', 'A breakpoint needs a source path and line.')
        path = workspace.confined(root, row['path'])
        line = row.get('line')
        if path.suffix.lower() != '.cs' or not path.is_file() or path.stat().st_size > workspace.TEXT_LIMIT:
            raise CyToolError('InvalidParameters', 'Choose an existing C# source file inside the workspace.')
        try:
            count = len(path.read_text('utf-8-sig').splitlines())
        except (UnicodeError, OSError):
            raise CyToolError('InvalidParameters', 'Breakpoints require readable UTF-8 source files.')
        if type(line) is not int or not 1 <= line <= count:
            raise CyToolError('InvalidParameters', 'Breakpoint line is outside the source file.')
        clean = {'path': path.relative_to(root).as_posix(), 'line': line}
        if clean not in result:
            result.append(clean)
    return result


def breakpoints(project, rows=None):
    root, _ = workspace.root_for(project)
    with _lock:
        session = _sessions.get(_key(project))
        if rows is not None and session and not session.closed:
            raise CyToolError('Busy', 'Use debug_control to change breakpoints in an active session.')
        record = read_json(project.dir / 'workspace-breakpoints.json', {})
        saved = record.get('breakpoints', []) if record.get('directory') == str(root) else []
        if rows is not None:
            saved = _validate_breakpoints(root, rows)
            write_json(project.dir / 'workspace-breakpoints.json', {'directory': str(root), 'breakpoints': saved})
    return {'projectId': project.id, 'breakpoints': saved}


class Session:
    def __init__(self, project, root, context, rows, stop_at_entry):
        self.project, self.root, self.context = project, root, context
        self.id = uuid.uuid4().hex
        self.started_at, self.snapshot_sequence = time.monotonic(), 0
        self.status, self.reason, self.error = 'building', '', ''
        self.stop_id, self.thread_id, self.exit_code = 0, 0, None
        self.rows, self.bound = rows, []
        self.frames, self.scopes, self.variables, self.threads = [], [], [], []
        self.references = set()
        self.selected_frame = 0
        self.stop_at_entry = stop_at_entry
        self.program, self.source_revision, self.output = '', '', ''
        self.capabilities = {}
        self.sequence, self.pending = 0, {}
        self.state_lock, self.commands = threading.RLock(), threading.RLock()
        self.condition = threading.Condition(self.state_lock)
        self.finished = threading.Event()
        self.closed = False
        self.console_log = None
        self.stdin = None
        self.reader = self.starter = None
        self.fatal = None
        self.live_output = output_events(context)

    def snapshot(self):
        with self.state_lock:
            self.snapshot_sequence += 1
            return copy.deepcopy({'projectId': self.project.id, 'sessionId': self.id, 'status': self.status,
                'startedAt': self.started_at, 'snapshotSequence': self.snapshot_sequence,
                'reason': self.reason, 'error': self.error, 'stopId': self.stop_id, 'threadId': self.thread_id,
                'exitCode': self.exit_code, 'breakpoints': self.bound or self.rows, 'frames': self.frames,
                'scopes': self.scopes, 'variables': self.variables, 'threads': self.threads,
                'frameId': self.selected_frame, 'program': self.program, 'output': self.output,
                'capabilities': self.capabilities})

    def attach(self, stdin, stdout):
        self.stdin = stdin
        def read():
            try:
                while True:
                    header, size = 0, None
                    while True:
                        line = stdout.readline(8193)
                        if not line:
                            return
                        header += len(line)
                        if header > 8192:
                            raise ValueError('DAP header exceeds 8192 bytes')
                        if line in (b'\r\n', b'\n'):
                            break
                        if line.lower().startswith(b'content-length:'):
                            size = int(line.split(b':', 1)[1].strip())
                    if size is None or not 0 < size <= 16 * 1024 * 1024:
                        raise ValueError('Invalid DAP content length')
                    payload = bytearray()
                    while len(payload) < size:
                        chunk = stdout.read(size - len(payload))
                        if not chunk:
                            raise ValueError('Truncated DAP message')
                        payload.extend(chunk)
                    self.receive(json.loads(payload.decode('utf-8')))
            except BaseException as exc:
                if not self.finished.is_set():
                    self.fatal = CyToolError('EngineFailed', 'Debugger protocol failed: ' + str(exc))
            finally:
                self.finished.set()
                with self.condition:
                    self.condition.notify_all()
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        def start():
            try:
                with self.commands:
                    self.status = 'starting'
                    self.capabilities = self.request('initialize', {'clientID': 'cydecompilator',
                        'clientName': 'CyDecompilator', 'adapterID': 'coreclr', 'pathFormat': 'path',
                        'linesStartAt1': True, 'columnsStartAt1': True, 'supportsVariableType': True,
                        'supportsVariablePaging': True, 'supportsRunInTerminalRequest': False})
                    self.request('launch', {'name': 'CyDecompilator', 'type': 'coreclr',
                        'program': self.program, 'cwd': str(Path(self.program).parent), 'args': self.arguments,
                        'console': 'internalConsole', 'stopAtEntry': self.stop_at_entry, 'justMyCode': True,
                        'enableStepFiltering': True})
                    self.set_breakpoints(self.rows)
                    with self.state_lock:
                        self.status = 'running'
                    self.request('configurationDone')
            except BaseException as exc:
                self.fatal = exc
        self.starter = threading.Thread(target=start, daemon=True)
        self.starter.start()

    def check(self):
        if self.fatal is not None:
            raise self.fatal

    def close(self):
        self.finished.set()
        with self.condition:
            self.condition.notify_all()
        if self.stdin:
            try:
                self.stdin.close()
            except OSError:
                pass
        for thread in (self.reader, self.starter):
            if thread:
                thread.join(timeout=5)

    def send(self, message):
        raw = json.dumps(message, ensure_ascii=True).encode('utf-8')
        try:
            self.stdin.write(('Content-Length: %d\r\n\r\n' % len(raw)).encode('ascii') + raw)
            self.stdin.flush()
        except (OSError, ValueError, AttributeError):
            raise CyToolError('EngineFailed', 'The debugger connection is closed.')

    def request(self, command, arguments=None, context=None):
        with self.condition:
            self.sequence += 1
            seq = self.sequence
            self.pending[seq] = None
            self.send({'seq': seq, 'type': 'request', 'command': command, 'arguments': arguments or {}})
            deadline = time.monotonic() + 20
            try:
                while self.pending[seq] is None:
                    self.context.check()
                    if context:
                        context.check()
                    if self.fatal:
                        raise self.fatal
                    if self.finished.is_set():
                        raise CyToolError('EngineFailed', 'The debugger session ended.')
                    if time.monotonic() > deadline:
                        raise CyToolError('Timeout', 'Debugger request timed out: ' + command)
                    self.condition.wait(.1)
                response = self.pending[seq]
                if not response.get('success'):
                    raise CyToolError('EngineFailed', response.get('message') or 'Debugger rejected ' + command)
                return response.get('body') or {}
            finally:
                self.pending.pop(seq, None)

    def receive(self, message):
        with self.condition:
            if message.get('type') == 'response':
                seq = message.get('request_seq')
                if seq in self.pending:
                    self.pending[seq] = message
                    self.condition.notify_all()
                return
            if message.get('type') == 'request':
                # Never launch arbitrary reverse-request commands or an external terminal.
                self.send({'seq': 0, 'type': 'response', 'request_seq': message['seq'],
                           'command': message.get('command', ''), 'success': False,
                           'message': 'Only the internal console is supported.'})
                return
            body, event = message.get('body') or {}, message.get('event')
            if event == 'stopped':
                self.status, self.reason = 'paused', body.get('reason', '')
                self.thread_id = body.get('threadId', 0)
                self.stop_id += 1
                self.clear_handles()
            elif event == 'continued':
                self.status = 'running'
                self.clear_handles()
            elif event == 'exited':
                self.exit_code = body.get('exitCode')
            elif event == 'terminated':
                self.status = 'terminated'
                self.clear_handles()
                self.finished.set()
            elif event == 'output':
                text = str(body.get('output', ''))
                self.output = (self.output + text)[-200000:]
                if self.console_log:
                    self.console_log.write(text)
                    self.console_log.flush()
                self.live_output('stderr' if body.get('category') == 'stderr' else 'stdout', text.rstrip('\r\n'))
            elif event == 'breakpoint':
                item = body.get('breakpoint') or {}
                for row in self.bound:
                    if row.get('id') == item.get('id'):
                        row.update(verified=bool(item.get('verified')), line=item.get('line', row['line']),
                                   message=item.get('message', ''))

    def clear_handles(self):
        self.frames, self.scopes, self.variables, self.threads = [], [], [], []
        self.references.clear()
        self.selected_frame = 0

    def set_breakpoints(self, rows, context=None):
        files = sorted({row['path'] for row in self.rows + rows})
        bound = []
        for relative in files:
            requested = [row for row in rows if row['path'] == relative]
            out = self.request('setBreakpoints', {'source': {'path': str(self.root / relative)},
                'breakpoints': [{'line': row['line']} for row in requested], 'sourceModified': False}, context)
            for index, row in enumerate(requested):
                item = (out.get('breakpoints') or [])[index] if index < len(out.get('breakpoints', [])) else {}
                bound.append(dict(row, verified=bool(item.get('verified')), id=item.get('id'),
                                  line=item.get('line', row['line']), message=item.get('message', '')))
        with self.state_lock:
            self.rows, self.bound = rows, bound
        write_json(self.project.dir / 'workspace-breakpoints.json', {'directory': str(self.root), 'breakpoints': rows})

    def paused(self, stop_id):
        with self.state_lock:
            if self.status != 'paused' or stop_id != self.stop_id:
                raise CyToolError('Conflict', 'The pause changed. Refresh the debugger before using frame or variable handles.')

    def inspect(self, context, stop_id, frame_id=0, thread_id=0):
        self.paused(stop_id)
        threads = self.request('threads', context=context).get('threads', [])[:200]
        thread = thread_id or self.thread_id
        if thread not in [t['id'] for t in threads]:
            raise CyToolError('InvalidParameters', 'Choose a thread returned by the debugger.')
        frames = self.request('stackTrace', {'threadId': thread, 'startFrame': 0, 'levels': 100}, context).get('stackFrames', [])
        for frame in frames:
            path = (frame.get('source') or {}).get('path')
            source = Path(path).resolve() if path else None
            frame['path'] = source.relative_to(self.root).as_posix() if source and source.is_relative_to(self.root) else ''
            frame.pop('source', None)
        frame_id = frame_id or (frames[0]['id'] if frames else 0)
        if frame_id and frame_id not in [f['id'] for f in frames]:
            raise CyToolError('InvalidParameters', 'Choose a frame returned by the debugger.')
        scopes = self.request('scopes', {'frameId': frame_id}, context).get('scopes', []) if frames else []
        variables, refs = [], set()
        for scope in scopes:
            reference = scope.get('variablesReference', 0)
            if reference:
                refs.add(reference)
                values = self.request('variables', {'variablesReference': reference, 'start': 0, 'count': 100}, context).get('variables', [])[:100]
                for value in values:
                    variables.append(dict(value, scope=scope.get('name', '')))
                    if value.get('variablesReference'):
                        refs.add(value['variablesReference'])
        with self.state_lock:
            self.paused(stop_id)
            self.threads, self.frames, self.scopes, self.variables = threads, frames, scopes, variables
            self.references, self.selected_frame, self.thread_id = refs, frame_id, thread
        result = self.snapshot()
        result['sourceChanged'] = source_stamp(self.root) != self.source_revision
        return result


def status(project):
    with _lock:
        session = _sessions.get(_key(project))
        root, _ = workspace.root_for(project)
        if session and (not session.closed or session.root == root):
            return session.snapshot()
        return {'projectId': project.id, 'status': 'idle', 'sessionId': '', 'breakpoints': breakpoints(project)['breakpoints']}


def launch(project, context, target_project='', executable='', arguments=(), rows=None, stop_at_entry=False, timeout=1800, receipt_id=''):
    if type(timeout) is not int or not 30 <= timeout <= 86400:
        raise CyToolError('InvalidParameters', 'Debugger timeout must be 30–86400 seconds.')
    if not isinstance(arguments, (list, tuple)) or any(not isinstance(arg, str) or '\0' in arg for arg in arguments):
        raise CyToolError('InvalidParameters', 'Debugger arguments must be a string array.')
    root, info = workspace.root_for(project)
    entry = workspace.confined(root, target_project or info['entry'])
    if not receipt_id and (entry.suffix != '.csproj' or not entry.is_file()):
        raise CyToolError('InvalidParameters', 'Select the startup C# project before debugging a solution.')
    adapter = components.locate('netcoredbg')
    if not adapter:
        raise CyToolError('MissingDependency', 'Install NetCoreDbg in the Engines tab before debugging.')
    with _lock:
        previous = _sessions.get(_key(project))
        if previous and not previous.closed:
            raise CyToolError('Busy', 'A debugger session is already active for this project.')
        saved = breakpoints(project)['breakpoints'] if rows is None else rows
        session = Session(project, root, context, _validate_breakpoints(root, saved), stop_at_entry)
        _sessions[_key(project)] = session
    session.arguments = list(arguments)
    try:
        context.check()
        session.source_revision = source_stamp(root)
        sdk = workspace.dotnet_sdk(context)
        if receipt_id:
            from .execution import verified_copy
            path, receipt = verified_copy(project, receipt_id)
            if not receipt.get('symbols'):
                raise CyToolError('Unsupported', 'Prepare a modified copy with portable symbols before debugging it.')
            if receipt.get('sourceDirectory') != str(root) or receipt.get('sourceRevision') != session.source_revision:
                raise CyToolError('Conflict', 'Sources no longer match the modified copy. Prepare and write a new copy.')
        else:
            path = _build_output(project, root, entry, executable, sdk, context)
        if path.suffix.lower() != '.dll' or not path.is_file():
            raise CyToolError('InvalidParameters', 'Choose a runnable .NET DLL for debugging.')
        if path == project.binary.resolve() or path == Path(project.meta().get('sourcePath', '')).resolve():
            raise CyToolError('InvalidParameters', 'The original application is protected. Debug the rebuilt project.')
        if not path.with_suffix('.runtimeconfig.json').is_file():
            raise CyToolError('Unsupported', 'Debug a runnable .NET Core project. Libraries and .NET Framework projects need a compatible executable host.')
        pdb = path.with_suffix('.pdb')
        if not pdb.is_file() or pdb.read_bytes()[:4] != b'BSJB':
            raise CyToolError('Unsupported', 'A portable PDB is required for source debugging.')
        if source_stamp(root) != session.source_revision:
            raise CyToolError('Conflict', 'Source files changed during the Debug build. Save and start again.')
        session.program = str(path)
        session.status = 'starting'
        if session.finished.is_set():
            session.status = 'terminated'
            return session.snapshot()
        Path(context.workdir).mkdir(parents=True, exist_ok=True)
        session.console_log = (Path(context.workdir) / 'debug-console.log').open('w', encoding='utf-8')
        process.run([adapter['exe'], '--interpreter=vscode'], cwd=path.parent, context=context,
                    timeout=timeout, log_name='debug-adapter', protocol=session)
        session.check()
        if session.status not in TERMINAL:
            raise CyToolError('EngineFailed', 'The debugger closed before reporting termination.')
        return session.snapshot()
    except BaseException as exc:
        with session.state_lock:
            session.status = 'cancelled' if context.cancellation and context.cancellation.event.is_set() else 'failed'
            session.error = str(exc)
            session.clear_handles()
        raise
    finally:
        session.finished.set()
        if session.console_log:
            session.console_log.close()
        session.closed = True


def _build_output(project, root, entry, executable, sdk, context):
    code, out, err = process.run([sdk, 'build', str(entry), '-c', 'Debug', '--nologo', '-v', 'minimal',
        '-p:DebugType=portable', '-p:DebugSymbols=true', '-p:Optimize=false', '-p:PublishReadyToRun=false'],
        cwd=root, context=context, timeout=900, log_name='debug-build', on_output=output_events(context))
    if code:
        raise CyToolError('EngineFailed', 'The Debug build failed:\n' + process.tail(out + '\n' + err, 35))
    if executable:
        path = (root / executable).resolve()
        if Path(executable).is_absolute():
            raise CyToolError('InvalidParameters', 'Choose a built assembly relative to the workspace.')
    else:
        code, out, err = process.run([sdk, 'msbuild', str(entry), '-nologo', '-p:Configuration=Debug',
                                    '-getProperty:TargetPath'], cwd=root, context=context, timeout=60, log_name='debug-target')
        if code:
            raise CyToolError('EngineFailed', 'Cannot determine the debug output: ' + process.tail(err or out))
        path = Path(out.strip()).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() != '.dll':
        raise CyToolError('InvalidParameters', 'Choose one built .NET DLL inside the source workspace; multi-target projects need an explicit output.')
    return path


def control(project, session_id, action, context, stop_id=0, frame_id=0, thread_id=0, reference=0, rows=None):
    with _lock:
        session = _sessions.get(_key(project))
    if session is None or session.id != session_id:
        raise CyToolError('Conflict', 'The debugger session changed. Refresh before sending commands.')
    if action == 'status':
        return session.snapshot()
    if action == 'stop' and session.status in ('building', 'starting'):
        if session.context.cancellation:
            session.context.cancellation.cancel()
        session.finished.set()
        return session.snapshot()
    # Serialise requests without preventing cancellation of a queued control job.
    while not session.commands.acquire(timeout=.1):
        context.check()
    try:
        context.check()
        if action == 'stop':
            if session.status not in TERMINAL:
                if session.status == 'building':
                    session.finished.set()
                    return session.snapshot()
                try:
                    session.request('disconnect', {'terminateDebuggee': True}, context)
                finally:
                    session.status = 'terminated'
                    session.finished.set()
            return session.snapshot()
        if session.status in TERMINAL or session.status in ('building', 'starting'):
            raise CyToolError('Busy', 'Wait for the debugger to finish starting.')
        if action == 'breakpoints':
            session.set_breakpoints(_validate_breakpoints(session.root, rows), context)
        elif action == 'pause':
            session.request('pause', {'threadId': thread_id or session.thread_id}, context)
        elif action == 'inspect':
            return session.inspect(context, stop_id, frame_id, thread_id)
        elif action == 'variables':
            session.paused(stop_id)
            if reference not in session.references:
                raise CyToolError('InvalidParameters', 'Use a current variable reference returned by this debugger.')
            values = session.request('variables', {'variablesReference': reference, 'start': 0, 'count': 100}, context).get('variables', [])[:100]
            session.paused(stop_id)
            for value in values:
                if value.get('variablesReference'):
                    session.references.add(value['variablesReference'])
            return dict(session.snapshot(), children=values, variablesReference=reference)
        elif action in ('continue', 'next', 'stepIn', 'stepOut'):
            session.paused(stop_id)
            thread = thread_id or session.thread_id
            if thread != session.thread_id:
                raise CyToolError('InvalidParameters', 'Inspect the selected thread before stepping it.')
            with session.state_lock:
                session.status = 'running'
                session.clear_handles()
            try:
                session.request(action, {'threadId': thread}, context)
            except BaseException:
                # A rejected command must not leave a paused debuggee displayed as running.
                with session.state_lock:
                    if session.stop_id == stop_id and session.status == 'running':
                        session.status = 'paused'
                raise
        else:
            raise CyToolError('InvalidParameters', 'Unknown debugger action.')
        return session.snapshot()
    finally:
        session.commands.release()
