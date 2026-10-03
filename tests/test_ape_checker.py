"""Tests for APE instruction clarity checker."""

from __future__ import annotations

from ai_lint.ape_checker import APEChecker


def test_ape_checker_vague_verbs(tmp_path):
    file = tmp_path / "CLAUDE.md"
    file.write_text("You should try to make this work.\n")
    checker = APEChecker()
    issues = checker.check_file(file)
    assert any(t == "vague_verb" for _, t, _ in issues)


def test_ape_checker_missing_constraint(tmp_path):
    file = tmp_path / "CLAUDE.md"
    file.write_text("Fix bugs in the codebase.\n")
    checker = APEChecker()
    issues = checker.check_file(file)
    assert any(t == "missing_constraint" for _, t, _ in issues)


def test_ape_checker_ambiguous_scope(tmp_path):
    file = tmp_path / "CLAUDE.md"
    file.write_text("Check Python files, JavaScript, etc.\n")
    checker = APEChecker()
    issues = checker.check_file(file)
    assert any(t == "ambiguous_scope" for _, t, _ in issues)


def test_ape_checker_incomplete_criteria(tmp_path):
    file = tmp_path / "CLAUDE.md"
    file.write_text("Verify the tests pass.\n")
    checker = APEChecker()
    issues = checker.check_file(file)
    assert any(t == "incomplete_criteria" for _, t, _ in issues)


def test_ape_checker_clear_instruction(tmp_path):
    file = tmp_path / "CLAUDE.md"
    file.write_text("NEVER add allow rules. ONLY tighten permissions.\n")
    checker = APEChecker()
    issues = checker.check_file(file)
    assert len(issues) == 0


def test_ape_checker_summarize(tmp_path):
    file = tmp_path / "CLAUDE.md"
    file.write_text("You should try to fix this, etc.\n")
    checker = APEChecker()
    issues = checker.check_file(file)
    summary = checker.summarize(issues)
    assert summary is not None
    assert "clarity" in summary.lower()


def test_ape_checker_nonexistent(tmp_path):
    checker = APEChecker()
    issues = checker.check_file(tmp_path / "nonexistent.md")
    assert issues == []
