"""Hook configuration checks: events, matchers, handlers and hook scripts."""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ai_lint._reference import (
    HOOK_TYPES,
    KNOWN_HOOK_EVENTS,
    KNOWN_TOOLS,
    LEGACY_TOOLS,
    NO_MATCHER_EVENTS,
    SHELL_META,
    TOOL_EVENTS,
)
from ai_lint._runtime import dedupe, log, read_text
from ai_lint.report import Report

PLACEHOLDER_RE = re.compile(r"^[\"']?\$\{?CLAUDE_(PROJECT_DIR|PLUGIN_ROOT|PLUGIN_DATA)\}?[\"']?")


class HookChecker:
    """Validate a hooks block and return its repaired form; records findings, never writes."""

    def __init__(self, check_env_secrets: Callable[..., dict]) -> None:
        self._check_env_secrets = check_env_secrets

    def resolve_script(self, first: str, base: Path) -> Path | None:
        token = first.strip("\"'")
        token = re.sub(r"\$\{?CLAUDE_PROJECT_DIR\}?", str(base), token)
        if "$" in token:
            return None
        token = os.path.expanduser(token)
        if "/" not in token:
            return None
        p = Path(token)
        return p if p.is_absolute() else base / p

    def to_exec_form(self, command: str, scope: str) -> tuple[str, list[str]] | None:
        """Split a simple shell-form command into exec form, anchoring relative paths."""
        body = PLACEHOLDER_RE.sub(lambda m: "${CLAUDE_" + m.group(1) + "}", command.strip())
        if SHELL_META.search(
            body.replace("${CLAUDE_PROJECT_DIR}", "")
            .replace("${CLAUDE_PLUGIN_ROOT}", "")
            .replace("${CLAUDE_PLUGIN_DATA}", "")
        ) or "$" in re.sub(r"\$\{CLAUDE_\w+\}", "", body):
            return None
        try:
            tokens = shlex.split(body)
        except ValueError:
            return None
        if not tokens:
            return None
        exe = tokens[0]
        if scope == "project" and "/" in exe and not exe.startswith(("/", "~", "$")):
            exe = "${CLAUDE_PROJECT_DIR}/" + exe.removeprefix("./")
        return exe, tokens[1:]

    def check_matcher(self, event: str, matcher: Any, path: Path, rep: Report) -> Any:
        if matcher in (None, "", "*"):
            return matcher
        if event in NO_MATCHER_EVENTS:
            rep.add(
                "info",
                "HOOK_MATCHER_IGNORED",
                path,
                f"{event}: matcher {matcher!r} is ignored (removed)",
                True,
            )
            return None
        if not isinstance(matcher, str) or event not in TOOL_EVENTS:
            return matcher
        if re.fullmatch(r"[\w\s,|-]*", matcher):
            tokens = [t.strip() for t in re.split(r"[|,]", matcher) if t.strip()]
            fixed = []
            for t in tokens:
                if t.startswith("mcp__"):
                    if t.count("__") == 1:
                        rep.add(
                            "warn",
                            "HOOK_MATCHER_MCP",
                            path,
                            f"{event}: {t!r} matches no tool; use {t}__.*",
                            True,
                        )
                        fixed.append(t + "__.*")
                        continue
                elif t in LEGACY_TOOLS:
                    rep.add(
                        "warn",
                        "PERM_LEGACY_TOOL",
                        path,
                        f"{event}: matcher {t!r} renamed to {LEGACY_TOOLS[t]!r}",
                        True,
                    )
                    t = LEGACY_TOOLS[t]
                elif t not in KNOWN_TOOLS:
                    rep.add("warn", "HOOK_MATCHER_TOOL", path, f"{event}: matcher {t!r} is not a tool name")
                fixed.append(t)
            new = "|".join(dedupe(fixed))
            return new if new != "|".join(tokens) else matcher
        head = re.match(r"^([A-Z][A-Za-z]+)\.\*", matcher)
        if head and head.group(1) in KNOWN_TOOLS:
            rep.add(
                "info",
                "HOOK_MATCHER_REGEX",
                path,
                f"{event}: {matcher!r} is unanchored and also matches other tools",
            )
        return matcher

    def check_handler(self, event: str, h: dict, base: Path, path: Path, rep: Report, scope: str) -> dict | None:
        rep.stats["hook handlers"] = rep.stats.get("hook handlers", 0) + 1
        h = dict(h)
        htype = h.get("type")
        if htype is None and h.get("command"):
            rep.add("warn", "HOOK_NO_TYPE", path, f"{event}: handler without 'type' (set to command)", True)
            h = {"type": "command", **h}
            htype = "command"
        if htype not in HOOK_TYPES:
            rep.add("error", "HOOK_TYPE", path, f"{event}: unknown handler type {htype!r} (dropped)", True)
            return None
        missing = [f for f in HOOK_TYPES[htype] if not h.get(f)]
        if missing:
            rep.add(
                "error",
                "HOOK_SHAPE",
                path,
                f"{event}: {htype} handler missing {', '.join(missing)} (dropped)",
                True,
            )
            return None
        if "if" in h and event not in TOOL_EVENTS:
            rep.add("error", "HOOK_IF_DEAD", path, f"{event}: handler with 'if' never runs on this event")
        if "once" in h:
            rep.add("warn", "HOOK_ONCE", path, f"{event}: 'once' is ignored in settings (removed)", True)
            h.pop("once")
        if "timeout" in h and not isinstance(h["timeout"], (int, float)):
            rep.add("error", "HOOK_SHAPE", path, f"{event}: timeout must be a number of seconds")

        if htype == "command":
            cmd = str(h["command"]).strip()
            if event == "PreToolUse" and h.get("async"):
                rep.add("warn", "HOOK_ASYNC_GATE", path, f"{event}: async hook cannot block ({cmd[:40]})")
            if event == "SessionStart" and re.search(r"\b(cat|type|Get-Content)\b.*\b(AGENTS|CLAUDE)\.md", cmd):
                rep.add(
                    "warn",
                    "HOOK_DUP_CONTEXT",
                    path,
                    f"{event}: prints instruction files already loaded natively",
                )
            if "args" not in h:
                first = cmd.split()[0] if cmd.split() else ""
                relative = "/" in first and not first.strip("\"'").startswith(("/", "~", "$"))
                unquoted_ph = bool(re.match(r"^\$\{?CLAUDE_\w+\}?/", cmd))
                if relative or unquoted_ph:
                    conv = self.to_exec_form(cmd, scope)
                    if conv and scope == "project":
                        code = "HOOK_RELATIVE_PATH" if relative else "HOOK_EXEC_FORM"
                        rep.add("warn", code, path, f"{event}: {cmd[:60]!r} -> exec form {conv[0]!r}", True)
                        h["command"], h["args"] = conv
                    elif relative:
                        rep.add(
                            "warn",
                            "HOOK_RELATIVE_PATH",
                            path,
                            f"{event}: {cmd[:60]!r} depends on the current directory",
                        )
            script = self.resolve_script(str(h["command"]).split()[0] if "args" not in h else h["command"], base)
            if script is not None:
                if not script.exists():
                    rep.add("error", "HOOK_MISSING_SCRIPT", path, f"{event}: script not found: {script}")
                else:
                    if not os.access(script, os.X_OK) and script not in rep.chmods:
                        rep.add(
                            "warn",
                            "HOOK_NOT_EXECUTABLE",
                            path,
                            f"{event}: {script} is not executable",
                            True,
                        )
                        rep.chmods.append(script)
                    body = read_text(script) or ""
                    if (
                        event == "PreToolUse"
                        and re.search(r"\bexit\s+1\b", body)
                        and not re.search(r"\bexit\s+2\b|permissionDecision|\"decision\"", body)
                    ):
                        rep.add(
                            "warn",
                            "HOOK_EXIT1",
                            path,
                            f"{event}: {script.name} uses exit 1, which does not block",
                        )
            if (
                event in ("PreToolUse", "UserPromptSubmit")
                and not h.get("timeout")
                and not h.get("async")
                and not re.match(r"^rtk\b", cmd)
            ):
                rep.add(
                    "info",
                    "HOOK_TIMEOUT",
                    path,
                    f"{event}: no timeout (default 600s) on a gating hook ({cmd[:40]})",
                )
        elif htype == "http":
            allowed = list(h.get("allowedEnvVars") or [])
            for k, v in (h.get("headers") or {}).items():
                missing_vars = sorted(set(re.findall(r"\$\{?(\w+)\}?", str(v))) - set(allowed))
                if missing_vars:
                    rep.add(
                        "error",
                        "HOOK_HTTP_ENV",
                        path,
                        f"{event}: header {k} uses {', '.join(missing_vars)} without allowedEnvVars (added)",
                        True,
                    )
                    allowed += missing_vars
            if allowed:
                h["allowedEnvVars"] = dedupe(allowed)
            h["headers"] = self._check_env_secrets(
                h.get("headers") or {}, path, rep, f"hooks.{event}.headers"
            ) or h.get("headers")
            if not h["headers"]:
                h.pop("headers")
        elif htype == "mcp_tool" and event in ("SessionStart", "Setup"):
            rep.add("warn", "HOOK_MCP_LAUNCH", path, f"{event}: mcp_tool hook is skipped at launch")
        return h

    def normalize_hook_entries(self, event: str, entries: Any, path: Path, rep: Report) -> list | None:
        def as_group(obj: Any) -> dict | None:
            if isinstance(obj, str):
                return {"hooks": [{"type": "command", "command": obj}]}
            if isinstance(obj, dict) and isinstance(obj.get("hooks"), list):
                return obj
            if isinstance(obj, dict) and (obj.get("command") or obj.get("type")):
                return {"hooks": [obj]}
            return None

        legacy = False
        groups: list[dict] = []
        if isinstance(entries, dict):
            legacy = True
            for matcher, cmds in entries.items():
                items = cmds if isinstance(cmds, list) else [cmds]
                hooks = [c if isinstance(c, dict) else {"type": "command", "command": c} for c in items]
                groups.append({"matcher": matcher, "hooks": hooks})
        elif isinstance(entries, str):
            legacy = True
            groups.append({"hooks": [{"type": "command", "command": entries}]})
        elif isinstance(entries, list):
            for g in entries:
                ng = as_group(g)
                if ng is None:
                    rep.add("error", "HOOK_SHAPE", path, f"{event}: unusable hook group dropped", True)
                    continue
                legacy |= ng is not g
                groups.append(ng)
        else:
            rep.add("error", "HOOK_SHAPE", path, f"{event}: expected a list of matcher groups")
            return None
        if legacy:
            rep.add("warn", "HOOK_LEGACY_FORMAT", path, f"{event}: legacy hook format converted", True)
            log(2, f"hooks.{event}: converted to {len(groups)} matcher group(s)", 2)
        return groups

    def check_hooks(self, hooks: Any, base: Path, path: Path, rep: Report, scope: str) -> Any:
        if not isinstance(hooks, dict):
            rep.add("error", "HOOK_SHAPE", path, "hooks must be an object keyed by event name")
            return hooks
        log(
            1,
            "hooks: " + ", ".join(f"{e}({len(v) if isinstance(v, (list, dict)) else 1})" for e, v in hooks.items()),
            1,
        )
        fixed: dict[str, Any] = {}
        for event, raw in hooks.items():
            if event not in KNOWN_HOOK_EVENTS:
                rep.add("warn", "HOOK_EVENT", path, f"unknown hook event {event!r}")
            groups = self.normalize_hook_entries(event, raw, path, rep)
            if groups is None:
                fixed[event] = raw
                continue
            out_groups = []
            for g in groups:
                g = dict(g)
                if "matcher" in g:
                    m = self.check_matcher(event, g["matcher"], path, rep)
                    if m is None:
                        g.pop("matcher")
                    else:
                        g["matcher"] = m
                handlers = [
                    h2
                    for h in g["hooks"]
                    if isinstance(h, dict) and (h2 := self.check_handler(event, h, base, path, rep, scope))
                ]
                if handlers:
                    out_groups.append({**g, "hooks": handlers})
            if out_groups:
                fixed[event] = out_groups
        return fixed
