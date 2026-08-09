"""Tests for subsystems not covered elsewhere: MCP roundtrip, memory,
slash commands, meta-tools (build/import), and the remaining tools.
These exercise real code with real side effects (a real subprocess for MCP).
"""
import json
import pathlib
import sys

import pytest

from arccode.tools import REGISTRY, Ctx
from arccode.memory import MemoryStore
from arccode.hooks import SlashCommands
from arccode.skills import SkillRegistry

PKG = pathlib.Path(__file__).resolve().parent.parent / "src" / "arccode"
STUB = pathlib.Path(__file__).resolve().parent / "mcp_stub.py"


def _ctx(tmp_path, **kw):
    return Ctx(cwd=str(tmp_path), agents_dir=str(tmp_path / "agents"),
               skills_dir=str(tmp_path / "skills"), yes=True, **kw)


# ---- MCP: real subprocess handshake + tools/list + tools/call ----

def test_mcp_client_roundtrip():
    from arccode.mcp import MCPClient
    client = MCPClient("stub", [sys.executable, str(STUB)])
    client.start()
    try:
        assert any(t["name"] == "echo" for t in client.tools)
        out = client.call_tool("echo", {"text": "ping"})
        assert out == "echo: ping"
    finally:
        client.stop()


def test_mcp_tools_register_into_registry():
    from arccode.mcp import MCPClient, register_mcp_tools
    client = MCPClient("stub", [sys.executable, str(STUB)])
    client.start()
    try:
        register_mcp_tools({"stub": client})
        assert "mcp__stub__echo" in REGISTRY
        result = REGISTRY["mcp__stub__echo"].handler({"text": "hi"}, None)
        assert result == "echo: hi"
    finally:
        client.stop()


# ---- Memory: persistence across instances ----

def test_memory_persists_and_searches(tmp_path):
    path = tmp_path / "mem.jsonl"
    m = MemoryStore(str(path))
    mid = m.remember("user prefers tabs over spaces", "preference", ["style"])
    assert mid
    # new instance reads the same file back
    m2 = MemoryStore(str(path))
    hits = m2.search("tabs")
    assert hits and "tabs" in hits[0]["content"]
    assert hits[0]["category"] == "preference"


def test_memory_tools_via_ctx(tmp_path):
    m = MemoryStore(str(tmp_path / "mem.jsonl"))
    ctx = _ctx(tmp_path, memory=m)
    REGISTRY["memory_remember"].handler(
        {"content": "deploys happen on fridays", "category": "fact"}, ctx)
    out = REGISTRY["memory_search"].handler({"query": "fridays"}, ctx)
    assert "fridays" in out


# ---- Slash commands ----

def test_slash_command_expand(tmp_path, monkeypatch):
    cmd_dir = tmp_path / ".arccode" / "commands"
    cmd_dir.mkdir(parents=True)
    (cmd_dir / "review.md").write_text("Please review $ARGUMENTS carefully.")
    monkeypatch.chdir(tmp_path)
    sc = SlashCommands()
    assert "review" in sc.names()
    assert sc.expand("/review the auth module") == "Please review the auth module carefully."
    assert sc.expand("not a command") == "not a command"


# ---- Meta-tools: build_agent, build_skill, import_skill ----

def test_build_skill_then_registry_sees_it(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    reg = SkillRegistry(str(skills_dir))
    ctx = _ctx(tmp_path, skills=reg)
    ctx.skills_dir = str(skills_dir)
    REGISTRY["build_skill"].handler(
        {"name": "haiku", "description": "Write haikus.", "body": "Three lines, 5-7-5."}, ctx)
    assert (skills_dir / "haiku" / "SKILL.md").exists()
    assert "haiku" in reg.skills  # reload happened
    assert "5-7-5" in reg.load("haiku")


def test_build_agent_writes_file(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    ctx = _ctx(tmp_path)
    ctx.agents_dir = str(agents_dir)
    out = REGISTRY["build_agent"].handler(
        {"name": "poet", "description": "Writes poems.",
         "system": "You write poems.", "model": "workhorse",
         "tools": ["read_file"]}, ctx)
    p = agents_dir / "poet.md"
    assert p.exists()
    from arccode.agents.loader import load_agent
    spec = load_agent(p)
    assert spec.name == "poet" and spec.model == "workhorse"
    assert spec.tools == ["read_file"]


def test_import_skill(tmp_path):
    # make a source skill folder elsewhere
    src = tmp_path / "external" / "mytool"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text("---\nname: mytool\ndescription: x\n---\nbody")
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    reg = SkillRegistry(str(skills_dir))
    ctx = _ctx(tmp_path, skills=reg)
    ctx.skills_dir = str(skills_dir)
    REGISTRY["import_skill"].handler({"source_dir": str(src)}, ctx)
    assert (skills_dir / "mytool" / "SKILL.md").exists()
    assert "mytool" in reg.skills


# ---- Remaining tools: edit, multi_edit, glob, todo ----

def test_edit_and_multiedit(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("a = 1\nb = 2\nc = 3\n")
    ctx = _ctx(tmp_path)
    REGISTRY["edit_file"].handler({"path": str(f), "old": "b = 2", "new": "b = 20"}, ctx)
    assert "b = 20" in f.read_text()
    REGISTRY["multi_edit"].handler({"path": str(f), "edits": [
        {"old": "a = 1", "new": "a = 10"}, {"old": "c = 3", "new": "c = 30"}]}, ctx)
    txt = f.read_text()
    assert "a = 10" in txt and "c = 30" in txt


def test_edit_rejects_ambiguous(tmp_path):
    f = tmp_path / "d.txt"
    f.write_text("x\nx\n")
    ctx = _ctx(tmp_path)
    out = REGISTRY["edit_file"].handler({"path": str(f), "old": "x", "new": "y"}, ctx)
    assert "ERROR" in out and f.read_text() == "x\nx\n"  # unchanged


def test_glob_and_todo(tmp_path):
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    ctx = _ctx(tmp_path)
    out = REGISTRY["glob"].handler({"pattern": "*.py", "root": str(tmp_path)}, ctx)
    assert "a.py" in out and "b.py" in out
    REGISTRY["todo_write"].handler({"todos": [
        {"content": "task one", "status": "pending", "id": "1"}]}, ctx)
    assert ctx.todos and ctx.todos[0]["content"] == "task one"


def test_bash_destructive_guard(tmp_path):
    ctx = _ctx(tmp_path)
    out = REGISTRY["bash"].handler({"command": "rm -rf /"}, ctx)
    assert "BLOCKED" in out
