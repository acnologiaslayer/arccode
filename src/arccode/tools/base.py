"""Tool registry + execution context.

Tools are the harness's hands. Each has a JSON schema (sent to the model) and
a handler(args, ctx) -> str. Danger tools require confirmation via the policy.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

REGISTRY: dict[str, Tool] = {}


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    handler: Callable[[dict, Ctx], str]
    danger: bool = False


def tool(name: str, description: str, schema: dict, danger: bool = False):
    def deco(fn: Callable[[dict, Ctx], str]):
        REGISTRY[name] = Tool(name, description, schema, fn, danger)
        return fn
    return deco


def tool_schemas(names: list[str]) -> list[dict]:
    out = []
    for n in names:
        t = REGISTRY.get(n)
        if t:
            out.append({"name": t.name, "description": t.description, "schema": t.schema})
    return out


@dataclass
class Ctx:
    """Shared runtime context passed to every tool handler."""
    cwd: str = "."
    agents_dir: str = ""
    skills_dir: str = ""
    orchestrator: object = None  # set by the runtime
    skills: object = None  # SkillRegistry
    memory: object = None  # MemoryStore
    hooks: object = None  # HookManager
    on_status: object = None  # optional callback(text) for live step feedback
    touched: set = field(default_factory=set)  # files created/edited this run
    todos: list = field(default_factory=list)
    yes: bool = False  # auto-confirm danger tools (non-interactive)
    usage: dict = field(default_factory=lambda: {"in": 0, "out": 0, "usd": 0.0})
    depth: int = 0  # spawn depth guard

    def confirm(self, tool_name: str, args: dict) -> bool:
        if self.yes:
            return True
        try:
            ans = input(f"[arccode] allow danger tool '{tool_name}' {args}? [y/N] ")
        except EOFError:
            return False
        return ans.strip().lower() in ("y", "yes")

    def child(self) -> Ctx:
        return Ctx(
            cwd=self.cwd, agents_dir=self.agents_dir, skills_dir=self.skills_dir,
            orchestrator=self.orchestrator, skills=self.skills, memory=self.memory,
            hooks=self.hooks, on_status=self.on_status, touched=self.touched,
            todos=list(self.todos),
            yes=self.yes, usage={"in": 0, "out": 0, "usd": 0.0}, depth=self.depth + 1)
