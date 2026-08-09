"""Orchestrator: spawn agents, fan out subtasks, join results (a swarm)."""
from __future__ import annotations

import concurrent.futures as cf

from .agents import Agent, load_registry
from .agents.loader import AgentSpec


class Orchestrator:
    def __init__(self, agents_dir: str, ctx, verbose: bool = False):
        self.agents_dir = agents_dir
        self.ctx = ctx
        self.verbose = verbose
        self.registry: dict[str, AgentSpec] = load_registry(agents_dir)

    def reload_agents(self) -> None:
        self.registry = load_registry(self.agents_dir)

    def get(self, name: str) -> AgentSpec | None:
        return self.registry.get(name)

    def spawn(self, agent_name: str, task: str, model: str | None = None,
              parent_ctx=None) -> str:
        spec = self.registry.get(agent_name)
        if not spec:
            return f"ERROR: no agent named {agent_name!r}. Available: {list(self.registry)}"
        if model:
            spec = spec.with_model(model)
        base = parent_ctx or self.ctx
        child = base.child()
        child.orchestrator = self
        child.skills = base.skills
        child.memory = base.memory
        result = Agent(spec, child, self.verbose).run(task)
        # bubble usage up to parent
        for k in ("in", "out", "usd"):
            base.usage[k] += child.usage[k]
        return result

    def fan_out(self, jobs: list[tuple[str, str]], max_workers: int = 4) -> dict:
        results: dict[str, str] = {}
        with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(self.spawn, a, t): (a, t) for a, t in jobs}
            for fut in cf.as_completed(futs):
                a, t = futs[fut]
                try:
                    results[f"{a}: {t[:40]}"] = fut.result()
                except Exception as e:  # noqa: BLE001
                    results[f"{a}: {t[:40]}"] = f"ERROR: {e}"
        return results
