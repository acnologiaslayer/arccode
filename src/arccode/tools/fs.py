"""Filesystem tools: read, write, edit, multiedit, ls, glob."""
from __future__ import annotations

import fnmatch
import os
import pathlib

from .base import tool

_MAX = 400_000


@tool("read_file", "Read a UTF-8 text file. Returns up to ~400k chars.",
      {"type": "object", "properties": {
          "path": {"type": "string"},
          "offset": {"type": "integer", "description": "start line (1-based)"},
          "limit": {"type": "integer", "description": "max lines"}},
       "required": ["path"]})
def read_file(args, ctx):
    p = pathlib.Path(args["path"])
    if not p.is_absolute():
        p = pathlib.Path(ctx.cwd) / p
    text = p.read_text(errors="replace")[:_MAX]
    lines = text.splitlines()
    off = max(0, int(args.get("offset", 1)) - 1)
    lim = int(args.get("limit", len(lines)))
    chunk = lines[off:off + lim]
    return "\n".join(f"{off + i + 1}\t{ln}" for i, ln in enumerate(chunk)) or "(empty)"


@tool("write_file", "Create or overwrite a file with the given content.",
      {"type": "object", "properties": {
          "path": {"type": "string"}, "content": {"type": "string"}},
       "required": ["path", "content"]}, danger=True)
def write_file(args, ctx):
    p = pathlib.Path(args["path"])
    if not p.is_absolute():
        p = pathlib.Path(ctx.cwd) / p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(args["content"])
    return f"wrote {len(args['content'])} bytes to {p}"


@tool("edit_file", "Replace an exact string in a file (must match once unless replace_all).",
      {"type": "object", "properties": {
          "path": {"type": "string"}, "old": {"type": "string"},
          "new": {"type": "string"}, "replace_all": {"type": "boolean"}},
       "required": ["path", "old", "new"]}, danger=True)
def edit_file(args, ctx):
    p = pathlib.Path(args["path"])
    if not p.is_absolute():
        p = pathlib.Path(ctx.cwd) / p
    text = p.read_text()
    count = text.count(args["old"])
    if count == 0:
        return f"ERROR: old string not found in {p}"
    if count > 1 and not args.get("replace_all"):
        return f"ERROR: old string matches {count} times; set replace_all or add context"
    text = text.replace(args["old"], args["new"])
    p.write_text(text)
    return f"edited {p} ({count} replacement(s))"


@tool("multi_edit", "Apply a sequence of {old,new} edits to one file atomically.",
      {"type": "object", "properties": {
          "path": {"type": "string"},
          "edits": {"type": "array", "items": {"type": "object", "properties": {
              "old": {"type": "string"}, "new": {"type": "string"},
              "replace_all": {"type": "boolean"}}, "required": ["old", "new"]}}},
       "required": ["path", "edits"]}, danger=True)
def multi_edit(args, ctx):
    p = pathlib.Path(args["path"])
    if not p.is_absolute():
        p = pathlib.Path(ctx.cwd) / p
    text = p.read_text()
    for i, e in enumerate(args["edits"]):
        if e["old"] not in text:
            return f"ERROR: edit #{i + 1} old string not found; aborted, no changes written"
        if text.count(e["old"]) > 1 and not e.get("replace_all"):
            return f"ERROR: edit #{i + 1} matches multiple times; aborted"
        text = text.replace(e["old"], e["new"])
    p.write_text(text)
    return f"applied {len(args['edits'])} edits to {p}"


@tool("list_dir", "List a directory (non-recursive).",
      {"type": "object", "properties": {"path": {"type": "string"}},
       "required": []})
def list_dir(args, ctx):
    p = pathlib.Path(args.get("path") or ctx.cwd)
    if not p.is_absolute():
        p = pathlib.Path(ctx.cwd) / p
    entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
    return "\n".join(f"{'d' if e.is_dir() else 'f'} {e.name}" for e in entries) or "(empty)"


@tool("glob", "Find files by glob pattern under a root (recursive with **).",
      {"type": "object", "properties": {
          "pattern": {"type": "string"}, "root": {"type": "string"}},
       "required": ["pattern"]})
def glob_tool(args, ctx):
    root = pathlib.Path(args.get("root") or ctx.cwd)
    if not root.is_absolute():
        root = pathlib.Path(ctx.cwd) / root
    matches = [str(p) for p in root.glob(args["pattern"]) if p.is_file()]
    matches.sort()
    return "\n".join(matches[:500]) or "(no matches)"
