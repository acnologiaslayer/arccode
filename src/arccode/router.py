"""Router: pick a model per task from complexity, cost, performance, intent.

Heuristic classifier first (free); an LLM classifier can be layered later.
Explicit overrides always win.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import MODELS, ROUTE_WEIGHTS, ModelSpec, resolve

# Intent -> capabilities the chosen model should have.
INTENT_NEEDS = {
    "bulk_read": {"cheap", "speed"},
    "implement": {"code", "tools"},
    "design": {"reasoning"},
    "debug": {"reasoning", "code"},
    "review": {"reasoning", "code"},
    "chat": {"speed"},
    "vision": {"vision"},
}

_TIER_CAP = {"frontier": 1.0, "mid": 0.8, "small": 0.5, "local": 0.4}
_TIER_LAT = {"frontier": 0.4, "mid": 0.7, "small": 0.9, "local": 0.6}


@dataclass
class RouteDecision:
    model: ModelSpec
    intent: str
    complexity: float
    reason: str


def classify(task: str) -> tuple[str, float]:
    t = task.lower()
    if any(w in t for w in ("image", "screenshot", "photo", "diagram of")):
        intent = "vision"
    elif any(w in t for w in ("bug", "error", "traceback", "fix ", "broken", "fails")):
        intent = "debug"
    elif any(w in t for w in ("architect", "design", "plan ", "trade-off", "scalab")):
        intent = "design"
    elif "review" in t:
        intent = "review"
    elif any(w in t for w in ("summarize", "read all", "digest", "extract from")):
        intent = "bulk_read"
    elif any(w in t for w in ("hi", "hello", "thanks")) and len(task) < 40:
        intent = "chat"
    else:
        intent = "implement"

    complexity = min(1.0,
                     len(task) / 1200
                     + 0.15 * t.count(" and ")
                     + (0.35 if any(w in t for w in
                        ("refactor", "distributed", "migrate", "concurren", "architecture")) else 0))
    return intent, round(complexity, 3)


def score(spec: ModelSpec, needs: set[str], complexity: float) -> float:
    cap_match = len(spec.strengths & needs) / max(1, len(needs))
    tier_fit = _TIER_CAP[spec.tier]
    # complex tasks reward higher tiers; simple tasks penalize overkill
    tier_term = tier_fit if complexity > 0.6 else 1 - abs(tier_fit - 0.6)
    capability = 0.5 * cap_match + 0.5 * tier_term
    cost = 1 - min(1.0, (spec.in_cost + spec.out_cost) / 90.0)
    latency = _TIER_LAT[spec.tier]
    w = ROUTE_WEIGHTS
    return w["capability"] * capability + w["cost"] * cost + w["latency"] * latency


def _usable_provider(provider: str) -> bool:
    """True if this provider can actually be called right now (key set or local up)."""
    try:
        from .credentials import resolve as resolve_cred
        secret, kind = resolve_cred(provider)
        if secret:
            return True
    except Exception:  # noqa: BLE001
        pass
    # Ollama (local) is usable when its service is detected as connected.
    try:
        from .services import connected_services
        return provider in connected_services()
    except Exception:  # noqa: BLE001
        return False


def route(task: str, *, force: str | None = None) -> RouteDecision:
    if force:
        spec = resolve(force)
        return RouteDecision(spec, "forced", 0.0, f"forced -> {spec.key}")
    intent, complexity = classify(task)
    needs = INTENT_NEEDS[intent]
    ranked = sorted(MODELS.values(), key=lambda s: score(s, needs, complexity), reverse=True)

    # Prefer models whose provider is actually usable right now (credential-aware
    # routing). This makes zero-config runs "just work" against connected free
    # services instead of failing on a higher-scoring but unauthenticated model.
    # Disabled in deterministic mode (ARCCODE_NO_AUTODETECT) so fitness ranking
    # can be reasoned about without regard to the local environment's keys.
    import os as _os
    if _os.environ.get("ARCCODE_NO_AUTODETECT"):
        best = ranked[0]
        reason = (f"intent={intent} complexity={complexity} needs={sorted(needs)} "
                  f"-> {best.key} ({best.id})")
        return RouteDecision(best, intent, complexity, reason)

    usable = [s for s in ranked if _usable_provider(s.provider)]
    pool = usable or ranked
    best = pool[0]
    gated = " (usable-only)" if usable and best is not ranked[0] else ""
    reason = (f"intent={intent} complexity={complexity} needs={sorted(needs)}{gated} "
              f"-> {best.key} ({best.id})")
    return RouteDecision(best, intent, complexity, reason)
