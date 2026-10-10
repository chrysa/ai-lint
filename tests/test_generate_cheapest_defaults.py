"""--generate sets the cheapest model and effort when the project has none, never overrides a choice."""

from __future__ import annotations

import json
import subprocess


def _repo(tmp_path, settings=None):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0"\n')
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    if settings is not None:
        (repo / ".claude").mkdir()
        (repo / ".claude" / "settings.json").write_text(json.dumps(settings))
    return repo


def _generated(m, repo, monkeypatch, tmp_path, **overrides):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    pol = m.load_policy(None, [repo])
    pol["generate"].update(overrides)
    rep = m.Report()
    m.generate_project(repo, pol, rep)
    return json.loads(rep.current(repo / ".claude" / "settings.json"))


def test_defaults_are_the_cheapest(linter_module, tmp_path, monkeypatch):
    data = _generated(linter_module, _repo(tmp_path), monkeypatch, tmp_path)
    assert data["model"] == "haiku"
    assert data["effortLevel"] == "low"


def test_an_existing_choice_is_kept(linter_module, tmp_path, monkeypatch):
    repo = _repo(tmp_path, {"model": "opus", "effortLevel": "high"})
    data = _generated(linter_module, repo, monkeypatch, tmp_path)
    assert (data["model"], data["effortLevel"]) == ("opus", "high")


def test_empty_values_disable_the_defaults(linter_module, tmp_path, monkeypatch):
    data = _generated(linter_module, _repo(tmp_path), monkeypatch, tmp_path, default_model="", default_effort="")
    assert "model" not in data and "effortLevel" not in data


def test_untrusted_policy_values_are_replaced(linter_module, tmp_path, monkeypatch):
    data = _generated(
        linter_module, _repo(tmp_path), monkeypatch, tmp_path, default_model="evil\nroute", default_effort="max; rm"
    )
    assert "model" not in data and "effortLevel" not in data
