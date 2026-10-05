"""Configurable model / effort / scope: the token checks read the policy
instead of hard-coded values, and per-type scope expectations fire findings."""

from __future__ import annotations

import json


def _policy(m, **tokens):
    pol = m.load_policy(None, [])
    pol["tokens"].update(tokens)
    return pol


def test_heavy_model_flagged_from_policy(linter_module, tmp_path, monkeypatch):
    m = linter_module
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "settings.json").write_text(json.dumps({"model": "sonnet"}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    rep = m.Report()
    # sonnet is heavy under this policy, opus is not -> the check reads the list
    m.check_token_levers(tmp_path, _policy(m, heavy_models=["sonnet"], preferred_model="haiku"), rep)
    assert any(f.code == "TOKEN_MODEL" for f in rep.findings)


def test_preferred_model_not_flagged(linter_module, tmp_path, monkeypatch):
    m = linter_module
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "settings.json").write_text(json.dumps({"model": "sonnet"}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    rep = m.Report()
    m.check_token_levers(tmp_path, _policy(m, heavy_models=["opus"]), rep)
    assert not any(f.code == "TOKEN_MODEL" for f in rep.findings)


def test_effort_above_ceiling_flagged(linter_module, tmp_path, monkeypatch):
    m = linter_module
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "settings.json").write_text(json.dumps({"effortLevel": "high"}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    rep = m.Report()
    m.check_effort_levels(tmp_path, _policy(m, max_effort="medium"), rep)
    assert any(f.code == "TOKEN_EFFORT" for f in rep.findings)


def test_effort_at_ceiling_ok(linter_module, tmp_path, monkeypatch):
    m = linter_module
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "settings.json").write_text(json.dumps({"effortLevel": "medium"}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    rep = m.Report()
    m.check_effort_levels(tmp_path, _policy(m, max_effort="high"), rep)
    assert not any(f.code == "TOKEN_EFFORT" for f in rep.findings)


def test_effort_check_disabled_by_empty_ceiling(linter_module, tmp_path, monkeypatch):
    m = linter_module
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "settings.json").write_text(json.dumps({"effortLevel": "high"}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    rep = m.Report()
    m.check_effort_levels(tmp_path, _policy(m, max_effort=""), rep)
    assert not any(f.code == "TOKEN_EFFORT" for f in rep.findings)


def test_scope_secret_in_committed_settings(linter_module, tmp_path):
    m = linter_module
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / "settings.json").write_text(json.dumps({"env": {"API_KEY": "sk-live-abc"}}))
    rep = m.Report()
    m.check_scopes(repo, m.load_policy(None, [repo]), rep)
    assert any(f.code == "SCOPE_SECRET" for f in rep.findings)


def test_scope_secret_allowed_when_policy_permits_project(linter_module, tmp_path):
    m = linter_module
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / "settings.json").write_text(json.dumps({"env": {"API_KEY": "x"}}))
    pol = m.load_policy(None, [repo])
    pol["scopes"]["secret"] = ["project", "local"]
    rep = m.Report()
    m.check_scopes(repo, pol, rep)
    assert not any(f.code == "SCOPE_SECRET" for f in rep.findings)


def test_scope_mismatch_project_skill_when_user_only(linter_module, tmp_path):
    m = linter_module
    repo = tmp_path / "repo"
    sk = repo / ".claude" / "skills" / "demo"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\nbody\n")
    pol = m.load_policy(None, [repo])
    pol["scopes"]["skill"] = ["user"]
    rep = m.Report()
    m.check_scopes(repo, pol, rep)
    assert any(f.code == "SCOPE_MISMATCH" for f in rep.findings)


def test_scopes_configurable_via_toml(linter_module, tmp_path):
    m = linter_module
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".prism-ai-lint.toml").write_text('[scopes]\nsecret = ["project", "local"]\n')
    pol = m.load_policy(None, [repo])
    assert pol["scopes"]["secret"] == ["project", "local"]
    assert pol["tokens"]["preferred_model"] == "sonnet"  # untouched default survives merge
