"""Anonymized issue report: unfixed findings rendered as Markdown for the public tracker.

Local and opt-in only: nothing is ever sent. When in doubt a value is removed, not kept.
"""

from __future__ import annotations

import getpass
import hashlib
import platform
import re
import socket
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path

from prism_ai_lint.finding import Finding

URL_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
IPV4_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
ABS_PATH_RE = re.compile(r"(?<![\w:])(?:~|[A-Za-z]:\\|/)[^\s'\"`,;)\]]*[/\\][^\s'\"`,;)\]]*")
QUOTED_RE = re.compile(r"`[^`\n]*`|\"[^\"\n]*\"|'[^'\n]*'")
KEEP_QUOTED = frozenset({"allow", "deny", "ask", "env", "hooks", "permissions", "mcpServers", "model"})


class Anonymizer:
    """Replace identifying values with stable tokens (`<PATH_1>`, `<PROJECT_1>`...)."""

    def __init__(
        self,
        redact_secrets: Callable[[str], str] = lambda t: t,
        known_names: Iterable[str] = (),
        extra_patterns: Iterable[str] = (),
    ) -> None:
        self._redact_secrets = redact_secrets
        self._names = sorted({n for n in known_names if len(n) >= 3}, key=len, reverse=True)
        self._extra = [re.compile(p) for p in extra_patterns]
        self._tokens: dict[tuple[str, str], str] = {}

    def token(self, kind: str, value: str) -> str:
        """Stable token for a value: the same input always maps to the same placeholder."""
        key = (kind, value)
        if key not in self._tokens:
            count = sum(1 for k, _ in self._tokens if k == kind) + 1
            self._tokens[key] = f"<{kind}_{count}>"
        return self._tokens[key]

    def scrub(self, text: str) -> str:
        """Anonymize free text: secrets, URLs, emails, IPs, paths, names, quoted values."""
        text = self._redact_secrets(text)
        for rx in self._extra:
            text = rx.sub("<REDACTED>", text)
        text = URL_RE.sub(lambda m: self.token("URL", m.group(0)), text)
        text = EMAIL_RE.sub(lambda m: self.token("EMAIL", m.group(0)), text)
        text = IPV4_RE.sub(lambda m: self.token("IP", m.group(0)), text)
        text = ABS_PATH_RE.sub(lambda m: self.token("PATH", m.group(0)), text)
        for name in self._names:
            text = re.sub(re.escape(name), lambda m: self.token("NAME", m.group(0)), text, flags=re.IGNORECASE)
        return QUOTED_RE.sub(self._quoted, text)

    def _quoted(self, match: re.Match[str]) -> str:
        inner = match.group(0)[1:-1].strip()
        if inner in KEEP_QUOTED or re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", inner) or inner.startswith("<"):
            return match.group(0)
        return "<VALUE>"


def local_identity(repos: Iterable[Path]) -> list[str]:
    """Names that must never leave the machine: user, host, home folder, repo folder names."""
    names = [Path.home().name, socket.gethostname().split(".")[0]]
    try:
        names.append(getpass.getuser())
    except (KeyError, OSError):
        pass
    names += [Path(r).resolve().name for r in repos]
    return [n for n in names if n]


class IssueReporter:
    """Render unfixed findings as an anonymized, editable Markdown issue body."""

    def __init__(self, anonymizer: Anonymizer, version: str) -> None:
        self.anon = anonymizer
        self.version = version

    def fingerprint(self, code: str) -> str:
        """Short duplicate-detection hash for a finding code."""
        return hashlib.sha256(code.encode()).hexdigest()[:10]

    def render(self, findings: list[Finding], profiles: list[str] | None = None) -> str:
        """Markdown body; only findings left unfixed are listed, grouped by code."""
        open_findings = [f for f in findings if not f.fixable]
        lines = [
            "## Fix request (anonymized, generated locally)",
            "",
            f"- prism-ai-lint: {self.version}",
            f"- OS: {platform.system()} / Python {sys.version_info.major}.{sys.version_info.minor}",
        ]
        if profiles:
            lines.append(f"- Detected profile: {', '.join(sorted(set(profiles)))}")
        lines += ["", "### Findings without an automatic fix", ""]
        if not open_findings:
            lines.append("None.")
            return "\n".join(lines) + "\n"
        counts = Counter(f.code for f in open_findings)
        first: dict[str, Finding] = {}
        for f in open_findings:
            first.setdefault(f.code, f)
        for code, n in counts.most_common():
            f = first[code]
            lines += [
                f"- **{code}** ({f.level}, x{n}, case `{self.fingerprint(code)}`)",
                f"  - example: {self.anon.scrub(f.message)}",
            ]
        lines += ["", "### Expected behaviour", "", "_Describe what the tool should do here (optional)._", ""]
        return "\n".join(lines)
