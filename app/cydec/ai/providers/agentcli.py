"""Providers reached through an agent command line already installed and signed in.

Codex, Claude Code, Antigravity and OpenCode are driven through the portable connector
library vendored in `cydec/ai/vendor/cyai_connectors`. They are session based: the provider
stores the history and is resumed with the identifier recorded in the conversation, so this
Tool sends one message per turn instead of replaying the transcript.

These programs are coding agents, not bare chat endpoints. Every connection here is opened
with the read-only sandbox and with approval requests declined, so a turn cannot edit files
or run a command that needs permission. That is a deliberate restriction of this Tool: it
is a place to talk to the model, not a place to let an agent act on the machine.

No account credential is handled here. The CLI uses the login the user already performed in
its own program, which is also why no token ever reaches a parameter, a job or a log.
"""
import threading
import time

from cytools_core import CyToolError

from ..vendor.cyai_connectors import ConnectorError, create_transport, descriptors
from .base import SESSION, ChatRequest, ChatResult, Delta, Provider  # noqa: F401

# Turning a connector failure into a CyTools code keeps the CLI, MCP and interface showing
# the same vocabulary instead of a provider-specific string.
ERROR_CODES = {'ExecutableMissing': 'MissingDependency', 'Cancelled': 'Cancelled',
               'Timeout': 'Timeout', 'ProviderError': 'ProviderFailed',
               'ProcessCrash': 'WorkerCrashed', 'MalformedJSON': 'ProtocolError',
               'UnexpectedEOF': 'ProtocolError', 'ProtocolError': 'ProtocolError',
               'SessionInvalid': 'InvalidParameters', 'Unsupported': 'Unsupported',
               'ModelDiscoveryFailed': 'ProviderFailed', 'AuthenticationRequired': 'AuthenticationRequired'}

# Providers whose adapter the vendored library implements and this project has executed.
IMPLEMENTED = ('codex', 'claude-code', 'antigravity', 'opencode')
# Declared in the catalogue, no adapter written: listing them is how the interface can say
# "known, not available" instead of pretending the provider does not exist.
DECLARED_ONLY = ('codebuddy', 'command-code', 'devin')

NAMES = {'codex': 'Codex', 'claude-code': 'Claude Code', 'antigravity': 'Antigravity',
         'opencode': 'OpenCode', 'codebuddy': 'CodeBuddy', 'command-code': 'Command Code',
         'devin': 'Devin'}

# Transports validated by a real turn on this machine are separated from the rest, so the
# interface can mark what was only wired up. See app/Docs/CapabilityCoverage.md.
TESTED = {'codex': ('app-server', 'cli-jsonl'), 'claude-code': ('cli-jsonl',),
          'antigravity': ('cli-jsonl',), 'opencode': ()}


QUOTES = {'’': "'", '‘': "'", '“': '"', '”': '"', '…': '...'}


def readable(text):
    """Normalise the vendored library's typographic punctuation.

    Its messages are written with curly quotes, which the font in the window cannot draw and
    which would surface to the user as empty boxes in the middle of an error. The vendored
    copy is left exactly as upstream wrote it; only the text handed to the interface changes.
    """
    result = str(text)
    for old, new in QUOTES.items():
        result = result.replace(old, new)
    return result


def translate(exc):
    return CyToolError(ERROR_CODES.get(getattr(exc, 'code', ''), 'ProviderFailed'),
                       readable(exc))


class _Cancellable:
    """Mixin giving the vendored transport the Tool's cancellation token and deadline.

    The connector polls `check()` inside its read loop, so overriding it is enough to stop a
    turn between two streamed lines without a watchdog thread and without killing a process
    that is already finishing.
    """

    token = None

    def check(self):
        if self.token is not None:
            self.token.check()
        super().check()


def _cancellable(cls):
    return type('Cancellable' + cls.__name__, (_Cancellable, cls), {})


