"""Tests for the PDF checker."""

from __future__ import annotations

from prism_ai_lint.pdf_checker import PdfChecker


def _pdf(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n" + b"x" * size)


def test_pdf_inside_claude_dir_is_found(tmp_path):
    _pdf(tmp_path / ".claude" / "skills" / "s" / "ref.pdf", 300_000)
    assert [p.name for p, _ in PdfChecker().heavy(tmp_path)] == ["ref.pdf"]


def test_pdf_referenced_from_instructions_is_found(tmp_path):
    _pdf(tmp_path / "docs" / "spec.pdf", 300_000)
    (tmp_path / "CLAUDE.md").write_text("Read docs/spec.pdf before coding.\n")
    assert [p.name for p, _ in PdfChecker().heavy(tmp_path)] == ["spec.pdf"]


def test_unreferenced_pdf_outside_claude_dir_is_ignored(tmp_path):
    _pdf(tmp_path / "docs" / "spec.pdf", 300_000)
    (tmp_path / "CLAUDE.md").write_text("Nothing here.\n")
    assert PdfChecker().heavy(tmp_path) == []


def test_small_pdf_is_ignored(tmp_path):
    _pdf(tmp_path / ".claude" / "small.pdf", 1_000)
    assert PdfChecker().heavy(tmp_path) == []


def test_reference_outside_repo_is_ignored(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _pdf(tmp_path / "outside.pdf", 300_000)
    (repo / "CLAUDE.md").write_text("See ../outside.pdf\n")
    assert PdfChecker().heavy(repo) == []


def test_url_reference_is_ignored(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("See https://example.com/a.pdf\n")
    assert PdfChecker().candidates(tmp_path) == []


def test_lint_emits_pdf_heavy_as_info(linter_module, tmp_path):
    m = linter_module
    _pdf(tmp_path / ".claude" / "ref.pdf", 300_000)
    pol = m.load_policy(None, [tmp_path])
    rep = m.Report()
    m.check_pdfs(tmp_path, pol, rep)
    assert [(f.level, f.code) for f in rep.findings] == [("info", "PDF_HEAVY")]
