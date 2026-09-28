"""The --guard PreToolUse checks (guard_check): block edits that loosen the
configuration, add attribution, or write config through the shell; allow the rest."""

from __future__ import annotations

import json


def g(m, **data):
    return m.guard_check(data)


def test_bash_linter_allowed(linter_module):
    assert (
        g(linter_module, tool_name="Bash", tool_input={"command": "python3 claude-lint.py . --fix"})
        is None
    )


def test_bash_generate_fix_blocked(linter_module):
    r = g(
        linter_module, tool_name="Bash", tool_input={"command": "claude-lint.py . --generate --fix"}
    )
    assert r and "generate" in r.lower()


def test_bash_interactive_blocked(linter_module):
    assert g(linter_module, tool_name="Bash", tool_input={"command": "claude-lint.py ~ --user -i"})


def test_bash_attribution_blocked(linter_module):
    r = g(
        linter_module,
        tool_name="Bash",
        tool_input={"command": "git commit -m 'x\n\nCo-Authored" + "-By: Claude'"},
    )
    assert r and "attribution" in r.lower()


def test_bash_config_write_via_shell_blocked(linter_module):
    r = g(
        linter_module, tool_name="Bash", tool_input={"command": "echo '{}' > .claude/settings.json"}
    )
    assert r and "Edit/Write" in r


def test_plain_bash_allowed(linter_module):
    assert g(linter_module, tool_name="Bash", tool_input={"command": "ls -al"}) is None


def test_edit_adding_allow_rule_blocked(linter_module, tmp_path):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"permissions": {"allow": [], "deny": ["Read(**/.env)"]}}))
    old = '"allow": []'
    new = '"allow": ["Bash(rm -rf /*)"]'
    r = g(
        linter_module,
        tool_name="Edit",
        tool_input={"file_path": str(s), "old_string": old, "new_string": new},
    )
    assert r  # loosening blocked


def test_edit_benign_comment_allowed(linter_module, tmp_path):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"permissions": {"allow": [], "deny": []}}, indent=2))
    r = g(
        linter_module,
        tool_name="Edit",
        tool_input={
            "file_path": str(s),
            "old_string": '"deny": []',
            "new_string": '"deny": ["Read(**/.env)"]',
        },
    )
    assert r is None  # tightening is fine


def test_edit_attribution_into_file_blocked(linter_module, tmp_path):
    f = tmp_path / "CLAUDE.md"
    f.write_text("# notes\n")
    trailer = "Generated with " + "Claude Code"  # built from parts: not a real trace
    r = g(
        linter_module,
        tool_name="Edit",
        tool_input={
            "file_path": str(f),
            "old_string": "# notes",
            "new_string": "# notes\n" + trailer,
        },
    )
    assert r and "attribution" in r.lower()


def test_unrelated_tool_ignored(linter_module):
    assert g(linter_module, tool_name="Read", tool_input={"file_path": "/x"}) is None


def test_run_guard_blocks_with_exit_2(linter_module, monkeypatch, capsys):
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "claude-lint.py . --generate --fix"}}
    )
    monkeypatch.setattr(linter_module.sys, "stdin", __import__("io").StringIO(payload))
    rc = linter_module.run_guard()
    assert rc == 2


def test_run_guard_allows_with_exit_0(linter_module, monkeypatch):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
    monkeypatch.setattr(linter_module.sys, "stdin", __import__("io").StringIO(payload))
    assert linter_module.run_guard() == 0


def test_run_guard_fails_closed_on_bad_json(linter_module, monkeypatch):
    monkeypatch.setattr(linter_module.sys, "stdin", __import__("io").StringIO("not json"))
    assert linter_module.run_guard() == 2
