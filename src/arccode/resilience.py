"""Resilient provider completion: retry transient errors, fall back to a
usable alternative model.

Real deployments hit transient failures constantly: 429 rate limits, 5xx, and
network timeouts. A harness that ends the run on the first one is fragile. This
wraps a completion call with:
  1. exponential backoff retries for *transient* errors (honoring Retry-After
     when the SDK exposes it),
  2. a fallback to the next credential-usable model when the primary stays
     unavailable (e.g. a rate-limited provider), so the task still completes.

Non-transient errors (auth, bad request) are not retried; they surface fast.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass

# HTTP-ish transient signals we should retry.
_TRANSIENT_CODES = (408, 409, 425, 429, 500, 502, 503, 504)
_TRANSIENT_HINTS = (
    "rate_limit", "rate limit", "429", "overloaded", "timeout", "timed out",
    "temporarily", "503", "502", "504", "connection", "econnreset", "reset by peer",
)


def _status_code(err: Exception) -> int | None:
    for attr in ("status_code", "status", "http_status"):
        v = getattr(err, attr, None)
        if isinstance(v, int):
            return v
    resp = getattr(err, "response", None)
    if resp is not None:
        v = getattr(resp, "status_code", None)
        if isinstance(v, int):
            return v
    return None


def is_transient(err: Exception) -> bool:
    code = _status_code(err)
    if code in _TRANSIENT_CODES:
        return True
    if code is not None and code < 400:
        return False
    msg = str(err).lower()
    return any(h in msg for h in _TRANSIENT_HINTS)


def _retry_after(err: Exception) -> float | None:
    resp = getattr(err, "response", None)
    headers = getattr(resp, "headers", None)
    if headers:
        for key in ("retry-after", "Retry-After"):
            val = headers.get(key) if hasattr(headers, "get") else None
            if val:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return None
    return None


@dataclass
class RetryPolicy:
    max_attempts: int = 4        # attempts per model before giving up on it
    base_delay: float = 0.8      # seconds; grows exponentially
    max_delay: float = 20.0
    jitter: float = 0.3          # +/- fraction of the delay


def _sleep_for(policy: RetryPolicy, attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return min(retry_after, policy.max_delay)
    delay = min(policy.base_delay * (2 ** attempt), policy.max_delay)
    jitter = delay * policy.jitter
    return max(0.0, delay + random.uniform(-jitter, jitter))


def complete_resilient(*, providers_and_models, system, messages, tools, effort,
                       policy: RetryPolicy | None = None, on_event=None, on_text=None):
    """Try each (provider, model_spec) in order; retry transient errors per model.

    providers_and_models: iterable of (provider, model_spec) to try in order.
    on_event: optional callback(kind, detail) for verbose logging.
    on_text: optional callback(delta) to stream assistant text as it arrives.
    Returns (completion, used_model_spec).
    Raises the last non-transient error, or the last transient error if every
    candidate is exhausted.
    """
    policy = policy or RetryPolicy()
    last_err: Exception | None = None

    for provider, spec in providers_and_models:
        for attempt in range(policy.max_attempts):
            try:
                comp = provider.complete(
                    model=spec.id, system=system, messages=messages,
                    tools=tools, effort=effort, max_out=spec.max_out,
                    on_text=on_text)
                return comp, spec
            except Exception as e:
                last_err = e
                if not is_transient(e):
                    raise  # auth/bad-request: fail fast
                if attempt < policy.max_attempts - 1:
                    delay = _sleep_for(policy, attempt, _retry_after(e))
                    if on_event:
                        on_event("retry", f"{spec.key}: transient error, retry "
                                          f"{attempt + 1}/{policy.max_attempts} in {delay:.1f}s")
                    time.sleep(delay)
                else:
                    if on_event:
                        on_event("fallback", f"{spec.key} exhausted; trying next model")
    if last_err:
        raise last_err
    raise RuntimeError("no candidate models to try")
