"""Contract of the published pre-commit hook (.pre-commit-hooks.yaml)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = (ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")


def _field(name: str) -> str:
    match = re.search(rf"^\s*{name}:\s*(.+)$", MANIFEST, re.MULTILINE)
    assert match, f"{name} missing from .pre-commit-hooks.yaml"
    return match.group(1).strip()


def test_entry_is_a_declared_console_script():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    scripts = pyproject.split("[project.scripts]", 1)[1].split("\n[", 1)[0]
    assert _field("language") == "python"
    assert re.search(rf"^{re.escape(_field('entry'))}\s*=", scripts, re.MULTILINE)


def test_hook_scans_repo_read_only_and_non_interactive():
    args = _field("args")
    assert '"."' in args
    for flag in ("--no-cli", "--no-scaffold", "--no-update-check"):
        assert f'"{flag}"' in args
    for forbidden in ("--fix", "--full-yes", "--generate", "-i", "--interactive", "--user"):
        assert f'"{forbidden}"' not in args
    assert _field("pass_filenames") == "false"


def test_files_filter_targets_agent_config_only():
    pattern = re.compile(_field("files"))
    for path in (
        ".claude/settings.json",
        ".claude/skills/check/SKILL.md",
        ".claude/agents/reviewer.md",
        "CLAUDE.md",
        "CLAUDE.local.md",
        "AGENTS.md",
        ".mcp.json",
        ".ai-lint.toml",
        ".github/workflows/ci.yml",
    ):
        assert pattern.search(path), path
    for path in ("src/app.py", "README.md", "docs/CLAUDE.md.bak", "package.json"):
        assert not pattern.search(path), path


def test_print_policy_matches_the_committed_example_byte_for_byte():
    """The example is regenerated with --print-policy; it must pass end-of-file-fixer as is."""
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, str(ROOT / "ai-lint.py"), "--print-policy"], capture_output=True, text=True, check=True
    ).stdout
    assert out.endswith("\n") and not out.endswith("\n\n")
    assert out == (ROOT / "ai-lint.example.toml").read_text(encoding="utf-8")
