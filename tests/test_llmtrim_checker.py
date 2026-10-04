"""Tests for llmtrim integration checker."""

from __future__ import annotations

from ai_lint.llmtrim_checker import LlmtrimChecker


def test_llmtrim_checker_is_installed():
    checker = LlmtrimChecker()
    # Just check it doesn't crash; llmtrim may or may not be installed
    result = checker.is_installed()
    assert isinstance(result, bool)


def test_llmtrim_checker_is_configured(tmp_path):
    checker = LlmtrimChecker()
    config = tmp_path / "settings.json"
    config.write_text('{"model": "claude-opus"}')
    assert checker.is_configured(config) is False


def test_llmtrim_checker_is_configured_with_llmtrim(tmp_path):
    checker = LlmtrimChecker()
    config = tmp_path / "settings.json"
    config.write_text('{"mcpServers": {"llmtrim": {}}}')
    assert checker.is_configured(config) is True


def test_llmtrim_checker_get_status():
    checker = LlmtrimChecker()
    status = checker.get_status()
    # Status is None if not installed, string if installed and running
    assert status is None or isinstance(status, str)


def test_llmtrim_checker_recommendation_heavy_context_not_configured(tmp_path):
    checker = LlmtrimChecker()
    config = tmp_path / "settings.json"
    config.write_text("{}")
    rec = checker.recommendation(token_budget=15000, is_configured=False)
    # Recommendation depends on whether llmtrim is installed
    if checker.is_installed():
        assert "configured" in (rec or "").lower()
    else:
        assert "install" in (rec or "").lower()


def test_llmtrim_checker_recommendation_light_context():
    checker = LlmtrimChecker()
    rec = checker.recommendation(token_budget=5000, is_configured=False)
    assert rec is None


def test_llmtrim_checker_recommendation_configured():
    checker = LlmtrimChecker()
    rec = checker.recommendation(token_budget=15000, is_configured=True)
    assert rec is None


def test_llmtrim_not_configured_by_unrelated_mcp_server(tmp_path):
    config = tmp_path / "settings.json"
    config.write_text('{"mcpServers": {"github": {"command": "gh"}}}')
    assert LlmtrimChecker().is_configured(config) is False


def test_llmtrim_non_object_settings_do_not_crash(tmp_path):
    config = tmp_path / "settings.json"
    config.write_text("[1, 2]")
    assert LlmtrimChecker().is_configured(config) is False


def test_recommendation_uses_the_given_threshold():
    checker = LlmtrimChecker()
    assert checker.recommendation(9000, False, threshold=8000, installed=False) is not None
    assert checker.recommendation(9000, False, threshold=12000, installed=False) is None


def test_token_budget_suggests_llmtrim_only_when_missing(linter_module, tmp_path, monkeypatch):
    m = linter_module
    big = tmp_path / "CLAUDE.md"
    big.write_text("- rule line that is long enough to weigh something\n" * 2000)
    pol = m.load_policy(None, [tmp_path])
    for path, expected in ((None, True), ("/usr/bin/llmtrim", False)):
        monkeypatch.setitem(m.LLMTRIM, "checked_cli", True)
        monkeypatch.setitem(m.LLMTRIM, "path", path)
        rep = m.Report()
        m.token_budget(tmp_path, False, pol, rep)
        assert ("LLMTRIM_SUGGESTED" in {f.code for f in rep.findings}) is expected
