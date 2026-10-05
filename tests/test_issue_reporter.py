"""Tests for the anonymized issue report."""

from __future__ import annotations

import pytest

from prism_ai_lint.finding import Finding
from prism_ai_lint.issue_reporter import Anonymizer, IssueReporter

TRAPS = [
    "/home/alice/work/secret-project/.claude/settings.json",
    "C:\\Users\\alice\\repo\\x.json",
    "alice@example.com",
    "https://git.internal.example/alice/secret-project.git",
    "10.1.2.3",
    "secret-project",
]


def _anon():
    return Anonymizer(lambda t: t.replace("sk-live-123", "***REDACTED***"), ["alice", "secret-project"])


@pytest.mark.parametrize("trap", TRAPS)
def test_traps_do_not_survive(trap):
    out = _anon().scrub(f"problem with {trap} near sk-live-123")
    assert trap not in out
    assert "sk-live-123" not in out


def test_tokens_are_stable():
    a = _anon()
    assert a.scrub("10.1.2.3 and 10.1.2.3") == "<IP_1> and <IP_1>"


def test_quoted_values_removed_but_codes_kept():
    out = _anon().scrub('server `my-private-server` uses `API_KEY` and "allow"')
    assert "my-private-server" not in out
    assert "API_KEY" in out and '"allow"' in out


def test_extra_patterns_are_removed():
    out = Anonymizer(extra_patterns=[r"ACME-\d+"]).scrub("ticket ACME-42 failed")
    assert "ACME-42" not in out


def test_report_lists_only_unfixed_findings_grouped():
    findings = [
        Finding("warn", "FOO_BAR", "/home/alice/x", "bad `thing` in /home/alice/x", fixable=False),
        Finding("warn", "FOO_BAR", "/home/alice/y", "bad again", fixable=False),
        Finding("info", "FIXED_ONE", "/home/alice/z", "auto", fixable=True),
    ]
    body = IssueReporter(_anon(), "1.2.3").render(findings, ["python-cli"])
    assert "FOO_BAR" in body and "x2" in body
    assert "FIXED_ONE" not in body
    assert "alice" not in body
    assert "python-cli" in body


def test_empty_report():
    assert "None." in IssueReporter(_anon(), "1").render([])


def test_cli_flag_and_env_off(env, monkeypatch):
    ok = env.run("--user-only", "--no-cli", "--report-issue", expect_ok=True)
    assert "Fix request" in ok.stdout
    monkeypatch.setenv("PRISM_AI_LINT_REPORTING", "off")
    off = env.run("--user-only", "--no-cli", "--report-issue", expect_ok=True)
    assert "disabled" in off.stdout
