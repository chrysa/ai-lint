"""Former ai-lint names keep working during the transition to prism-ai-lint."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_former_policy_file_is_read_with_a_deprecation_warning(linter_module, tmp_path, capsys):
    (tmp_path / ".ai-lint.toml").write_text("[tokens]\nmax_always_loaded = 1234\n")
    policy = linter_module.load_policy(None, [tmp_path])
    assert policy["tokens"]["max_always_loaded"] == 1234
    assert "rename it to .prism-ai-lint.toml" in capsys.readouterr().err


def test_new_policy_file_wins_without_warning(linter_module, tmp_path, capsys):
    (tmp_path / ".ai-lint.toml").write_text("[tokens]\nmax_always_loaded = 1\n")
    (tmp_path / ".prism-ai-lint.toml").write_text("[tokens]\nmax_always_loaded = 2\n")
    assert linter_module.load_policy(None, [tmp_path])["tokens"]["max_always_loaded"] == 2
    assert "former policy name" not in capsys.readouterr().err


def test_former_policy_file_stays_protected(tmp_path):
    from prism_ai_lint.content_validation import CriticalContentValidator

    assert CriticalContentValidator([tmp_path]).is_critical(tmp_path / ".ai-lint.toml")


def test_restore_finds_sessions_in_the_former_cache(linter_module, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    session = tmp_path / ".cache" / "ai-lint" / "trash" / "20260101T000000000000"
    original = tmp_path / "work" / "note.md"
    (session / str(original).lstrip("/")).parent.mkdir(parents=True)
    (session / str(original).lstrip("/")).write_text("back")
    assert linter_module.restore_trash(None) == 0
    assert original.read_text() == "back"


def test_former_flags_file_is_honoured(tmp_path):
    (tmp_path / ".ai-lint.toml").write_text('[flags]\nformat = "json"\n')
    env = {**os.environ, "HOME": str(tmp_path), "AI_LINT_UPDATE_CHECK": "0"}
    res = subprocess.run(
        [sys.executable, str(ROOT / "prism-ai-lint.py"), ".", "--no-cli", "--no-scaffold", "--no-history"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert res.stdout.lstrip().startswith("{")
