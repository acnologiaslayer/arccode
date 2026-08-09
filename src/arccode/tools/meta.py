"""Meta tools: spawn sub-agents, load/build skills, build agents."""
from __future__ import annotations

import pathlib

from .base import tool


@tool("spawn_agent", "Delegate a subtask to a named agent (auto-routed unless model given).",
      {"type": "object", "properties": {
          "agent": {"type": "string"},
          "task": {"type": "string"},
          "model": {"type": "string", "description": "optional catalog key/id override"}},
       "required": ["agent", "task"]})
def spawn_agent(args, ctx):
    if not ctx.orchestrator:
        return "orchestrator unavailable"
    if ctx.depth >= 3:
        return "spawn depth limit reached; complete the task directly"
    return ctx.orchestrator.spawn(args["agent"], args["task"], args.get("model"), ctx)


@tool("list_skills", "List available skills (name + description index).",
      {"type": "object", "properties": {}, "required": []})
def list_skills(args, ctx):
    if not ctx.skills:
        return "no skills registry"
    return ctx.skills.index() or "(no skills)"


@tool("load_skill", "Load a skill's full body into context by name.",
      {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]})
def load_skill(args, ctx):
    if not ctx.skills:
        return "no skills registry"
    try:
        return ctx.skills.load(args["name"])
    except KeyError:
        return f"no such skill: {args['name']}"


@tool("build_agent", "Create a new agent definition (.md) and register it.",
      {"type": "object", "properties": {
          "name": {"type": "string"},
          "description": {"type": "string"},
          "system": {"type": "string"},
          "model": {"type": "string"},
          "tools": {"type": "array", "items": {"type": "string"}},
          "skills": {"type": "array", "items": {"type": "string"}}},
       "required": ["name", "description", "system"]}, danger=True)
def build_agent(args, ctx):
    import yaml
    meta = {
        "name": args["name"],
        "description": args["description"],
        "model": args.get("model", "auto"),
        "tools": args.get("tools", ["read_file", "write_file", "edit_file", "bash", "grep"]),
        "skills": args.get("skills", []),
    }
    fm = "---\n" + yaml.safe_dump(meta, sort_keys=False) + "---\n\n" + args["system"] + "\n"
    p = pathlib.Path(ctx.agents_dir) / f"{args['name']}.md"
    p.write_text(fm)
    if ctx.orchestrator:
        ctx.orchestrator.reload_agents()
    return f"created agent {p}"


@tool("build_skill", "Create a new skill (SKILL.md) and register it.",
      {"type": "object", "properties": {
          "name": {"type": "string"},
          "description": {"type": "string"},
          "body": {"type": "string"}},
       "required": ["name", "description", "body"]}, danger=True)
def build_skill(args, ctx):
    d = pathlib.Path(ctx.skills_dir) / args["name"]
    d.mkdir(parents=True, exist_ok=True)
    fm = f"---\nname: {args['name']}\ndescription: {args['description']}\n---\n\n{args['body']}\n"
    (d / "SKILL.md").write_text(fm)
    if ctx.skills:
        ctx.skills.reload()
    return f"created skill {d / 'SKILL.md'}"


@tool("import_skill", "Import an external skill folder (with SKILL.md) into the registry.",
      {"type": "object", "properties": {"source_dir": {"type": "string"}},
       "required": ["source_dir"]}, danger=True)
def import_skill(args, ctx):
    import shutil
    src = pathlib.Path(args["source_dir"])
    if not (src / "SKILL.md").exists():
        return f"no SKILL.md in {src}"
    dest = pathlib.Path(ctx.skills_dir) / src.name
    shutil.copytree(src, dest, dirs_exist_ok=True)
    if ctx.skills:
        ctx.skills.reload()
    return f"imported skill -> {dest}"
