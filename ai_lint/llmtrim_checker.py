"""llmtrim integration checker — detect and recommend compression."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class LlmtrimChecker:
    """Check llmtrim installation and recommend compression for heavy contexts."""

    def is_installed(self) -> bool:
        """Check if llmtrim is available on PATH."""
        return shutil.which("llmtrim") is not None

    def is_configured(self, config_path: Path) -> bool:
        """Check if llmtrim is configured in Claude Code settings."""
        if not config_path.exists():
            return False
        try:
            import json

            settings = json.loads(config_path.read_text())
            if not isinstance(settings, dict):
                return False
            mcp = settings.get("mcpServers")
            subagents = settings.get("subagents")
            in_mcp = isinstance(mcp, dict) and any("llmtrim" in str(k).lower() for k in mcp)
            in_agents = isinstance(subagents, dict) and any("llmtrim" in str(v).lower() for v in subagents.values())
            return in_mcp or in_agents
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return False

    def get_status(self) -> str | None:
        """Get llmtrim daemon status. Returns status string or None if not available."""
        if not self.is_installed():
            return None
        try:
            result = subprocess.run(
                ["llmtrim", "status"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                # Extract first line (savings summary)
                lines = result.stdout.strip().split("\n")
                return lines[0] if lines else None
        except (OSError, subprocess.TimeoutExpired):
            pass
        return None

    def recommendation(self, token_budget: float, is_configured: bool) -> str | None:
        """Recommend llmtrim if context is heavy and it's not configured."""
        if is_configured:
            return None
        if token_budget > 10000:  # Heavy context
            if self.is_installed():
                return "llmtrim is installed but not configured — consider `llmtrim setup` to enable compression"
            else:
                return "Context is heavy (>10k tokens per-session) — install llmtrim for automatic compression"
        return None
