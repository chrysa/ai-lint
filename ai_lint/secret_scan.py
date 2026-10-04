"""Inline secret detection in env, headers and args mappings (settings, hooks, MCP)."""

from __future__ import annotations

import re
from pathlib import Path

from ai_lint._reference import SECRET_KEY_RE, SECRET_VALUE_PATTERNS
from ai_lint.report import Report


class InlineSecretScanner:
    """Flag literal secrets; optionally replace them by ${VAR} references or remove them."""

    def check_env_secrets(self, env: dict, path: Path, rep: Report, ctx: str, mode: str = "report") -> dict:
        """mode: report | reference (-> ${VAR}) | remove."""
        out = dict(env or {})
        for k, v in (env or {}).items():
            if not isinstance(v, str):
                continue
            bare = re.sub(r"^(bearer|token|basic)\s+", "", v, flags=re.I)
            if bare.startswith("$"):
                continue
            if any(p.search(bare) for p in SECRET_VALUE_PATTERNS) or (SECRET_KEY_RE.search(k) and len(bare) >= 12):
                var = re.sub(r"[^A-Z0-9]+", "_", k.upper()).strip("_")
                if k.lower() == "authorization" and "." in ctx:
                    var = re.sub(r"[^A-Z0-9]+", "_", ctx.split(".")[1].upper()) + "_TOKEN"
                if mode == "reference":
                    prefix = v.split(" ")[0] + " " if v.lower().startswith(("bearer ", "token ", "basic ")) else ""
                    out[k] = f"{prefix}${{{var}}}"
                    action = f"replaced by {out[k]}; export {var} (or inject it from the vault)"
                elif mode == "remove":
                    out.pop(k)
                    action = f"removed; export {var} in your shell profile or inject it from the vault"
                else:
                    action = "reference an env var or the vault instead"
                rep.add(
                    "error" if mode != "report" or ".claude.json" not in str(path) else "warn",
                    "SECRET_INLINE",
                    path,
                    f"{ctx}: {k} holds a literal secret; {action}",
                    mode != "report",
                )
        return out
