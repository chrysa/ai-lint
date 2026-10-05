"""Interactive self-update prompt for clone-based prism-ai-lint installs."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from prism_ai_lint.git_runner import GitRunner
from prism_ai_lint.self_update_config import SelfUpdateConfig


class SelfUpdater:
    yes_answers = {"y", "yes", "o", "oui"}
    disabled_values = {"0", "false", "no", "off"}

    def __init__(self, config: SelfUpdateConfig | None = None) -> None:
        self.config = config or SelfUpdateConfig.from_env()
        self.updated = False

    def wants_update(self, answer: str) -> bool:
        return answer.strip().lower() in self.yes_answers

    def prompt(self, local_sha: str, remote_sha: str) -> str:
        return (
            f"prism-ai-lint update available on {self.config.remote}/{self.config.release_branch}: "
            f"{local_sha[:12]} -> {remote_sha[:12]}."
        )

    def check(self, args: Any, force: bool = False) -> None:
        if self._skip_for_run(args, force):
            return
        if not self._due(force):
            return

        git = GitRunner(self.config.source_root)
        top = git.output("rev-parse", "--show-toplevel")
        if not top:
            return
        git = GitRunner(Path(top.strip()))
        current = (git.output("rev-parse", "--abbrev-ref", "HEAD") or "").strip()
        if current != self.config.release_branch:
            if force:
                print(
                    "prism-ai-lint update check skipped: current branch is "
                    f"{current!r}, release branch is {self.config.release_branch!r}."
                )
            self._mark_checked()
            return

        try:
            fetched = git.run("fetch", "--quiet", self.config.remote, self.config.release_branch, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as e:
            if force:
                print(f"prism-ai-lint update check failed: {e}", file=sys.stderr)
            self._mark_checked()
            return
        self._mark_checked()
        if fetched.returncode != 0:
            if force:
                err = (fetched.stderr or fetched.stdout or "git fetch failed").strip()
                print(f"prism-ai-lint update check failed: {err}", file=sys.stderr)
            return

        local_sha = (git.output("rev-parse", "HEAD") or "").strip()
        remote_sha = (git.output("rev-parse", "FETCH_HEAD") or "").strip()
        if not local_sha or not remote_sha:
            return
        if local_sha == remote_sha:
            if force:
                print(f"prism-ai-lint is up to date on {self.config.remote}/{self.config.release_branch}.")
            return
        ancestor = git.run("merge-base", "--is-ancestor", local_sha, remote_sha, timeout=10)
        if ancestor.returncode != 0:
            if force:
                print(
                    "prism-ai-lint update check found a non-fast-forward difference on "
                    f"{self.config.remote}/{self.config.release_branch}; update manually.",
                    file=sys.stderr,
                )
            return

        self._offer_pull(git, local_sha, remote_sha)

    def _skip_for_run(self, args: Any, force: bool) -> bool:
        if getattr(args, "no_update_check", False) and not force:
            return True
        interactive = sys.stdin.isatty() and sys.stderr.isatty()
        return bool(
            not force
            and (
                getattr(args, "format", "text") != "text"
                or getattr(args, "quiet", False)
                or not interactive
                or os.environ.get("CI")
            )
        )

    def _due(self, force: bool = False) -> bool:
        mode = os.environ.get("AI_LINT_UPDATE_CHECK", "").lower()
        if force or mode == "always":
            return True
        if mode in self.disabled_values:
            return False
        raw_days = os.environ.get("AI_LINT_UPDATE_CHECK_DAYS")
        try:
            interval = float(raw_days) * 86400 if raw_days is not None else self.config.interval_seconds
        except ValueError:
            interval = self.config.interval_seconds
        if interval <= 0:
            return True
        try:
            data = json.loads(self.config.cache_path.read_text(encoding="utf-8"))
            checked_at = float(data.get("checked_at", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            checked_at = 0
        return time.time() - checked_at >= interval

    def _mark_checked(self) -> None:
        try:
            self.config.cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps({"checked_at": time.time()}, indent=2, ensure_ascii=False) + "\n"
            self.config.cache_path.write_text(payload, encoding="utf-8")
        except OSError:
            pass

    def _offer_pull(self, git: GitRunner, local_sha: str, remote_sha: str) -> None:
        msg = self.prompt(local_sha, remote_sha)
        if not (sys.stdin.isatty() and sys.stderr.isatty()):
            root = shlex.quote(str(git.root))
            print(
                f"{msg}\nRun: git -C {root} pull --ff-only {self.config.remote} {self.config.release_branch}",
                file=sys.stderr,
            )
            return
        print(f"{msg} Pull now? [y/N] ", end="", file=sys.stderr, flush=True)
        try:
            answer = input()
        except EOFError:
            return
        if not self.wants_update(answer):
            print("prism-ai-lint update skipped.", file=sys.stderr)
            return
        dirty = (git.output("status", "--porcelain") or "").strip()
        if dirty:
            root = shlex.quote(str(git.root))
            print(
                "prism-ai-lint update skipped: working tree is not clean. Run manually after committing/stashing:\n"
                f"  git -C {root} pull --ff-only {self.config.remote} {self.config.release_branch}",
                file=sys.stderr,
            )
            return
        pulled = git.run("pull", "--ff-only", self.config.remote, self.config.release_branch, timeout=60)
        if pulled.returncode == 0:
            self.updated = True
            print("prism-ai-lint updated. Re-run the command to use the new code.", file=sys.stderr)
        else:
            err = (pulled.stderr or pulled.stdout or "git pull failed").strip()
            print(f"prism-ai-lint update failed: {err}", file=sys.stderr)
