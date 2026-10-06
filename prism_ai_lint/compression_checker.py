"""Compression layers checker: rtk, llmtrim and a routing gateway can compress the same traffic twice."""

from __future__ import annotations

import json
import re
from typing import Any

LOCAL_GATEWAY_RE = re.compile(r"(?:^https?://(?:localhost|127\.0\.0\.1|\[::1\])[:/])|(?:omniroute)", re.IGNORECASE)


class CompressionChecker:
    """Detect token-compression layers declared in settings; stdlib only, read-only."""

    @staticmethod
    def layers(settings: list[Any]) -> list[str]:
        """Names of the compression layers found in parsed settings objects (sorted)."""
        found: set[str] = set()
        for s in settings:
            if not isinstance(s, dict):
                continue
            blob = json.dumps(s.get("hooks") or {}) + json.dumps(s.get("mcpServers") or {})
            if re.search(r"\brtk\b", blob):
                found.add("rtk")
            if "llmtrim" in blob.lower():
                found.add("llmtrim")
            env = s.get("env")
            base = env.get("ANTHROPIC_BASE_URL") if isinstance(env, dict) else None
            if isinstance(base, str) and LOCAL_GATEWAY_RE.search(base):
                found.add("router")
        return sorted(found)

    def advice(self, layers: list[str]) -> str | None:
        """One finding message when two or more layers are active, else None."""
        if len(layers) < 2:
            return None
        return (
            f"{' + '.join(layers)} are all configured: they may compress the same traffic twice "
            "(lost context, little extra saving); keep one layer per path and measure the gain"
        )
