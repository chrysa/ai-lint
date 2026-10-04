"""Default-verbosity progress bar: writes to stderr only when enabled, never to
stdout, and stays silent when piped (the test process has no TTY)."""

from __future__ import annotations


def test_progress_silent_when_disabled(linter_module, capsys, monkeypatch):
    m = linter_module
    monkeypatch.setattr(m.state, "progress", False)
    m.progress(1, 10, "repo")
    err = capsys.readouterr()
    assert err.out == "" and err.err == ""


def test_progress_writes_stderr_when_enabled(linter_module, capsys, monkeypatch):
    m = linter_module
    monkeypatch.setattr(m.state, "progress", True)
    m.progress(3, 10, "myrepo")
    cap = capsys.readouterr()
    assert cap.out == "", "progress must never touch stdout"
    assert "scan [" in cap.err and "3/10" in cap.err


def test_report_stdout_has_no_bar(env):
    # piped run (no TTY): the bar must not appear anywhere in stdout
    proc = env.run(str(env.repos[0]), "--no-cli", "--no-history", "--details", expect_ok=True)
    assert "scan [" not in proc.stdout
