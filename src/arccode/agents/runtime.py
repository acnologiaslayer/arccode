"""The agent runtime loop (ReAct): call model, run tools, repeat until done."""
from __future__ import annotations

from rich.console import Console

from ..config import MODELS_BY_ID
from ..providers import Message, get_provider
from ..router import route
from ..tools import DEFAULT_TOOLS, REGISTRY, tool_schemas
from .loader import AgentSpec

console = Console(stderr=True)


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
        model_id = decision.model.id
        provider = get_provider(model_id)
        tool_names = self.spec.tools or DEFAULT_TOOLS
        schemas = tool_schemas(tool_names)

        if self.verbose:
            console.print(f"[dim]agent={self.spec.name} model={decision.model.key} "
                          f"({model_id}) :: {decision.reason}[/dim]")

        self.messages.append(Message("user", task))
        final = ""
        for step in range(max_steps):
            try:
                comp = provider.complete(
                    model=model_id, system=self._system(),
                    messages=self.messages, tools=schemas,
                    effort=self.spec.effort, max_out=decision.model.max_out)
            except Exception as e:  # noqa: BLE001
                msg = str(e).splitlines()[0] if str(e) else e.__class__.__name__
                if self.verbose:
                    console.print(f"[red]provider error: {msg}[/red]")
                return f"ERROR: provider call failed ({decision.model.id}): {msg}"

            self._account(model_id, comp.usage)

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
