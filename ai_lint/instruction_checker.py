"""Instruction files, rules and auto memory: size, @imports, AGENTS.md wiring, rule frontmatter."""

from __future__ import annotations

import os
import re
from pathlib import Path

from ai_lint._markup import (
    frontmatter_block,
    import_targets,
    set_frontmatter,
    split_frontmatter,
    strip_code,
    strip_html_comments,
)
from ai_lint._reference import RULE_TYPOS
from ai_lint._runtime import add_gitignore, is_ignored, is_tracked, log, read_text, state
from ai_lint.ape_checker import APEChecker
from ai_lint.report import Report


class InstructionChecker:
    """Check instruction files, rules and auto memory; records findings, never writes."""

    def __init__(self) -> None:
        self._clarity = APEChecker()

    def check_imports(
        self,
        path: Path,
        text: str,
        rep: Report,
        policy: dict,
        root: Path | None,
        depth: int = 1,
        seen: set | None = None,
    ) -> None:
        seen = seen if seen is not None else {path.resolve()}
        for ref, target in import_targets(path, text):
            log(2, f"import @{ref} (depth {depth})", 2)
            if not target.exists():
                rep.add("error", "IMPORT_MISSING", path, f"@{ref} does not resolve")
                continue
            if depth > policy["instructions"]["max_import_depth"]:
                rep.add("error", "IMPORT_DEPTH", path, f"@{ref} is {depth} hops deep (max 4): not loaded")
                continue
            if root is not None:
                try:
                    target.resolve().relative_to(root.resolve())
                except ValueError:
                    rep.add(
                        "info",
                        "IMPORT_EXTERNAL",
                        path,
                        f"@{ref} is outside the project (approval prompt)",
                    )
            resolved = target.resolve()
            if resolved in seen or target.is_dir():
                continue
            seen.add(resolved)
            sub = read_text(target)
            if sub:
                self.check_imports(target, sub, rep, policy, root, depth + 1, seen)

    def check_instruction_style(self, path: Path, effective: str, pol: dict, rep: Report) -> None:
        """Suggest terser, list-shaped, imperative wording for always-loaded
        instructions. All info-level: style, never correctness."""
        if not pol.get("style_checks", True):
            return
        body = strip_code(effective)  # do not lint prose inside fenced code blocks
        # Prose blocks: a run of long, non-list, non-heading, non-table lines that
        # would read faster as bullet points.
        run = 0
        min_lines = pol.get("prose_block_lines", 4)
        min_chars = pol.get("prose_line_min_chars", 60)
        flagged_prose = False
        for line in body.splitlines():
            s = line.strip()
            is_prose = bool(s) and len(s) >= min_chars and not re.match(r"^([-*+]|\d+[.)]|#{1,6}\s|\||>)", s)
            run = run + 1 if is_prose else 0
            if run >= min_lines and not flagged_prose:
                rep.add(
                    "info",
                    "INSTR_PROSE",
                    path,
                    f"{run}+ prose lines in a row: bullet points read faster and cost fewer tokens",
                )
                flagged_prose = True
        # Filler / polite wording: drop it for the imperative.
        low = body.lower()
        hits = [w for w in pol.get("filler_phrases", []) if re.search(rf"\b{re.escape(w)}\b", low)]
        if hits:
            rep.add(
                "info",
                "INSTR_FILLER",
                path,
                f"filler wording ({', '.join(sorted(set(hits))[:4])}...): write direct imperatives",
            )
        unclear = self._clarity.check_text(effective)
        if len(unclear) >= pol.get("vague_wording_min", 3):
            rep.add("info", "INSTR_VAGUE", path, self._clarity.summarize(unclear) or "unclear wording")

    def check_instruction_file(
        self, path: Path, scope: str, policy: dict, rep: Report, root: Path | None
    ) -> str | None:
        try:
            size = path.stat().st_size
        except OSError:
            log(2, f"{path}: absent", 1)
            return None
        if size > 4 * 1024 * 1024:
            rep.add("error", "INSTR_TOO_LARGE", path, f"{size} bytes: skipped entirely by Claude Code")
            return None
        text = read_text(path)
        if text is None:
            return None
        rep.stats["instruction files"] = rep.stats.get("instruction files", 0) + 1
        pol = policy["instructions"]
        effective = strip_html_comments(text)
        lines, tokens = effective.count("\n") + 1, len(effective.encode()) // 4
        log(1, f"{path}: {lines} lines, ~{tokens} tokens (HTML comments excluded)", 1)
        if scope == "user" and lines > pol["user_max_lines"]:
            rep.add(
                "warn",
                "INSTR_USER_TOO_LONG",
                path,
                f"{lines} lines (~{tokens} tokens) in every session",
            )
        elif lines > pol["project_warn_lines"] or tokens > pol["warn_tokens"]:
            rep.add("warn", "INSTR_LONG", path, f"{lines} lines (~{tokens} tokens)")
        self.check_instruction_style(path, effective, pol, rep)
        self.check_imports(path, text, rep, policy, root)
        return text

    def check_agents_md(self, repo: Path, policy: dict, rep: Report) -> None:
        agents = next((p for p in (repo / "AGENTS.md", repo / ".claude/AGENTS.md") if p.exists()), None)
        claude = next((p for p in (repo / "CLAUDE.md", repo / ".claude/CLAUDE.md") if p.exists()), None)
        local = repo / "CLAUDE.local.md"
        doctrine = (repo / policy["instructions"]["doctrine_dir"]).is_dir()
        marker = policy["instructions"]["generated_marker"]
        if local.exists() and (repo / ".git").exists():
            if is_tracked(repo, "CLAUDE.local.md"):
                rep.add(
                    "warn",
                    "LOCAL_MD_NOT_IGNORED",
                    local,
                    "CLAUDE.local.md is committed: git rm --cached CLAUDE.local.md",
                )
            elif not is_ignored(repo, "CLAUDE.local.md"):
                rep.add("warn", "LOCAL_MD_NOT_IGNORED", local, "CLAUDE.local.md is not gitignored", True)
                add_gitignore(repo, "CLAUDE.local.md", rep)
        if not agents:
            return
        if claude is None:
            if local.exists():
                rep.add(
                    "warn",
                    "AGENTS_SHADOWED_LOCAL",
                    repo,
                    "CLAUDE.local.md stops AGENTS.md from loading (CLAUDE.md importing it created)",
                    state.scaffold,
                )
                if state.scaffold:
                    rep.new_files[repo / "CLAUDE.md"] = ("@AGENTS.md\n", 0o644)
            elif state.cli_version and state.cli_version < (2, 1, 277):
                rep.add(
                    "warn",
                    "AGENTS_OLD_CLI",
                    repo,
                    f"claude {'.'.join(map(str, state.cli_version))} does not read AGENTS.md",
                )
            return
        if claude.is_symlink():
            rep.add("info", "AGENTS_SYMLINK", claude, "CLAUDE.md is a symlink")
            return
        text = read_text(claude) or ""
        rel = os.path.relpath(agents, claude.parent)
        imports = {ref for ref, _ in import_targets(claude, text)}
        if rel in imports or "AGENTS.md" in imports or f"./{rel}" in imports:
            return
        if doctrine or marker in "\n".join(text.splitlines()[:5]):
            return  # both are renders of the same source
        code = "AGENTS_MENTION" if "AGENTS.md" in text else "AGENTS_IGNORED"
        rep.add("warn", code, claude, f"AGENTS.md is not imported (added @{rel} at the top)", True)
        rep.edit(claude, text, f"@{rel}\n\n{text}")

    def check_rendered(self, repo: Path, policy: dict, rep: Report) -> None:
        pol = policy["instructions"]
        if not (repo / pol["doctrine_dir"]).is_dir():
            return
        for rel in pol["rendered_files"]:
            f = repo / rel
            head = "\n".join((read_text(f) or "").splitlines()[:5])
            if f.exists() and pol["generated_marker"] not in head and head.strip() != "@AGENTS.md":
                rep.add(
                    "warn",
                    "RENDER_HAND_EDITED",
                    f,
                    f"no '{pol['generated_marker']}' header: hand-edited render",
                )

    def check_rules(self, root: Path, rep: Report, project_root: Path | None) -> None:
        rules = root / "rules"
        if not rules.is_dir():
            return
        files = sorted(rules.rglob("*.md"))
        log(1, f"{rules}: {len(files)} rule file(s)", 1)
        for f in files:
            rep.stats["rules"] = rep.stats.get("rules", 0) + 1
            if f.is_symlink() and project_root is not None:
                try:
                    f.resolve().relative_to(project_root.resolve())
                except ValueError:
                    rep.add("info", "RULE_EXTERNAL", f, "symlinked outside the project")
            text = read_text(f) or ""
            meta, offset = split_frontmatter(text)
            if meta is None:
                rep.add("info", "RULE_UNSCOPED", f, "no 'paths': loads in every session")
                continue
            new = text
            if offset:
                rep.add(
                    "warn",
                    "FRONTMATTER_OFFSET",
                    f,
                    "frontmatter not on line 1 (leading lines removed)",
                    True,
                )
                new = text.lstrip("\ufeff \t\r\n")
            renames = {k: RULE_TYPOS[k] for k in meta if k in RULE_TYPOS and "paths" not in meta}
            if renames:
                rep.add("warn", "RULE_FIELD", f, f"{', '.join(renames)} renamed to 'paths'", True)
                new = set_frontmatter(new, {}, renames)
            ignored = [k for k in meta if k != "paths" and k not in renames]
            if ignored:
                rep.add("info", "RULE_FIELD", f, f"ignored field(s): {', '.join(ignored)}")
            block = frontmatter_block(new)
            for pat in re.findall(r"[\"']([^\"']+)[\"']", block):
                if pat.count("[") != pat.count("]") and "\\[" not in pat:
                    rep.add(
                        "error",
                        "RULE_PATTERN",
                        f,
                        f"pattern {pat!r} has an unbalanced '[': matches nothing",
                    )
            if "paths" not in meta and not renames:
                rep.add("info", "RULE_UNSCOPED", f, "no 'paths': loads in every session")
            if new != text:
                rep.edit(f, text, new)

    def check_auto_memory(self, cfg: Path, policy: dict, rep: Report) -> None:
        proj = cfg / "projects"
        if not proj.is_dir():
            return
        pol = policy["memory"]
        for idx in sorted(proj.glob("*/memory/MEMORY.md")):
            try:
                size = idx.stat().st_size
            except OSError:
                continue
            lines = (read_text(idx) or "").count("\n") + 1
            if lines > pol["max_lines"] or size > pol["max_bytes"]:
                rep.add(
                    "warn",
                    "MEMORY_INDEX",
                    idx,
                    f"{lines} lines / {size} bytes: content past the limit is not loaded",
                )
