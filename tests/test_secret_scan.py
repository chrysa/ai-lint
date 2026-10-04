"""InlineSecretScanner modes: report, reference, remove; env references are left alone."""

from __future__ import annotations

from pathlib import Path

from ai_lint.report import Report
from ai_lint.secret_scan import InlineSecretScanner

ENV = {"API_TOKEN": "literal-value-not-secret", "SAFE": "${FROM_ENV}", "PORT": "8080"}


def _scan(mode, path=Path("/repo/.claude/settings.json")):
    rep = Report()
    out = InlineSecretScanner().check_env_secrets(dict(ENV), path, rep, "env", mode)
    return out, [(f.level, f.code, f.fixable) for f in rep.findings]


def test_report_mode_flags_without_changing_values():
    out, findings = _scan("report")
    assert out == ENV
    assert findings == [("error", "SECRET_INLINE", False)]


def test_reference_mode_replaces_literal_by_env_reference():
    out, findings = _scan("reference")
    assert out["API_TOKEN"] == "${API_TOKEN}"
    assert out["SAFE"] == "${FROM_ENV}" and out["PORT"] == "8080"
    assert findings == [("error", "SECRET_INLINE", True)]


def test_remove_mode_drops_only_the_literal_secret():
    out, _findings = _scan("remove")
    assert "API_TOKEN" not in out
    assert out["SAFE"] == "${FROM_ENV}"


def test_read_only_claude_json_is_reported_as_warning():
    _out, findings = _scan("report", Path("/home/u/.claude.json"))
    assert findings == [("warn", "SECRET_INLINE", False)]
