"""Shell tools: bash (foreground + background), grep."""
from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid

from .base import tool

# Background task registry: id -> {proc, output, done, cmd}
_BG: dict[str, dict] = {}

# Minimal destructive-command guard (mirrors jcode's safety gate).
_DANGER_SUBSTR = ("rm -rf /", "mkfs", ":(){", "dd if=", "> /dev/sd", "shutdown", "reboot")


def _looks_destructive(cmd: str) -> bool:
    c = cmd.lower()
    return any(s in c for s in _DANGER_SUBSTR)


@tool("bash", "Run a shell command and return combined stdout/stderr.",
      {"type": "object", "properties": {
          "command": {"type": "string"},
          "timeout": {"type": "integer", "description": "seconds (default 120)"},
          "cwd": {"type": "string"}},
       "required": ["command"]}, danger=True)
def bash(args, ctx):
    cmd = args["command"]
    if _looks_destructive(cmd):
        return "BLOCKED: command matched destructive-safety guard; refused."
    cwd = args.get("cwd") or ctx.cwd
    try:
        r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True,
                           text=True, timeout=int(args.get("timeout", 120)))
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out"
    out = (r.stdout or "") + (r.stderr or "")
    return f"(exit {r.returncode})\n{out[:100_000]}" or f"(exit {r.returncode}, no output)"


@tool("bash_background", "Start a long-running command in the background. Returns a task id.",
      {"type": "object", "properties": {
          "command": {"type": "string"}, "cwd": {"type": "string"}},
       "required": ["command"]}, danger=True)
def bash_background(args, ctx):
    cmd = args["command"]
    if _looks_destructive(cmd):
        return "BLOCKED: command matched destructive-safety guard; refused."
    tid = "bg_" + uuid.uuid4().hex[:8]
    proc = subprocess.Popen(cmd, shell=True, cwd=args.get("cwd") or ctx.cwd,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    entry = {"proc": proc, "output": "", "done": False, "cmd": cmd}
    _BG[tid] = entry

    def _pump():
        for line in proc.stdout:
            entry["output"] += line
        proc.wait()
        entry["done"] = True

    threading.Thread(target=_pump, daemon=True).start()
    return f"started {tid}: {cmd}"


@tool("bash_output", "Get output/status of a background task by id.",
      {"type": "object", "properties": {"task_id": {"type": "string"}},
       "required": ["task_id"]})
def bash_output(args, ctx):
    e = _BG.get(args["task_id"])
    if not e:
        return f"no such task {args['task_id']}"
    status = "done" if e["done"] else "running"
    return f"[{status}] {e['cmd']}\n{e['output'][-50_000:]}"


@tool("grep", "Search file contents with a regex (uses ripgrep if available).",
      {"type": "object", "properties": {
          "pattern": {"type": "string"}, "path": {"type": "string"},
          "glob": {"type": "string"}, "ignore_case": {"type": "boolean"}},
       "required": ["pattern"]})
def grep(args, ctx):
    path = args.get("path") or ctx.cwd
    flags = ["-n", "--color=never"]
    if args.get("ignore_case"):
        flags.append("-i")
    if args.get("glob"):
        flags += ["-g", args["glob"]]
    from shutil import which
    if which("rg"):
        cmd = ["rg", *flags, args["pattern"], path]
    else:
        cmd = ["grep", "-rn", args["pattern"], path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return "ERROR: search timed out"
    out = r.stdout or r.stderr or "(no matches)"
    return out[:80_000]
