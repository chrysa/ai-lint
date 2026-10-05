"""Real legacy Git bytes and interrupted CLI runs do not produce tracebacks."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from prism_ai_lint.git_runner import GitRunner
from prism_ai_lint.project_profile import ProjectProfiler
from prism_ai_lint.self_update import SelfUpdater

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def legacy_repo(tmp_path):
    def git(*args, **kwargs):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True, **kwargs)

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("config", "i18n.commitEncoding", "ISO-8859-1")
    git("config", "i18n.logOutputEncoding", "ISO-8859-1")
    git("commit", "--allow-empty", "-F", "-", input=b"Legacy caf\xe8 message\n")
    raw = git("log", "-1", "--format=%B").stdout
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    return tmp_path


def test_legacy_history_output_remains_available(linter_module, legacy_repo):
    output = linter_module.git(legacy_repo, "log", "-1", "--format=%H%x00%B%x01")
    assert "Legacy caf" in output
    assert "\ufffd" in output
    assert "\x00" in output and "\x01" in output


def test_shared_runner_handles_legacy_bytes(legacy_repo):
    runner = GitRunner(legacy_repo)
    assert "Legacy caf" in runner.output("log", "-1", "--format=%B")
    assert runner.run("log", "-1", "--format=%B").returncode == 0
    assert "Legacy caf" in ProjectProfiler(legacy_repo)._git("log", "-1", "--format=%B")


def test_cli_scans_real_non_utf8_history(legacy_repo):
    task_env = dict(os.environ, HOME=str(legacy_repo / "home"), AI_LINT_UPDATE_CHECK="0")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "prism-ai-lint.py"),
            str(legacy_repo),
            "--format",
            "json",
            "--no-cli",
            "--no-scaffold",
            "--no-update-check",
        ],
        capture_output=True,
        text=True,
        env=task_env,
        timeout=30,
    )
    assert result.returncode in (0, 1), result.stderr
    data = json.loads(result.stdout)
    assert data["repositories"] == [str(legacy_repo)]
    assert "UnicodeDecodeError" not in result.stderr


def test_cli_interrupt_exits_130_without_traceback():
    script = """
import runpy
from prism_ai_lint import _engine
def interrupt():
    raise KeyboardInterrupt
_engine.main = interrupt
runpy.run_path('prism-ai-lint.py', run_name='__main__')
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 130
    assert "prism-ai-lint interrupted." in result.stderr
    assert "Traceback" not in result.stderr


def test_successful_pull_marks_updater_for_exit(monkeypatch, tmp_path, capsys):
    updater = SelfUpdater()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "y")
    git = SimpleNamespace(
        root=tmp_path, output=lambda *a: "", run=lambda *a, **k: subprocess.CompletedProcess([], 0, "", "")
    )
    updater._offer_pull(git, "a" * 40, "b" * 40)
    assert updater.updated
    assert "Re-run the command" in capsys.readouterr().err


def test_failed_pull_does_not_mark_success(monkeypatch, tmp_path):
    updater = SelfUpdater()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "y")
    git = SimpleNamespace(
        root=tmp_path, output=lambda *a: "", run=lambda *a, **k: subprocess.CompletedProcess([], 1, "", "failed")
    )
    updater._offer_pull(git, "a" * 40, "b" * 40)
    assert not updater.updated


def test_main_stops_before_scan_after_update(linter_module, monkeypatch, tmp_path):
    def updated(self, args, force=False):
        self.updated = True

    monkeypatch.setattr(SelfUpdater, "check", updated)

    def scan_must_not_run(*args, **kwargs):
        raise AssertionError("updated code must be rerun before scanning")

    monkeypatch.setattr(linter_module, "run_lint", scan_must_not_run)
    assert linter_module.main([str(tmp_path), "--no-cli"]) == 0
