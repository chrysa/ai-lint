"""The --guard PreToolUse checks (guard_check): block edits that loosen the
configuration, add attribution, or write config through the shell; allow the rest."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from prism_ai_lint.guard_checker import GuardChecker


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
    assert g(guard_module, tool_name="Bash", tool_input={"command": "python3 prism-ai-lint.py . --fix"}) is None


def test_bash_generate_fix_blocked(guard_module):
    r = g(guard_module, tool_name="Bash", tool_input={"command": "prism-ai-lint.py . --generate --fix"})
    assert r and "generate" in r.lower()


def test_bash_interactive_blocked(guard_module):
    assert g(guard_module, tool_name="Bash", tool_input={"command": "prism-ai-lint.py ~ --user -i"})


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
    f = tmp_path / ".claude" / "rules" / "conventions.md"
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
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "prism-ai-lint.py . --generate --fix"}})
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

    import prism_ai_lint.guard_checker as guard_module

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
    assert reason
    assert "new allow rule" in reason


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
    assert linter_module.lint_toml_violations("", "") == ["cannot verify .prism-ai-lint.toml: no TOML parser available"]


@pytest.mark.parametrize(
    ("filename", "old", "new", "expected"),
    [
        (".mcp.json", "{}", '{"mcpServers": {"demo": {"command": "run"}}}', "new MCP server"),
        ("claude_desktop_config.json", "{}", '{"mcpServers": {"demo": {"command": "run"}}}', "new MCP server"),
        (".claude-plugin/plugin.json", "{}", '{"hooks": {}}', "plugin hooks added"),
        (".claude-plugin/marketplace.json", "{}", '{"plugins": [{"name": "demo"}]}', "new marketplace plugin"),
        (
            "hooks/hooks.json",
            '{"hooks": {"PreToolUse": [{"hooks": [{"command": "validate"}]}]}}',
            "{}",
            "hook(s) removed",
        ),
        ("settings.local.json", "{}", "broken", "must stay strict JSON"),
        ("settings.json", "broken", "{}", None),
        (
            ".claude/skills/demo/SKILL.md",
            "---\nallowed-tools: Read\n---\nInspect.\n",
            "---\nallowed-tools: Read Bash\n---\nInspect.\n",
            "allowed-tools extended",
        ),
        (
            ".github/workflows/agent.yml",
            "name: claude-code\n",
            "name: claude-code\npull_request_target:\n",
            "pull_request_target trigger added",
        ),
        ("notes.md", "# Notes\n", "# Updated notes\n", None),
    ],
)
def test_guard_write_dispatch(guard_module, tmp_path, filename, old, new, expected):
    path = tmp_path / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(old)
    reason = guard_module.guard_check(
        {
            "tool_name": "Write",
            "cwd": str(tmp_path),
            "tool_input": {"file_path": filename, "content": new},
        }
    )
    if expected is None:
        assert reason is None
    else:
        assert reason
        assert expected in reason


def test_notebook_edit_still_checks_protected_paths(guard_module, tmp_path):
    reason = guard_module.guard_check(
        {
            "tool_name": "NotebookEdit",
            "cwd": str(tmp_path),
            "tool_input": {"notebook_path": ".git/hooks/demo.ipynb"},
        }
    )
    assert reason
    assert "git hooks" in reason


def test_guard_protects_every_module_of_the_linter_package(linter_module, tmp_path):
    from pathlib import Path

    checker = linter_module._guard_checker()
    package = checker.engine_path.parent
    for name in ("_reference.py", "_runtime.py", "content_validation.py", "report.py", "__init__.py"):
        assert checker.protected_path(package / name) == "the linter itself", name
    assert checker.protected_path(package.parent / "prism-ai-lint.py") == "the linter itself"
    assert checker.protected_path(Path(tmp_path) / "notes.md") is None


def test_guard_runs_as_the_session_hook_launches_it(tmp_path):
    """The session hook runs `python prism_ai_lint/_engine.py --guard` from the agent's cwd.
    An import failure there exits 1, which Claude Code treats as non-blocking."""
    import json
    import subprocess
    import sys
    from pathlib import Path

    engine = Path(__file__).resolve().parent.parent / "prism_ai_lint" / "_engine.py"
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"permissions": {"deny": ["Read(./.env)"]}}))
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(settings), "content": json.dumps({"permissions": {"deny": []}})},
    }
    res = subprocess.run(
        [sys.executable, str(engine), "--guard"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        timeout=60,
    )
    assert "ModuleNotFoundError" not in res.stderr
    assert res.returncode == 2, res.stderr


def test_guard_blocks_on_a_broken_policy_and_skips_repo_plugins(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path

    engine = Path(__file__).resolve().parent.parent / "prism_ai_lint" / "_engine.py"
    (tmp_path / ".claude-lint.toml").write_text("not = [valid toml\n")
    plugins = tmp_path / ".prism-ai-lint" / "plugins"
    plugins.mkdir(parents=True)
    marker = tmp_path / "plugin-ran"
    (plugins / "evil.py").write_text(f"open({str(marker)!r}, 'w').write('x')\n")
    payload = {"tool_name": "Read", "tool_input": {"file_path": str(tmp_path / "a.txt")}}
    res = subprocess.run(
        [sys.executable, str(engine), "--guard"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        timeout=60,
    )
    assert res.returncode == 2, res.stderr
    assert not marker.exists()


@pytest.mark.parametrize(
    "command",
    [
        "sed -i s/x/y/ prism_ai_lint/guard_checker.py",
        "echo x > prism_ai_lint/_reference.py",
        "cp evil.py .prism-ai-lint/plugins/evil.py",
        "echo 'x=1' > .claude-lint.toml",
    ],
)
def test_bash_cannot_rewrite_the_linter_or_its_policy(guard_module, command):
    assert g(guard_module, tool_name="Bash", tool_input={"command": command}) is not None


def test_linter_runs_through_the_engine_path_follow_the_same_rules(guard_module):
    engine = "/opt/x/.venv/bin/python3 /opt/x/prism_ai_lint/_engine.py"
    assert g(guard_module, tool_name="Bash", tool_input={"command": f"{engine} . --details"}) is None
    assert g(guard_module, tool_name="Bash", tool_input={"command": f"{engine} . --fix"}) is None
    for flag in ("--policy p.toml", "--full-yes", "--plugin-dir /tmp/p", "-i"):
        cmd = f"{engine} . {flag}"
        assert g(guard_module, tool_name="Bash", tool_input={"command": cmd}) is not None, flag
