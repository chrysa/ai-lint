"""Neutral AGENTS project contract mapping."""

from pathlib import Path


class AgentsAdapter:
    name = "agents"
    target = "AGENTS.md"

    def sources(self, root: Path) -> list[Path]:
        return [root / self.target]
