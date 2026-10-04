"""Text helpers for Markdown instruction files: frontmatter, code spans, comments, @imports."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

IMPORT_RE = re.compile(r"(?<![\w@`])@((?:~/|\.{1,2}/|/)?[\w.\-/]+[\w/])")


def split_frontmatter(text: str) -> tuple[dict[str, str] | None, int]:
    """Return (flat top-level keys, offset). offset > 0 means the block doesn't start on line 1."""
    stripped = text.lstrip("\ufeff \t\r\n")
    offset = len(text) - len(stripped)
    if not stripped.startswith("---"):
        return None, 0
    end = stripped.find("\n---", 3)
    if end == -1:
        return None, 0
    meta: dict[str, str] = {}
    for line in stripped[3:end].splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if m:
            meta[m.group(1)] = m.group(2).strip().strip("'\"")
    return meta, offset


def frontmatter_block(text: str) -> str:
    stripped = text.lstrip("\ufeff \t\r\n")
    end = stripped.find("\n---", 3)
    return stripped[3:end] if stripped.startswith("---") and end != -1 else ""


def yaml_scalar(value: str) -> str:
    if re.search(r"(:\s|^[\s\-?\[\]{}#&*!|>'\"%@`]|\s#|\s$)", value):
        return json.dumps(value, ensure_ascii=False)
    return value


def set_frontmatter(text: str, updates: dict[str, str], renames: dict[str, str] | None = None) -> str:
    text = text.lstrip("\ufeff \t\r\n") if text.lstrip("\ufeff \t\r\n").startswith("---") else text
    if text.startswith("---") and (end := text.find("\n---", 3)) != -1:
        head, body = text[3:end].strip("\n").splitlines(), text[end + 4 :]
        for old, new in (renames or {}).items():
            head = [re.sub(rf"^{re.escape(old)}(\s*:)", rf"{new}\1", l) for l in head]
        for key, val in updates.items():
            line = f"{key}: {yaml_scalar(val)}"
            idx = next((i for i, l in enumerate(head) if re.match(rf"^{re.escape(key)}\s*:", l)), None)
            if idx is None:
                head.insert(0 if key == "name" else len(head), line)
            else:
                head[idx] = line
        return "---\n" + "\n".join(head) + "\n---" + body
    lines = [f"{k}: {yaml_scalar(v)}" for k, v in updates.items()]
    return "---\n" + "\n".join(lines) + "\n---\n\n" + text.lstrip("\n")


def strip_code(text: str) -> str:
    """Remove fenced blocks and inline code spans (imports inside them are literal).
    Fences may be indented (e.g. nested in a numbered list), so allow leading
    whitespace on the opening and closing lines."""
    text = re.sub(r"(?ms)^[ \t]*(```+|~~~+)[^\n]*\n.*?^[ \t]*\1[ \t]*$", "", text)
    return re.sub(r"`[^`\n]*`", "", text)


def strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def import_targets(path: Path, text: str) -> list[tuple[str, Path]]:
    refs = []
    for m in IMPORT_RE.finditer(strip_html_comments(strip_code(text))):
        ref = m.group(1)
        target = Path(os.path.expanduser(ref))
        if not target.is_absolute():
            target = path.parent / target
        explicit = ref.startswith(("~/", "./", "../", "/")) or re.search(r"\.\w{1,6}$", ref)
        if target.exists() or explicit:
            refs.append((ref, target))
    return refs
