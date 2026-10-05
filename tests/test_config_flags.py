"""[flags] defaults: only non-writing options, validated, command line wins."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from prism_ai_lint.config_flags import ConfigFlags

ROOT = Path(__file__).resolve().parent.parent


def _write(tmp_path, body):
    p = tmp_path / ".prism-ai-lint.toml"
    p.write_text(body)
    return ConfigFlags(p)


def test_safe_flags_become_defaults(tmp_path):
    defaults, rejected = _write(tmp_path, '[flags]\nstrict = true\nverbose = 2\nformat = "json"\n').load()
    assert defaults == {"strict": True, "verbose": 2, "format": "json"}
    assert rejected == []


def test_writing_or_approving_flags_are_rejected(tmp_path):
    body = "[flags]\nfix = true\nfull_yes = true\napprove_conversion = true\nuser = true\nplugin_dir = '/tmp'\n"
    defaults, rejected = _write(tmp_path, body).load()
    assert defaults == {}
    assert len(rejected) == 5


def test_wrong_types_and_choices_are_rejected(tmp_path):
    defaults, rejected = _write(tmp_path, '[flags]\nstrict = "yes"\nverbose = -1\nformat = "xml"\n').load()
    assert defaults == {}
    assert len(rejected) == 3


def test_missing_or_broken_file(tmp_path):
    assert ConfigFlags(tmp_path / "none.toml").load() == ({}, [])
    defaults, rejected = _write(tmp_path, "[flags\n").load()
    assert defaults == {} and len(rejected) == 1


def test_cli_run_honours_flags_and_command_line_wins(tmp_path):
    (tmp_path / ".prism-ai-lint.toml").write_text('[flags]\nformat = "json"\nfix = true\n')
    base = [sys.executable, str(ROOT / "prism-ai-lint.py"), ".", "--no-cli", "--no-scaffold", "--no-history"]
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "AI_LINT_UPDATE_CHECK": "0"}
    res = subprocess.run(base, cwd=tmp_path, capture_output=True, text=True, env=env, timeout=120)
    assert res.stdout.lstrip().startswith("{")
    assert "fix: not allowed in [flags]" in res.stderr
    assert not (tmp_path / ".claude").exists()  # fix = true was not applied
    res = subprocess.run(
        [*base, "--format", "text"], cwd=tmp_path, capture_output=True, text=True, env=env, timeout=120
    )
    assert not res.stdout.lstrip().startswith("{")
