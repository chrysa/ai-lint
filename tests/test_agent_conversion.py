"""Conversion previews preserve instructions and never apply critical edits."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ai_lint.agent_converter import AgentConverter

ROOT = Path(__file__).resolve().parents[1]


def converter():
    return AgentConverter(lambda text: text)


@pytest.mark.parametrize(
    ("source", "target", "filename", "output"),
    [
        ("claude", "codex", "CLAUDE.md", "AGENTS.md"),
        ("codex", "claude", "AGENTS.md", "CLAUDE.md"),
        ("agents", "claude", "AGENTS.md", "CLAUDE.md"),
        ("claude", "agents", "CLAUDE.md", "AGENTS.md"),
    ],
)
def test_lossless_mapping(tmp_path, source, target, filename, output):
    text = "# Safety\nNever loosen permissions.\nAsk for human validation.\n\n# Checks\nRun pytest before merge.\n"
    (tmp_path / filename).write_text(text)
    plan = converter().plan(tmp_path, source, target)
    assert plan["output"]["path"] == output
    assert plan["output"]["content"] == text
    assert plan["complete"]
    assert plan["requires_human_validation"]
    assert not plan["applied"]
    assert not (tmp_path / output).exists()


def test_all_claude_sources_and_duplicates_preserved(tmp_path):
    (tmp_path / ".claude/rules").mkdir(parents=True)
    rule = "Never change critical content without human approval.\n"
    (tmp_path / "CLAUDE.md").write_text(rule)
    (tmp_path / ".claude/CLAUDE.md").write_text("Keep the runtime standard library only.\n")
    (tmp_path / ".claude/rules/security.md").write_text(rule)
    plan = converter().plan(tmp_path, "claude", "codex")
    assert len(plan["canonical"]["documents"]) == 3
    assert plan["output"]["content"].count(rule) == 2
    assert "DUPLICATE_RULE" in {d["code"] for d in plan["diagnostics"]}


def test_unmapped_rules_imports_and_settings_block_completion(tmp_path):
    (tmp_path / ".claude/rules").mkdir(parents=True)
    text = '---\npaths: ["src/**"]\n---\nNever bypass validation.\nSee @../private.md\n'
    (tmp_path / ".claude/rules/safety.md").write_text(text)
    (tmp_path / ".claude/settings.json").write_text('{"permissions":{"deny":["Bash(rm *)"]}}')
    plan = converter().plan(tmp_path, "claude", "agents")
    codes = {d["code"] for d in plan["diagnostics"]}
    assert {"UNMAPPED_METADATA", "UNRESOLVED_IMPORT", "UNMAPPED_CONFIG"} <= codes
    assert text == plan["output"]["content"]
    assert not plan["complete"]
    assert (tmp_path / ".claude/settings.json").exists()


def test_conflict_never_overwrites_target(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("Never deploy without approval.\n")
    (tmp_path / "AGENTS.md").write_text("Run all tests before committing.\n")
    plan = converter().plan(tmp_path, "claude", "codex")
    assert any(d["code"] == "TARGET_CONFLICT" for d in plan["diagnostics"])
    assert (tmp_path / "AGENTS.md").read_text() == "Run all tests before committing.\n"


def test_codex_override_is_authoritative(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Default contract.\n")
    (tmp_path / "AGENTS.override.md").write_text("Override contract.\n")
    plan = converter().plan(tmp_path, "codex", "claude")
    assert plan["output"]["content"] == "Override contract.\n"
    assert plan["canonical"]["documents"][0]["path"] == "AGENTS.override.md"


@pytest.mark.parametrize("name", ["CLAUDE.md", "AGENTS.md"])
def test_symlink_sources_or_targets_are_not_read(tmp_path, name):
    private = tmp_path / "private.txt"
    private.write_text("Sensitive external instructions.\n")
    (tmp_path / name).symlink_to(private)
    plan = converter().plan(tmp_path, "claude", "codex")
    assert "Sensitive external instructions." not in str(plan)
    assert any(d["code"] == "UNSAFE_SOURCE" for d in plan["diagnostics"])


def test_invalid_utf8_is_reported(tmp_path):
    (tmp_path / "CLAUDE.md").write_bytes(b"\xff")
    plan = converter().plan(tmp_path, "claude", "agents")
    assert any(d["code"] == "UNREADABLE_SOURCE" for d in plan["diagnostics"])


def test_redaction_covers_canonical_output_and_diff(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("Never reveal SECRET_VALUE.\n")
    plan = AgentConverter(lambda s: s.replace("SECRET_VALUE", "[redacted]")).plan(tmp_path, "claude", "codex")
    assert "SECRET_VALUE" not in json.dumps(plan)
    assert "[redacted]" in plan["output"]["diff"]


@pytest.mark.parametrize("mode", ["json", "terminal"])
def test_cli_preview_is_read_only_and_does_not_scan_or_prompt(tmp_path, mode):
    (tmp_path / "CLAUDE.md").write_text("Never loosen security rules.\n")
    before = sorted(p.name for p in tmp_path.iterdir())
    args = [sys.executable, str(ROOT / "ai-lint.py"), str(tmp_path), "--convert-to", "codex"]
    args += ["--format", "json"] if mode == "json" else ["--interactive"]
    result = subprocess.run(args, input="", capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    if mode == "json":
        plan = json.loads(result.stdout)["conversion_plans"][0]
        assert plan["output"]["path"] == "AGENTS.md"
    else:
        assert "AGENT CONVERSION" in result.stdout
        assert "Never loosen security rules." in result.stdout
    assert sorted(p.name for p in tmp_path.iterdir()) == before


@pytest.mark.parametrize("args", [["--fix"], ["--generate"], ["--user"], ["--guard"], ["--restore"]])
def test_conversion_cannot_enter_writing_or_other_modes(tmp_path, args):
    result = subprocess.run(
        [sys.executable, str(ROOT / "ai-lint.py"), str(tmp_path), "--convert-to", "claude", *args],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 2
    assert not list(tmp_path.iterdir())


def test_codex_target_override_blocks_complete_plan(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("Never deploy without validation.\n")
    (tmp_path / "AGENTS.override.md").write_text("Existing override.\n")
    plan = converter().plan(tmp_path, "claude", "codex")
    assert any(d["code"] == "TARGET_OVERRIDE" for d in plan["diagnostics"])
    assert not plan["complete"]


def test_crlf_content_is_preserved(tmp_path):
    text = "# Safety\r\nNever loosen permissions.\r\n"
    (tmp_path / "CLAUDE.md").write_bytes(text.encode())
    assert converter().plan(tmp_path, "claude", "codex")["output"]["content"] == text


def test_symlinked_rules_directory_is_reported(tmp_path):
    (tmp_path / ".claude").mkdir()
    outside = tmp_path / "external"
    outside.mkdir()
    (outside / "secret.md").write_text("Private instructions.\n")
    (tmp_path / ".claude/rules").symlink_to(outside, target_is_directory=True)
    plan = converter().plan(tmp_path, "claude", "codex")
    assert not plan["canonical"]["documents"]
    assert any(d["code"] == "UNSAFE_SOURCE" for d in plan["diagnostics"])
