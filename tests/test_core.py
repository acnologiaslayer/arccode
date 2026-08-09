"""Offline tests: routing, loaders, tool registry. No network/API needed."""
from arccode.config import MODELS, resolve
from arccode.router import classify, route
from arccode.agents import load_registry
from arccode.skills import SkillRegistry
from arccode.tools import REGISTRY, DEFAULT_TOOLS
import pathlib

PKG = pathlib.Path(__file__).resolve().parent.parent / "src" / "arccode"


def test_catalog_nonempty():
    assert "workhorse" in MODELS
    assert resolve("workhorse").provider == "anthropic"


def test_classify_intents():
    assert classify("summarize all the docs")[0] == "bulk_read"
    assert classify("fix the failing test")[0] == "debug"
    assert classify("design a scalable queue")[0] == "design"


def test_router_picks_cheap_for_bulk_read():
    d = route("summarize every file in the repo")
    assert d.model.tier in ("small", "local")


def test_router_picks_strong_for_design():
    d = route("architect a distributed, fault-tolerant migration plan")
    assert d.model.tier in ("frontier", "mid")


def test_force_override_wins():
    d = route("say hi", force="frontier-reason")
    assert d.model.key == "frontier-reason"


def test_agents_load():
    reg = load_registry(PKG / "agents" / "registry")
    assert "coordinator" in reg
    assert reg["implementer"].model == "workhorse"


def test_skills_load_and_index():
    sk = SkillRegistry(str(PKG / "skills" / "registry"))
    assert "mermaid-diagrams" in sk.skills
    assert "mermaid" in sk.index().lower()


def test_tools_registered():
    for name in ("read_file", "bash", "spawn_agent", "build_agent", "web_search"):
        assert name in REGISTRY
    assert "read_file" in DEFAULT_TOOLS
