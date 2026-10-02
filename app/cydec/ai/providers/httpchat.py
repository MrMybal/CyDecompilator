"""Providers reached over HTTP: OpenAI compatible endpoints, Anthropic and Ollama.

These are stateless. The Tool sends the system prompt and the stored transcript on every
turn, which means the conversation kept in `data/conversations` is literally the context the
model sees, and trimming it with `history_limit` really does change the reply.

One adapter covers every OpenAI compatible server because they all speak the same
`/chat/completions` shape: OpenAI itself, OpenRouter, LM Studio, vLLM, a bare llama.cpp
server, or any other endpoint the user points at. Anthropic and the native Ollama protocol
differ enough to deserve their own request builders rather than a translation layer that
would quietly drop fields.

The API key is read at call time from the credential store and placed in a header. It is
never a job parameter, never written to the conversation and never streamed as an event.
"""
import json
import time

from cytools_core import CyToolError

from .. import credentials
from .base import STATELESS, ChatResult, Delta, Provider

CONNECT_TIMEOUT = 20.0
# A long read timeout only bounds the gap *between* two streamed chunks, not the whole
# reply: a model that keeps producing tokens is never cut off by it.
READ_TIMEOUT = 300.0


def _httpx():
    try:
        import httpx
    except ImportError:  # pragma: no cover - declared in requirements.txt
        raise CyToolError('MissingDependency',
                          'The httpx package is required for HTTP providers.')
    return httpx


def _clean(value, limit=600):
    """Provider error bodies can echo a request header. Never surface one unfiltered."""
    text = str(value or '')
    for marker in ('sk-', 'Bearer ', 'api_key', 'x-api-key'):
        if marker in text:
            return 'The provider returned an error whose body was withheld because it may ' \
                   'contain a credential. Check the key and the endpoint.'
    return text[:limit]


def _fail(response):
    body = ''
    try:
        body = response.text
    except Exception:
        body = ''
    code = {401: 'AuthenticationRequired', 403: 'AccessDenied', 404: 'NotFound',
            429: 'RateLimited', 400: 'InvalidParameters'}.get(response.status_code, 'ProviderFailed')
    raise CyToolError(code, 'HTTP %d from the provider. %s'
                      % (response.status_code, _clean(body)))


class HttpProvider(Provider):
    kind = STATELESS
    supports_model_list = True
    requires_api_key = True
    default_base_url = ''
    key_provider = ''

    def base_url(self, request=None):
        settings = (request.settings if request is not None else {}) or {}
        value = str(settings.get('base_url') or self.settings.get('base_url')
                    or self.default_base_url or '').strip().rstrip('/')
        if not value:
            raise CyToolError('InvalidParameters',
                              'Set the base URL of the endpoint for provider %s.' % self.id)
        if not value.startswith(('http://', 'https://')):
            raise CyToolError('InvalidParameters', 'The base URL must start with http:// or https://')
        return value

    def api_key(self):
        return credentials.resolve(self.key_provider or self.id)

    def headers(self):
        key = self.api_key()
        if self.requires_api_key and not key:
            raise CyToolError('AuthenticationRequired',
                              'No API key is configured for %s. Add it in Providers, or export %s.'
                              % (self.name, credentials.ENVIRONMENT.get(self.key_provider or self.id,
                                                                        'the provider variable')))
        headers = {'Content-Type': 'application/json'}
        if key:
            headers['Authorization'] = 'Bearer ' + key
        return headers

    def client(self, request=None):
        httpx = _httpx()
        return httpx.Client(timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT))

    def detect(self):
        report = {'id': self.id, 'name': self.name, 'kind': self.kind,
                  'transports': list(self.transports),
                  'credential': credentials.status(self.key_provider or self.id)}
        try:
            url = self.base_url()
        except CyToolError as exc:
            return {**report, 'available': False, 'status': 'NotConfigured', 'detail': str(exc)}
        report['endpoint'] = url
        if self.requires_api_key and not self.api_key():
            return {**report, 'available': False, 'status': 'Authentication Required',
                    'detail': 'No API key configured for this provider.'}
        try:
            models = self.list_models()
        except CyToolError as exc:
            return {**report, 'available': False, 'status': 'Error', 'detail': str(exc)}
        return {**report, 'available': True, 'status': 'Connected', 'modelCount': len(models)}


