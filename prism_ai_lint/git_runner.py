"""Small git command runner used by prism-ai-lint integrations."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitRunner:
    def __init__(self, root: Path) -> None:
        self.root = root

    def output(self, *args: str, timeout: int = 30) -> str | None:
        try:
            res = subprocess.run(
                ["git", "-C", str(self.root), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return res.stdout if res.returncode == 0 else None

    def run(self, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
