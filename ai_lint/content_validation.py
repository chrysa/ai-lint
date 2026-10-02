"""Human validation gates for critical content files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ai_lint.critical_content_policy import CriticalContentPolicy


@dataclass
class CriticalContentValidator:
    repo_roots: list[Path] = field(default_factory=list)
    policy: CriticalContentPolicy = field(default_factory=CriticalContentPolicy)

    def validation_reason(self, path: Path, old: str, new: str) -> str | None:
        if old == new or not self.is_critical(path):
            return None
        return self.policy.validation_hint

    def is_critical(self, path: Path) -> bool:
        rel = self._relative_path(path)
        if rel is None:
            return False
        if len(rel.parts) == 1:
            if rel.name in self.policy.instruction_files:
                return True
            if rel.name in self.policy.config_files:
                return True
        if len(rel.parts) == 2 and rel.parts[0] == "docs" and rel.name in self.policy.docs_files:
            return True
        return self._is_rule_file(rel)

    def _relative_path(self, path: Path) -> Path | None:
        resolved = path.resolve()
        roots = self.repo_roots or [Path.cwd()]
        for root in roots:
            try:
                return resolved.relative_to(root.resolve())
            except ValueError:
                continue
        return None

    def _is_rule_file(self, rel: Path) -> bool:
        parts = rel.parts
        return (
            len(parts) >= 3
            and parts[0] == self.policy.rule_dir_parts[0]
            and parts[1] == self.policy.rule_dir_parts[1]
            and rel.suffix == ".md"
        )
