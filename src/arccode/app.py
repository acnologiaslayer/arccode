"""Application assembly: build a ready-to-run Ctx + Orchestrator.

This wires config dirs, skills, memory, MCP, and hooks into one App object the
CLI (or any embedder) can use.
"""
from __future__ import annotations

import pathlib

from .hooks import HookManager, SlashCommands
from .memory import MemoryStore
from .orchestrator import Orchestrator
from .skills import SkillRegistry
from .tools import Ctx


def _pkg_dir() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent


def _resolve_dir(env_val: str | None, default: pathlib.Path) -> str:
    return str(pathlib.Path(env_val).expanduser()) if env_val else str(default)


class App:
    def __init__(self, *, cwd: str = ".", yes: bool = False, verbose: bool = False,
                 agents_dir: str | None = None, skills_dir: str | None = None,
                 enable_mcp: bool = True):
        pkg = _pkg_dir()
        self.agents_dir = _resolve_dir(agents_dir, pkg / "agents" / "registry")
        self.skills_dir = _resolve_dir(skills_dir, pkg / "skills" / "registry")
        self.verbose = verbose

        home = pathlib.Path.home() / ".arccode"
        home.mkdir(parents=True, exist_ok=True)

        self.skills = SkillRegistry(self.skills_dir)
        self.memory = MemoryStore(str(home / "memory.jsonl"))
        self.hooks = HookManager()
        self.commands = SlashCommands()

        self.ctx = Ctx(cwd=cwd, agents_dir=self.agents_dir, skills_dir=self.skills_dir,
                       skills=self.skills, memory=self.memory, hooks=self.hooks, yes=yes)
        self.orchestrator = Orchestrator(self.agents_dir, self.ctx, verbose=verbose)
        self.ctx.orchestrator = self.orchestrator

        if enable_mcp:
            self._connect_mcp()

    def _connect_mcp(self) -> None:
        try:
            from .mcp import connect_all, load_mcp_config, register_mcp_tools
            clients = connect_all(load_mcp_config())
            if clients:
                register_mcp_tools(clients)
                self.mcp_clients = clients
        except Exception:  # noqa: BLE001
            self.mcp_clients = {}

    def run(self, task: str, agent: str = "coordinator", model: str | None = None,
            max_steps: int = 40, session=None) -> str:
        task = self.commands.expand(task)
        if session is None:
            return self.orchestrator.spawn(agent, task, model, self.ctx)
        # Session-backed run: preserve and persist history on the top-level agent.
        from .agents import Agent
        spec = self.orchestrator.get(session.agent or agent)
        if not spec:
            return f"ERROR: no agent named {session.agent or agent!r}"
        if model:
            spec = spec.with_model(model)
        self.ctx.orchestrator = self.orchestrator
        agent_obj = Agent(spec, self.ctx, verbose=self.verbose, history=session.messages)
        result = agent_obj.run(task, max_steps=max_steps)
        session.messages = agent_obj.messages
        session.usage = self.ctx.usage
        session.save()
        return result

    def usage(self) -> dict:
        return self.ctx.usage
