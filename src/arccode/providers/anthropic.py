"""Anthropic provider adapter (lazy import of the SDK)."""
from __future__ import annotations

import json
import os

from .base import Completion, Message, ToolCall


class AnthropicProvider:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = None

    def _client_or_raise(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:
                raise RuntimeError(
                    "anthropic SDK not installed. Run: pip install 'arccode[anthropic]'"
                ) from e
            if not self.api_key:
                raise RuntimeError("ANTHROPIC_API_KEY not set")
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def complete(self, *, model, system, messages, tools, effort="medium", max_out=4096):
        client = self._client_or_raise()
        model_name = model.split(":", 1)[1] if ":" in model else model
        resp = client.messages.create(
            model=model_name,
            system=system or "You are a helpful assistant.",
            max_tokens=max_out,
            tools=[_tool(t) for t in tools],
            messages=[_msg(m) for m in messages],
        )
        text, calls = "", []
        for block in resp.content:
            if block.type == "text":
                text += block.text
            elif block.type == "tool_use":
                calls.append(ToolCall(block.id, block.name, dict(block.input)))
        return Completion(
            text, calls,
            {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens},
            resp.stop_reason or "stop",
        )


def _tool(t: dict) -> dict:
    return {"name": t["name"], "description": t["description"], "input_schema": t["schema"]}


def _msg(m: Message) -> dict:
    if m.role == "tool":
        return {"role": "user", "content": [{
            "type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}]}
    if m.role == "assistant" and m.tool_calls:
        content = []
        if m.content:
            content.append({"type": "text", "text": m.content})
        for c in m.tool_calls:
            content.append({"type": "tool_use", "id": c.id, "name": c.name, "input": c.args})
        return {"role": "assistant", "content": content}
    return {"role": m.role, "content": m.content}
