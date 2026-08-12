"""Provider factory: map a provider-qualified model id to an adapter instance."""
from __future__ import annotations

from .anthropic import AnthropicProvider
from .base import Completion, Message, Provider, ToolCall
from .openai_compat import OpenAICompatProvider

_CACHE: dict[str, Provider] = {}


def get_provider(model_id: str) -> Provider:
    """model_id is provider-qualified, e.g. 'anthropic:claude-...' or 'groq:...'.

    Anthropic uses its native SDK; everything else (openai, ollama, groq,
    gemini, cerebras, mistral, openrouter, github, ...) is OpenAI-compatible and
    driven by one adapter that resolves base_url + key from the service registry.
    """
    provider = model_id.split(":", 1)[0] if ":" in model_id else "openai"
    if provider in _CACHE:
        return _CACHE[provider]
    if provider == "anthropic":
        p: Provider = AnthropicProvider()
    else:
        p = OpenAICompatProvider(provider=provider)
    _CACHE[provider] = p
    return p


__all__ = ["Completion", "Message", "Provider", "ToolCall", "get_provider"]
