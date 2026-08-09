"""Productivity + memory tools: todo list and persistent memory."""
from __future__ import annotations

import json

from .base import tool


@tool("todo_write", "Replace the task todo list. Each item: {content, status, id}.",
      {"type": "object", "properties": {
          "todos": {"type": "array", "items": {"type": "object", "properties": {
              "content": {"type": "string"},
              "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
              "id": {"type": "string"}}, "required": ["content", "status", "id"]}}},
       "required": ["todos"]})
def todo_write(args, ctx):
    ctx.todos = args["todos"]
    lines = []
    for t in ctx.todos:
        mark = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}.get(t["status"], "[ ]")
        lines.append(f"{mark} {t['content']}")
    return "todos updated:\n" + "\n".join(lines)


@tool("todo_read", "Read the current todo list.",
      {"type": "object", "properties": {}, "required": []})
def todo_read(args, ctx):
    if not ctx.todos:
        return "(no todos)"
    return json.dumps(ctx.todos, indent=2)


@tool("memory_remember", "Persist a fact/preference to long-term memory.",
      {"type": "object", "properties": {
          "content": {"type": "string"},
          "category": {"type": "string", "enum": ["fact", "preference", "entity", "correction"]},
          "tags": {"type": "array", "items": {"type": "string"}}},
       "required": ["content"]})
def memory_remember(args, ctx):
    if not ctx.memory:
        return "memory store unavailable"
    mid = ctx.memory.remember(args["content"], args.get("category", "fact"),
                              args.get("tags", []))
    return f"remembered ({mid})"


@tool("memory_search", "Search long-term memory.",
      {"type": "object", "properties": {
          "query": {"type": "string"}, "limit": {"type": "integer"}},
       "required": ["query"]})
def memory_search(args, ctx):
    if not ctx.memory:
        return "memory store unavailable"
    hits = ctx.memory.search(args["query"], int(args.get("limit", 5)))
    if not hits:
        return "(no matches)"
    return "\n".join(f"- [{h['category']}] {h['content']}" for h in hits)
