"""The detailed report quantifies the token gain per finding and a total."""

from __future__ import annotations


def _f(m, code, msg, level="warn"):
    return m.Finding(level, code, "/x/a", msg, False)


def test_finding_gain_parses_message(linter_module):
    m = linter_module
    assert m._finding_gain(_f(m, "TOKEN_AGENT_PACK", "80 subagents ~3186 tokens")) == 3186
    assert m._finding_gain(_f(m, "TOKEN_SKILL_DESC", "description 464 chars")) == (464 - 400) // 4
    assert m._finding_gain(_f(m, "RULE_UNSCOPED", "no 'paths'")) == 60
    assert m._finding_gain(_f(m, "SKILL_NAME", "rename")) == 0


def test_details_report_shows_total(env, linter_module):
    proc = env.run(str(env.repos[0]), "--user", "--no-cli", "--no-history", "--details", "--lang", "en", expect_ok=True)
    assert "Potential savings:" in proc.stdout
    assert "tokens/session" in proc.stdout
