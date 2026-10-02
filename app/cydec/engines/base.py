"""The contract every decompilation engine implements.

An engine turns a project's input file into an *analysis* (the list of units it can
decompile, plus whatever it learns about strings, imports, sections...), then decompiles
or disassembles one unit on demand. A unit is a function for native code, a type for
.NET/Java/Android, a code object for Python and an entry point for shaders.

Function record (every key except id/name is optional):
    {'id': stable id, 'name': original name, 'address': '0x401000', 'size': 123,
     'kind': 'function'|'type'|'method'|'code'|'entry', 'signature': '...',
     'parent': 'namespace or class', 'callees': [ids], 'callers': [ids]}

`analyze` returns the analysis dict. When the engine decompiles everything up front it
adds `_code`: a list of (unit id, source text) pairs, which the caller stores in the
project cache after saving the analysis (saving an analysis clears the previous cache).

Engines never print to stdout (the CLI and MCP transports own it); they log through the
context, check cancellation regularly and isolate external programs in subprocesses that
`process.run` stops when the job is cancelled.
"""
from cytools_core import CyToolError


class EngineContext:
    """What a handler gives an engine: cancellation, progress, log and a private workdir."""

    def __init__(self, cancellation=None, progress=None, log=None, workdir=None, options=None, emit=None):
        self.cancellation = cancellation
        self._progress = progress
        self._log = log
        self._emit = emit
        self.workdir = workdir
        self.options = dict(options or {})

    def emit(self, event_type, data):
        if self._emit is not None:
            self._emit(event_type, data)

    def check(self):
        if self.cancellation is not None:
            self.cancellation.check()

    def progress(self, percent, step=''):
        if self._progress is not None:
            self._progress(max(0.0, min(100.0, float(percent))), step)

    def log(self, message, level='Info'):
        if self._log is not None:
            self._log(str(message), level)


class Engine:
    id = ''
    name = ''
    license = ''
    url = ''
    description = ''
    formats = ()
    # Downloadable components this engine needs (see components.py).
    components = ()
    language = 'c'
    supports_decompile = True
    supports_disassemble = False

    def descriptor(self):
        return {'id': self.id, 'name': self.name, 'license': self.license, 'url': self.url,
                'description': self.description, 'formats': list(self.formats),
                'components': list(self.components), 'language': self.language,
                'supportsDecompile': self.supports_decompile,
                'supportsDisassemble': self.supports_disassemble}

    def availability(self):
        """{'available': bool, 'missing': [component ids], 'detail': str}."""
        from .. import components
        missing = [c for c in self.components if not components.locate(c)]
        return {'available': not missing, 'missing': missing,
                'detail': ('Install: ' + ', '.join(missing)) if missing else 'Ready'}

    def require(self):
        state = self.availability()
        if not state['available']:
            raise CyToolError('MissingDependency',
                              '%s needs components that are not installed: %s. Install them '
                              'from the Engines tab or with the install_component operation.'
                              % (self.name, ', '.join(state['missing'])), recoverable=True)

    def accepts(self, detect_record):
        return detect_record.get('format') in self.formats

    def analyze(self, project, context):
        raise NotImplementedError

    def decompile(self, project, analysis, function, context):
        raise CyToolError('Unsupported', '%s cannot decompile.' % self.name)

    def disassemble(self, project, analysis, function, context):
        raise CyToolError('Unsupported', '%s has no disassembly view.' % self.name)
