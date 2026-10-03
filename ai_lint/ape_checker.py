"""APE (Automatic Prompt Engineering) checker for instruction clarity."""

from __future__ import annotations

import re
from pathlib import Path


class APEChecker:
    """Validate instruction files against APE clarity principles."""

    # APE principles: clarity, completeness, constraints, objectives
    CLARITY_ISSUES = {
        "vague_verb": (
            r"\b(should|might|could|may|try|attempt|maybe)\b",
            "Vague instruction — use direct verbs (MUST, DO, ONLY, NEVER)",
        ),
        "missing_constraint": (
            r"\b(fix|build|make|create|update)\b",
            "Missing constraint — add ONLY/NEVER/ALWAYS to bound execution",
        ),
        "ambiguous_scope": (
            r"(etc\.|and so on|similar|basically)",
            "Ambiguous scope — specify exactly what is included/excluded",
        ),
        "incomplete_criteria": (
            r"\b(check|validate|verify|ensure)\b(?!.*\b(by|with|using|via)\b)",
            "Incomplete criteria — specify HOW to validate",
        ),
    }

    def __init__(self) -> None:
        self.compiled_patterns = {
            name: re.compile(pattern, re.IGNORECASE) for name, (pattern, _) in self.CLARITY_ISSUES.items()
        }

    def check_file(self, path: Path) -> list[tuple[int, str, str]]:
        """Scan instruction file for clarity issues. Returns (line_num, issue_type, message)."""
        if not path.exists():
            return []
        issues = []
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        for line_num, line in enumerate(text.split("\n"), 1):
            # Skip comments, headings, code blocks
            if line.strip().startswith("#") or line.strip().startswith("```"):
                continue
            for issue_type, pattern in self.compiled_patterns.items():
                if pattern.search(line):
                    _, message = self.CLARITY_ISSUES[issue_type]
                    issues.append((line_num, issue_type, message))
        return issues

    def summarize(self, issues: list[tuple[int, str, str]]) -> str | None:
        """Return summary of clarity issues found, or None if clear."""
        if not issues:
            return None
        counts = {}
        for _, issue_type, _ in issues:
            counts[issue_type] = counts.get(issue_type, 0) + 1
        summary = "Instruction clarity issues: " + ", ".join(
            f"{count} {t.replace('_', ' ')}" for t, count in counts.items()
        )
        return summary
