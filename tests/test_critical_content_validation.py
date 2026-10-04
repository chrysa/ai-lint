"""Tests for critical content file validation (#16)."""

from __future__ import annotations

from ai_lint.content_validation import CriticalContentValidator


def test_instruction_files_are_critical(tmp_path):
    validator = CriticalContentValidator(repo_roots=[tmp_path])
    for name in ["CLAUDE.md", "AGENTS.md", "README.md", "ARCHITECTURE.md"]:
        assert validator.is_critical(tmp_path / name), f"{name} should be critical"


def test_config_files_are_critical(tmp_path):
    validator = CriticalContentValidator(repo_roots=[tmp_path])
    for name in [".ai-lint.toml", "pyproject.toml", ".mcp.json"]:
        assert validator.is_critical(tmp_path / name), f"{name} should be critical"


def test_legacy_config_files_are_critical(tmp_path):
    validator = CriticalContentValidator(repo_roots=[tmp_path])
    for name in [".claude-lint.toml", ".agent-lint.toml"]:
        assert validator.is_critical(tmp_path / name), f"{name} should be critical"


def test_docs_files_listed_in_policy_are_critical(tmp_path, monkeypatch):
    from ai_lint._runtime import state

    monkeypatch.setattr(state, "critical_extra", ("docs/FIXER_POLICY.md", "docs/SHARED_STANDARDS_MAPPING.md"))
    validator = CriticalContentValidator(repo_roots=[tmp_path])
    docs_path = tmp_path / "docs"
    docs_path.mkdir()
    for name in ["FIXER_POLICY.md", "SHARED_STANDARDS_MAPPING.md"]:
        assert validator.is_critical(docs_path / name), f"docs/{name} should be critical"


def test_rule_files_are_critical(tmp_path):
    validator = CriticalContentValidator(repo_roots=[tmp_path])
    rules_path = tmp_path / ".claude" / "rules"
    rules_path.mkdir(parents=True)
    rule_file = rules_path / "custom.md"
    assert validator.is_critical(rule_file), ".claude/rules/*.md should be critical"


def test_non_critical_files_pass(tmp_path):
    validator = CriticalContentValidator(repo_roots=[tmp_path])
    for name in ["main.py", "setup.sh", "data.json"]:
        assert not validator.is_critical(tmp_path / name), f"{name} should not be critical"


def test_validation_reason_for_critical_files(tmp_path):
    validator = CriticalContentValidator(repo_roots=[tmp_path])
    reason = validator.validation_reason(tmp_path / ".ai-lint.toml", "old", "new")
    assert reason is not None
    assert "critical" in reason.lower()


def test_validation_skipped_for_unchanged_critical(tmp_path):
    validator = CriticalContentValidator(repo_roots=[tmp_path])
    reason = validator.validation_reason(tmp_path / ".ai-lint.toml", "same", "same")
    assert reason is None, "no change means no validation needed"


def test_validation_skipped_for_non_critical(tmp_path):
    validator = CriticalContentValidator(repo_roots=[tmp_path])
    reason = validator.validation_reason(tmp_path / "data.json", "old", "new")
    assert reason is None, "non-critical files don't need validation"
