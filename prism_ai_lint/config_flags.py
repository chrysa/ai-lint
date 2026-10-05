"""CLI defaults from the [flags] table of the policy file, limited to options that never write."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

# Only options that change what is reported or which external tools are probed. Anything
# that writes, approves, widens the scope or loads code (fix, generate, interactive,
# full_yes, user, approve_conversion, plugin_dir, policy...) must come from the command
# line: a policy file inside a scanned repository must not turn a read-only run into one
# that modifies files or approves critical content.
SAFE_FLAGS: dict[str, type] = {
    "strict": bool,
    "no_history": bool,
    "no_cli": bool,
    "no_rtk": bool,
    "no_update_check": bool,
    "no_scaffold": bool,
    "details": bool,
    "all": bool,
    "diff": bool,
    "quiet": bool,
    "verbose": int,
    "format": str,
    "lang": str,
    "min_level": str,
}
CHOICES = {"format": ("text", "json"), "lang": ("en", "fr"), "min_level": ("error", "warn", "info")}


class ConfigFlags:
    """Read [flags] from a policy file and return argparse defaults plus rejection notes."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[dict[str, Any], list[str]]:
        try:
            with self.path.open("rb") as fh:
                table = tomllib.load(fh).get("flags", {})
        except FileNotFoundError:
            return {}, []
        except (OSError, tomllib.TOMLDecodeError) as e:
            return {}, [f"{self.path}: ignored ({e})"]
        if not isinstance(table, dict):
            return {}, [f"{self.path}: [flags] must be a table"]
        defaults: dict[str, Any] = {}
        rejected: list[str] = []
        for key, value in table.items():
            kind = SAFE_FLAGS.get(key)
            if kind is None:
                rejected.append(f"{key}: not allowed in [flags] (pass it on the command line)")
            elif type(value) is not kind or (isinstance(value, int) and value < 0):
                rejected.append(f"{key}: expected {kind.__name__}, got {value!r}")
            elif key in CHOICES and value not in CHOICES[key]:
                rejected.append(f"{key}: expected one of {', '.join(CHOICES[key])}, got {value!r}")
            else:
                defaults[key] = value
        return defaults, rejected
