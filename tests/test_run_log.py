"""Each run appends a JSON record to ~/.cache/prism-ai-lint/logs/<date>.log."""

from __future__ import annotations

import datetime as dt
import json


def _log_file(env):
    return env.home / ".cache" / "prism-ai-lint" / "logs" / (dt.date.today().isoformat() + ".log")


def test_run_writes_log(env):
    env.run(str(env.repos[0]), "--no-cli", "--no-history", expect_ok=True)
    lf = _log_file(env)
    assert lf.is_file()
    rec = json.loads(lf.read_text().splitlines()[-1])
    assert rec["version"]
    assert "findings" in rec and "exit" in rec and "elapsed_s" in rec


def test_runs_append(env):
    env.run(str(env.repos[0]), "--no-cli", "--no-history", expect_ok=True)
    env.run(str(env.repos[0]), "--no-cli", "--no-history", "--lang", "en", expect_ok=True)
    lines = _log_file(env).read_text().splitlines()
    assert len(lines) >= 2


def test_log_has_no_secret_values(env):
    # the user settings fixture holds a fake key; the log must not echo file contents
    env.run("--user-only", "--no-cli", expect_ok=True)
    text = _log_file(env).read_text()
    assert "sk-ant-api03" not in text
