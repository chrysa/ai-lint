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


def test_token_budget_before_after(linter_module):
    m = linter_module
    after = {"total": 5000, "sums": {}, "counts": {}, "groups": []}
    out = m.render_token_budget(after, color=False, before={"total": 8000})
    assert "was ~8000" in out and "-3000" in out


def test_token_budget_potential(linter_module):
    m = linter_module
    b = {"total": 5000, "sums": {}, "counts": {}, "groups": [], "potential": 1200}
    out = m.render_token_budget(b, color=False)
    assert "~1200 tokens/session reclaimable" in out
