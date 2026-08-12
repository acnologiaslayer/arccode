"""Import all tool modules so their @tool decorators register into REGISTRY."""
from __future__ import annotations

from . import fs, meta, productivity, shell, web  # noqa: F401
from .base import REGISTRY, Ctx, Tool, tool, tool_schemas

# Default toolset every agent gets unless it declares its own `tools:` list.
DEFAULT_TOOLS = [
    "read_file", "write_file", "edit_file", "multi_edit", "list_dir", "glob",
    "bash", "bash_background", "bash_output", "grep",
    "web_fetch", "web_search",
    "todo_write", "todo_read", "memory_remember", "memory_search",
    "spawn_agent", "list_skills", "load_skill", "build_agent", "build_skill", "import_skill",
]

__all__ = ["DEFAULT_TOOLS", "REGISTRY", "Ctx", "Tool", "tool", "tool_schemas"]
