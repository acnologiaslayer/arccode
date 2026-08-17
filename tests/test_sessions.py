"""Tests for resumable sessions: real serialization, save/load, and a real
App.run session-backed loop (LLM stubbed) that persists and resumes history.
"""


import arccode.agents.runtime as rt
from arccode.providers.base import Completion, Message, ToolCall
from arccode.session import Session, _dict_to_msg, _msg_to_dict, list_sessions


class FakeProvider:
    def __init__(self, script):
        self.script = list(script)

    def complete(self, *, model, system, messages, tools, effort="medium", max_out=4096, on_text=None):
        return self.script.pop(0)


def test_message_roundtrip_serialization():
    m = Message("assistant", "hi", [ToolCall("c1", "write_file", {"path": "x"})], None)
    d = _msg_to_dict(m)
    back = _dict_to_msg(d)
    assert back.role == "assistant" and back.content == "hi"
    assert back.tool_calls[0].name == "write_file"
    assert back.tool_calls[0].args == {"path": "x"}


def test_session_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr("arccode.session.pathlib.Path.home", lambda: tmp_path)
    s = Session.create("coordinator")
    s.messages = [Message("user", "hello"), Message("assistant", "hi there")]
    s.usage = {"in": 5, "out": 3, "usd": 0.01}
    s.save()
    assert s.path.exists()
    loaded = Session.load(s.id)
    assert loaded.agent == "coordinator"
    assert [m.content for m in loaded.messages] == ["hello", "hi there"]
    assert loaded.usage["in"] == 5
    ids = [row["id"] for row in list_sessions()]
    assert s.id in ids


def test_app_run_persists_and_resumes(tmp_path, monkeypatch):
    # isolate the sessions dir under tmp
    monkeypatch.setattr("arccode.session.pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    from arccode.app import App

    # First turn: assistant answers plainly (no tools).
    fake1 = FakeProvider([Completion("first answer", [], {"in": 4, "out": 2}, "stop")])
    monkeypatch.setattr(rt, "get_provider", lambda m: fake1)

    a = App(cwd=str(tmp_path), yes=True, enable_mcp=False)
    s = Session.create("coordinator")
    r1 = a.run("remember the number 42", agent="coordinator", model="workhorse", session=s)
    assert r1 == "first answer"
    sid = s.id

    # history now has: user, assistant  (2 messages) and is on disk
    reloaded = Session.load(sid)
    assert len(reloaded.messages) == 2
    assert reloaded.messages[0].content == "remember the number 42"

    # Second turn resumes: the prior history must be passed back to the provider.
    seen = {}

    class Capture:
        def complete(self, *, model, system, messages, tools, effort="medium", max_out=4096, on_text=None):
            seen["n_in"] = len(messages)
            return Completion("second answer", [], {"in": 3, "out": 1}, "stop")

    monkeypatch.setattr(rt, "get_provider", lambda m: Capture())
    a2 = App(cwd=str(tmp_path), yes=True, enable_mcp=False)
    r2 = a2.run("what number?", agent="coordinator", model="workhorse", session=reloaded)
    assert r2 == "second answer"
    # provider saw prior 2 messages + the new user turn = 3 before responding
    assert seen["n_in"] == 3
    # persisted history grew to 4 (u,a,u,a)
    assert len(Session.load(sid).messages) == 4
