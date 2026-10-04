"""Modular CLI flags and config file handling."""

from __future__ import annotations

import argparse
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CLIFlags:
    """CLI flags with config file override support."""

    fix: bool = False
    user: bool = False
    user_only: bool = False
    strict: bool = False
    no_history: bool = False
    no_scaffold: bool = False
    no_cli: bool = False
    no_rtk: bool = False
    no_update_check: bool = False
    update_check: bool = False
    interactive: bool = False
    full_yes: bool = False
    convert_to: str | None = None
    convert_from: str | None = None
    approve_conversion: bool = False
    apply_conversion: bool = False
    verbose: int = 0
    format: str = "text"  # text, brief, json
    detail: bool = False
    diff: bool = False
    graphify: bool = False

    def merge_from_toml(self, toml_flags: dict) -> None:
        """Update flags from TOML config [flags] section, skipping defaults."""
        for key, value in toml_flags.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def to_args_namespace(self) -> argparse.Namespace:
        """Convert to argparse.Namespace for CLI compatibility."""
        return argparse.Namespace(**self.__dict__)

    @classmethod
    def from_args_namespace(cls, args: argparse.Namespace) -> CLIFlags:
        """Extract CLIFlags from argparse result."""
        flags = cls()
        for field_name in flags.__dataclass_fields__:
            if hasattr(args, field_name):
                setattr(flags, field_name, getattr(args, field_name))
        return flags


def load_flags_from_config(config_path: Path) -> dict | None:
    """Load [flags] section from TOML config file."""
    if not config_path.exists():
        return None
    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        return data.get("flags", {})
    except (OSError, ValueError, RuntimeError):
        return None


def apply_config_flags(args: argparse.Namespace, config_path: Path | None) -> None:
    """Apply config file flags to args as baseline; CLI parsing overrides after."""
    if not config_path:
        return
    toml_flags = load_flags_from_config(config_path)
    if not toml_flags:
        return
    # Set TOML flags first; they act as defaults. Caller should re-parse CLI args
    # after this to override (argparse handles precedence via nargs/action).
    for key, value in toml_flags.items():
        if hasattr(args, key):
            setattr(args, key, value)
