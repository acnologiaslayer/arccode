"""Free/paid AI service registry with auto-detection.

On startup arccode probes every known service and connects to whichever are
usable right now: local Ollama (no key), and any hosted provider whose API key
is present in the environment. Most listed hosted providers have a free tier.

Each service is OpenAI-Chat-Completions compatible (or has a shim), so one
adapter drives all of them by swapping base_url + key.

Design goals:
- Zero config to get value: if Ollama is running or any key is set, it works.
- Truthful: we only advertise a provider as connected if it is actually usable.
- Cheap detection: env-var check for keys, a short TCP/HTTP probe for Ollama.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx


@dataclass(frozen=True)
class SeedModel:
    """A known model offered by a service, with routing metadata."""
    id: str            # provider-local model name (no provider prefix)
    tier: str          # frontier | mid | small | local
    ctx: int
    strengths: frozenset[str]
    in_cost: float = 0.0   # most free tiers are $0 to the user
    out_cost: float = 0.0
    max_out: int = 4096


@dataclass(frozen=True)
class Service:
    name: str                      # provider id used in model ids, e.g. "groq"
    label: str                     # human label
    base_url: str | None           # OpenAI-compatible endpoint (None = native SDK)
    key_envs: tuple[str, ...]      # env vars that hold the API key (first found wins)
    free: bool                     # has a usable free tier
    signup: str                    # where to get a key
    seeds: tuple[SeedModel, ...] = ()   # static known models (used if no live list)
    dynamic: bool = False          # discover models live (e.g. Ollama)

    def api_key(self) -> str | None:
        for e in self.key_envs:
            v = os.environ.get(e)
            if v:
                return v
        return None


# ---------------------------------------------------------------------------
# The registry. Free-tier hosted providers + local Ollama, all OpenAI-compatible.
# ---------------------------------------------------------------------------

SERVICES: dict[str, Service] = {
    "ollama": Service(
        "ollama", "Ollama (local)", "http://localhost:11434/v1", ("OLLAMA_API_KEY",),
        free=True, signup="https://ollama.com (run `ollama serve`)",
        dynamic=True),  # models discovered live from /api/tags

    "groq": Service(
        "groq", "Groq", "https://api.groq.com/openai/v1", ("GROQ_API_KEY",),
        free=True, signup="https://console.groq.com/keys",
        seeds=(
            SeedModel("llama-3.3-70b-versatile", "mid", 128_000,
                      frozenset({"code", "tools", "reasoning", "speed"})),
            SeedModel("llama-3.1-8b-instant", "small", 128_000,
                      frozenset({"speed", "cheap", "tools"})),
            SeedModel("qwen-2.5-coder-32b", "mid", 128_000,
                      frozenset({"code", "tools", "speed"})),
        )),

    "gemini": Service(
        "gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai",
        ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        free=True, signup="https://aistudio.google.com/apikey",
        seeds=(
            SeedModel("gemini-2.0-flash", "mid", 1_000_000,
                      frozenset({"code", "tools", "reasoning", "speed", "vision"})),
            SeedModel("gemini-2.0-flash-lite", "small", 1_000_000,
                      frozenset({"speed", "cheap", "vision"})),
        )),

    "cerebras": Service(
        "cerebras", "Cerebras", "https://api.cerebras.ai/v1", ("CEREBRAS_API_KEY",),
        free=True, signup="https://cloud.cerebras.ai",
        seeds=(
            SeedModel("llama-3.3-70b", "mid", 128_000,
                      frozenset({"code", "tools", "reasoning", "speed"})),
            SeedModel("llama3.1-8b", "small", 128_000,
                      frozenset({"speed", "cheap", "tools"})),
        )),

    "mistral": Service(
        "mistral", "Mistral", "https://api.mistral.ai/v1", ("MISTRAL_API_KEY",),
        free=True, signup="https://console.mistral.ai/api-keys",
        seeds=(
            SeedModel("mistral-large-latest", "frontier", 128_000,
                      frozenset({"reasoning", "code", "tools"})),
            SeedModel("mistral-small-latest", "small", 128_000,
                      frozenset({"speed", "cheap", "tools", "code"})),
            SeedModel("codestral-latest", "mid", 256_000,
                      frozenset({"code", "tools"})),
        )),

    "openrouter": Service(
        "openrouter", "OpenRouter", "https://openrouter.ai/api/v1", ("OPENROUTER_API_KEY",),
        free=True, signup="https://openrouter.ai/keys",
        seeds=(
            SeedModel("meta-llama/llama-3.3-70b-instruct:free", "mid", 128_000,
                      frozenset({"code", "tools", "reasoning"})),
            SeedModel("google/gemini-2.0-flash-exp:free", "mid", 1_000_000,
                      frozenset({"code", "tools", "reasoning", "vision"})),
            SeedModel("qwen/qwen-2.5-coder-32b-instruct:free", "mid", 32_000,
                      frozenset({"code", "tools"})),
        )),

    "github": Service(
        "github", "GitHub Models", "https://models.inference.ai.azure.com",
        ("GITHUB_MODELS_TOKEN", "GITHUB_TOKEN"),
        free=True, signup="https://github.com/marketplace/models (use a PAT)",
        seeds=(
            SeedModel("gpt-4o", "frontier", 128_000,
                      frozenset({"reasoning", "code", "tools", "vision"})),
            SeedModel("gpt-4o-mini", "small", 128_000,
                      frozenset({"speed", "cheap", "tools"})),
        )),

    # Paid, kept for completeness; only connect if a key is present.
    "openai": Service(
        "openai", "OpenAI", None, ("OPENAI_API_KEY",),
        free=False, signup="https://platform.openai.com/api-keys",
        seeds=(
            SeedModel("gpt-5-mini", "small", 128_000,
                      frozenset({"speed", "cheap", "tools"}), 0.15, 0.60),
            SeedModel("gpt-5-nano", "small", 400_000,
                      frozenset({"speed", "cheap"}), 0.05, 0.20),
        )),
    "anthropic": Service(
        "anthropic", "Anthropic", None, ("ANTHROPIC_API_KEY",),
        free=False, signup="https://console.anthropic.com/settings/keys",
        seeds=(
            SeedModel("claude-sonnet-4-5", "mid", 200_000,
                      frozenset({"code", "tools", "reasoning"}), 3, 15),
            SeedModel("claude-opus-4-1", "frontier", 200_000,
                      frozenset({"reasoning", "code", "tools"}), 15, 75),
        )),
}


def _ollama_up(timeout: float = 1.0) -> list[str]:
    """Return locally installed Ollama model names, or [] if not reachable."""
    base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    root = base.removesuffix("/v1")  # /api/tags lives at root
    try:
        r = httpx.get(root.rstrip("/") + "/api/tags", timeout=timeout)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:  # noqa: BLE001
        return []


@dataclass
class Detected:
    service: Service
    connected: bool
    reason: str                 # why connected / why not
    live_models: list[str] = field(default_factory=list)


def detect(*, probe_ollama: bool = True) -> dict[str, Detected]:
    """Probe every service. A service is connected if usable right now."""
    out: dict[str, Detected] = {}
    for name, svc in SERVICES.items():
        if svc.dynamic and name == "ollama":
            models = _ollama_up() if probe_ollama else []
            if models:
                out[name] = Detected(svc, True, f"running with {len(models)} model(s)", models)
            else:
                out[name] = Detected(svc, False, "not running (start with `ollama serve`)")
            continue
        key = svc.api_key()
        if key:
            out[name] = Detected(svc, True, f"key found in {svc.key_envs[0]}")
        else:
            tier = "free" if svc.free else "paid"
            out[name] = Detected(svc, False, f"no key ({tier}); get one at {svc.signup}")
    return out


def connected_services(*, probe_ollama: bool = True) -> dict[str, Detected]:
    return {n: d for n, d in detect(probe_ollama=probe_ollama).items() if d.connected}