class OpenAICompatibleProvider(HttpProvider):
    """`/chat/completions` with server sent events, the shape almost every endpoint speaks."""

    transports = ('chat-completions',)
    supports_lora = False
    documentation = ('Any server exposing the OpenAI /v1/chat/completions contract: OpenAI, '
                     'OpenRouter, LM Studio, vLLM, a llama.cpp server, or a private gateway.')

    def list_models(self, transport=''):
        httpx = _httpx()
        url = self.base_url() + '/models'
        headers = self.headers()
        with self.client() as client:
            try:
                response = client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                raise CyToolError('NetworkError',
                                  'Cannot reach %s: %s' % (url, _clean(exc, 200))) from exc
            if response.status_code >= 400:
                _fail(response)
            try:
                rows = response.json().get('data', [])
            except ValueError:
                raise CyToolError('ProtocolError', 'The model list was not JSON.')
        return [{'id': str(row.get('id', '')), 'name': str(row.get('id', '')),
                 'description': str(row.get('description') or row.get('owned_by') or '')[:300]}
                for row in rows if isinstance(row, dict) and row.get('id')]

    def body(self, request):
        payload = {'model': request.model, 'messages': request.payload(), 'stream': True}
        for key, field in (('temperature', 'temperature'), ('top_p', 'top_p'),
                           ('max_tokens', 'max_tokens'), ('seed', 'seed'),
                           ('presence_penalty', 'presence_penalty'),
                           ('frequency_penalty', 'frequency_penalty')):
            value = request.settings.get(key)
            if value is not None and value != '':
                payload[field] = value
        if payload.get('seed') in (-1, '-1'):
            payload.pop('seed')
        extra = request.settings.get('extra_body')
        if isinstance(extra, dict):
            payload.update(extra)
        return payload

    def chat(self, request, on_delta):
        if not request.model:
            raise CyToolError('InvalidParameters', 'Select or type a model id for %s.' % self.name)
        url = self.base_url(request) + '/chat/completions'
        started = time.monotonic()
        text = []
        usage = {}
        model = request.model
        on_delta(Delta.STATUS, 'Requesting %s' % url)
        httpx = _httpx()
        with self.client(request) as client:
            # httpx opens the connection when the context manager is entered, not when
            # stream() is called, so the whole `with` has to be inside the guard: a guard
            # around the call alone lets a refused connection escape as an unhandled exception.
            try:
                with client.stream('POST', url, headers=self.headers(),
                                   json=self.body(request)) as response:
                    if response.status_code >= 400:
                        response.read()
                        _fail(response)
                    for line in response.iter_lines():
                        request.check()
                        if not line or not line.startswith('data:'):
                            continue
                        chunk = line[5:].strip()
                        if chunk == '[DONE]':
                            break
                        try:
                            data = json.loads(chunk)
                        except ValueError:
                            raise CyToolError('ProtocolError',
                                              'Malformed stream chunk from the provider.')
                        if data.get('error'):
                            raise CyToolError('ProviderFailed', _clean(data['error']))
                        model = data.get('model') or model
                        if data.get('usage'):
                            usage = data['usage']
                        for choice in data.get('choices', []):
                            delta = choice.get('delta') or {}
                            piece = delta.get('content') or ''
                            reasoning = delta.get('reasoning_content') or delta.get('reasoning') or ''
                            if reasoning:
                                on_delta(Delta.THINKING, reasoning)
                            if piece:
                                text.append(piece)
                                on_delta(Delta.TEXT, piece)
            except httpx.HTTPError as exc:
                raise CyToolError('NetworkError',
                                  'Cannot reach %s: %s' % (url, _clean(exc, 200))) from exc
        joined = ''.join(text)
        if not joined.strip():
            raise CyToolError('EmptyResponse', 'The provider returned no text.')
        return ChatResult(joined, model=model, usage=usage, transport='chat-completions',
                          seconds=time.monotonic() - started, endpoint=url)


class OpenAIProvider(OpenAICompatibleProvider):
    id = 'openai'
    name = 'OpenAI API'
    default_base_url = 'https://api.openai.com/v1'
    documentation = 'The OpenAI platform API. Billed per request against your own API key.'


