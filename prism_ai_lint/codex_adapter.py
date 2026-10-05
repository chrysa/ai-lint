"""Codex maps project instructions to AGENTS.md, with override precedence."""

from pathlib import Path


class CodexAdapter:
    name = "codex"
    target = "AGENTS.md"

    def sources(self, root: Path) -> list[Path]:
        override = root / "AGENTS.override.md"
        return [override if override.exists() or override.is_symlink() else root / self.target]
