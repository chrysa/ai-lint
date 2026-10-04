"""Skills, subagents and their assets: frontmatter, names, descriptions, tools, spec portability."""

from __future__ import annotations

import re
from pathlib import Path

from ai_lint._markup import (
    derive_description,
    frontmatter_of,
    frontmatter_values,
    move_to_metadata,
    set_frontmatter,
    slugify,
    split_frontmatter,
)
from ai_lint._reference import (
    AGENT_FIELDS,
    AGENT_TYPOS,
    KNOWN_TOOLS,
    LEGACY_TOOLS,
    SKILL_FIELDS,
    SKILL_SPEC_FIELDS,
    SKILL_TYPOS,
)
from ai_lint._runtime import _writable, log, read_text
from ai_lint.instruction_checker import InstructionChecker
from ai_lint.report import Report


class SkillAgentChecker:
    """Check skill and subagent definitions; records findings and safe repairs, never writes."""

    def __init__(self, instructions: InstructionChecker) -> None:
        self._instructions = instructions

    def check_skill(self, d: Path, policy: dict, rep: Report) -> str | None:
        rep.stats["skills"] = rep.stats.get("skills", 0) + 1
        pol = policy["skills"]
        name_re = re.compile(pol["name_pattern"])
        sk = d / "SKILL.md"
        if not sk.is_file():
            alt = next((f for f in d.iterdir() if f.is_file() and f.name.lower() == "skill.md"), None)
            if not alt:
                # A grouping directory (holds nested skill subdirs, e.g. gitnexus/gitnexus-cli/
                # or ui-styling/ui-styling/) is not itself a skill: don't flag it.
                try:
                    if any((sub / "SKILL.md").is_file() for sub in d.iterdir() if sub.is_dir()):
                        return None
                except OSError:
                    pass
                rep.add("error", "SKILL_MISSING", d, "directory without SKILL.md")
                return None
            rep.add("error", "SKILL_MISSING", d, f"{alt.name} must be named SKILL.md (copied)", True)
            rep.new_files[sk] = (read_text(alt) or "", 0o644)
        text = rep.current(sk) or ""
        meta, offset = split_frontmatter(text)
        new = text
        if offset:
            rep.add(
                "warn",
                "FRONTMATTER_OFFSET",
                sk,
                "frontmatter not on line 1 (leading lines removed)",
                True,
            )
            new = text.lstrip("\ufeff \t\r\n")
        if meta is None:
            meta = {}
        renames = {k: SKILL_TYPOS[k] for k in meta if k in SKILL_TYPOS and SKILL_TYPOS[k] not in meta}
        if renames:
            rep.add(
                "warn",
                "SKILL_FIELD",
                sk,
                "renamed: " + ", ".join(f"{a} -> {b}" for a, b in renames.items()),
                True,
            )
            meta = {renames.get(k, k): v for k, v in meta.items()}
        trig_key = next((k for k in ("triggers", "trigger") if k in meta), None)
        if trig_key and not meta.get("when_to_use"):
            phrases = frontmatter_values(new, trig_key)
            if phrases:
                updates_trig = "Use when the user says: " + "; ".join(phrases)
                rep.add(
                    "info",
                    "SKILL_FIELD",
                    sk,
                    f"{trig_key} is ignored by Claude Code (copied into when_to_use, original kept under metadata)",
                    True,
                )
                meta = {**meta, "when_to_use": updates_trig}
                pending_when = updates_trig
            else:
                pending_when = None
        else:
            pending_when = None
        unknown = [k for k in meta if k not in SKILL_FIELDS]
        move_meta: list[str] = []
        if pending_when and trig_key:
            unknown = [k for k in unknown if k not in ("trigger", "triggers")] + [trig_key]
        if unknown:
            movable = [k for k in unknown if k not in ("trigger", "triggers") or pending_when]
            can_move = bool(movable) and ("metadata" not in meta or meta.get("metadata", "") == "")
            rep.add(
                "info",
                "SKILL_FIELD",
                sk,
                f"custom field(s) ignored by Claude Code: {', '.join(unknown)}"
                + (" (moved under metadata:)" if can_move else "")
                + ("; put trigger phrases in description or when_to_use" if len(movable) < len(unknown) else ""),
                can_move,
            )
            if can_move:
                move_meta = movable
        if pol["portable"]:
            extra = [k for k in meta if k in SKILL_FIELDS and k not in SKILL_SPEC_FIELDS]
            if extra:
                rep.add("info", "SKILL_PORTABILITY", sk, f"Claude Code-only field(s): {', '.join(extra)}")
        updates: dict[str, str] = {}
        if pending_when:
            updates["when_to_use"] = pending_when
        name, desc = meta.get("name", ""), meta.get("description", "")
        dir_ok = bool(name_re.match(d.name))
        if name and name != d.name:
            rep.add(
                "info" if not pol["portable"] else "warn",
                "SKILL_NAME",
                sk,
                f"name {name!r} differs from directory {d.name!r} (the command is /{d.name})"
                + (" (aligned)" if dir_ok else ""),
                dir_ok,
            )
            if dir_ok:
                updates["name"] = d.name
        elif not name and pol["portable"] and dir_ok:
            rep.add(
                "info",
                "SKILL_NAME",
                sk,
                "no name (the spec requires one; set to the directory name)",
                True,
            )
            updates["name"] = d.name
        if not dir_ok:
            rep.add(
                "warn",
                "SKILL_NAME",
                d,
                f"directory {d.name!r} is not a valid skill name; rename to {slugify(d.name)!r}",
            )
        if not desc:
            derived = derive_description(new)
            rep.add(
                "warn",
                "SKILL_DESCRIPTION",
                sk,
                "no description" + (" (derived from body)" if derived else ""),
                bool(derived),
            )
            if derived:
                updates["description"] = desc = derived
        listing = len(desc) + len(meta.get("when_to_use", ""))
        if listing > pol["max_listing_chars"]:
            rep.add(
                "warn",
                "SKILL_DESCRIPTION",
                sk,
                f"description + when_to_use = {listing} chars (truncated at {pol['max_listing_chars']})",
            )
        elif pol["portable"] and len(desc) > pol["portable_description_chars"]:
            rep.add(
                "info",
                "SKILL_PORTABILITY",
                sk,
                f"description {len(desc)} chars (> {pol['portable_description_chars']})",
            )
        body_lines = new.count("\n") + 1
        if body_lines > pol["max_lines"]:
            ro = "" if _writable(sk) else " (read-only: synced/symlinked store — edit it upstream)"
            rep.add("warn", "SKILL_LONG", sk, f"{body_lines} lines{ro}")
        if meta.get("context") != "fork":
            stray = [k for k in ("agent", "background") if k in meta]
            if stray:
                rep.add("warn", "SKILL_FORK_FIELD", sk, f"{', '.join(stray)} ignored without context: fork")
        words = "|".join(map(re.escape, pol["side_effect_words"]))
        dmi = meta.get("disable-model-invocation", "").lower() in ("true", "yes", "on", "1")
        if re.search(rf"\b({words})\b", f"{d.name} {name}".replace("_", " ").replace("-", " "), re.I) and not dmi:
            gate = pol.get("gate_side_effects", True)
            rep.add(
                "warn",
                "SKILL_SIDE_EFFECT",
                sk,
                "side-effect workflow can be auto-invoked by the model"
                + (" (disable-model-invocation: true added)" if gate else ""),
                gate,
            )
            if gate:
                updates["disable-model-invocation"] = "true"
        tools = meta.get("allowed-tools", "")
        if re.search(r"(^|[\s,\[])(Bash|PowerShell)(\(\*\)|(?=[\s,\]]|$))|Bash\(\*", tools):
            rep.add("warn", "SKILL_BROAD_TOOLS", sk, f"allowed-tools grants unrestricted shell: {tools}")
        if renames or updates or new != text or move_meta:
            out = set_frontmatter(new, updates, renames) if (renames or updates) else new
            if move_meta:
                out = move_to_metadata(out, move_meta)
            if sk in rep.new_files:
                rep.new_files[sk] = (out, 0o644)
            else:
                rep.edit(sk, text, out)
            log(2, f"skill {d.name}: " + ", ".join([*renames.values(), *updates]), 2)
        return d.name

    def check_agent_assets(self, root: Path, policy: dict, rep: Report, scope: str, project_root: Path | None) -> None:
        skills = root / "skills"
        names: set[str] = set()
        if skills.is_dir():
            if scope == "user" and (skills / "manifest.json").exists():
                rep.add(
                    "warn",
                    "SKILL_MANIFEST_BUG",
                    skills / "manifest.json",
                    "may move skills to .trash on CLIs < 2.1.280",
                )
            dirs = sorted(p for p in skills.iterdir() if p.is_dir() and not p.name.startswith("."))
            log(1, f"{skills}: {len(dirs)} skill dir(s)", 1)
            for d in dirs:
                if d.name.lower() == "synced":
                    if scope != "user":
                        rep.add("error", "SKILL_RESERVED", d, "reserved directory name")
                    continue  # downloaded from claude.ai: never edited here
                n = self.check_skill(d, policy, rep)
                if n:
                    names.add(n)
        agents = root / "agents"
        if agents.is_dir():
            files = sorted(agents.rglob("*.md"))
            log(1, f"{agents}: {len(files)} subagent(s)", 1)
            rep.agent_unknown = {}
            for f in files:
                self.check_subagent(f, rep)
            for field_name, paths in sorted(rep.agent_unknown.items()):
                if len(paths) >= 10:
                    log(
                        1,
                        f"pack convention field {field_name!r} in {len(paths)} subagents "
                        f"(ignored by Claude Code, harmless)",
                        1,
                    )
                else:
                    for p in paths:
                        rep.add("info", "AGENT_FIELD", p, f"unrecognised field: {field_name}")
        commands = root / "commands"
        if commands.is_dir():
            files = sorted(commands.rglob("*.md"))
            log(1, f"{commands}: {len(files)} command(s)", 1)
            for f in files:
                rep.stats["commands"] = rep.stats.get("commands", 0) + 1
                cmd_name = ":".join(f.relative_to(commands).with_suffix("").parts)
                if cmd_name in names:
                    rep.add("warn", "COMMAND_SHADOWED", f, f"skill '{cmd_name}' has the same name and wins")
                meta = frontmatter_of(f)
                if not (meta or {}).get("description"):
                    rep.add("info", "COMMAND_FRONTMATTER", f, "no description (first line is used)")
        self._instructions.check_rules(root, rep, project_root)

    def check_subagent(self, f: Path, rep: Report) -> None:
        rep.stats["subagents"] = rep.stats.get("subagents", 0) + 1
        text = read_text(f) or ""
        meta, offset = split_frontmatter(text)
        meta = meta or {}
        new = text.lstrip("\ufeff \t\r\n") if offset else text
        if offset:
            rep.add(
                "warn",
                "FRONTMATTER_OFFSET",
                f,
                "frontmatter not on line 1 (leading lines removed)",
                True,
            )
        renames = {k: AGENT_TYPOS[k] for k in meta if k in AGENT_TYPOS and AGENT_TYPOS[k] not in meta}
        if renames:
            rep.add(
                "warn",
                "AGENT_FIELD",
                f,
                "renamed: " + ", ".join(f"{a} -> {b}" for a, b in renames.items()),
                True,
            )
            meta = {renames.get(k, k): v for k, v in meta.items()}
        for k in meta:
            if k not in AGENT_FIELDS:
                rep.agent_unknown.setdefault(k, []).append(f)
        updates = {}
        if not meta.get("name"):
            updates["name"] = slugify(f.stem)
        if not meta.get("description") and (derived := derive_description(new)):
            updates["description"] = derived
        missing = [k for k in ("name", "description") if not meta.get(k)]
        if missing:
            still = [k for k in missing if k not in updates]
            rep.add(
                "error",
                "AGENT_FRONTMATTER",
                f,
                "missing: "
                + ", ".join(missing)
                + (f" (filled: {', '.join(updates)})" if updates else "")
                + (
                    f" (cannot derive: {', '.join(still)}; if this file is not a subagent, move it out of agents/)"
                    if still
                    else ""
                ),
                bool(updates),
            )
        tools = meta.get("tools", "")
        tool_renames = {}
        if tools:
            names = [re.sub(r"\(.*", "", t).strip() for t in re.split(r"[,\s\[\]]+", tools) if t.strip()]
            bad = [t for t in names if t and not t.startswith("mcp__") and t not in KNOWN_TOOLS]
            for t in bad:
                if t in LEGACY_TOOLS:
                    tool_renames[t] = LEGACY_TOOLS[t]
            still_bad = [t for t in bad if t not in tool_renames]
            if tool_renames:
                rep.add(
                    "warn",
                    "PERM_LEGACY_TOOL",
                    f,
                    "tools: " + ", ".join(f"{a} -> {b}" for a, b in tool_renames.items()),
                    True,
                )
            if still_bad:
                level = "error" if len(still_bad) == len(names) else "warn"
                rep.add(level, "AGENT_TOOLS", f, f"unknown tool(s): {', '.join(still_bad)}")
        if renames or updates or tool_renames or new != text:
            out = set_frontmatter(new, updates, renames) if (renames or updates) else new
            if tool_renames:
                key = "tools"

                def fix_line(m: re.Match) -> str:
                    line = m.group(0)
                    for a, b in tool_renames.items():
                        line = re.sub(rf"\b{a}\b", b, line)
                    return line

                out = re.sub(rf"(?m)^{key}\s*:.*$", fix_line, out, count=1)
            rep.edit(f, text, out)
