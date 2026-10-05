"""PDF checker: heavy PDFs reachable from agent context should be exported as light text."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

PDF_REF_RE = re.compile(r"""(?<![\w/.-])((?:\.{0,2}/)?[\w@./-]*?[\w-]\.pdf)\b""", re.IGNORECASE)
CONTEXT_FILES = ("CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md", ".claude/AGENTS.md", "CLAUDE.local.md")
MAX_DOC_BYTES = 200_000


class PdfChecker:
    """Find PDFs the agent can load (referenced from instructions or shipped inside `.claude/`)."""

    def __init__(self, min_bytes: int = 200_000) -> None:
        self.min_bytes = min_bytes

    @staticmethod
    def converter() -> str | None:
        """Path of `pdftotext` if present (optional, never required)."""
        return shutil.which("pdftotext")

    def candidates(self, repo: Path) -> list[Path]:
        """PDFs inside `.claude/` plus PDFs referenced from instruction and skill markdown."""
        found: dict[Path, None] = {}
        dot = repo / ".claude"
        if dot.is_dir():
            for pdf in sorted(dot.rglob("*.pdf")):
                if pdf.is_file() and not pdf.is_symlink():
                    found[pdf] = None
        docs = [repo / rel for rel in CONTEXT_FILES]
        if dot.is_dir():
            docs += sorted(dot.rglob("*.md"))
        for doc in docs:
            for ref in self._references(doc):
                target = (doc.parent / ref).resolve() if not ref.startswith("/") else Path(ref)
                if self._inside(target, repo) and target.is_file():
                    found[target] = None
        return list(found)

    def heavy(self, repo: Path) -> list[tuple[Path, int]]:
        """(pdf, size in bytes) for every candidate at or above the size threshold."""
        out = []
        for pdf in self.candidates(repo):
            try:
                size = pdf.stat().st_size
            except OSError:
                continue
            if size >= self.min_bytes:
                out.append((pdf, size))
        return out

    def advice(self, size: int) -> str:
        """Short, honest recommendation; the tool never converts anything itself."""
        kb = size // 1024
        if self.converter():
            return f"{kb} KB PDF in agent context: export to text (`pdftotext -layout file.pdf file.txt`) and reference the text"
        return (
            f"{kb} KB PDF in agent context: export to text or Markdown (e.g. pdftotext) and reference the text instead"
        )

    @staticmethod
    def _references(doc: Path) -> list[str]:
        try:
            if doc.stat().st_size > MAX_DOC_BYTES:
                return []
            text = doc.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return [m.group(1).strip() for m in PDF_REF_RE.finditer(text) if "://" not in m.group(1)]

    @staticmethod
    def _inside(path: Path, repo: Path) -> bool:
        try:
            path.relative_to(repo.resolve())
        except ValueError:
            return False
        return True
