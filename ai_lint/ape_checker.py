"""Instruction clarity (APE-style): hedging verbs and open-ended scope in agent instructions."""

from __future__ import annotations

import re
from pathlib import Path

# Only wording an agent cannot act on deterministically. Ordinary verbs (fix, build,
# verify...) are not flagged: they are what instructions are made of. "should" is left
# to the filler-wording check so one word is never reported twice.
CLARITY_ISSUES = {
    "vague_verb": (
        r"\b(might|could|maybe|perhaps|try to|attempt to)\b",
        "hedging verb: state what to do (DO / NEVER / ONLY)",
    ),
    "ambiguous_scope": (
        r"(\betc\.?(?=\W|$)|\band so on\b|\bbasically\b|\band similar\b)",
        "open-ended scope: list exactly what is included",
    ),
}


class APEChecker:
    """Find instruction lines an agent cannot act on deterministically."""

    def __init__(self) -> None:
        self.compiled_patterns = {name: re.compile(p, re.IGNORECASE) for name, (p, _) in CLARITY_ISSUES.items()}

    def check_text(self, text: str) -> list[tuple[int, str, str]]:
        """Return (line number, issue type, message) for every unclear line, outside code."""
        issues = []
        in_fence = False
        for line_num, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if s.startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            if in_fence or s.startswith("#"):
                continue
            s = re.sub(r"`[^`\n]*`", "", s)
            for issue_type, pattern in self.compiled_patterns.items():
                if pattern.search(s):
                    issues.append((line_num, issue_type, CLARITY_ISSUES[issue_type][1]))
        return issues

    def check_file(self, path: Path) -> list[tuple[int, str, str]]:
        try:
            return self.check_text(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            return []

    def summarize(self, issues: list[tuple[int, str, str]]) -> str | None:
        """One-line summary with counts per issue type and the first lines, or None."""
        if not issues:
            return None
        counts: dict[str, int] = {}
        for _, issue_type, _ in issues:
            counts[issue_type] = counts.get(issue_type, 0) + 1
        lines = ", ".join(str(n) for n, _, _ in issues[:5])
        kinds = ", ".join(f"{count} {t.replace('_', ' ')}" for t, count in counts.items())
        return f"unclear wording ({kinds}; lines {lines}): state exactly what to do and its scope"
