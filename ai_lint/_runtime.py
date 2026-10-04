"""Per-run state and base helpers shared by the engine and the checker modules."""

from __future__ import annotations

import datetime as dt
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class RunState:
    """Options set once by main(); read everywhere through `state`."""

    verbosity: int = 0
    show_diff: bool = False  # --diff: print a unified diff of every changed file
    debug_log_path: Path | None = None
    debug_log_fh: Any = None
    scaffold: bool = True
    cli_version: tuple[int, ...] | None = None
    lang: str = "fr"  # brief-report language: "fr" or "en" (set from --lang / $LANG)
    progress: bool = False
    first_report: Any = None
    interactive_ran: bool = False
    show_all: bool = False
    min_level: str = "info"  # hide findings below this level in the report (--min-level)


state = RunState()

_COLOR_ERR = sys.stderr.isatty()
_READ_CACHE: dict = {}  # (path, mtime_ns, size) -> text; keyed on stat so a write misses


def _loc(fr: str, en: str) -> str:
    """Pick the brief-report string for the active language."""
    return en if state.lang == "en" else fr


def log(level: int, msg: str, indent: int = 0) -> None:
    if state.debug_log_fh is not None:
        timestamp = dt.datetime.now().isoformat(timespec="milliseconds")
        state.debug_log_fh.write(f"{timestamp} [{level}] {'  ' * indent}{msg}\n")
        state.debug_log_fh.flush()
    if state.verbosity >= level:
        line = f"{'  ' * indent}{ {1: '·', 2: '»', 3: 'debug'}.get(level, '·') } {msg}"
        print(f"\033[2m{line}\033[0m" if _COLOR_ERR else line, file=sys.stderr)


def read_text(p: Path) -> str | None:
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
    except OSError:
        return None
    hit = _READ_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if len(_READ_CACHE) > 20000:  # bound memory on huge scans
        _READ_CACHE.clear()
    _READ_CACHE[key] = text
    return text


def dedupe(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    return [x for x in seq if not (x in seen or seen.add(x))]  # type: ignore[func-returns-value]
