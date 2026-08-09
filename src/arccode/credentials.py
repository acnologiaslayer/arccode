"""Resolve provider credentials: static API key first, then OAuth bearer token.

Central place both provider adapters call so auth logic lives in one spot.
"""
from __future__ import annotations

import os

_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": "OLLAMA_API_KEY",
}


def api_key(provider: str) -> str | None:
    return os.environ.get(_KEY_ENV.get(provider, ""))


def bearer_token(provider: str) -> str | None:
    """Return an OAuth access token for the provider, if the user logged in."""
    try:
        from .auth import get_access_token
        return get_access_token(provider)
    except Exception:  # noqa: BLE001
        return None


def resolve(provider: str) -> tuple[str | None, str]:
    """Return (secret, kind) where kind is 'api_key' or 'oauth' or 'none'.

    API key takes precedence (explicit override), then OAuth bearer token.
    """
    key = api_key(provider)
    if key:
        return key, "api_key"
    tok = bearer_token(provider)
    if tok:
        return tok, "oauth"
    return None, "none"
