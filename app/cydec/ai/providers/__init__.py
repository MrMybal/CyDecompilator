"""AI providers, vendored from CyTools_AIChat (same author) and trimmed to chat use.

Agent command lines (Codex, Claude Code, Antigravity, OpenCode) reuse a login the user
already performed; HTTP providers (OpenAI, OpenRouter, any OpenAI compatible server such
as LM Studio or vLLM, Anthropic, Ollama) take an API key or a local base URL.
"""
import concurrent.futures

from cytools_core import CyToolError

from .agentcli import DECLARED_ONLY, IMPLEMENTED, AgentCliProvider, DeclaredProvider
from .base import SESSION, STATELESS, ChatRequest, ChatResult, Delta, Provider
from .httpchat import (AnthropicProvider, CustomOpenAIProvider, OllamaProvider, OpenAIProvider,
                       OpenRouterProvider)

HTTP_PROVIDERS = (AnthropicProvider, OpenAIProvider, OpenRouterProvider, CustomOpenAIProvider,
                  OllamaProvider)

__all__ = ['Registry', 'ChatRequest', 'ChatResult', 'Delta', 'Provider', 'SESSION', 'STATELESS']


class Registry:
    def __init__(self, settings=None, workspace=None):
        self.settings = dict(settings or {})
        self.providers = {}
        agent_settings = {'workspace': str(workspace or '.'), **self.settings.get('agents', {})}
        for provider_id in IMPLEMENTED:
            try:
                self.providers[provider_id] = AgentCliProvider(provider_id, agent_settings)
            except CyToolError:
                self.providers[provider_id] = DeclaredProvider(provider_id)
        for factory in HTTP_PROVIDERS:
            instance = factory(self.settings.get(factory.id, {}))
            self.providers[instance.id] = instance

    def get(self, provider_id):
        provider = self.providers.get(str(provider_id))
        if provider is None:
            raise CyToolError('NotFound', 'Unknown AI provider: %s. Known: %s'
                              % (provider_id, ', '.join(sorted(self.providers))))
        return provider

    def descriptors(self):
        return [p.descriptor() for p in self.providers.values()]

    def _detect_one(self, key):
        try:
            return self.providers[key].detect()
        except CyToolError as exc:
            return {'id': key, 'name': self.providers[key].name, 'available': False,
                    'status': 'Error', 'detail': str(exc)}
        except Exception as exc:
            return {'id': key, 'name': self.providers[key].name, 'available': False,
                    'status': 'Error', 'detail': repr(exc)[:300]}

    def detect(self, provider_id=''):
        if provider_id:
            return [self._detect_one(self.get(provider_id).id)]
        keys = list(self.providers)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(keys) or 1)) as pool:
            return list(pool.map(self._detect_one, keys))

    def close(self):
        for provider in self.providers.values():
            try:
                provider.close()
            except Exception:
                pass
