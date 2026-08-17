"""Normalized provider interface shared by every model backend.

The rest of arccode only ever sees Message / ToolCall / Completion, so
providers are hot-swappable and the agent loop is model-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class Message:
    role: str  # "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # set on role=="tool" results


@dataclass
class Completion:
    text: str
    tool_calls: list[ToolCall]
    usage: dict  # {"in": int, "out": int}
    stop: str


class Provider(Protocol):
    def complete(
        self,
        *,
        model: str,  # provider-qualified id; adapter strips the prefix
        system: str,
        messages: list[Message],
        tools: list[dict],
        effort: str = "medium",
        max_out: int = 4096,
        on_text=None,  # optional callback(delta:str) for streamed text
    ) -> Completion:
        ...
