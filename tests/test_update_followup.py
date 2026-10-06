"""Tests for the post-update follow-up (changelog and repairs)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from prism_ai_lint.git_runner import GitRunner
from prism_ai_lint.update_followup import UpdateFollowUp


def _repo(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

    def git(*a):
        return subprocess.run(
            ["git", *a], cwd=root, env={**__import__("os").environ, **env}, capture_output=True, text=True, check=True
        ).stdout.strip()

    git("init", "-q")
    for i in range(3):
        (root / "f").write_text(str(i))
        git("add", "f")
        git("commit", "-q", "-m", f"feat: change {i}")
    return root, git("rev-parse", "HEAD~2"), git("rev-parse", "HEAD")


def _follow(tmp_path, answers, ran):
    root, old, new = _repo(tmp_path)
    it = iter(answers)
    f = UpdateFollowUp(
        GitRunner(root), ask=lambda _p: next(it), run=lambda c: ran.append(c) or 0, home=tmp_path / "home"
    )
    return f, old, new


def test_changelog_lists_new_commits(tmp_path):
    f, old, new = _follow(tmp_path, [], [])
    lines = f.changelog(old, new)
    assert len(lines) == 2
    assert "change 2" in lines[0]


def test_skip_runs_nothing(tmp_path):
    ran = []
    f, old, new = _follow(tmp_path, ["n", ""], ran)
    f.offer(old, new)
    assert ran == []


def test_folder_runs_fix_on_that_folder_only(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    ran = []
    f, old, new = _follow(tmp_path, ["y", str(target), "y"], ran)
    f.offer(old, new)
    assert len(ran) == 1
    assert str(target.resolve()) in ran[0]
    assert "--fix" in ran[0]
    assert "--user" not in ran[0]


def test_all_runs_home_with_user_scope(tmp_path):
    ran = []
    f, old, new = _follow(tmp_path, ["n", "all", "y"], ran)
    f.offer(old, new)
    assert str(tmp_path / "home") in ran[0]
    assert "--user" in ran[0]


def test_declined_confirmation_runs_nothing(tmp_path):
    ran = []
    f, old, new = _follow(tmp_path, ["n", "all", "n"], ran)
    f.offer(old, new)
    assert ran == []


def test_invalid_folder_runs_nothing(tmp_path):
    ran = []
    f, old, new = _follow(tmp_path, ["n", str(tmp_path / "missing")], ran)
    f.offer(old, new)
    assert ran == []


def test_command_never_loosens_flags(tmp_path):
    f, _, _ = _follow(tmp_path, [], [])
    cmd = f.command_for("all")
    assert cmd is not None
    assert "--full-yes" not in cmd
    assert Path(cmd[1]).name == "prism-ai-lint.py"
