"""Terminal formatting helpers for interactive review."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable


class Tty:
    def __init__(self, home_formatter: Callable[[str], str] | None = None) -> None:
        on = os.sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        c = lambda code: f"\033[{code}m" if on else ""
        self.b, self.dim, self.r, self.red, self.grn, self.yel, self.cyan = (
            c(1),
            c(2),
            c(0),
            c(31),
            c(32),
            c(33),
            c(36),
        )
        self.width = min(shutil.get_terminal_size((110, 40)).columns, 140)
        self._home_formatter = home_formatter or str

    def rule(self, title: str = "") -> None:
        line = "─" * max(0, self.width - len(title) - 3)
        print(f"\n{self.b}── {title} {line}{self.r}" if title else f"{self.dim}{'─' * self.width}{self.r}")

    def short(self, path: str, width: int) -> str:
        formatted = self._home_formatter(str(path))
        if len(formatted) <= width:
            return formatted
        return formatted[: width // 3] + "…" + formatted[-(width - width // 3 - 1) :]
