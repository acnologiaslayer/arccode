"""Agent definitions: parse .md-with-frontmatter files into AgentSpec."""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

import frontmatter


@dataclass
class AgentSpec:
    name: str
    system: str
    description: str = ""
    model: str | None = None  # None => auto-route
    effort: str = "medium"
    tools: list[str] = field(default_factory=list)  # empty => DEFAULT_TOOLS
    skills: list[str] = field(default_factory=list)

    def with_model(self, model: str | None) -> AgentSpec:
        return AgentSpec(self.name, self.system, self.description, model,
                         self.effort, list(self.tools), list(self.skills))


def load_agent(path: str | pathlib.Path) -> AgentSpec:
    post = frontmatter.load(str(path))
    m = post.metadata
    model = m.get("model")
    if model in (None, "auto", "inherit", ""):
        model = None
    return AgentSpec(
        name=m.get("name", pathlib.Path(path).stem),
        system=post.content.strip(),
        description=m.get("description", ""),
        model=model,
        effort=m.get("effort", "medium"),
        tools=list(m.get("tools", []) or []),
        skills=list(m.get("skills", []) or []),
    )


def load_registry(agents_dir: str | pathlib.Path) -> dict[str, AgentSpec]:
    root = pathlib.Path(agents_dir)
    reg: dict[str, AgentSpec] = {}
    if not root.exists():
        return reg
    for md in root.glob("*.md"):
        try:
            spec = load_agent(md)
            reg[spec.name] = spec
        except Exception:  # noqa: BLE001
            continue
    return reg