class OpenRouterProvider(OpenAICompatibleProvider):
    id = 'openrouter'
    name = 'OpenRouter'
    default_base_url = 'https://openrouter.ai/api/v1'
    documentation = 'A gateway in front of many providers, with one OpenRouter API key.'


class CustomOpenAIProvider(OpenAICompatibleProvider):
    id = 'openai-compatible'
    name = 'OpenAI-compatible endpoint'
    requires_api_key = False
    default_base_url = 'http://127.0.0.1:1234/v1'
    documentation = ('Point this at any OpenAI-compatible server: LM Studio, vLLM, a llama.cpp '
                     'server you started yourself, or a company gateway. A key is optional.')


class AnthropicProvider(HttpProvider):
    id = 'anthropic'
    name = 'Claude API'
    transports = ('messages',)
    default_base_url = 'https://api.anthropic.com/v1'
    key_provider = 'anthropic'
    documentation = ('The Anthropic Messages API, billed against your own key. To talk to '
                     'Claude with an existing subscription instead, use the Claude Code provider.')
    version_header = '2023-06-01'

    def headers(self):
        key = self.api_key()
        if not key:
            raise CyToolError('AuthenticationRequired',
                              'No API key is configured for the Claude API. Add it in Providers, '
                              'or export ANTHROPIC_API_KEY.')
        return {'Content-Type': 'application/json', 'x-api-key': key,
                'anthropic-version': self.version_header}

    def list_models(self, transport=''):
        httpx = _httpx()
        url = self.base_url() + '/models'
        headers = self.headers()
        with self.client() as client:
            try:
                response = client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                raise CyToolError('NetworkError',
                                  'Cannot reach %s: %s' % (url, _clean(exc, 200))) from exc
            if response.status_code >= 400:
                _fail(response)
            rows = response.json().get('data', [])
        return [{'id': str(row.get('id', '')), 'name': str(row.get('display_name') or row.get('id', '')),
                 'description': str(row.get('created_at') or '')[:300]}
                for row in rows if isinstance(row, dict) and row.get('id')]

    def body(self, request):
        # Anthropic keeps the system prompt out of the message list and requires max_tokens.
        payload = {'model': request.model, 'messages': request.payload(include_system=False),
                   'stream': True,
                   'max_tokens': int(request.settings.get('max_tokens') or 4096)}
        if request.system_prompt:
            payload['system'] = request.system_prompt
        for key in ('temperature', 'top_p', 'top_k'):
            value = request.settings.get(key)
            if value is not None and value != '':
                payload[key] = value
        return payload

    def chat(self, request, on_delta):
        if not request.model:
            raise CyToolError('InvalidParameters', 'Select or type a model id for %s.' % self.name)
        url = self.base_url(request) + '/messages'
        started = time.monotonic()
        text = []
        usage = {}
        on_delta(Delta.STATUS, 'Requesting %s' % url)
        httpx = _httpx()
        headers = self.headers()
        with self.client(request) as client:
            try:
                with client.stream('POST', url, headers=headers,
                                   json=self.body(request)) as response:
                    if response.status_code >= 400:
                        response.read()
                        _fail(response)
                    for line in response.iter_lines():
                        request.check()
                        if not line or not line.startswith('data:'):
                            continue
                        try:
                            data = json.loads(line[5:].strip())
                        except ValueError:
                            raise CyToolError('ProtocolError',
                                              'Malformed stream chunk from the provider.')
                        kind = data.get('type')
                        if kind == 'content_block_delta':
                            delta = data.get('delta') or {}
                            if delta.get('type') == 'text_delta' and delta.get('text'):
                                text.append(delta['text'])
                                on_delta(Delta.TEXT, delta['text'])
                            elif delta.get('type') == 'thinking_delta' and delta.get('thinking'):
                                on_delta(Delta.THINKING, delta['thinking'])
                        elif kind == 'message_delta' and data.get('usage'):
                            usage.update(data['usage'])
                        elif kind == 'message_start':
                            usage.update((data.get('message') or {}).get('usage') or {})
                        elif kind == 'error':
                            raise CyToolError('ProviderFailed', _clean(data.get('error')))
            except httpx.HTTPError as exc:
                raise CyToolError('NetworkError',
                                  'Cannot reach %s: %s' % (url, _clean(exc, 200))) from exc
        joined = ''.join(text)
        if not joined.strip():
            raise CyToolError('EmptyResponse', 'The provider returned no text.')
        return ChatResult(joined, model=request.model, usage=usage, transport='messages',
                          seconds=time.monotonic() - started, endpoint=url)


