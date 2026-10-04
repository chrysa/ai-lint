"""HookChecker in isolation: no engine state, injected secret scan."""

from __future__ import annotations

from ai_lint.hook_checker import HookChecker
from ai_lint.report import Report


def _checker(calls=None):
    def env_secrets(mapping, path, rep, ctx):
        if calls is not None:
            calls.append(ctx)
        return {k: "${REDACTED}" for k in mapping}

    return HookChecker(check_env_secrets=env_secrets)


def _codes(rep):
    return {(f.level, f.code) for f in rep.findings}


def test_non_object_hooks_is_an_error_and_left_unchanged(tmp_path):
    rep = Report()
    assert _checker().check_hooks([], tmp_path, tmp_path / "settings.json", rep, "project") == []
    assert ("error", "HOOK_SHAPE") in _codes(rep)


def test_unknown_event_is_reported_and_valid_handler_kept(tmp_path):
    rep = Report()
    hooks = {"NoSuchEvent": [{"hooks": [{"type": "command", "command": "true"}]}]}
    fixed = _checker().check_hooks(hooks, tmp_path, tmp_path / "settings.json", rep, "project")
    assert ("warn", "HOOK_EVENT") in _codes(rep)
    assert fixed["NoSuchEvent"][0]["hooks"][0]["command"] == "true"


def test_http_headers_go_through_the_injected_secret_scan(tmp_path):
    calls: list[str] = []
    rep = Report()
    hooks = {"PostToolUse": [{"hooks": [{"type": "http", "url": "https://example.test", "headers": {"X": "v"}}]}]}
    fixed = _checker(calls).check_hooks(hooks, tmp_path, tmp_path / "settings.json", rep, "project")
    assert calls == ["hooks.PostToolUse.headers"]
    assert fixed["PostToolUse"][0]["hooks"][0]["headers"] == {"X": "${REDACTED}"}


def test_resolve_script_anchors_project_dir_and_ignores_bare_commands(tmp_path):
    checker = _checker()
    assert checker.resolve_script("${CLAUDE_PROJECT_DIR}/hooks/x.sh", tmp_path) == tmp_path / "hooks" / "x.sh"
    assert checker.resolve_script("echo", tmp_path) is None
    assert checker.resolve_script("$OTHER/x.sh", tmp_path) is None
