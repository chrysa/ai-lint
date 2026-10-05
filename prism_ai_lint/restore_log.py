"""Crash-resistant restore script writer."""

from __future__ import annotations

from pathlib import Path


class RestoreLog(list):
    """Undo commands, written as soon as each move happens."""

    def __init__(self, script: Path) -> None:
        super().__init__()
        self.script = script

    def append(self, line: str) -> None:
        super().append(line)
        self.script.parent.mkdir(parents=True, exist_ok=True)
        new = not self.script.exists()
        with self.script.open("a", encoding="utf-8") as fh:
            if new:
                fh.write("#!/bin/sh\n# Annule les déplacements de cette session\n")
            fh.write(line + "\n")
        self.script.chmod(0o755)