class OllamaProvider(HttpProvider):
    """Ollama's own newline-delimited protocol, plus its OpenAI compatible surface."""

    id = 'ollama'
    name = 'Ollama'
    transports = ('native', 'chat-completions')
    requires_api_key = False
    default_base_url = 'http://127.0.0.1:11434'
    documentation = ('A local Ollama server. `native` uses /api/chat and reports the models '
                     'actually pulled; `chat-completions` uses its OpenAI compatible surface.')

    def list_models(self, transport=''):
        httpx = _httpx()
        url = self.base_url() + '/api/tags'
        with self.client() as client:
            try:
                response = client.get(url, timeout=10.0)
            except httpx.HTTPError as exc:
                raise CyToolError('NetworkError',
                                  'Cannot reach the Ollama server at %s. Start it with '
                                  '`ollama serve`. (%s)'
                                  % (self.base_url(), _clean(exc, 160))) from exc
            if response.status_code >= 400:
                _fail(response)
            rows = response.json().get('models', [])
        return [{'id': str(row.get('model') or row.get('name', '')),
                 'name': str(row.get('name', '')),
                 'description': 'size %s bytes' % row.get('size', '?')}
                for row in rows if isinstance(row, dict) and (row.get('model') or row.get('name'))]

    def chat(self, request, on_delta):
        if self.transport_for(request.transport) == 'chat-completions':
            delegate = CustomOpenAIProvider({'base_url': self.base_url(request) + '/v1'})
            delegate.requires_api_key = False
            return delegate.chat(request, on_delta)
        if not request.model:
            raise CyToolError('InvalidParameters', 'Select a model pulled into Ollama.')
        url = self.base_url(request) + '/api/chat'
        options = {}
        for key, field in (('temperature', 'temperature'), ('top_p', 'top_p'), ('top_k', 'top_k'),
                           ('seed', 'seed'), ('repeat_penalty', 'repeat_penalty'),
                           ('max_tokens', 'num_predict'), ('context_tokens', 'num_ctx')):
            value = request.settings.get(key)
            if value is not None and value != '':
                options[field] = value
        payload = {'model': request.model, 'messages': request.payload(), 'stream': True}
        if options:
            payload['options'] = options
        started = time.monotonic()
        text = []
        usage = {}
        on_delta(Delta.STATUS, 'Requesting %s' % url)
        httpx = _httpx()
        with self.client(request) as client:
            try:
                with client.stream('POST', url, json=payload) as response:
                    if response.status_code >= 400:
                        response.read()
                        _fail(response)
                    for line in response.iter_lines():
                        request.check()
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except ValueError:
                            raise CyToolError('ProtocolError',
                                              'Malformed stream chunk from Ollama.')
                        if data.get('error'):
                            raise CyToolError('ProviderFailed', _clean(data['error']))
                        piece = (data.get('message') or {}).get('content') or ''
                        thinking = (data.get('message') or {}).get('thinking') or ''
                        if thinking:
                            on_delta(Delta.THINKING, thinking)
                        if piece:
                            text.append(piece)
                            on_delta(Delta.TEXT, piece)
                        if data.get('done'):
                            usage = {key: data[key] for key in
                                     ('prompt_eval_count', 'eval_count', 'total_duration',
                                      'load_duration', 'eval_duration') if key in data}
                            break
            except httpx.HTTPError as exc:
                raise CyToolError('NetworkError',
                                  'Cannot reach the Ollama server at %s. Start it with '
                                  '`ollama serve`. (%s)'
                                  % (self.base_url(request), _clean(exc, 160))) from exc
        joined = ''.join(text)
        if not joined.strip():
            raise CyToolError('EmptyResponse', 'Ollama returned no text.')
        return ChatResult(joined, model=request.model, usage=usage, transport='native',
                          seconds=time.monotonic() - started, endpoint=url)
