"""Config profiles: storage model + CLI lifecycle and precedence.

Covers the ProfileStore round-trip, the active-pointer semantics, env application,
and the `arccode profile` subcommands plus how `run` layers a profile under
explicit flags (command line always wins).
"""
from typer.testing import CliRunner

from arccode.cli import _merge, app
from arccode.profiles import Profile, ProfileStore, apply_env, resolve_active

runner = CliRunner()


# --- storage model ---------------------------------------------------------

def test_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCCODE_HOME", str(tmp_path))
    store = ProfileStore()
    store.set(Profile(name="work", agent="implementer", yes=True,
                      env={"ARCCODE_CONFIG": "~/w.yaml"}))
    store.set(Profile(name="local", model="ollama/qwen2.5-3b"))
    store.use("work")
    store.save()

    again = ProfileStore.load()
    assert set(again.profiles) == {"work", "local"}
    assert again.active == "work"
    assert again.get("work").agent == "implementer"
    assert again.get("work").yes is True
    assert again.get("work").env == {"ARCCODE_CONFIG": "~/w.yaml"}
    assert again.get("local").model == "ollama/qwen2.5-3b"


def test_first_profile_becomes_active(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCCODE_HOME", str(tmp_path))
    store = ProfileStore()
    store.set(Profile(name="a"))
    assert store.active == "a"          # first set auto-activates
    store.set(Profile(name="b"))
    assert store.active == "a"          # later sets do not steal active


def test_delete_clears_active(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCCODE_HOME", str(tmp_path))
    store = ProfileStore()
    store.set(Profile(name="a"))
    assert store.delete("a") is True
    assert store.active is None
    assert store.delete("missing") is False


def test_corrupt_store_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCCODE_HOME", str(tmp_path))
    (tmp_path / "profiles.json").write_text("{not json")
    store = ProfileStore.load()
    assert store.profiles == {}
    assert store.active is None


def test_resolve_active_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCCODE_HOME", str(tmp_path))
    s = ProfileStore()
    s.set(Profile(name="a", agent="researcher"))
    s.set(Profile(name="b", agent="debugger"))
    s.use("a")
    s.save()
    assert resolve_active().name == "a"
    monkeypatch.setenv("ARCCODE_PROFILE", "b")
    assert resolve_active().name == "b"


def test_apply_env_does_not_clobber(monkeypatch):
    monkeypatch.setenv("EXISTING", "keep")
    monkeypatch.delenv("FRESH", raising=False)
    applied = apply_env(Profile(name="p", env={"EXISTING": "no", "FRESH": "yes"}))
    assert "FRESH" in applied and "EXISTING" not in applied
    import os
    assert os.environ["EXISTING"] == "keep"      # explicit env wins
    assert os.environ["FRESH"] == "yes"


# --- merge precedence ------------------------------------------------------

def test_merge_profile_fills_gaps():
    p = Profile(name="x", agent="implementer", model="workhorse", yes=True, max_steps=12)
    agent, model, cwd, yes, ms = _merge(
        p, agent=None, model=None, cwd=None, yes=False, max_steps=None)
    assert (agent, model, yes, ms) == ("implementer", "workhorse", True, 12)
    assert cwd == "."


def test_merge_cli_overrides_profile():
    p = Profile(name="x", agent="implementer", model="workhorse")
    agent, model, *_ = _merge(
        p, agent="debugger", model="fast-cheap", cwd=None, yes=False, max_steps=None)
    assert agent == "debugger" and model == "fast-cheap"


def test_merge_without_profile_uses_defaults():
    agent, model, cwd, yes, ms = _merge(
        None, agent=None, model=None, cwd=None, yes=False, max_steps=None)
    assert (agent, model, cwd, yes, ms) == ("coordinator", None, ".", False, 40)


# --- CLI lifecycle ---------------------------------------------------------

def test_cli_profile_set_list_use_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCCODE_HOME", str(tmp_path))

    r = runner.invoke(app, ["profile", "set", "work", "-a", "implementer",
                            "--yes", "-e", "ARCCODE_CONFIG=/tmp/x.yaml", "--activate"])
    assert r.exit_code == 0
    assert (tmp_path / "profiles.json").exists()

    r = runner.invoke(app, ["profile", "list"])
    assert r.exit_code == 0 and "work" in r.stdout

    r = runner.invoke(app, ["profile", "set", "local", "-m", "ollama/qwen2.5-3b"])
    assert r.exit_code == 0
    r = runner.invoke(app, ["profile", "use", "local"])
    assert r.exit_code == 0
    assert ProfileStore.load().active == "local"

    r = runner.invoke(app, ["profile", "delete", "work"])
    assert r.exit_code == 0
    assert "work" not in ProfileStore.load().profiles


def test_cli_profile_use_unknown_errs(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCCODE_HOME", str(tmp_path))
    r = runner.invoke(app, ["profile", "use", "ghost"])
    assert r.exit_code == 1
    assert "Unknown profile" in r.stdout


def test_cli_profile_set_bad_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCCODE_HOME", str(tmp_path))
    r = runner.invoke(app, ["profile", "set", "p", "-e", "NOTAKEYVALUE"])
    assert r.exit_code == 1
    assert "bad --env" in r.stdout