class AgentCliProvider(Provider):
    kind = SESSION
    supports_streaming = True
    supports_system_prompt = True
    documentation = 'Uses the account already signed in inside the agent CLI.'

    def __init__(self, provider_id, settings=None):
        super().__init__(settings)
        catalogue = descriptors()
        if provider_id not in catalogue:
            raise CyToolError('NotFound', 'Unknown provider: ' + str(provider_id))
        self.id = provider_id
        self.descriptor_data = catalogue[provider_id]
        self.name = NAMES.get(provider_id, self.descriptor_data.get('name', provider_id))
        implemented = [t['id'] for t in self.descriptor_data['transports'] if t['implemented']]
        preferred = self.descriptor_data.get('preferred_transport')
        self.transports = tuple([preferred] + [t for t in implemented if t != preferred]
                                if preferred in implemented else implemented)
        self.untested = tuple(t for t in self.transports if t not in TESTED.get(provider_id, ()))
        self.supports_model_list = self.descriptor_data['capabilities'].get('models') == 'declared'
        self._transports = {}
        self._lock = threading.RLock()
        self._active = None

    # ------------------------------------------------------------------ plumbing

    def config(self, transport, request=None):
        values = {'transport': transport,
                  'timeout': float((request.settings if request else self.settings)
                                   .get('timeout_seconds') or self.settings.get('timeout_seconds') or 900),
                  'cwd': str(self.settings.get('workspace') or '.')}
        executable = (request.settings.get('executable') if request else '') or self.settings.get('executable')
        if executable:
            values['executable'] = str(executable)
        return values

    def _instance(self, transport, request=None, sink=None):
        transport = self.transport_for(transport)
        with self._lock:
            existing = self._transports.get(transport)
            if existing is not None:
                existing.config.update(self.config(transport, request))
                existing.sink = sink or (lambda channel, value: None)
                existing.token = request.cancellation if request else None
                return existing
            base = create_transport(self.id, self.config(transport, request), sink)
            instance = _cancellable(type(base))(self.descriptor_data,
                                                self.config(transport, request), sink)
            instance.name = transport
            instance.token = request.cancellation if request else None
            self._transports[transport] = instance
            return instance

    # ------------------------------------------------------------------ description

    def descriptor(self):
        value = super().descriptor()
        value.update(untestedTransports=list(self.untested),
                     capabilities=self.descriptor_data['capabilities'],
                     declaredTransports=[t['id'] for t in self.descriptor_data['transports']])
        return value

    def detect(self):
        report = {'id': self.id, 'name': self.name, 'kind': self.kind,
                  'transports': list(self.transports)}
        if not self.transports:
            report.update(available=False, status='NotImplemented',
                          detail='Declared in the catalogue; no adapter is implemented for it.')
            return report
        instance = self._instance(self.transports[-1] if self.transports[-1] == 'cli-jsonl'
                                  else self.transports[0])
        try:
            found = instance.detect()
        except ConnectorError as exc:
            return {**report, 'available': False, 'status': 'Error', 'detail': readable(exc)}
        report.update(available=found.get('status') == 'Installed', status=found.get('status', ''),
                      version=str(found.get('version', ''))[:200],
                      command=' '.join(found.get('command', [])) if found.get('command') else '',
                      detail=readable(found.get('error', '')))
        return report

    def authenticate(self):
        """Ask the CLI whether an account is signed in. Only the conclusion is returned."""
        instance = self._instance('cli-jsonl' if 'cli-jsonl' in self.transports else self.transports[0])
        try:
            return {'providerId': self.id, **instance.connect()}
        except ConnectorError as exc:
            raise translate(exc)

    def list_models(self, transport=''):
        instance = self._instance(transport)
        try:
            rows = instance.list_models()
        except ConnectorError as exc:
            raise translate(exc)
        result = []
        for row in rows:
            if isinstance(row, str):
                result.append({'id': row})
            elif isinstance(row, dict):
                result.append({'id': str(row.get('id') or row.get('model') or row.get('slug') or ''),
                               'name': str(row.get('displayName') or row.get('name') or ''),
                               'description': str(row.get('description') or '')[:300]})
        return [row for row in result if row['id']]

    # ------------------------------------------------------------------ one turn

    def first_message(self, request):
        """A session provider has no per-turn system field: fold it into the opening message.

        Claude Code is the exception; it takes a real `--append-system-prompt`, applied in
        `arguments` below. For the others the prompt is sent once, at the start of the native
        session, and the conversation records that this is what happened.
        """
        if request.system_prompt and not request.native_id and self.id != 'claude-code':
            return ('%s\n\n---\n\n%s' % (request.system_prompt, request.prompt), True)
        return (request.prompt, False)

    def chat(self, request, on_delta):
        transport = self.transport_for(request.transport)
        collected = {'native': request.native_id, 'usage': {}, 'thinking': 0}

        def sink(channel, value):
            if channel != 'event' or not isinstance(value, dict):
                return
            kind = value.get('type', '')
            text = value.get('text', '')
            metadata = value.get('metadata') or {}
            if kind == 'TextDelta' and text:
                on_delta(Delta.TEXT, text)
            elif kind == 'ThinkingDelta' and text:
                collected['thinking'] += len(text)
                on_delta(Delta.THINKING, text)
            elif kind == 'SessionStarted' and metadata.get('native_id'):
                collected['native'] = metadata['native_id']
            elif kind == 'UsageUpdated' and metadata.get('usage'):
                collected['usage'] = metadata['usage']
            elif kind in ('ToolStarted', 'ToolCompleted', 'CommandStarted', 'CommandCompleted',
                          'FileChanged', 'ApprovalDenied'):
                on_delta(Delta.TOOL, kind)

        instance = self._instance(transport, request, sink)
        prompt, folded = self.first_message(request)
        if self.id == 'claude-code' and request.system_prompt:
            instance.config['system_prompt'] = request.system_prompt
        else:
            instance.config.pop('system_prompt', None)
        started = time.monotonic()
        self._active = instance
        try:
            existing = instance.session
            reuse = (existing is not None and request.native_id
                     and existing.native_id == request.native_id
                     and (existing.model or '') == (request.model or '')
                     and transport == 'app-server')
            if not reuse:
                if request.native_id:
                    instance.resume_session(request.native_id, request.model)
                else:
                    instance.start_session(request.model)
                collected['native'] = instance.session.native_id or collected['native']
            on_delta(Delta.STATUS, 'Sending to %s (%s)' % (self.name, transport))
            text = instance.send(prompt)
        except ConnectorError as exc:
            # A broken session process must not be reused for the next turn.
            with self._lock:
                self._transports.pop(transport, None)
            try:
                instance.disconnect()
            except Exception:
                pass
            raise translate(exc)
        finally:
            self._active = None
        native = (instance.session.native_id if instance.session else '') or collected['native']
        return ChatResult(text, native_id=native or '', model=request.model,
                          usage=collected['usage'], transport=transport,
                          seconds=time.monotonic() - started,
                          systemPromptFolded=folded,
                          thinkingCharacters=collected['thinking'])

    def cancel(self):
        active = self._active
        if active is not None:
            active.cancel()

    def close(self):
        with self._lock:
            for instance in self._transports.values():
                try:
                    instance.disconnect()
                except Exception:
                    pass
            self._transports.clear()


