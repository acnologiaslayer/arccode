"""Tests for resilient completion: retry transient errors, fall back to another
model, fail fast on non-transient errors. No network, all synthetic providers.
"""
import time

import pytest

from arccode import resilience
from arccode.resilience import RetryPolicy, complete_resilient, is_transient
from arccode.providers.base import Completion


class _Err(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status_code = status


class _Model:
    def __init__(self, key):
        self.key = key
        self.id = f"prov:{key}"
        self.max_out = 64


class _Provider:
    """Fails `fail_times` with a transient error, then returns a completion.
    If `fatal` is set, raises a non-transient error instead."""
    def __init__(self, fail_times=0, fatal=False, text="ok"):
        self.fail_times = fail_times
        self.fatal = fatal
        self.text = text
        self.calls = 0

    def complete(self, **kw):
        self.calls += 1
        if self.fatal:
            raise _Err("401 invalid api key", status=401)
        if self.calls <= self.fail_times:
            raise _Err("429 rate_limit_error", status=429)
        return Completion(self.text, [], {"in": 1, "out": 1}, "stop")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(resilience.time, "sleep", lambda s: None)


def test_is_transient_classification():
    assert is_transient(_Err("429 rate_limit", 429))
    assert is_transient(_Err("503 overloaded", 503))
    assert is_transient(_Err("connection timed out"))
    assert not is_transient(_Err("401 unauthorized", 401))
    assert not is_transient(_Err("400 bad request", 400))


def test_retry_then_succeed_same_model():
    p = _Provider(fail_times=2, text="recovered")
    m = _Model("primary")
    comp, used = complete_resilient(
        providers_and_models=[(p, m)], system="s", messages=[], tools=[],
        effort="low", policy=RetryPolicy(max_attempts=4))
    assert comp.text == "recovered"
    assert used.key == "primary"
    assert p.calls == 3  # 2 failures + 1 success


def test_falls_back_to_next_model_when_primary_exhausted():
    primary = _Provider(fail_times=99)   # always 429
    backup = _Provider(fail_times=0, text="from-backup")
    events = []
    comp, used = complete_resilient(
        providers_and_models=[(primary, _Model("primary")), (backup, _Model("backup"))],
        system="s", messages=[], tools=[], effort="low",
        policy=RetryPolicy(max_attempts=3),
        on_event=lambda k, d: events.append((k, d)))
    assert comp.text == "from-backup"
    assert used.key == "backup"
    assert primary.calls == 3          # exhausted its attempts
    assert any(k == "fallback" for k, _ in events)


def test_non_transient_fails_fast_no_retry():
    p = _Provider(fatal=True)
    with pytest.raises(_Err):
        complete_resilient(
            providers_and_models=[(p, _Model("primary"))],
            system="s", messages=[], tools=[], effort="low",
            policy=RetryPolicy(max_attempts=4))
    assert p.calls == 1  # no retries on auth error


def test_retry_after_header_respected(monkeypatch):
    class _Resp:
        headers = {"retry-after": "2"}
    class _E(Exception):
        status_code = 429
        response = _Resp()
    captured = {}
    monkeypatch.setattr(resilience.time, "sleep", lambda s: captured.setdefault("slept", s))

    class P:
        def __init__(self): self.calls = 0
        def complete(self, **kw):
            self.calls += 1
            if self.calls == 1:
                raise _E()
            return Completion("ok", [], {"in": 1, "out": 1}, "stop")
    comp, _ = complete_resilient(
        providers_and_models=[(P(), _Model("m"))], system="s", messages=[],
        tools=[], effort="low", policy=RetryPolicy(max_attempts=3))
    assert comp.text == "ok"
    assert captured["slept"] == 2.0   # honored Retry-After


def test_friendly_error_messages():
    from arccode.agents.runtime import _friendly_error
    class E(Exception):
        status_code = 429
    assert "Rate limited" in _friendly_error("openai:gpt-4o", E(), "429 rate_limit")
    assert "Authentication failed" in _friendly_error("openai:gpt-4o", Exception("401 unauthorized"), "401")
    assert "Network problem" in _friendly_error("openai:gpt-4o", Exception("connection timed out"), "timeout")
    assert "arccode doctor" in _friendly_error("openai:gpt-4o", Exception("weird"), "weird 500")
