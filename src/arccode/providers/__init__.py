"""Provider factory: map a provider-qualified model id to an adapter instance."""
from __future__ import annotations

from .anthropic import AnthropicProvider
from .base import Completion, Message, Provider, ToolCall
from .openai_compat import OpenAICompatProvider

_CACHE: dict[str, Provider] = {}


def get_provider(model_id: str) -> Provider:
    """model_id is provider-qualified, e.g. 'anthropic:claude-...' or 'ollama:...'."""
    provider = model_id.split(":", 1)[0] if ":" in model_id else "openai"
    if provider in _CACHE:
        return _CACHE[provider]
    if provider == "anthropic":
        p: Provider = AnthropicProvider()
    elif provider in ("openai", "ollama", "openrouter"):
        p = OpenAICompatProvider(provider=provider)
    else:
        raise ValueError(f"unknown provider: {provider!r}")
    _CACHE[provider] = p
    return p


__all__ = ["get_provider", "Provider", "Message", "ToolCall", "Completion"]
