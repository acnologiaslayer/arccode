"""Model catalog, pricing, and routing weights.

Single source of truth the router reads. Costs are USD per 1M tokens.
Edit this file (or point ARCCODE_CONFIG at a YAML override) to add models.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml


@dataclass(frozen=True)
class ModelSpec:
    key: str  # short catalog key, e.g. "workhorse"
    id: str  # provider-qualified id, e.g. "anthropic:claude-sonnet-4-5"
    provider: str  # anthropic | openai | ollama | openrouter
    tier: str  # frontier | mid | small | local
    in_cost: float  # $ / 1M input tokens
    out_cost: float  # $ / 1M output tokens
    ctx: int  # context window
    strengths: frozenset[str] = field(default_factory=frozenset)
    max_out: int = 4096


# Default catalog. Swap ids for whatever you actually have access to.
DEFAULT_MODELS: dict[str, ModelSpec] = {
    "frontier-reason": ModelSpec(
        "frontier-reason", "anthropic:claude-opus-4-1", "anthropic", "frontier",
        15, 75, 200_000, frozenset({"reasoning", "code", "tools"})),
    "workhorse": ModelSpec(
        "workhorse", "anthropic:claude-sonnet-4-5", "anthropic", "mid",
        3, 15, 200_000, frozenset({"code", "tools", "reasoning"})),
    "fast-cheap": ModelSpec(
        "fast-cheap", "openai:gpt-5-mini", "openai", "small",
        0.15, 0.60, 128_000, frozenset({"speed", "cheap", "tools"})),
    "bulk-read": ModelSpec(
        "bulk-read", "openai:gpt-5-nano", "openai", "small",
        0.05, 0.20, 400_000, frozenset({"speed", "cheap"})),
    "local": ModelSpec(
        "local", "ollama:qwen2.5-coder", "ollama", "local",
        0, 0, 32_000, frozenset({"code", "cheap", "local"})),
}

# How much each factor matters when scoring a model for a task.
ROUTE_WEIGHTS = {"capability": 0.45, "cost": 0.30, "latency": 0.25}

# OAuth provider endpoints. client_id is intentionally blank by default: OAuth
# clients are issued by each provider, so users set their own via
# ~/.arccode/oauth.json or ARCCODE_<PROVIDER>_CLIENT_ID. These are the standard
# public endpoints; override token/auth URLs there too if a provider differs.
OAUTH_PROVIDERS: dict[str, dict] = {
    "openai": {
        "auth_url": "https://auth.openai.com/authorize",
        "token_url": "https://auth.openai.com/oauth/token",
        "client_id": "",
        "scopes": ["openid", "profile", "email", "offline_access"],
    },
    "anthropic": {
        "auth_url": "https://claude.ai/oauth/authorize",
        "token_url": "https://claude.ai/oauth/token",
        "client_id": "",
        "scopes": ["org:create_api_key", "user:profile", "user:inference"],
    },
    # Generic examples for OIDC providers that support device flow:
    "github": {
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "device_url": "https://github.com/login/device/code",
        "client_id": "",
        "scopes": ["read:user"],
    },
}


def _catalog_key(provider: str, model_id: str) -> str:
    """A short, stable catalog key for an auto-discovered model."""
    slug = model_id.split("/")[-1].replace(":free", "").replace(":", "-")
    return f"{provider}/{slug}"


_EMBED_HINTS = ("embed", "nomic-embed", "bge-", "gte-", "e5-", "all-minilm")


def _is_embedding_model(name: str) -> bool:
    n = name.lower()
    return any(h in n for h in _EMBED_HINTS)


def _models_from_services() -> dict[str, ModelSpec]:
    """Build catalog entries from every currently-connected service.

    Zero-config power: if Ollama is running or any provider key is set, those
    models appear in the catalog automatically. Disable with ARCCODE_NO_AUTODETECT.
    """
    if os.environ.get("ARCCODE_NO_AUTODETECT"):
        return {}
    try:
        from .services import connected_services
    except Exception:  # noqa: BLE001
        return {}

    models: dict[str, ModelSpec] = {}
    try:
        detected = connected_services()
    except Exception:  # noqa: BLE001
        return {}

    for name, det in detected.items():
        svc = det.service
        if svc.dynamic and det.live_models:
            for m in det.live_models:
                if _is_embedding_model(m):
                    continue  # embedding models can't chat; skip
                key = _catalog_key(name, m)
                models[key] = ModelSpec(
                    key, f"{name}:{m}", name, "local", 0.0, 0.0, 32_000,
                    frozenset({"local", "cheap", "code"}))
        for s in svc.seeds:
            key = _catalog_key(name, s.id)
            models[key] = ModelSpec(
                key, f"{name}:{s.id}", name, s.tier, s.in_cost, s.out_cost,
                s.ctx, s.strengths, s.max_out)
    return models


def load_models() -> dict[str, ModelSpec]:
    """Return the catalog: auto-detected services, then YAML override on top.

    Auto-detected free/local models are the base. A YAML file at ARCCODE_CONFIG
    adds or overrides entries and always wins. If nothing is detected and no
    override exists, fall back to the static DEFAULT_MODELS so the catalog is
    never empty.
    """
    models = _models_from_services()
    if not models:
        models = dict(DEFAULT_MODELS)

    path = os.environ.get("ARCCODE_CONFIG")
    if path and os.path.exists(path):
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        for key, m in (data.get("models") or {}).items():
            models[key] = ModelSpec(
                key, m["id"], m["provider"], m.get("tier", "mid"),
                float(m.get("in_cost", 0)), float(m.get("out_cost", 0)),
                int(m.get("ctx", 128_000)),
                frozenset(m.get("strengths", [])), int(m.get("max_out", 4096)))
    return models


MODELS = load_models()
MODELS_BY_ID = {m.id: m for m in MODELS.values()}


def resolve(key_or_id: str) -> ModelSpec:
    """Accept either a catalog key or a full provider-qualified id.

    Canonical tier keys from DEFAULT_MODELS (workhorse, frontier-reason, ...)
    always resolve, even when the live catalog is built from detected services,
    so pinned aliases and tests stay stable.
    """
    if key_or_id in MODELS:
        return MODELS[key_or_id]
    if key_or_id in MODELS_BY_ID:
        return MODELS_BY_ID[key_or_id]
    if key_or_id in DEFAULT_MODELS:
        return DEFAULT_MODELS[key_or_id]
    _by_default_id = {m.id: m for m in DEFAULT_MODELS.values()}
    if key_or_id in _by_default_id:
        return _by_default_id[key_or_id]
    raise KeyError(f"unknown model: {key_or_id!r} (not a catalog key or known id)")
