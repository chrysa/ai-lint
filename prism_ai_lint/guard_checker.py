"""PreToolUse checks that block configuration loosening and unvalidated critical edits."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from prism_ai_lint.content_validation import CriticalContentValidator

GUARD_MARKER = "--guard"
CONFIG_HINT = re.compile(
    r"(settings(\.local)?\.json|\.mcp\.json|\.claude\.json|/\.claude/|\.claude/|"
    r"\.agent-lint\.toml|\.claude-lint\.toml|\.git/hooks|ai-lint|ai_lint[/\\]|\.ai-lint\b|"
    r"SKILL\.md|CLAUDE(\.local)?\.md|AGENTS\.md)"
)
BASH_WRITE_HINT = re.compile(
    r"(>|\btee\b|\bsed\s+-i|\bperl\s+-[a-z]*i|\bmv\b|\bcp\b|\brm\b|\bln\b|\bchmod\b|"
    r"\btruncate\b|\bdd\b|\binstall\b|\bpython3?\b|\bnode\b|\bruby\b|\bjq\b.*>|\bgit\s+(checkout|restore|apply|stash))"
)


class GuardChecker:
    """Evaluate edits with shared parsing and permission helpers supplied by the caller."""

    def __init__(
        self,
        *,
        covers: Callable[[str, str], bool],
        split_rule: Callable[[str], tuple[str, str | None] | None],
        split_frontmatter: Callable[[str], tuple[dict[str, str] | None, int]],
        frontmatter_block: Callable[[str], str],
        read_text: Callable[[Path], str | None],
        config_dir: Callable[[], Path],
        lenient_json: Callable[[str], tuple[Any, bool]],
        attribution_patterns: list[re.Pattern[str]],
        toml_parser: Any,
        engine_path: Path,
    ) -> None:
        self.covers = covers
        self.split_rule = split_rule
        self.split_frontmatter = split_frontmatter
        self.frontmatter_block = frontmatter_block
        self.read_text = read_text
        self.config_dir = config_dir
        self.lenient_json = lenient_json
        self._attribution_patterns = attribution_patterns
        self.tomllib = toml_parser
        self.engine_path = engine_path.resolve()

    def _norm_handlers(self, hooks: Any) -> set[str]:
        if not isinstance(hooks, dict):
            return set()
        return {
            f"{event}:{self._handler_target(handler)}"
            for event, groups in hooks.items()
            for handler in self._handlers(groups)
        }

    def _handlers(self, groups: Any):
        if not isinstance(groups, list):
            return
        for group in groups:
            if not isinstance(group, dict):
                continue
            for handler in group.get("hooks", []):
                if isinstance(handler, dict):
                    yield handler

    def _handler_target(self, handler: dict) -> str:
        target = handler.get("command") or handler.get("url") or f"{handler.get('server')}:{handler.get('tool')}"
        target = " ".join([str(target), *map(str, handler.get("args") or [])])
        return re.sub(r"[\"']?\$\{?CLAUDE_PROJECT_DIR\}?[\"']?/|^\./", "", target.strip())

    def settings_violations(self, old: dict, new: dict) -> list[str]:
        po, pn = old.get("permissions") or {}, new.get("permissions") or {}
        return (
            self._allow_violations(po, pn)
            + self._restriction_violations(po, pn)
            + self._permission_mode_violations(po, pn)
            + self._hook_violations(old, new)
            + self._environment_violations(old, new)
            + self._executable_violations(old, new)
        )

    def _allow_violations(self, po: dict, pn: dict) -> list[str]:
        v: list[str] = []
        ao, an = list(po.get("allow") or []), list(pn.get("allow") or [])
        for r in an:
            if r in ao or any(self.covers(o, r) for o in ao):
                continue
            parsed = self.split_rule(r)
            if parsed and parsed[0] == "Bash" and (parsed[1] or "").startswith("rtk "):
                plain = f"Bash({parsed[1][4:]})"
                if plain in ao or any(self.covers(o, plain) for o in ao):
                    continue  # rtk routing of an existing rule: same scope
            v.append(f"new allow rule {r!r}")
        return v

    def _restriction_violations(self, po: dict, pn: dict) -> list[str]:
        v: list[str] = []
        for key, stricter in (("deny", ()), ("ask", ("deny",))):
            for r in po.get(key) or []:
                pools = [pn.get(key) or []] + [pn.get(k) or [] for k in stricter]
                if not any(r in pool or any(self.covers(n, r) for n in pool) for pool in pools):
                    v.append(f"{key} rule removed {r!r}")
        return v

    def _permission_mode_violations(self, po: dict, pn: dict) -> list[str]:
        v: list[str] = []
        if pn.get("defaultMode") in ("bypassPermissions", "auto", "acceptEdits") and pn.get("defaultMode") != po.get(
            "defaultMode"
        ):
            v.append(f"defaultMode set to {pn.get('defaultMode')!r}")
        for k in ("disableBypassPermissionsMode", "disableAutoMode"):
            if po.get(k) and pn.get(k) != po.get(k):
                v.append(f"{k} relaxed")
        if set(pn.get("additionalDirectories") or []) - set(po.get("additionalDirectories") or []):
            v.append("additionalDirectories extended")
        return v

    def _hook_violations(self, old: dict, new: dict) -> list[str]:
        v: list[str] = []
        removed = self._norm_handlers(old.get("hooks")) - self._norm_handlers(new.get("hooks"))
        if removed:
            v.append("hook(s) removed: " + ", ".join(sorted(removed)[:3]))
        if new.get("disableAllHooks") and not old.get("disableAllHooks"):
            v.append("disableAllHooks enabled")
        if new.get("enableAllProjectMcpServers") and not old.get("enableAllProjectMcpServers"):
            v.append("enableAllProjectMcpServers enabled")
        if set(new.get("enabledMcpjsonServers") or []) - set(old.get("enabledMcpjsonServers") or []):
            v.append("enabledMcpjsonServers extended")
        return v

    def _environment_violations(self, old: dict, new: dict) -> list[str]:
        v: list[str] = []
        so, sn = old.get("sandbox") or {}, new.get("sandbox") or {}
        if so.get("enabled") and not sn.get("enabled"):
            v.append("sandbox disabled")
        if sn.get("allowUnsandboxedCommands") and not so.get("allowUnsandboxedCommands"):
            v.append("allowUnsandboxedCommands enabled")
        if set((new.get("env") or {})) - set((old.get("env") or {})):
            v.append("env variable(s) added")
        return v

    def _executable_violations(self, old: dict, new: dict) -> list[str]:
        v: list[str] = []
        for k in (
            "apiKeyHelper",
            "awsAuthRefresh",
            "awsCredentialExport",
            "otelHeadersHelper",
            "statusLine",
            "fileSuggestion",
            "processWrapper",
            "extraKnownMarketplaces",
            "enabledPlugins",
        ):
            if new.get(k) not in (None, old.get(k)):
                v.append(f"{k} added or changed (executes code)")
        attr = new.get("attribution")
        if isinstance(attr, dict) and any(attr.get(k) for k in ("commit", "pr")):
            v.append("attribution re-enabled")
        return v

    def mcp_violations(self, old: dict, new: dict) -> list[str]:
        so = old.get("mcpServers", old) if isinstance(old, dict) else {}
        sn = new.get("mcpServers", new) if isinstance(new, dict) else {}
        v = [f"new MCP server {n!r}" for n in set(sn) - set(so)]
        for n in set(sn) & set(so):
            v.extend(self._mcp_server_violations(n, so[n], sn[n]))
        return v

    def _mcp_server_violations(self, n: str, old: Any, new: Any) -> list[str]:
        v: list[str] = []
        a, b = old if isinstance(old, dict) else {}, new if isinstance(new, dict) else {}
        old_cmd = " ".join([str(a.get("command") or a.get("url") or ""), *map(str, a.get("args") or [])]).split()
        new_cmd = " ".join([str(b.get("command") or b.get("url") or ""), *map(str, b.get("args") or [])]).split()
        if old_cmd != new_cmd:
            v.append(f"MCP server {n!r} command/url changed")
        if set(b.get("env") or {}) - set(a.get("env") or {}):
            v.append(f"MCP server {n!r} env extended")
        return v

    def frontmatter_violations(self, old: str, new: str) -> list[str]:
        mo, _ = self.split_frontmatter(old)
        mn, _ = self.split_frontmatter(new)
        mo, mn = mo or {}, mn or {}
        v = []
        tok = lambda s: {t for t in re.split(r"[\s,\[\]]+", s or "") if t}
        for key in ("allowed-tools", "tools", "allowed_tools", "allowedTools"):
            if tok(mn.get(key)) - tok(mo.get(key)):
                v.append(f"{key} extended")
        if mo.get("disable-model-invocation", "").lower() in ("true", "yes", "on", "1") and mn.get(
            "disable-model-invocation", ""
        ).lower() not in ("true", "yes", "on", "1"):
            v.append("disable-model-invocation removed")
        if set(tok(mo.get("disallowed-tools"))) - tok(mn.get("disallowed-tools")) or set(
            tok(mo.get("disallowedTools"))
        ) - tok(mn.get("disallowedTools")):
            v.append("disallowed tools reduced")
        v.extend(self._frontmatter_execution_violations(mo, mn, old, new))
        return v

    def _frontmatter_execution_violations(self, mo: dict, mn: dict, old: str, new: str) -> list[str]:
        v: list[str] = []
        if ("hooks" in self.frontmatter_block(new)) and "hooks" not in self.frontmatter_block(old):
            v.append("frontmatter hooks added")
        if mn.get("permissionMode") in ("bypassPermissions", "auto", "acceptEdits") and mn.get(
            "permissionMode"
        ) != mo.get("permissionMode"):
            v.append("permissionMode loosened")
        if (
            mn.get("mcpServers") or "mcpServers" in self.frontmatter_block(new)
        ) and "mcpServers" not in self.frontmatter_block(old):
            v.append("inline mcpServers added")
        if re.search(r"(?m)^\s*!`|^```!", new) and not re.search(r"(?m)^\s*!`|^```!", old):
            v.append("shell injection (!`cmd`) added")
        return v

    def lint_toml_violations(self, old: str, new: str) -> list[str]:
        if self.tomllib is None:
            return ["cannot verify .prism-ai-lint.toml: no TOML parser available"]
        try:
            o = self.tomllib.loads(old) if old.strip() else {}
            n = self.tomllib.loads(new)
        except Exception as e:  # noqa: BLE001
            return [f"invalid TOML: {e}"]
        o.pop("reference", None)
        n.pop("reference", None)
        return [] if o == n else ["only the [reference] table may change"]

    def protected_path(self, p: Path) -> str | None:
        rp = p.resolve()
        s = str(rp)
        package = self.engine_path.parent
        if rp in (self.engine_path, Path(__file__).resolve(), package.parent / "prism-ai-lint.py") or rp.is_relative_to(
            package
        ):
            return "the linter itself"
        if rp.name == ".claude.json":
            return "~/.claude.json is written by Claude Code"
        if s.startswith(
            (
                "/etc/claude-code",
                "/Library/Application Support/ClaudeCode",
                "C:\\Program Files\\ClaudeCode",
            )
        ):
            return "managed settings"
        if "/skills/synced/" in s:
            return "skills synced from claude.ai"
        if "/.claude/plugins/" in s and str(self.config_dir()) in s:
            return "installed plugins (managed by the CLI)"
        if "/.git/hooks/" in s or s.endswith("/.git/hooks"):
            return "git hooks (installed by the linter only)"
        existing = self.read_text(rp) or ""
        if f'"{GUARD_MARKER}"' in existing:
            return "the guarded session settings"
        return None

    def _guard_json(self, old: str, new: str, label: str) -> tuple[dict, dict] | str:
        """Parse the pre/post contents of a guarded JSON file. The old text is
        read leniently (a malformed file on disk must not block a repair); the new
        text must be strict JSON, else a guard block reason is returned. Non-object
        JSON is normalised to an empty dict so callers can treat both as mappings."""
        try:
            o = self.lenient_json(old)[0] if old.strip() else {}
        except json.JSONDecodeError:
            o = {}
        try:
            n = json.loads(new)
        except json.JSONDecodeError as e:
            return f"guard: {label} must stay strict JSON ({e})"
        return (o if isinstance(o, dict) else {}), (n if isinstance(n, dict) else {})

    def guard_check(self, data: dict) -> str | None:
        """Return a block reason, or None to let the normal permission flow decide."""
        tool = data.get("tool_name", "")
        ti = data.get("tool_input") or {}
        cwd = Path(data.get("cwd") or os.getcwd())
        if tool in ("Bash", "PowerShell", "Monitor"):
            return self._command_reason(str(ti.get("command", "")))
        if tool not in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            return None
        raw = ti.get("file_path") or ti.get("notebook_path")
        if not raw:
            return None
        path = Path(os.path.expanduser(raw))
        path = path if path.is_absolute() else cwd / path
        why = self.protected_path(path)
        if why:
            return f"guard: {path} is protected ({why})"
        old = self.read_text(path) or ""
        if tool == "NotebookEdit":
            return None
        new = self._edited_content(tool, ti, old)
        return self._content_reason(path, cwd, old, new)

    def _content_reason(self, path: Path, cwd: Path, old: str, new: str) -> str | None:
        for pat in self._attribution_patterns:
            if pat.search(new) and not pat.search(old):
                return "guard: assistant attribution is forbidden"
        violations = self._file_violations(path, old, new)
        if isinstance(violations, str):
            return violations
        if violations:
            return (
                "guard: this change would loosen the configuration: "
                + "; ".join(violations)
                + ". Leave it for the human and list it under 'not fixed'."
            )
        content_reason = CriticalContentValidator([cwd]).validation_reason(path, old, new)
        if content_reason:
            return f"guard: {path} needs validation ({content_reason})"
        return None

    def _command_reason(self, cmd: str) -> str | None:
        linter = r"\S*(prism-ai-lint\.py|prism_ai_lint[/\\]_engine\.py)"
        if re.fullmatch(rf"\s*(rtk\s+)?(\S*python[\d.]*\s+)?{linter}(\s+[\w\-./=~:]+)*\s*", cmd):
            human_only = r"--session-settings\b|--policy\b|\s-i\b|--interactive\b|--full-yes\b|--plugin-dir\b"
            if re.search(human_only, cmd) or (re.search(r"--generate\b", cmd) and re.search(r"--fix\b", cmd)):
                return (
                    "guard: --generate --fix, --session-settings, --policy, -i/--full-yes and --plugin-dir "
                    "add permissions or run code: the human runs them (a --generate preview is allowed)"
                )
            return None  # the linter only tightens
        if CONFIG_HINT.search(cmd) and BASH_WRITE_HINT.search(cmd):
            return (
                "guard: agent configuration files may only be changed with Edit/Write "
                "(so the change can be inspected), or by running prism-ai-lint.py"
            )
        for pat in self._attribution_patterns:
            if pat.search(cmd):
                return "guard: assistant attribution is forbidden"
        return None

    def _edited_content(self, tool: str, ti: dict, old: str) -> str:
        if tool == "Write":
            new = str(ti.get("content", ""))
        elif tool == "Edit":
            a, b = str(ti.get("old_string", "")), str(ti.get("new_string", ""))
            new = old.replace(a, b) if ti.get("replace_all") else old.replace(a, b, 1)
        elif tool == "MultiEdit":
            new = old
            for e in ti.get("edits") or []:
                a, b = str(e.get("old_string", "")), str(e.get("new_string", ""))
                new = new.replace(a, b) if e.get("replace_all") else new.replace(a, b, 1)
        return new

    def _file_violations(self, path: Path, old: str, new: str) -> list[str] | str:
        name = path.name
        validator = None
        label = name
        if name in ("settings.json", "settings.local.json") or re.search(r"settings.*\.json$", name):
            label, validator = "settings", self.settings_violations
        elif name in (".mcp.json", "claude_desktop_config.json"):
            label = "Desktop config" if name == "claude_desktop_config.json" else name
            validator = self.mcp_violations
        elif path.parent.name == ".claude-plugin":
            validator = {"plugin.json": self._plugin_violations, "marketplace.json": self._marketplace_violations}.get(
                name
            )
        elif name == "hooks.json" and path.parent.name == "hooks":
            validator = self._hooks_file_violations
        if validator is None:
            return self._text_file_violations(path, old, new)
        parsed = self._guard_json(old, new, label)
        if isinstance(parsed, str):
            return parsed
        return validator(*parsed)

    def _plugin_violations(self, old: dict, new: dict) -> list[str]:
        return [
            f"plugin {key} added or changed (executes code)"
            for key in ("hooks", "mcpServers", "lspServers", "monitors", "channels", "userConfig")
            if new.get(key) not in (None, old.get(key))
        ]

    def _marketplace_violations(self, old: dict, new: dict) -> list[str]:
        on = {p.get("name") for p in old.get("plugins") or [] if isinstance(p, dict)}
        nn = {p.get("name") for p in new.get("plugins") or [] if isinstance(p, dict)}
        return [f"new marketplace plugin {x!r}" for x in sorted(nn - on)]

    def _hooks_file_violations(self, old: dict, new: dict) -> list[str]:
        return self.settings_violations({"hooks": old.get("hooks")}, {"hooks": new.get("hooks")})

    def _text_file_violations(self, path: Path, old: str, new: str) -> list[str]:
        name = path.name
        violations: list[str] = []
        if path.suffix in (".yml", ".yaml") and "/.github/workflows/" in str(path) and "claude-code" in new:
            violations = self._workflow_violations(old, new)
        elif name in (".prism-ai-lint.toml", ".ai-lint.toml", ".claude-lint.toml", ".agent-lint.toml"):
            violations = self.lint_toml_violations(old, new)
        elif name.endswith(".md") and (
            "/.claude/skills/" in str(path) or "/.claude/agents/" in str(path) or "/.claude/commands/" in str(path)
        ):
            violations = self.frontmatter_violations(old, new)
        return violations

    def _workflow_violations(self, old: str, new: str) -> list[str]:
        risky = [
            (
                r"dangerously-skip-permissions|permission-mode\W+bypassPermissions",
                "permissions bypass added",
            ),
            (r"(?m)^\s*pull_request_target\s*:", "pull_request_target trigger added"),
            (
                r"(allowed_tools|allowedTools)\W+[^\n]*\bBash(\(\*\))?(?=[\s,\"']|$)",
                "unrestricted Bash added",
            ),
        ]
        violations = [msg for pat, msg in risky if re.search(pat, new) and not re.search(pat, old)]
        if re.search(r"(?m)^\s*permissions\s*:", old) and not re.search(r"(?m)^\s*permissions\s*:", new):
            violations.append("workflow permissions block removed")
        return violations

    def run_guard(
        self,
        stdin: TextIO | None = None,
        stderr: TextIO | None = None,
        check: Callable[[dict], str | None] | None = None,
    ) -> int:
        try:
            data = json.load(sys.stdin if stdin is None else stdin)
            reason = (self.guard_check if check is None else check)(data if isinstance(data, dict) else {})
        except Exception as e:  # noqa: BLE001 - fail closed: any internal error blocks
            reason = f"guard: internal error, blocking by default ({e.__class__.__name__}: {e})"
        if reason:
            print(reason, file=sys.stderr if stderr is None else stderr)
            return 2
        return 0
