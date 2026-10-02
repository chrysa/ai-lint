"""Critical content policy defaults."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CriticalContentPolicy:
    instruction_files: frozenset[str] = frozenset(
        {
            "CLAUDE.md",
            "AGENTS.md",
            "README.md",
            "ARCHITECTURE.md",
            "DECISIONS.md",
            "TESTING.md",
        }
    )
    docs_files: frozenset[str] = frozenset(
        {
            "CLAUDE_CODE_BEST_PRACTICES.md",
            "FIXER_POLICY.md",
            "SHARED_STANDARDS_MAPPING.md",
        }
    )
    config_files: frozenset[str] = frozenset(
        {
            ".ai-lint.toml",
            "pyproject.toml",
            ".mcp.json",
            ".claude-lint.toml",
            ".agent-lint.toml",
        }
    )
    rule_dir_parts: tuple[str, str] = (".claude", "rules")
    validation_hint: str = "critical content file: human validation required before changing it"
