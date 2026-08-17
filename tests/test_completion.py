"""Shell tab-completion: dynamic value completers + the `completion` command.

These exercise the real completers (agents come from the on-disk registry, models
from the catalog) and the install flow that wires a loader into a shell rc.
"""
import pathlib

from typer.testing import CliRunner

from arccode.cli import _complete_agents, _complete_models, app

runner = CliRunner()


def test_complete_agents_lists_builtin_agents():
    names = [name for name, _help in _complete_agents("")]
    # the six built-in agents must be offered
    for expected in ("coordinator", "researcher", "implementer", "architect",
                     "debugger", "reviewer"):
        assert expected in names


def test_complete_agents_respects_prefix():
    names = [n for n, _ in _complete_agents("re")]
    assert names == sorted(names)                 # stable, sorted order
    assert all(n.startswith("re") for n in names)
    assert "researcher" in names and "reviewer" in names
    assert "coordinator" not in names


def test_complete_models_prefix_filters_catalog():
    # Under the deterministic test catalog, models are tier aliases.
    keys = [k for k, _id in _complete_models("work")]
    assert keys == ["workhorse"]


def test_complete_models_empty_prefix_returns_many():
    keys = [k for k, _ in _complete_models("")]
    assert len(keys) >= 3
    assert keys == sorted(keys)   # stable, sorted order


def test_completion_command_prints_script_for_bash():
    result = runner.invoke(app, ["completion", "bash"])
    assert result.exit_code == 0
    # Click/Typer bash completion scripts define this function.
    assert "_arccode_completion" in result.stdout


def test_completion_rejects_unknown_shell():
    result = runner.invoke(app, ["completion", "tcsh"])
    assert result.exit_code == 1
    assert "unsupported shell" in result.stdout


def test_completion_install_wires_loader_into_bashrc(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    result = runner.invoke(app, ["completion", "bash", "--install"])
    assert result.exit_code == 0
    rc = tmp_path / ".bashrc"
    assert rc.exists()
    body = rc.read_text()
    assert "arccode shell completion" in body
    assert "completion.bash" in body
    # the generated script itself was written out
    assert (tmp_path / ".arccode" / "completion.bash").exists()

    # running again is idempotent (no duplicate loader lines)
    result2 = runner.invoke(app, ["completion", "bash", "--install"])
    assert result2.exit_code == 0
    assert "already installed" in result2.stdout
    assert rc.read_text().count("source ") == 1


def test_completion_install_fish_writes_completions_file(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    result = runner.invoke(app, ["completion", "fish", "--install"])
    assert result.exit_code == 0
    dest = tmp_path / ".config" / "fish" / "completions" / "arccode.fish"
    assert dest.exists() and dest.read_text().strip()
