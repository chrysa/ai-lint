"""Tests for the compression layers checker."""

from __future__ import annotations

from prism_ai_lint.compression_checker import CompressionChecker

RTK = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "rtk hook claude"}]}]}}
TRIM = {"mcpServers": {"llmtrim": {"command": "llmtrim"}}}
ROUTER = {"env": {"ANTHROPIC_BASE_URL": "http://localhost:20128/v1"}}


def test_single_layer_is_silent():
    c = CompressionChecker()
    assert c.layers([RTK]) == ["rtk"]
    assert c.advice(c.layers([RTK])) is None


def test_two_layers_are_reported():
    c = CompressionChecker()
    layers = c.layers([RTK, TRIM])
    assert layers == ["llmtrim", "rtk"]
    assert "twice" in (c.advice(layers) or "")


def test_local_gateway_counts_as_a_layer():
    assert CompressionChecker().layers([RTK, ROUTER]) == ["router", "rtk"]


def test_remote_base_url_is_not_a_gateway():
    assert CompressionChecker().layers([{"env": {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}}]) == []


def test_non_dict_settings_do_not_crash():
    assert CompressionChecker().layers([[1], None, "x"]) == []


def test_lint_emits_compression_double_as_info(linter_module, tmp_path, monkeypatch):
    import json

    m = linter_module
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "home"))
    dot = tmp_path / "repo" / ".claude"
    dot.mkdir(parents=True)
    (dot / "settings.json").write_text(json.dumps({**RTK, **TRIM}))
    rep = m.Report()
    m.check_compression(tmp_path / "repo", rep)
    assert [(f.level, f.code) for f in rep.findings] == [("info", "COMPRESSION_DOUBLE")]


def _cfg(tmp_path, monkeypatch, user, project):
    import json

    home = tmp_path / "home"
    home.mkdir()
    (home / "settings.json").write_text(json.dumps(user))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    dot = tmp_path / "repo" / ".claude"
    dot.mkdir(parents=True)
    (dot / "settings.json").write_text(json.dumps(project))
    return tmp_path / "repo", home


def test_user_layers_are_not_repeated_in_every_repo(linter_module, tmp_path, monkeypatch):
    repo, _ = _cfg(tmp_path, monkeypatch, {**RTK, **TRIM}, {})
    rep = linter_module.Report()
    linter_module.check_compression(repo, rep)
    assert rep.findings == []


def test_user_double_is_reported_once_at_user_scope(linter_module, tmp_path, monkeypatch):
    _, home = _cfg(tmp_path, monkeypatch, {**RTK, **TRIM}, {})
    rep = linter_module.Report()
    linter_module.lint_user(linter_module.load_policy(None, [tmp_path]), rep, [])
    assert [f.code for f in rep.findings if f.code == "COMPRESSION_DOUBLE"] == ["COMPRESSION_DOUBLE"]


def test_project_layer_on_top_of_user_layer_is_reported(linter_module, tmp_path, monkeypatch):
    repo, _ = _cfg(tmp_path, monkeypatch, RTK, TRIM)
    rep = linter_module.Report()
    linter_module.check_compression(repo, rep)
    assert [f.code for f in rep.findings] == ["COMPRESSION_DOUBLE"]
