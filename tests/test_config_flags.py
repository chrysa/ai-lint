"""Tests for modular CLI flags and config file handling."""

from __future__ import annotations

import argparse
from pathlib import Path

from ai_lint.config_flags import CLIFlags, apply_config_flags, load_flags_from_config


def test_cli_flags_defaults():
    flags = CLIFlags()
    assert flags.fix is False
    assert flags.user is False
    assert flags.strict is False
    assert flags.verbose == 0
    assert flags.format == "text"


def test_cli_flags_to_namespace():
    flags = CLIFlags(fix=True, user=True, verbose=2)
    ns = flags.to_args_namespace()
    assert ns.fix is True
    assert ns.user is True
    assert ns.verbose == 2


def test_cli_flags_from_namespace():
    ns = argparse.Namespace(fix=True, user=True, verbose=2, strict=False)
    flags = CLIFlags.from_args_namespace(ns)
    assert flags.fix is True
    assert flags.user is True
    assert flags.verbose == 2


def test_cli_flags_merge_from_toml():
    flags = CLIFlags()
    toml_flags = {"fix": True, "strict": True, "verbose": 2}
    flags.merge_from_toml(toml_flags)
    assert flags.fix is True
    assert flags.strict is True
    assert flags.verbose == 2


def test_load_flags_from_toml_file(tmp_path):
    config_file = tmp_path / ".ai-lint.toml"
    config_file.write_text(
        """
[flags]
fix = true
user = true
verbose = 1
strict = false
"""
    )
    flags = load_flags_from_config(config_file)
    assert flags is not None
    assert flags["fix"] is True
    assert flags["user"] is True
    assert flags["verbose"] == 1
    assert flags["strict"] is False


def test_load_flags_nonexistent_file():
    flags = load_flags_from_config(Path("/nonexistent/.ai-lint.toml"))
    assert flags is None


def test_load_flags_no_flags_section(tmp_path):
    config_file = tmp_path / ".ai-lint.toml"
    config_file.write_text("[other]\nkey = true")
    flags = load_flags_from_config(config_file)
    assert flags == {}


def test_apply_config_flags_override(tmp_path):
    config_file = tmp_path / ".ai-lint.toml"
    config_file.write_text("[flags]\nfix = true\nuser = true")
    args = argparse.Namespace(fix=False, user=False, strict=False, verbose=0)
    apply_config_flags(args, config_file)
    assert args.fix is True  # config should set it
    assert args.user is True


def test_apply_config_flags_applies_all(tmp_path):
    config_file = tmp_path / ".ai-lint.toml"
    config_file.write_text("[flags]\nfix = true\nuser = true\nstrict = false")
    args = argparse.Namespace(fix=False, user=False, strict=True, verbose=0)
    apply_config_flags(args, config_file)
    # Config flags applied; CLI precedence is caller's responsibility via argparse ordering.
    assert args.fix is True
    assert args.user is True
    assert args.strict is False


def test_apply_config_flags_no_config():
    args = argparse.Namespace(fix=False, user=False)
    apply_config_flags(args, None)
    assert args.fix is False
    assert args.user is False
