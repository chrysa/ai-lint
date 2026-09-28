"""--min-level hides findings below the chosen severity."""

from __future__ import annotations


def test_visible_findings_filters(linter_module, monkeypatch):
    m = linter_module
    monkeypatch.setattr(m, "MIN_LEVEL", "warn")
    fs = [m.Finding("error", "E", "/a", "m"), m.Finding("warn", "W", "/a", "m"), m.Finding("info", "I", "/a", "m")]
    codes = {f.code for f in m.visible_findings(fs)}
    assert codes == {"E", "W"}


def test_min_level_error_only(linter_module, monkeypatch):
    m = linter_module
    monkeypatch.setattr(m, "MIN_LEVEL", "error")
    fs = [m.Finding("error", "E", "/a", "m"), m.Finding("warn", "W", "/a", "m")]
    assert {f.code for f in m.visible_findings(fs)} == {"E"}


def test_min_level_cli_drops_info(env):
    proc = env.run("--user-only", "--no-cli", "--details", "--min-level", "warn", expect_ok=True)
    assert "INFO " not in proc.stdout
