"""Configuration for prism-ai-lint self-update checks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SelfUpdateConfig:
    release_branch: str = "main"
    remote: str = "origin"
    interval_seconds: float = 24 * 60 * 60
    source_root: Path = Path(__file__).resolve().parents[1]
    cache_path: Path = Path(os.path.expanduser("~/.cache/prism-ai-lint/update-check.json"))

    @classmethod
    def from_env(cls) -> SelfUpdateConfig:
        return cls(
            release_branch=os.environ.get("AI_LINT_RELEASE_BRANCH", cls.release_branch),
            remote=os.environ.get("AI_LINT_UPDATE_REMOTE", cls.remote),
        )
