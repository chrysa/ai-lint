"""Detect Claude account capabilities and recommend config."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class AccountCapabilities:
    """Detected Claude account features."""

    model_available: str | None = None  # opus, sonnet, haiku
    has_vision: bool = False
    has_file_handling: bool = False
    token_limit: int = 200000  # conservative default
    supported_tools: list[str] | None = None

    def is_premium(self) -> bool:
        """Check if account has premium features."""
        return self.model_available in ("opus", "sonnet")

    def recommendation_for_model(self) -> str | None:
        """Recommend model choice if limited."""
        if not self.model_available:
            return "Model not detected — verify Claude CLI auth"
        if self.model_available == "haiku":
            return "Using Haiku limits parallelization — consider Sonnet for faster builds"
        return None


class AccountCapabilitiesChecker:
    """Detect Claude account capabilities via CLI."""

    def detect(self) -> AccountCapabilities:
        """Detect account capabilities by querying Claude CLI."""
        model = self._detect_model()
        token_limit = self._detect_token_limit(model)
        return AccountCapabilities(
            model_available=model,
            has_vision=True,  # all modern Claude versions support vision
            has_file_handling=True,  # all modern Claude versions support files
            token_limit=token_limit,
            supported_tools=["bash", "read", "write", "edit"],  # standard
        )

    def _detect_model(self) -> str | None:
        """Detect available Claude model."""
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                output = result.stdout.lower()
                if "opus" in output:
                    return "opus"
                elif "sonnet" in output:
                    return "sonnet"
                elif "haiku" in output:
                    return "haiku"
        except (OSError, subprocess.TimeoutExpired):
            pass
        return None

    def _detect_token_limit(self, model: str | None) -> int:
        """Return token limit for detected model."""
        limits = {
            "opus": 200000,
            "sonnet": 200000,
            "haiku": 100000,
        }
        return limits.get(model or "", 200000)

    def check_settings(self, settings_path) -> dict:
        """Analyze settings.json to infer account capabilities."""
        try:
            if not settings_path.exists():
                return {}
            settings = json.loads(settings_path.read_text())
            return {
                "model": settings.get("model"),
                "has_mcp": bool(settings.get("mcpServers")),
                "has_hooks": bool(settings.get("hooks")),
                "has_subagents": bool(settings.get("subagents")),
            }
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
