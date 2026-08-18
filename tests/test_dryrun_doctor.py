"""--dry-run planning mode and the richer `doctor` command.

Dry-run must resolve routing/agent/tools/cost *without* calling a model or
writing anything; doctor must report structured checks and a pass/warn/fail
summary. These run under the deterministic catalog (see conftest).
"""
import json

from typer.testing import CliRunner

from arccode.cli import app

runner = CliRunner()


# --- dry run ---------------------------------------------------------------

def test_dry_run_json_shape():
    r = runner.invoke(app, ["run", "Summarize the architecture",
                            "-a", "researcher", "--dry-run", "--json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["dry_run"] is True
    assert data["agent"] == "researcher"
    for key in ("model", "routing", "tools", "cost_estimate_usd", "cost_basis"):
        assert key in data
    assert data["model"]["id"]
    assert isinstance(data["tools"], list) and data["tools"]


def test_dry_run_forced_model_is_reported():
    r = runner.invoke(app, ["run", "do a thing", "-m", "workhorse",
                            "--dry-run", "--json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["routing"]["forced"] is True
    assert data["model"]["key"] == "workhorse"


def test_dry_run_cost_estimate_matches_catalog():
    # workhorse is 3/15 per 1M tokens under the deterministic catalog.
    r = runner.invoke(app, ["run", "x", "-m", "workhorse", "--dry-run", "--json"])
    data = json.loads(r.stdout)
    basis = data["cost_basis"]
    expected = (basis["in_tokens"] / 1_000_000) * basis["in_per_m"] \
        + (basis["out_tokens"] / 1_000_000) * basis["out_per_m"]
    assert abs(data["cost_estimate_usd"] - round(expected, 6)) < 1e-9
    assert basis["in_per_m"] == 3 and basis["out_per_m"] == 15


def test_dry_run_writes_nothing(tmp_path):
    # Point cwd at an empty dir and confirm dry-run leaves it untouched.
    before = {p.name for p in tmp_path.iterdir()}
    r = runner.invoke(app, ["run", "create a file called out.txt",
                            "-a", "implementer", "--cwd", str(tmp_path),
                            "--dry-run"])
    assert r.exit_code == 0
    after = {p.name for p in tmp_path.iterdir()}
    assert before == after                      # no side effects
    assert "no model was called" in r.stdout


def test_dry_run_table_default():
    r = runner.invoke(app, ["run", "hello", "-a", "researcher", "--dry-run"])
    assert r.exit_code == 0
    assert "execution plan" in r.stdout
    assert "est. cost" in r.stdout


def test_dry_run_unknown_agent_errs():
    r = runner.invoke(app, ["run", "hi", "-a", "nope", "--dry-run"])
    assert r.exit_code == 1
    assert "Unknown agent" in r.stdout


# --- doctor ----------------------------------------------------------------

def test_doctor_runs_and_reports_core_checks(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCCODE_HOME", str(tmp_path))
    r = runner.invoke(app, ["doctor"])
    assert r.exit_code == 0
    for label in ("Python", "model catalog", "agents:", "profiles:",
                  "sessions:", "config dir"):
        assert label in r.stdout


def test_doctor_flags_bad_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCCODE_HOME", str(tmp_path))
    monkeypatch.setenv("ARCCODE_CONFIG", str(tmp_path / "missing.yaml"))
    r = runner.invoke(app, ["doctor"])
    assert r.exit_code == 0                       # doctor reports, does not crash
    assert "ARCCODE_CONFIG points to missing file" in r.stdout
    assert "problem(s)" in r.stdout


def test_doctor_reports_saved_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCCODE_HOME", str(tmp_path))
    runner.invoke(app, ["profile", "set", "p1", "-a", "researcher", "--activate"])
    r = runner.invoke(app, ["doctor"])
    assert "profiles: 1 saved, active: p1" in r.stdout
