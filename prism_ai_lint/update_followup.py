"""After a successful self-update: offer the changelog and a config repair run on the new code."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from prism_ai_lint.git_runner import GitRunner

MAX_CHANGELOG_LINES = 40
YES = {"y", "yes", "o", "oui"}
ALL_WORDS = {"a", "all", "pc", "tout"}


class UpdateFollowUp:
    """Interactive follow-up. Repairs run in a fresh process (the new code), with `--fix` only,
    which never loosens a config and keeps a backup; the exact command is shown first."""

    def __init__(
        self,
        git: GitRunner,
        ask: Callable[[str], str] | None = None,
        run: Callable[[list[str]], int] | None = None,
        home: Path | None = None,
    ) -> None:
        self.git = git
        self.ask = ask or self._ask
        self.run = run or self._run
        self.home = home or Path.home()

    @staticmethod
    def _ask(prompt: str) -> str:
        print(prompt, end="", file=sys.stderr, flush=True)
        try:
            return input().strip()
        except EOFError:
            return ""

    @staticmethod
    def _run(cmd: list[str]) -> int:
        return subprocess.run(cmd, check=False).returncode

    def changelog(self, old_sha: str, new_sha: str) -> list[str]:
        """Commit subjects between two revisions, newest first, capped."""
        out = self.git.output("log", "--no-merges", "--format=%h %s", f"{old_sha}..{new_sha}") or ""
        lines = [line for line in out.splitlines() if line.strip()]
        if len(lines) > MAX_CHANGELOG_LINES:
            extra = len(lines) - MAX_CHANGELOG_LINES
            lines = lines[:MAX_CHANGELOG_LINES] + [f"... and {extra} more (git log {old_sha[:12]}..{new_sha[:12]})"]
        return lines

    def command_for(self, target: str) -> list[str] | None:
        """The repair command for a folder path, or for the whole machine; None when invalid."""
        script = str(self.git.root / "prism-ai-lint.py")
        if target.lower() in ALL_WORDS:
            return [sys.executable, script, str(self.home), "--user", "--fix", "--no-update-check"]
        folder = Path(target).expanduser()
        if not folder.is_dir():
            return None
        return [sys.executable, script, str(folder.resolve()), "--fix", "--no-update-check"]

    def offer(self, old_sha: str, new_sha: str) -> None:
        """Ask about the changelog, then about where to apply repairs, and act on the answers."""
        if self.ask("Show the changelog? [y/N] ").lower() in YES:
            for line in self.changelog(old_sha, new_sha) or ["(no commits found)"]:
                print(line, file=sys.stderr)
        answer = self.ask(
            "Apply configuration repairs now? folder path, 'all' (whole PC: home + user scope), Enter to skip: "
        )
        if not answer:
            print("No repairs applied. Run prism-ai-lint --fix whenever you want.", file=sys.stderr)
            return
        cmd = self.command_for(answer)
        if cmd is None:
            print(f"Not a folder: {answer!r}. No repairs applied.", file=sys.stderr)
            return
        shown = " ".join(cmd[1:])
        if self.ask(f"Run `python {shown}` (backups kept, never loosens)? [y/N] ").lower() not in YES:
            print("No repairs applied.", file=sys.stderr)
            return
        code = self.run(cmd)
        print(f"Repairs finished (exit {code}).", file=sys.stderr)
