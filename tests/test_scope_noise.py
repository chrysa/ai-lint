"""User-scope findings must not be repeated in every project report; generated hooks stay lint-clean."""

from __future__ import annotations

import ast

LONG = "x" * 500


def _skill(root, name):
    d = root / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {LONG}\n---\nbody\n")


def test_user_skill_description_not_reported_without_user_scope(linter_module, tmp_path, monkeypatch):
    home = tmp_path / "home"
    _skill(home, "u")
    repo = tmp_path / "repo"
    _skill(repo / ".claude", "p")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    pol = linter_module.load_policy(None, [repo])
    rep = linter_module.Report()
    linter_module.token_budget(repo, False, pol, rep)
    paths = [str(f.path) for f in rep.findings if f.code == "TOKEN_SKILL_DESC"]
    assert len(paths) == 1
    assert "/repo/" in paths[0]


def test_user_skill_description_reported_with_user_scope(linter_module, tmp_path, monkeypatch):
    home = tmp_path / "home"
    _skill(home, "u")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    pol = linter_module.load_policy(None, [tmp_path])
    rep = linter_module.Report()
    linter_module.token_budget(None, True, pol, rep)
    assert [f.code for f in rep.findings].count("TOKEN_SKILL_DESC") == 1


def test_generated_format_hook_has_no_blind_except(linter_module):
    tree = ast.parse(linter_module.FORMAT_HOOK)
    blind = [
        n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and getattr(n.type, "id", None) == "Exception"
    ]
    assert blind == []