class DeclaredProvider(Provider):
    """A connector present in the catalogue with no adapter: listed, reported as not implemented."""

    kind = SESSION
    transports = ()

    def __init__(self, provider_id, settings=None):
        super().__init__(settings)
        catalogue = descriptors()
        self.id = provider_id
        self.descriptor_data = catalogue.get(provider_id, {})
        self.name = NAMES.get(provider_id, self.descriptor_data.get('name', provider_id))
        self.documentation = ('Declared in the connector catalogue. No adapter is implemented '
                              'in this version, so it cannot run a turn.')

    def descriptor(self):
        value = super().descriptor()
        value.update(implemented=False,
                     declaredTransports=[t['id'] for t in self.descriptor_data.get('transports', [])])
        return value

    def detect(self):
        return {'id': self.id, 'name': self.name, 'kind': self.kind, 'available': False,
                'status': 'NotImplemented', 'transports': [],
                'detail': 'Declared in the connector catalogue; no adapter in this version.'}

    def chat(self, request, on_delta):
        raise CyToolError('Unsupported',
                          'Provider %s has no adapter in this version of the Tool.' % self.id)


# The vendored CLI adapter does not know about a system prompt flag. Claude Code has a real
# one, so it is added here rather than by editing the vendored library, which stays a copy of
# its upstream source.
def install_system_prompt_support():
    from ..vendor.cyai_connectors.cli import CliTransport
    if getattr(CliTransport, '_cydec_system_prompt', False):
        return
    original = CliTransport.arguments

    def arguments(self, prompt):
        command, input_text, env = original(self, prompt)
        system_prompt = self.config.get('system_prompt')
        if system_prompt and self.id == 'claude-code':
            # Appending keeps Claude Code's own operating instructions in place instead of
            # replacing them with a chat persona that removes its safety framing.
            command = command + ['--append-system-prompt', str(system_prompt)]
        return command, input_text, env

    CliTransport.arguments = arguments
    CliTransport._cydec_system_prompt = True


install_system_prompt_support()
