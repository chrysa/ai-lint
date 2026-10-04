"""Per-run state and base helpers shared by the engine and the checker modules."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ai_lint.report import Report


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


def dump_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def config_dir() -> Path:
    return Path(os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"))


def lenient_json(raw: str) -> tuple[Any, bool]:
    """Parse JSON; on failure retry without BOM, comments and trailing commas."""
    try:
        return json.loads(raw), False
    except json.JSONDecodeError as first_error:
        text = raw.lstrip("\ufeff")
        out, i, n, in_str = [], 0, len(text), False
        while i < n:
            c = text[i]
            if in_str:
                out.append(c)
                if c == "\\" and i + 1 < n:
                    out.append(text[i + 1])
                    i += 1
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
                out.append(c)
            elif text.startswith("//", i):
                while i < n and text[i] != "\n":
                    i += 1
                continue
            elif text.startswith("/*", i):
                end = text.find("*/", i + 2)
                i = n if end == -1 else end + 2
                continue
            else:
                out.append(c)
            i += 1
        try:
            return json.loads(re.sub(r",(\s*[}\]])", r"\1", "".join(out))), True
        except json.JSONDecodeError:
            raise first_error from None


def git(repo: Path, *args: str) -> str | None:
    log(3, "git -C " + str(repo) + " " + " ".join(args))
    try:
        res = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return res.stdout if res.returncode == 0 else None


def is_ignored(repo: Path, rel: str) -> bool:
    return git(repo, "check-ignore", "-q", rel) is not None


def is_tracked(repo: Path, rel: str) -> bool:
    return git(repo, "ls-files", "--error-unmatch", rel) is not None


def add_gitignore(repo: Path, entry: str, rep: Report) -> None:
    gi = repo / ".gitignore"
    cur = rep.current(gi) or ""
    if entry in cur.splitlines():
        return
    new = cur + ("" if not cur or cur.endswith("\n") else "\n") + entry + "\n"
    if gi.exists() or gi in rep.edits:
        rep.edit(gi, read_text(gi) or "", new)
    else:
        rep.new_files[gi] = (new, 0o644)
    log(2, f".gitignore: add {entry}", 2)
