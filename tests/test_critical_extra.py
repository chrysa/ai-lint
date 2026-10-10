"""[critical] extra_files: repository-specific critical files, added on top of generic defaults."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from prism_ai_lint._runtime import state
from prism_ai_lint.content_validation import CriticalContentValidator

ROOT = Path(__file__).resolve().parent.parent


def test_generic_defaults_do_not_name_project_documents(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "critical_extra", ())
    validator = CriticalContentValidator([tmp_path])
    assert not validator.is_critical(tmp_path / "docs" / "CONVENTIONS.md")
    assert validator.is_critical(tmp_path / "AGENTS.md")


def test_extra_files_from_policy_are_critical(linter_module, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "critical_extra", ())
    (tmp_path / ".prism-ai-lint.toml").write_text(
        '[critical]\nextra_files = ["docs/OPS.md", "../escape.md", "/etc/x"]\n'
    )
    linter_module.load_policy(None, [tmp_path])
    assert state.critical_extra == ("docs/OPS.md",)
    validator = CriticalContentValidator([tmp_path])
    assert validator.is_critical(tmp_path / "docs" / "OPS.md")
    assert validator.validation_reason(tmp_path / "docs" / "OPS.md", "a", "b") is not None


def test_this_repository_keeps_its_documents_protected_under_the_guard():
    """Moving project documents out of the defaults must not loosen the guard here."""
    target = ROOT / "docs" / "CONVENTIONS.md"
    payload = {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(target), "old_string": "prism-ai-lint", "new_string": "x"},
    }
    res = subprocess.run(
        [sys.executable, str(ROOT / "prism_ai_lint" / "_engine.py"), "--guard"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=60,
    )
    assert res.returncode == 2, res.stderr
    assert "needs validation" in res.stderr
