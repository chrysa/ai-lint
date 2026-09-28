"""Smoke tests: the CLI runs read-only over the miniature environment without
crashing, and the module imports cleanly for white-box tests."""

from __future__ import annotations


def test_module_imports(linter_module):
    assert hasattr(linter_module, "VERSION")
    assert isinstance(linter_module.VERSION, str)


def test_readonly_project_scope(env):
    proc = env.run(str(env.repos[0]), "--no-cli", "--no-history", expect_ok=True)
    assert proc.stdout or proc.stderr


def test_readonly_user_scope(env):
    proc = env.run("--user-only", "--no-cli", expect_ok=True)
    assert proc.stdout or proc.stderr


def test_no_traceback_details(env):
    env.run(str(env.repos[0]), "--user", "--no-cli", "--no-history", "--details", expect_ok=True)
