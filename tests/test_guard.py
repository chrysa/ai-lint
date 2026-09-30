"""The --guard PreToolUse checks (guard_check): block edits that loosen the
configuration, add attribution, or write config through the shell; allow the rest."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from ai_lint.guard_checker import GuardChecker


@pytest.fixture(params=["legacy", "class"])
def guard_module(request, linter_module):
    if request.param == "legacy":
        return linter_module
    checker = linter_module._guard_checker()
    assert isinstance(checker, GuardChecker)
    return SimpleNamespace(guard_check=checker.guard_check, run_guard=checker.run_guard, sys=linter_module.sys)


def g(m, **data):
    return m.guard_check(data)


def test_bash_linter_allowed(guard_module):
    assert g(guard_module, tool_name="Bash", tool_input={"command": "python3 ai-lint.py . --fix"}) is None


def test_bash_generate_fix_blocked(guard_module):
    r = g(guard_module, tool_name="Bash", tool_input={"command": "ai-lint.py . --generate --fix"})
    assert r and "generate" in r.lower()


def test_bash_interactive_blocked(guard_module):
    assert g(guard_module, tool_name="Bash", tool_input={"command": "ai-lint.py ~ --user -i"})


def test_bash_attribution_blocked(guard_module):
    r = g(
        guard_module,
        tool_name="Bash",
        tool_input={"command": "git commit -m 'x\n\nCo-Authored" + "-By: Claude'"},
    )
    assert r and "attribution" in r.lower()


def test_bash_config_write_via_shell_blocked(guard_module):
    r = g(guard_module, tool_name="Bash", tool_input={"command": "echo '{}' > .claude/settings.json"})
    assert r and "Edit/Write" in r


def test_plain_bash_allowed(guard_module):
    assert g(guard_module, tool_name="Bash", tool_input={"command": "ls -al"}) is None


def test_edit_adding_allow_rule_blocked(guard_module, tmp_path):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"permissions": {"allow": [], "deny": ["Read(**/.env)"]}}))
    old = '"allow": []'
    new = '"allow": ["Bash(rm -rf /*)"]'
    r = g(
        guard_module,
        tool_name="Edit",
        tool_input={"file_path": str(s), "old_string": old, "new_string": new},
    )
    assert r  # loosening blocked


def test_edit_benign_comment_allowed(guard_module, tmp_path):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"permissions": {"allow": [], "deny": []}}, indent=2))
    r = g(
        guard_module,
        tool_name="Edit",
        tool_input={
            "file_path": str(s),
            "old_string": '"deny": []',
            "new_string": '"deny": ["Read(**/.env)"]',
        },
    )
    assert r is None  # tightening is fine


def test_edit_attribution_into_file_blocked(guard_module, tmp_path):
    f = tmp_path / "CLAUDE.md"
    f.write_text("# notes\n")
    trailer = "Generated with " + "Claude Code"  # built from parts: not a real trace
    r = g(
        guard_module,
        tool_name="Edit",
        tool_input={
            "file_path": str(f),
            "old_string": "# notes",
            "new_string": "# notes\n" + trailer,
        },
    )
    assert r and "attribution" in r.lower()


def test_edit_critical_content_requires_validation(guard_module, tmp_path):
    f = tmp_path / "README.md"
    f.write_text("# Project\n")

    r = g(
        guard_module,
        tool_name="Edit",
        cwd=str(tmp_path),
        tool_input={
            "file_path": str(f),
            "old_string": "# Project",
            "new_string": "# Project\n\nUpdated scope.",
        },
    )

    assert r and "validation" in r.lower()


def test_write_critical_rule_requires_validation(guard_module, tmp_path):
    f = tmp_path / ".claude" / "rules" / "shared-standards.md"
    f.parent.mkdir(parents=True)
    f.write_text("# Rules\n")

    r = g(
        guard_module,
        tool_name="Write",
        cwd=str(tmp_path),
        tool_input={"file_path": str(f), "content": "# Rules\n\nChanged.\n"},
    )

    assert r and "critical content" in r.lower()


def test_noncritical_content_edit_allowed(guard_module, tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("# Notes\n")

    r = g(
        guard_module,
        tool_name="Edit",
        cwd=str(tmp_path),
        tool_input={"file_path": str(f), "old_string": "# Notes", "new_string": "# Notes\n\nMore."},
    )

    assert r is None


def test_unrelated_tool_ignored(guard_module):
    assert g(guard_module, tool_name="Read", tool_input={"file_path": "/x"}) is None


def test_run_guard_blocks_with_exit_2(guard_module, monkeypatch, capsys):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ai-lint.py . --generate --fix"}})
    monkeypatch.setattr(guard_module.sys, "stdin", __import__("io").StringIO(payload))
    rc = guard_module.run_guard()
    assert rc == 2


def test_run_guard_allows_with_exit_0(guard_module, monkeypatch):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
    monkeypatch.setattr(guard_module.sys, "stdin", __import__("io").StringIO(payload))
    assert guard_module.run_guard() == 0


def test_run_guard_fails_closed_on_bad_json(guard_module, monkeypatch):
    monkeypatch.setattr(guard_module.sys, "stdin", __import__("io").StringIO("not json"))
    assert guard_module.run_guard() == 2


def test_guard_protects_original_engine_path(linter_module):
    checker = linter_module._guard_checker()
    assert checker.protected_path(checker.engine_path) == "the linter itself"
    from pathlib import Path

    import ai_lint.guard_checker as guard_module

    assert checker.protected_path(Path(guard_module.__file__)) == "the linter itself"


def test_guard_run_fails_closed_on_internal_error(linter_module):
    checker = linter_module._guard_checker()
    errors = io.StringIO()
    payload = io.StringIO('{"tool_name": "Edit", "tool_input": 42}')
    assert checker.run_guard(stdin=payload, stderr=errors) == 2
    assert "internal error, blocking by default" in errors.getvalue()


def test_guard_wrapper_uses_current_dependencies(linter_module, monkeypatch, tmp_path):
    monkeypatch.setattr(linter_module, "config_dir", lambda: tmp_path)
    plugin = tmp_path / ".claude" / "plugins" / "demo.json"
    assert linter_module.protected_path(plugin) == "installed plugins (managed by the CLI)"


def test_multiedit_loosening_blocked(guard_module, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"permissions": {"allow": [], "deny": []}}')
    reason = guard_module.guard_check(
        {
            "tool_name": "MultiEdit",
            "cwd": str(tmp_path),
            "tool_input": {
                "file_path": "settings.json",
                "edits": [{"old_string": '"allow": []', "new_string": '"allow": ["Bash(*)"]'}],
            },
        }
    )
    assert reason and "new allow rule" in reason


def test_guard_json_repair_and_invalid_output(linter_module):
    checker = linter_module._guard_checker()
    assert checker._guard_json("broken", "{}", "settings") == ({}, {})
    assert "must stay strict JSON" in checker._guard_json("{}", "broken", "settings")


def test_guard_settings_hook_removal(linter_module):
    checker = linter_module._guard_checker()
    hooks = {"PreToolUse": [{"hooks": [{"command": "validate"}]}]}
    assert checker.settings_violations({"hooks": hooks}, {}) == ["hook(s) removed: PreToolUse:validate"]


def test_guard_mcp_command_change(linter_module):
    checker = linter_module._guard_checker()
    old = {"mcpServers": {"demo": {"command": "safe"}}}
    new = {"mcpServers": {"demo": {"command": "other"}}}
    assert checker.mcp_violations(old, new) == ["MCP server 'demo' command/url changed"]


def test_guard_frontmatter_extension(linter_module):
    checker = linter_module._guard_checker()
    old = "---\nallowed-tools: Read\n---\nInspect.\n"
    new = "---\nallowed-tools: Read Bash\n---\nInspect.\n"
    assert checker.frontmatter_violations(old, new) == ["allowed-tools extended"]


def test_guard_toml_parser_unavailable(linter_module, monkeypatch):
    monkeypatch.setattr(linter_module, "tomllib", None)
    assert linter_module.lint_toml_violations("", "") == ["cannot verify .ai-lint.toml without Python 3.11"]
