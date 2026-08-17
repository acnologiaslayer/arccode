"""The agent runtime loop (ReAct): call model, run tools, repeat until done."""
from __future__ import annotations

from rich.console import Console

from ..config import MODELS, MODELS_BY_ID
from ..providers import Message, get_provider
from ..resilience import RetryPolicy, complete_resilient
from ..router import route
from ..tools import DEFAULT_TOOLS, REGISTRY, tool_schemas
from .loader import AgentSpec

console = Console(stderr=True)


def _fallback_models(primary):
    """Ordered candidate models: primary first, then other usable providers,
    cheapest tiers first, so a rate-limited primary can fail over gracefully."""
    from ..router import _usable_provider
    seen = {primary.id}
    ordered = [primary]
    tier_rank = {"small": 0, "local": 1, "mid": 2, "frontier": 3}
    for spec in sorted(MODELS.values(), key=lambda s: tier_rank.get(s.tier, 9)):
        if spec.id in seen:
            continue
        if _usable_provider(spec.provider):
            ordered.append(spec)
            seen.add(spec.id)
    return ordered


class Agent:
    def __init__(self, spec: AgentSpec, ctx, verbose: bool = False,
                 history: list[Message] | None = None):
        self.spec = spec
        self.ctx = ctx
        self.verbose = verbose
        self.messages: list[Message] = list(history) if history else []

    def _system(self) -> str:
        parts = [self.spec.system]
        if self.ctx.skills:
            idx = self.ctx.skills.index()
            if idx:
                parts.append("\n## Available skills (call load_skill to use)\n" + idx)
        return "\n".join(parts)

    def run(self, task: str, max_steps: int = 40) -> str:
        decision = route(task, force=self.spec.model)
        # If the agent pins a model whose provider isn't usable right now, fall
        # back to credential-aware auto-routing so zero-config runs still work.
        if self.spec.model:
            from ..router import _usable_provider
            if not _usable_provider(decision.model.provider):
                alt = route(task, force=None)
                if _usable_provider(alt.model.provider):
                    if self.verbose:
                        console.print(f"[dim]pinned {decision.model.key} unusable "
                                      f"(no creds); falling back to {alt.model.key}[/dim]")
                    decision = alt
        model_id = decision.model.id
        tool_names = self.spec.tools or DEFAULT_TOOLS
        schemas = tool_schemas(tool_names)

        if self.verbose:
            console.print(f"[dim]agent={self.spec.name} model={decision.model.key} "
                          f"({model_id}) :: {decision.reason}[/dim]")

        self.messages.append(Message("user", task))
        final = ""
        candidates = [(get_provider(s.id), s) for s in _fallback_models(decision.model)]
        active_id = model_id

        def _log(kind, detail):
            if self.verbose:
                color = "yellow" if kind == "retry" else "magenta"
                console.print(f"[{color}]{detail}[/{color}]")

        for step in range(max_steps):
            try:
                comp, used = complete_resilient(
                    providers_and_models=candidates,
                    system=self._system(), messages=self.messages,
                    tools=schemas, effort=self.spec.effort,
                    policy=RetryPolicy(), on_event=_log)
            except Exception as e:  # noqa: BLE001
                msg = str(e).splitlines()[0] if str(e) else e.__class__.__name__
                if self.verbose:
                    console.print(f"[red]provider error: {msg}[/red]")
                return f"ERROR: provider call failed ({active_id}): {msg}"

            # If we failed over to a different model, keep using it first next turn.
            if used.id != active_id:
                active_id = used.id
                candidates = [(get_provider(s.id), s) for s in _fallback_models(used)]
                if self.verbose:
                    console.print(f"[magenta]failed over to {used.key} ({used.id})[/magenta]")

            self._account(used.id, comp.usage)

            if comp.text:
                final = comp.text
            self.messages.append(Message("assistant", comp.text, comp.tool_calls))

            if not comp.tool_calls:
                return final

            for call in comp.tool_calls:
                result = self._run_tool(call)
                self.messages.append(
                    Message("tool", str(result), tool_call_id=call.id))
        return final or "(max steps reached)"

    def _run_tool(self, call) -> str:
        tool = REGISTRY.get(call.name)
        if not tool:
            return f"ERROR: unknown tool {call.name}"
        if self.verbose:
            console.print(f"[dim]  -> {call.name}({call.args})[/dim]")
        if self.ctx.hooks:
            allowed, msg = self.ctx.hooks.fire("PreToolUse", call.name, str(call.args))
            if not allowed:
                return f"BLOCKED by hook: {msg}"
        if tool.danger and not self.ctx.confirm(call.name, call.args):
            return "DENIED by user/policy"
        try:
            result = tool.handler(call.args, self.ctx)
        except Exception as e:  # noqa: BLE001
            result = f"ERROR in {call.name}: {e}"
        if self.ctx.hooks:
            self.ctx.hooks.fire("PostToolUse", call.name, str(result)[:2000])
        return result

    def _account(self, model_id: str, usage: dict) -> None:
        spec = MODELS_BY_ID.get(model_id)
        self.ctx.usage["in"] += usage.get("in", 0)
        self.ctx.usage["out"] += usage.get("out", 0)
        if spec:
            self.ctx.usage["usd"] += (
                usage.get("in", 0) / 1e6 * spec.in_cost
                + usage.get("out", 0) / 1e6 * spec.out_cost)
