"""The contract every provider implements, and the shape of one chat turn.

A provider is either *stateless* or *session based*, and the difference is not cosmetic.
A stateless provider is sent the whole transcript on every turn, so the conversation stored
by this Tool is the context, and editing or truncating it changes what the model sees. A
session provider keeps the history itself; the Tool sends only the new message and resumes
with the native identifier it recorded, so trimming the local transcript changes the
display but not what the provider remembers. `kind` carries that difference to the
interface, to MCP and to the saved conversation instead of leaving it implicit.
"""
from cytools_core import CyToolError

STATELESS = 'stateless'
SESSION = 'session'


class Delta:
    """Channels a provider may stream. Only `text` is part of the reply that gets stored."""
    TEXT = 'text'
    THINKING = 'thinking'
    STATUS = 'status'
    TOOL = 'tool'


class ChatRequest:
    """Everything one turn needs, already validated by the Runtime against the manifest."""

    def __init__(self, *, prompt, messages=(), system_prompt='', model='', transport='',
                 settings=None, native_id='', cancellation=None, workspace=None):
        self.prompt = prompt
        self.messages = list(messages)
        self.system_prompt = system_prompt or ''
        self.model = model or ''
        self.transport = transport or ''
        self.settings = dict(settings or {})
        self.native_id = native_id or ''
        self.cancellation = cancellation
        self.workspace = workspace

    def check(self):
        if self.cancellation is not None:
            self.cancellation.check()

    def payload(self, include_system=True):
        """The OpenAI style message list: system prompt, prior turns, then the new message."""
        items = []
        if include_system and self.system_prompt:
            items.append({'role': 'system', 'content': self.system_prompt})
        items.extend(self.messages)
        items.append({'role': 'user', 'content': self.prompt})
        return items


class ChatResult(dict):
    def __init__(self, text, *, native_id='', model='', usage=None, transport='', seconds=0.0,
                 **extra):
        super().__init__(text=text, nativeId=native_id or '', model=model or '',
                         usage=usage or {}, transport=transport or '',
                         seconds=round(float(seconds), 3), **extra)


class Provider:
    """Base class. Subclasses never print to stdout: the CLI and MCP transports own it."""

    id = ''
    name = ''
    kind = STATELESS
    # Transport identifiers this provider can actually run, most capable first.
    transports = ()
    # Transports whose adapter exists but was never executed on any machine by this project.
    untested = ()
    supports_system_prompt = True
    supports_streaming = True
    supports_model_list = False
    supports_lora = False
    requires_api_key = False
    documentation = ''

    def __init__(self, settings=None):
        self.settings = dict(settings or {})

    # ------------------------------------------------------------------ description

    def descriptor(self):
        return {'id': self.id, 'name': self.name, 'kind': self.kind,
                'transports': list(self.transports),
                'defaultTransport': self.transports[0] if self.transports else '',
                'supportsSystemPrompt': self.supports_system_prompt,
                'supportsStreaming': self.supports_streaming,
                'supportsModelList': self.supports_model_list,
                'supportsLora': self.supports_lora,
                'requiresApiKey': self.requires_api_key,
                'documentation': self.documentation}

    def transport_for(self, transport):
        if not transport:
            if not self.transports:
                raise CyToolError('Unsupported', 'Provider %s has no usable transport.' % self.id)
            return self.transports[0]
        if transport not in self.transports:
            raise CyToolError('InvalidParameters',
                              'Transport %s is not available for %s. Available: %s'
                              % (transport, self.id, ', '.join(self.transports) or 'none'))
        return transport

    # ------------------------------------------------------------------ behaviour

    def detect(self):
        """Report availability without sending anything to the provider."""
        raise NotImplementedError

    def list_models(self, transport=''):
        raise CyToolError('Unsupported',
                          'Provider %s does not publish a model catalogue; type a model id.'
                          % self.id)

    def chat(self, request, on_delta):
        raise NotImplementedError

    def cancel(self):
        """Best effort interruption of the turn in flight. Resources are freed by `chat`."""

    def close(self):
        """Release anything held between turns. Called when the Tool shuts down."""
