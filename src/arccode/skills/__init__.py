"""Skill registry with progressive disclosure.

A skill is a folder containing SKILL.md with frontmatter {name, description}.
The description is always available (cheap index); the body loads on demand.
"""
from __future__ import annotations

import pathlib

import frontmatter


class SkillRegistry:
    def __init__(self, root: str):
        self.root = pathlib.Path(root)
        self.skills: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        self.skills.clear()
        if not self.root.exists():
            return
        for skill_md in self.root.glob("*/SKILL.md"):
            post = frontmatter.load(skill_md)
            name = post.get("name", skill_md.parent.name)
            self.skills[name] = {
                "description": post.get("description", ""),
                "body": post.content,
                "dir": skill_md.parent,
            }

    def index(self) -> str:
        return "\n".join(
            f"- {name}: {s['description']}" for name, s in sorted(self.skills.items()))

    def load(self, name: str) -> str:
        s = self.skills[name]
        return f"# Skill: {name}\n{s['body']}"

    def match(self, text: str) -> list[str]:
        """Naive trigger match: skill whose description keywords appear in text."""
        t = text.lower()
        hits = []
        for name, s in self.skills.items():
            words = [w.strip('.,"').lower() for w in s["description"].split()
                     if len(w) > 4]
            if any(w in t for w in words[:12]):
                hits.append(name)
        return hits
