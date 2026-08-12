"""Provider adapter tests that don't need a live API.

Covers the OpenAI-compat max_tokens -> max_completion_tokens fallback (newer
models reject max_tokens), and message serialization for the tool loop.
"""
import pytest

from arccode.providers.base import Message, ToolCall
from arccode.providers.openai_compat import OpenAICompatProvider, _msg, _wants_completion_tokens


class _FakeResp:
    class _Choice:
        class _Msg:
            content = "ok"
            tool_calls = None
        message = _Msg()
        finish_reason = "stop"
    choices = [_Choice()]
    class _Usage:
        prompt_tokens = 5
        completion_tokens = 2
    usage = _Usage()


class _FakeCompletions:
    def __init__(self, reject_max_tokens):
        self.reject = reject_max_tokens
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.reject and "max_tokens" in kwargs:
            raise Exception("Unsupported parameter: 'max_tokens' is not supported "
                            "with this model. Use 'max_completion_tokens' instead.")
        return _FakeResp()


class _FakeClient:
    def __init__(self, reject_max_tokens):
        self.chat = type("chat", (), {"completions": _FakeCompletions(reject_max_tokens)})()


def _provider_with(client):
    p = OpenAICompatProvider(provider="openai", api_key="sk-test")
    p._client = client  # bypass credential resolution
    return p


def test_wants_completion_tokens_detection():
    assert _wants_completion_tokens(Exception("use 'max_completion_tokens' instead"))
    assert _wants_completion_tokens(Exception("max_tokens is not supported"))
    assert not _wants_completion_tokens(Exception("some other 400 error"))


def test_max_tokens_path_used_when_supported():
    client = _FakeClient(reject_max_tokens=False)
    p = _provider_with(client)
    comp = p.complete(model="openai:gpt-4o", system="s",
                      messages=[Message("user", "hi")], tools=[], max_out=64)
    assert comp.text == "ok"
    calls = client.chat.completions.calls
    assert len(calls) == 1
    assert "max_tokens" in calls[0]


def test_falls_back_to_max_completion_tokens():
    client = _FakeClient(reject_max_tokens=True)
    p = _provider_with(client)
    comp = p.complete(model="openai:gpt-5-mini", system="s",
                      messages=[Message("user", "hi")], tools=[], max_out=64)
    assert comp.text == "ok"                       # recovered, no crash
    calls = client.chat.completions.calls
    assert len(calls) == 2                          # retried
    assert "max_tokens" in calls[0]                 # first attempt classic
    assert "max_completion_tokens" in calls[1]      # retry uses new param
    assert "max_tokens" not in calls[1]


def test_non_param_error_reraises():
    class _Boom:
        calls = []
        def create(self, **kwargs):
            self.calls.append(kwargs)
            raise Exception("500 internal server error")
    client = type("c", (), {"chat": type("ch", (), {"completions": _Boom()})()})()
    p = _provider_with(client)
    with pytest.raises(Exception, match="500"):
        p.complete(model="openai:gpt-4o", system="s",
                   messages=[Message("user", "hi")], tools=[], max_out=64)


def test_msg_serialization_tool_loop():
    # assistant tool call round-trips into OpenAI shape
    a = _msg(Message("assistant", "", [ToolCall("c1", "read_file", {"path": "x"})]))
    assert a["role"] == "assistant"
    assert a["tool_calls"][0]["function"]["name"] == "read_file"
    # tool result carries the id
    t = _msg(Message("tool", "file contents", tool_call_id="c1"))
    assert t == {"role": "tool", "tool_call_id": "c1", "content": "file contents"}
