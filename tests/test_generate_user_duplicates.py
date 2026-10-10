"""--generate does not copy into a project what the user scope already has."""

from __future__ import annotations

import subprocess


def _py_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0"\n')
    (repo / "Makefile").write_text("lint:\n\ttrue\ntest:\n\ttrue\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def _generate(m, repo, policy_overrides=None):
    pol = m.load_policy(None, [repo])
    if policy_overrides:
        pol["generate"].update(policy_overrides)
    rep = m.Report()
    m.generate_project(repo, pol, rep)
    return rep


def _cfg(tmp_path, monkeypatch, skills=(), agents=()):
    cfg = tmp_path / "cfg"
    for s in skills:
        (cfg / "skills" / s).mkdir(parents=True)
        (cfg / "skills" / s / "SKILL.md").write_text(f"---\nname: {s}\ndescription: mine\n---\n")
    for a in agents:
        (cfg / "agents" / "pack").mkdir(parents=True, exist_ok=True)
        (cfg / "agents" / "pack" / f"{a}.md").write_text(f"---\nname: {a}\ndescription: mine\n---\n")
    cfg.mkdir(exist_ok=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))


def test_a_skill_the_user_scope_has_is_not_copied(linter_module, tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch, skills=["check"])
    repo = _py_repo(tmp_path)
    rep = _generate(linter_module, repo)
    created = {p.parent.name for p in rep.new_files if p.name == "SKILL.md"}
    assert "check" not in created
    assert "review-changes" in created
    skipped = [f for f in rep.findings if f.code == "GENERATE_SKIPPED"]
    assert len(skipped) == 1
    assert "skill /check" in skipped[0].message
    assert skipped[0].level == "info"


def test_an_agent_found_in_a_user_subfolder_is_not_copied(linter_module, tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch, agents=["code-reviewer"])
    rep = _generate(linter_module, _py_repo(tmp_path))
    created = {p.stem for p in rep.new_files if p.parent.name == "agents"}
    assert "code-reviewer" not in created
    assert "security-auditor" in created


def test_nothing_changes_without_a_user_duplicate(linter_module, tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    rep = _generate(linter_module, _py_repo(tmp_path))
    assert [f for f in rep.findings if f.code == "GENERATE_SKIPPED"] == []
    assert any(p.parent.name == "check" for p in rep.new_files)


def test_the_policy_key_restores_the_copy(linter_module, tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch, skills=["check"], agents=["code-reviewer"])
    rep = _generate(linter_module, _py_repo(tmp_path), {"skip_user_duplicates": False})
    assert any(p.parent.name == "check" for p in rep.new_files)
    assert any(p.stem == "code-reviewer" for p in rep.new_files)
    assert [f for f in rep.findings if f.code == "GENERATE_SKIPPED"] == []


def test_an_existing_project_file_is_left_alone(linter_module, tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch, skills=["check"])
    repo = _py_repo(tmp_path)
    (repo / ".claude" / "skills" / "check").mkdir(parents=True)
    (repo / ".claude" / "skills" / "check" / "SKILL.md").write_text("mine\n")
    rep = _generate(linter_module, repo)
    assert [f for f in rep.findings if f.code == "GENERATE_SKIPPED"] == []
