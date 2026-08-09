"""Persistent, resumable sessions.

Stores an agent's message history + usage to ~/.arccode/sessions/<id>.json so a
run can be resumed later. Serializes the normalized Message/ToolCall types.
"""
from __future__ import annotations

import json
import pathlib
import time
import uuid

from .providers.base import Message, ToolCall


def _sessions_dir() -> pathlib.Path:
    d = pathlib.Path.home() / ".arccode" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def _msg_to_dict(m: Message) -> dict:
    return {
        "role": m.role,
        "content": m.content,
        "tool_call_id": m.tool_call_id,
        "tool_calls": [{"id": c.id, "name": c.name, "args": c.args} for c in m.tool_calls],
    }


def _dict_to_msg(d: dict) -> Message:
    return Message(
        role=d["role"],
        content=d.get("content", ""),
        tool_calls=[ToolCall(c["id"], c["name"], c["args"]) for c in d.get("tool_calls", [])],
        tool_call_id=d.get("tool_call_id"),
    )


class Session:
    def __init__(self, sid: str, agent: str, messages: list[Message] | None = None,
                 usage: dict | None = None, meta: dict | None = None):
        self.id = sid
        self.agent = agent
        self.messages = messages or []
        self.usage = usage or {"in": 0, "out": 0, "usd": 0.0}
        self.meta = meta or {}

    @property
    def path(self) -> pathlib.Path:
        return _sessions_dir() / f"{self.id}.json"

    def save(self) -> None:
        data = {
            "id": self.id,
            "agent": self.agent,
            "updated": time.time(),
            "usage": self.usage,
            "meta": self.meta,
            "messages": [_msg_to_dict(m) for m in self.messages],
        }
        self.path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, sid: str) -> "Session":
        p = _sessions_dir() / f"{sid}.json"
        if not p.exists():
            raise FileNotFoundError(f"no session {sid!r} at {p}")
        data = json.loads(p.read_text())
        return cls(
            data["id"], data.get("agent", "coordinator"),
            [_dict_to_msg(m) for m in data.get("messages", [])],
            data.get("usage"), data.get("meta"))

    @classmethod
    def create(cls, agent: str) -> "Session":
        return cls(new_id(), agent)


def list_sessions() -> list[dict]:
    out = []
    for p in sorted(_sessions_dir().glob("*.json"), reverse=True):
        try:
            d = json.loads(p.read_text())
            out.append({
                "id": d.get("id", p.stem),
                "agent": d.get("agent", "?"),
                "turns": len(d.get("messages", [])),
                "usd": d.get("usage", {}).get("usd", 0.0),
                "updated": d.get("updated", 0),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return out
