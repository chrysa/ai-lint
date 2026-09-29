"""Non-fixable findings explain WHY in the report, so a recurring 'same output'
is self-evident (human judgment / content rewrite / history)."""

from __future__ import annotations


def test_why_manual_known_codes(linter_module):
    m = linter_module
    for code in ("IMPORT_MISSING", "SKILL_MISSING", "INSTR_LONG", "PERM_EXEC_RUNNER", "API_KEY_LEAK"):
        assert m._why_manual(code), code


def test_why_manual_unknown_is_empty(linter_module):
    assert linter_module._why_manual("JSON_REPAIRED") == ""


def test_report_shows_reason(env):
    repo = env.repos[0]
    (repo / ".claude" / "skills" / "broken").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "skills" / "broken" / "notes.txt").write_text("x")
    out = env.run(str(repo), "--details", "--no-cli").stdout
    assert "not auto-fixed:" in out
