"""Hooks + slash commands.

Hooks: shell commands run on lifecycle events (PreToolUse, PostToolUse,
SessionStart, etc.). Config at ~/.arccode/hooks.json or ./.arccode/hooks.json:
  {"PreToolUse": [{"match": "bash", "command": "echo blocked >&2; exit 2"}]}
A non-zero exit on PreToolUse blocks the tool.

Slash commands: markdown files in ./.arccode/commands/*.md or
~/.arccode/commands/*.md whose body is a prompt template with $ARGUMENTS.
"""
from __future__ import annotations

import json
import pathlib
import subprocess

import frontmatter


def _load_json(paths: list[pathlib.Path]) -> dict:
    merged: dict[str, list] = {}
    for p in paths:
        if p.exists():
            try:
                data = json.loads(p.read_text())
            except json.JSONDecodeError:
                continue
            for event, hooks in data.items():
                merged.setdefault(event, []).extend(hooks)
    return merged


class HookManager:
    def __init__(self):
        self.hooks = _load_json([
            pathlib.Path.home() / ".arccode" / "hooks.json",
            pathlib.Path(".arccode") / "hooks.json",
        ])

    def fire(self, event: str, tool_name: str = "", payload: str = "") -> tuple[bool, str]:
        """Return (allowed, message). allowed=False blocks (PreToolUse only)."""
        for hook in self.hooks.get(event, []):
            match = hook.get("match", "")
            if match and match not in tool_name:
                continue
            cmd = hook.get("command")
            if not cmd:
                continue
            r = subprocess.run(cmd, shell=True, input=payload, capture_output=True, text=True)
            if event == "PreToolUse" and r.returncode != 0:
                return False, (r.stderr or r.stdout or "blocked by hook").strip()
        return True, ""


class SlashCommands:
    def __init__(self):
        self.commands: dict[str, str] = {}
        for root in (pathlib.Path(".arccode") / "commands",
                     pathlib.Path.home() / ".arccode" / "commands"):
            if root.exists():
                for md in root.glob("*.md"):
                    post = frontmatter.load(str(md))
                    self.commands.setdefault(md.stem, post.content)

    def expand(self, text: str) -> str:
        """If text starts with /name, expand into the command template."""
        if not text.startswith("/"):
            return text
        parts = text[1:].split(maxsplit=1)
        name = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        template = self.commands.get(name)
        if template is None:
            return text
        return template.replace("$ARGUMENTS", args)

    def names(self) -> list[str]:
        return sorted(self.commands)
