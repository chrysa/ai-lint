"""Instruction clarity: hedging verbs and open-ended scope, low false positives."""

from __future__ import annotations

from prism_ai_lint.ape_checker import APEChecker


def _types(text):
    return [t for _, t, _ in APEChecker().check_text(text)]


def test_hedging_verb_is_flagged():
    assert _types("You might want to try to run the tests.\n") == ["vague_verb"]


def test_open_ended_scope_is_flagged():
    assert _types("Lint Python, JavaScript, etc.\n") == ["ambiguous_scope"]


def test_ordinary_imperatives_are_not_flagged():
    text = "Fix failing tests.\nBuild the image.\nVerify with `make check`.\nUpdate the changelog.\n"
    assert _types(text) == []


def test_code_blocks_inline_code_and_headings_are_ignored():
    text = "# Might be a heading\n```sh\ntry to run etc.\n```\nRun `maybe-tool` now.\n"
    assert _types(text) == []


def test_summarize_reports_counts_and_lines():
    issues = APEChecker().check_text("Maybe do X.\nAdd A, B, etc.\nYou could skip Y.\n")
    summary = APEChecker().summarize(issues)
    assert summary is not None
    assert "2 vague verb" in summary and "1 ambiguous scope" in summary and "lines 1, 2, 3" in summary
    assert APEChecker().summarize([]) is None


def test_missing_file_yields_nothing(tmp_path):
    assert APEChecker().check_file(tmp_path / "nonexistent.md") == []
