"""Critical content policy defaults."""

from __future__ import annotations

from dataclasses import dataclass, field

from prism_ai_lint._runtime import state


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
    # Project-specific documents are added per repository with [critical] extra_files.
    docs_files: frozenset[str] = frozenset()
    extra_paths: frozenset[str] = field(default_factory=lambda: frozenset(state.critical_extra))
    config_files: frozenset[str] = frozenset(
        {
            ".prism-ai-lint.toml",
            ".ai-lint.toml",
            "pyproject.toml",
            ".mcp.json",
            ".claude-lint.toml",
            ".agent-lint.toml",
        }
    )
    rule_dir_parts: tuple[str, str] = (".claude", "rules")
    validation_hint: str = "critical content file: human validation required before changing it"
