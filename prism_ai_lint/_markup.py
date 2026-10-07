"""Text helpers for Markdown instruction files: frontmatter, code spans, comments, @imports."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from prism_ai_lint._runtime import read_text

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


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:64] or "unnamed"


def derive_description(text: str) -> str | None:
    body = text
    stripped = body.lstrip("\ufeff \t\r\n")
    if stripped.startswith("---") and (end := stripped.find("\n---", 3)) != -1:
        body = stripped[end + 4 :]
    body = strip_html_comments(strip_code(body))
    for para in re.split(r"\n\s*\n", body):
        para = " ".join(
            l.strip() for l in para.splitlines() if l.strip() and not l.lstrip().startswith(("#", "|", ">", "!"))
        )
        para = re.sub(r"[*_`]", "", para).strip(" -")
        if len(para) >= 20:
            return re.split(r"(?<=[.!?])\s", para)[0][:300]
    return None


def frontmatter_values(text: str, key: str) -> list[str]:
    """Values of a top-level frontmatter key: inline list, scalar or '- item' block."""
    block = frontmatter_block(text).splitlines()
    for i, line in enumerate(block):
        m = re.match(rf"^{re.escape(key)}\s*:\s*(.*)$", line)
        if not m:
            continue
        val = m.group(1).strip()
        if val.startswith("["):
            return [v.strip().strip("'\"") for v in val.strip("[]").split(",") if v.strip()]
        if val:
            return [val.strip("'\"")]
        items = []
        for nxt in block[i + 1 :]:
            if re.match(r"^\s*-\s+", nxt):
                items.append(re.sub(r"^\s*-\s+", "", nxt).strip().strip("'\""))
            elif nxt.startswith((" ", "\t")):
                continue
            else:
                break
        return items
    return []


def frontmatter_of(path: Path) -> dict[str, str]:
    """The frontmatter of a Markdown file as a flat dict ({} when none/unreadable)."""
    meta, _ = split_frontmatter(read_text(path) or "")
    return meta or {}


def move_to_metadata(text: str, keys: list[str]) -> str:
    """Move top-level frontmatter entries (with their indented continuation) under metadata:."""
    stripped = text.lstrip("\ufeff \t\r\n")
    end = stripped.find("\n---", 3)
    if not stripped.startswith("---") or end == -1:
        return text
    lines, body = stripped[3:end].strip("\n").splitlines(), stripped[end + 4 :]
    entries: list[list[str]] = []
    for line in lines:
        if entries and (
            line.startswith((" ", "\t")) or line.lstrip().startswith("- ") and not re.match(r"^[\w-]+\s*:", line)
        ):
            entries[-1].append(line)
        else:
            entries.append([line])
    keep, moved, meta_idx = [], [], None
    for e in entries:
        key = (re.match(r"^([\w-]+)\s*:", e[0]) or [None, None])[1]
        if key in keys:
            moved.append(e)
        else:
            if key == "metadata":
                meta_idx = len(keep)
            keep.append(e)
    if not moved:
        return text
    block = ["  " + l for e in moved for l in e]
    if meta_idx is None:
        keep.append(["metadata:"] + block)
    else:
        keep[meta_idx] = [re.sub(r"^metadata\s*:.*$", "metadata:", keep[meta_idx][0])] + keep[meta_idx][1:] + block
    return "---\n" + "\n".join(l for e in keep for l in e) + "\n---" + body


SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")


def shorten_description(desc: str, limit: int) -> str:
    """A deterministic shorter description: whole leading sentences that fit `limit`, else a word-boundary cut."""
    text = " ".join(desc.split())
    if len(text) <= limit:
        return text
    kept = ""
    for sentence in SENTENCE_END_RE.split(text):
        candidate = f"{kept} {sentence}".strip()
        if len(candidate) > limit:
            break
        kept = candidate
    if kept:
        return kept
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "…"
