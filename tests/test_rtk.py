"""rtk rewrite probe: must detect support from stdout, not the exit code
(rtk 0.42.1 exits 3 on a successful rewrite)."""

from __future__ import annotations

import shutil
import subprocess

import pytest


class _Res:
    def __init__(self, rc, out):
        self.returncode = rc
        self.stdout = out
        self.stderr = ""


def _fake_run_factory(supported_prefixes):
    """Simulate rtk 0.42.1: rewrite prints 'rtk <cmd>' and exits 3 when supported,
    prints nothing and exits 1 otherwise; --version/gain/--help succeed."""

    def fake(cmd, timeout=10):
        if cmd[:2] == ["rtk", "rewrite"]:
            raw = cmd[2] if len(cmd) > 2 else ""
            first = raw.split()[0] if raw.split() else ""
            if first in supported_prefixes:
                return _Res(3, f"rtk {raw}")
            return _Res(1, "")
        if cmd == ["rtk", "--version"]:
            return _Res(0, "rtk 0.42.1")
        if cmd[:2] == ["rtk", "gain"]:
            return _Res(0, "usage")
        if cmd == ["rtk", "--help"]:
            return _Res(
                0, "  git   thing\n  cargo build\n" + "\n".join(f"  cmd{i} x" for i in range(12))
            )
        return _Res(0, "")

    return fake


def _reset_rtk(m):
    m.RTK.update(
        {
            "path": None,
            "version": None,
            "genuine": False,
            "help_commands": set(),
            "rewrite_cli": None,
            "rewrite_cache": {},
            "exclude": set(),
            "config": None,
        }
    )


def test_rewrite_probe_ignores_exit_code(linter_module, monkeypatch, tmp_path):
    m = linter_module
    _reset_rtk(m)
    monkeypatch.setattr(m.shutil, "which", lambda x: "/usr/bin/rtk")
    monkeypatch.setattr(m, "_run", _fake_run_factory({"git", "cargo"}))
    monkeypatch.setattr(m, "read_text", lambda p: None)  # no config file
    m.detect_rtk(use_cli=True)
    assert m.RTK["rewrite_cli"] is True
    assert m.rtk_rewrites("git status") is True
    assert m.rtk_rewrites("cargo build") is True
    assert m.rtk_rewrites("frobnicate x") is False


@pytest.mark.skipif(not shutil.which("rtk"), reason="rtk not installed")
def test_real_rtk_rewrite_is_detected(linter_module):
    # Integration guard against the real binary on this machine.
    res = subprocess.run(["rtk", "rewrite", "git status"], capture_output=True, text=True)
    assert res.stdout.strip().startswith("rtk"), (res.returncode, res.stdout)
