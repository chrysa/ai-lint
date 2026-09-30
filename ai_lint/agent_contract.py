"""Lossless, source-aware project instruction representation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentContract:
    """Keep complete documents rather than guessing which prose is a safety rule."""

    documents: list[dict[str, str]] = field(default_factory=list)
    diagnostics: list[dict[str, str]] = field(default_factory=list)

    def add(self, path: str, content: str) -> None:
        self.documents.append({"path": path, "content": content})

    def warn(self, code: str, path: str, message: str) -> None:
        self.diagnostics.append({"code": code, "path": path, "message": message})

    def render(self) -> str:
        if len(self.documents) == 1:
            return self.documents[0]["content"]
        return "\n\n".join(f"<!-- Source: {d['path']} -->\n{d['content']}" for d in self.documents)
