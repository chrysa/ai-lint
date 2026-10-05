"""Explicit Claude project instruction mapping."""

from pathlib import Path


class ClaudeAdapter:
    name = "claude"
    target = "CLAUDE.md"

    def sources(self, root: Path) -> list[Path]:
        rules = root / ".claude" / "rules"
        # Never follow rule-directory symlinks during discovery.
        nested = (
            sorted(rules.rglob("*.md"))
            if rules.is_dir() and not rules.is_symlink() and not (root / ".claude").is_symlink()
            else []
        )
        return [root / "CLAUDE.md", root / ".claude" / "CLAUDE.md", *nested]
