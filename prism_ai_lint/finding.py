"""Finding model emitted by prism-ai-lint checks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Finding:
    level: str
    code: str
    path: str
    message: str
    fixable: bool = False
