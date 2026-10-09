"""Portfolio checker: the same agents or skills copied into many scanned projects.

A single project cannot see this: each copy looks fine on its own. Across a folder of
repositories, a pack copied everywhere is listed in every session of every project and drifts
silently. This reports each such pack once, with its cost per session and its drift."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from prism_ai_lint._markup import frontmatter_of


@dataclass(frozen=True)
class CopiedItem:
    repo: Path
    path: Path
    digest: str
    tokens: int


class PortfolioChecker:
    """Group identical agents and skills by the set of projects that carry them."""

    def __init__(self, min_projects: int = 5) -> None:
        self.min_projects = min_projects

    @staticmethod
    def _tokens(path: Path, fallback_name: str) -> int:
        meta = frontmatter_of(path)
        return (len(meta.get("name", fallback_name)) + min(len(meta.get("description", "")), 1536) + 20) // 4

    def collect(self, repos: list[Path]) -> dict[tuple[str, str], list[CopiedItem]]:
        """(kind, name) to every copy of that agent or skill found under the repositories."""
        found: dict[tuple[str, str], list[CopiedItem]] = defaultdict(list)
        for repo in repos:
            claude = repo / ".claude"
            for path in sorted((claude / "agents").glob("**/*.md")) if (claude / "agents").is_dir() else []:
                self._add(found, ("agent", path.stem), repo, path)
            for path in sorted((claude / "skills").glob("*/SKILL.md")) if (claude / "skills").is_dir() else []:
                self._add(found, ("skill", path.parent.name), repo, path)
        return found

    def _add(self, found: dict, key: tuple[str, str], repo: Path, path: Path) -> None:
        if path.is_symlink():
            return
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:10]
        except OSError:
            return
        found[key].append(CopiedItem(repo, path, digest, self._tokens(path, key[1])))

    def packs(self, repos: list[Path]) -> list[dict]:
        """Packs copied into at least `min_projects` projects, biggest cost first.

        Items that appear in exactly the same set of projects form one pack."""
        if len(repos) < self.min_projects:
            return []
        by_projects: dict[frozenset[Path], list[tuple[tuple[str, str], list[CopiedItem]]]] = defaultdict(list)
        for key, copies in self.collect(repos).items():
            where = frozenset(c.repo for c in copies)
            if len(where) >= self.min_projects:
                by_projects[where].append((key, copies))
        out = []
        for where, items in by_projects.items():
            per_project = sum(sum(c.tokens for c in copies) // len(where) for _, copies in items)
            out.append(
                {
                    "projects": sorted(where),
                    "names": sorted(f"{kind}:{name}" for (kind, name), _ in items),
                    "tokens_per_project": per_project,
                    "versions": max(len({c.digest for c in copies}) for _, copies in items),
                    "first_path": min(c.path for _, copies in items for c in copies),
                }
            )
        return sorted(out, key=lambda p: -p["tokens_per_project"] * len(p["projects"]))
