"""MCP configuration checks: .mcp.json servers and the read-only ~/.claude.json."""

from __future__ import annotations

import copy
import json
import os
import shlex
import shutil
from pathlib import Path

from prism_ai_lint._reference import SECRET_VALUE_PATTERNS
from prism_ai_lint._runtime import config_dir, dump_json, lenient_json, log, read_text
from prism_ai_lint.report import Report
from prism_ai_lint.secret_scan import InlineSecretScanner


class McpChecker:
    """Validate MCP server definitions and repair what is safe; records findings, never writes."""

    def __init__(self, secrets: InlineSecretScanner) -> None:
        self._secrets = secrets

    @staticmethod
    def _command_found(command: str, config: Path) -> bool:
        """True when the command can run: on PATH, or an existing file (relative to the config's folder).
        Commands with variables are not judged; a malformed command is left to MCP_COMMAND_ARGS."""
        try:
            parts = shlex.split(command)
        except ValueError:
            return True
        if not parts or "$" in parts[0]:
            return True
        first = os.path.expanduser(parts[0])
        if os.sep in first:
            target = Path(first) if os.path.isabs(first) else config.parent / first
            return target.exists()
        return shutil.which(first) is not None

    def check_servers(self, servers: dict, path: Path, rep: Report, ctx: str, writable: bool) -> dict:
        out = {}
        for name, cfg in servers.items():
            rep.stats["MCP servers"] = rep.stats.get("MCP servers", 0) + 1
            if not isinstance(cfg, dict) or not (cfg.get("command") or cfg.get("url")):
                rep.add("error", "MCP_SHAPE", path, f"{ctx}.{name}: needs 'command' or 'url'")
                out[name] = cfg
                continue
            cfg = dict(cfg)
            kind = cfg.get("type") or ("http" if cfg.get("url") else "stdio")
            log(
                2,
                f"{name}: {kind} {cfg.get('url') or cfg.get('command')}, {len(cfg.get('env') or {})} env var(s)",
                2,
            )
            if cfg.get("url") and "type" not in cfg:
                rep.add("warn", "MCP_TYPE", path, f"{ctx}.{name}: url without type (set to http)", writable)
                if writable:
                    cfg = {"type": "http", **cfg}
            elif cfg.get("type") == "sse":
                rep.add("info", "MCP_SSE", path, f"{ctx}.{name}: SSE transport is deprecated")
            elif cfg.get("type") not in (None, "stdio", "http", "sse", "ws"):
                rep.add("error", "MCP_TYPE", path, f"{ctx}.{name}: unknown type {cfg.get('type')!r}")
            if (
                kind == "stdio"
                and isinstance(cfg.get("command"), str)
                and not self._command_found(cfg["command"], path)
            ):
                rep.add(
                    "info",
                    "MCP_BROKEN",
                    path,
                    f"{ctx}.{name}: command {shlex.split(cfg['command'])[0]!r} not found; the server cannot "
                    "start but its entry is still loaded",
                )
            if (
                cfg.get("command")
                and " " in str(cfg["command"]).strip()
                and not cfg.get("args")
                and not os.path.exists(str(cfg["command"]))
            ):
                parts = shlex.split(str(cfg["command"]))
                rep.add(
                    "warn",
                    "MCP_COMMAND_ARGS",
                    path,
                    f"{ctx}.{name}: command contains arguments (split into args)",
                    writable,
                )
                if writable:
                    cfg["command"], cfg["args"] = parts[0], parts[1:]
            mode = "reference" if writable else "report"
            for sect in ("env", "headers"):
                if isinstance(cfg.get(sect), dict):
                    cfg[sect] = self._secrets.check_env_secrets(cfg[sect], path, rep, f"{ctx}.{name}.{sect}", mode)
            for a in cfg.get("args", []) or []:
                if isinstance(a, str) and any(p.search(a) for p in SECRET_VALUE_PATTERNS):
                    rep.add(
                        "error",
                        "SECRET_INLINE",
                        path,
                        f"{ctx}.{name}: literal secret in args (move it to env)",
                    )
            out[name] = cfg
        return out

    def check_mcp(self, path: Path, rep: Report, policy: dict) -> None:
        raw = read_text(path)
        if raw is None:
            log(2, f"{path}: absent", 1)
            return
        log(1, f"{path}", 1)
        try:
            data, repaired = lenient_json(raw)
        except json.JSONDecodeError as e:
            rep.add("error", "JSON_INVALID", path, f"invalid JSON, not auto-repairable: {e}")
            return
        if repaired:
            rep.add("error", "JSON_REPAIRED", path, "comments, trailing commas or BOM in strict JSON", True)
        if not isinstance(data, dict):
            rep.add("error", "MCP_SHAPE", path, "top level must be an object")
            return
        new = copy.deepcopy(data)
        if (
            "mcpServers" not in data
            and data
            and all(isinstance(v, dict) and (v.get("command") or v.get("url")) for v in data.values())
        ):
            rep.add(
                "warn",
                "MCP_MISPLACED",
                path,
                "servers declared at top level (moved under mcpServers)",
                True,
            )
            new = {"mcpServers": copy.deepcopy(data)}
        servers = new.get("mcpServers")
        if not isinstance(servers, dict):
            rep.add("error", "MCP_SHAPE", path, "missing 'mcpServers' object")
            return
        log(1, f"{len(servers)} MCP server(s): " + ", ".join(servers), 2)
        if len(servers) > policy["mcp"]["max_servers"]:
            rep.add("warn", "MCP_TOO_MANY", path, f"{len(servers)} servers; each one costs context")
        new["mcpServers"] = self.check_servers(servers, path, rep, "mcpServers", True)
        if new != data or repaired:
            rep.edit(path, raw, dump_json(new))

    def check_claude_json(self, rep: Report, repos: list[Path]) -> None:
        """~/.claude.json is written by Claude Code itself: validate, never edit."""
        path = Path(os.path.expanduser("~/.claude.json"))
        if os.environ.get("CLAUDE_CONFIG_DIR"):
            path = config_dir() / ".claude.json"
        raw = read_text(path)
        if raw is None:
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            rep.add("error", "JSON_INVALID", path, f"invalid JSON ({e}); restore from ~/.claude/backups/")
            return
        log(1, f"{path} (read-only)", 1)
        if isinstance(data.get("mcpServers"), dict):
            self.check_servers(data["mcpServers"], path, rep, "mcpServers", False)
        for proj, cfg in (data.get("projects") or {}).items():
            if isinstance(cfg, dict) and isinstance(cfg.get("mcpServers"), dict) and cfg["mcpServers"]:
                if not repos or any(str(r) == proj for r in repos):
                    self.check_servers(cfg["mcpServers"], path, rep, f"projects[{proj}].mcpServers", False)
