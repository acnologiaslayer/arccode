"""Integration tests exercising the REAL agent loop, tools, spawn, and hooks.

Only the LLM is substituted with a scripted FakeProvider. Everything else -
the ReAct loop, tool schemas, tool execution, side effects, orchestrator spawn,
hook firing, usage accounting - is real arccode code with real effects on disk.
"""
import pathlib

import pytest

import arccode.providers as providers
from arccode.providers.base import Completion, ToolCall
from arccode.agents import Agent, AgentSpec
from arccode.orchestrator import Orchestrator
from arccode.tools import Ctx
from arccode.hooks import HookManager

PKG = pathlib.Path(__file__).resolve().parent.parent / "src" / "arccode"


class FakeProvider:
    """Returns a scripted sequence of completions, one per turn."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def complete(self, *, model, system, messages, tools, effort="medium", max_out=4096):
        self.calls.append({"model": model, "system": system,
                           "n_messages": len(messages), "tool_names": [t["name"] for t in tools]})
        return self.script.pop(0)


@pytest.fixture
def patch_provider(monkeypatch):
    def _install(script):
        fake = FakeProvider(script)
        monkeypatch.setattr(providers, "get_provider", lambda model_id: fake)
        # runtime imports get_provider by name, patch there too
        import arccode.agents.runtime as rt
        monkeypatch.setattr(rt, "get_provider", lambda model_id: fake)
        return fake
    return _install


def _ctx(tmp_path):
    return Ctx(cwd=str(tmp_path), agents_dir=str(PKG / "agents" / "registry"),
               skills_dir=str(PKG / "skills" / "registry"), yes=True)


def test_real_loop_executes_tool_and_writes_file(patch_provider, tmp_path):
    """The loop must actually call write_file and produce a real file."""
    target = tmp_path / "out.txt"
    fake = patch_provider([
        Completion("", [ToolCall("c1", "write_file",
                   {"path": str(target), "content": "hello-arccode"})],
                   {"in": 10, "out": 5}, "tool_use"),
        Completion("done: wrote the file", [], {"in": 8, "out": 4}, "stop"),
    ])
    spec = AgentSpec("t", "system", model="workhorse", tools=["write_file", "read_file"])
    ctx = _ctx(tmp_path)
    result = Agent(spec, ctx).run("write the file")

    assert target.read_text() == "hello-arccode"        # real side effect
    assert "done" in result                              # final assistant text
    assert len(fake.calls) == 2                          # looped: tool turn + final
    assert "write_file" in fake.calls[0]["tool_names"]   # schema was sent
    assert ctx.usage["in"] == 18 and ctx.usage["out"] == 9  # usage accounted both turns


def test_unknown_tool_is_reported_not_crashed(patch_provider, tmp_path):
    fake = patch_provider([
        Completion("", [ToolCall("c1", "does_not_exist", {})], {"in": 1, "out": 1}, "tool_use"),
        Completion("handled", [], {"in": 1, "out": 1}, "stop"),
    ])
    spec = AgentSpec("t", "s", model="workhorse", tools=["read_file"])
    result = Agent(spec, _ctx(tmp_path)).run("go")
    # the tool-result fed back must contain the error, and loop continues to finish
    assert result == "handled"


def test_tool_exception_is_caught(patch_provider, tmp_path):
    fake = patch_provider([
        Completion("", [ToolCall("c1", "read_file", {"path": str(tmp_path / "nope.txt")})],
                   {"in": 1, "out": 1}, "tool_use"),
        Completion("recovered", [], {"in": 1, "out": 1}, "stop"),
    ])
    spec = AgentSpec("t", "s", model="workhorse", tools=["read_file"])
    result = Agent(spec, _ctx(tmp_path)).run("read missing")
    assert result == "recovered"  # exception surfaced to model, not raised


def test_provider_error_returns_gracefully(monkeypatch, tmp_path):
    class Boom:
        def complete(self, **kw):
            raise RuntimeError("410 Gone: model retired")
    import arccode.agents.runtime as rt
    monkeypatch.setattr(rt, "get_provider", lambda m: Boom())
    spec = AgentSpec("t", "s", model="workhorse")
    result = Agent(spec, _ctx(tmp_path)).run("go")
    assert result.startswith("ERROR: provider call failed")
    assert "410 Gone" in result


def test_real_spawn_via_orchestrator(patch_provider, tmp_path):
    """spawn_agent tool must route through the real Orchestrator to a real sub-agent."""
    child_file = tmp_path / "child.txt"
    # Completions are consumed in true global turn order from one shared queue:
    #   1. coordinator turn 1 -> spawn_agent (control passes to child)
    #   2. child turn 1 -> write_file
    #   3. child turn 2 -> report "child done"
    #   4. coordinator turn 2 -> "coordinator done"
    fake = patch_provider([
        Completion("", [ToolCall("s1", "spawn_agent",
                   {"agent": "implementer", "task": "make child file"})],
                   {"in": 2, "out": 2}, "tool_use"),
        Completion("", [ToolCall("w1", "write_file",
                   {"path": str(child_file), "content": "from-child"})],
                   {"in": 2, "out": 2}, "tool_use"),
        Completion("child done", [], {"in": 2, "out": 2}, "stop"),
        Completion("coordinator done", [], {"in": 2, "out": 2}, "stop"),
    ])
    ctx = _ctx(tmp_path)
    orch = Orchestrator(str(PKG / "agents" / "registry"), ctx)
    ctx.orchestrator = orch
    result = orch.spawn("coordinator", "delegate to implementer", parent_ctx=ctx)

    assert child_file.read_text() == "from-child"   # sub-agent really ran and wrote
    assert "coordinator done" in result
    assert len(fake.calls) == 4                      # both agents looped


def test_real_hook_blocks_tool(patch_provider, tmp_path, monkeypatch):
    """A PreToolUse hook returning non-zero must block the tool in the real loop."""
    blocked_target = tmp_path / "blocked.txt"
    fake = patch_provider([
        Completion("", [ToolCall("c1", "write_file",
                   {"path": str(blocked_target), "content": "should-not-exist"})],
                   {"in": 1, "out": 1}, "tool_use"),
        Completion("acknowledged block", [], {"in": 1, "out": 1}, "stop"),
    ])
    hm = HookManager()
    hm.hooks = {"PreToolUse": [{"match": "write_file", "command": "exit 2"}]}
    ctx = _ctx(tmp_path)
    ctx.hooks = hm
    spec = AgentSpec("t", "s", model="workhorse", tools=["write_file"])
    result = Agent(spec, ctx).run("try to write")

    assert not blocked_target.exists()   # hook prevented the side effect
    assert result == "acknowledged block"
