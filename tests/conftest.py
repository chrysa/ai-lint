"""Test harness for claude-lint.

Builds a miniature reproduction of the real environment (user scope +
project repos) inside temporary directories, with HOME and CLAUDE_CONFIG_DIR
overridden so nothing touches the developer's real config.

Everything written here is disposable and lives under pytest's tmp_path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "claude-lint.py"


def _load_module():
    """Import the linter module for white-box tests (now a normal importable name,
    so coverage and mypy see it directly)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import claude_lint

    return claude_lint


@pytest.fixture(scope="session")
def linter_module():
    return _load_module()


def _git(path: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(path), *args],
        check=True,
        capture_output=True,
    )


def _write(path: Path, text: str, mode: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mode is not None:
        os.chmod(path, mode)
    return path


def _make_git_repo(path: Path, files: dict[str, str]) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        _write(path / rel, content)
    _git(path, "init", "-q")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    return path


def _build_user_scope(cfg: Path) -> None:
    """~/.claude-perso equivalent: skills, subagents, agency pack, generated
    family, user hooks, settings, a leaked API key, signatures."""
    # settings.json with a hook pointing at a MISSING script
    _write(
        cfg / "settings.json",
        json.dumps(
            {
                "model": "claude-opus-4-8",
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [{"type": "command", "command": str(cfg / "hooks" / "missing.sh")}],
                        }
                    ]
                },
                "permissions": {"allow": ["Bash(rtk *)"], "deny": [], "ask": []},
            },
            indent=2,
        ),
    )
    # a fake leaked API key in a stray file
    _write(cfg / "notes.txt", "backup key sk-ant-api03-" + "A" * 80 + "\n")

    # user-scope skill (duplicated at project scope elsewhere)
    _write(
        cfg / "skills" / "check" / "SKILL.md",
        "---\nname: check\ndescription: run the project's lint and test commands\n---\n\nRun lint then tests.\n",
    )
    # a generated family of subagents (llmtrim-*)
    for name in ("llmtrim-codex", "llmtrim-grok", "llmtrim-kimi"):
        _write(
            cfg / "agents" / f"{name}.md",
            f"---\nname: {name}\ndescription: delegate to {name} provider\nmodel: inherit\n---\n\n"
            f"<!-- llmtrim-owned-route-agent-v1 -->\n<!-- llmtrim-route-v1:{name} -->\n\nRoute the task.\n",
        )
    # an agency pack: agents/agency/<domain>/
    for domain in ("backend", "frontend", "security"):
        _write(
            cfg / "agents" / "agency" / domain / "lead.md",
            f"---\nname: {domain}-lead\ndescription: {domain} domain lead\n---\n\n{domain} work.\n",
        )
    # a user-scope subagent duplicated at project scope
    _write(
        cfg / "agents" / "reviewer.md",
        "---\nname: reviewer\ndescription: review code changes for quality and correctness issues\n---\n\nReview diffs.\n",
    )
    # a big CLAUDE.md (1200 lines)
    _write(cfg / "CLAUDE.md", "# User memory\n" + "\n".join(f"- rule {i}" for i in range(1200)) + "\n")


def _build_projects(home: Path) -> list[Path]:
    """~60 repos in miniature: a couple of real repos, a copied repo, worktrees,
    a plugins dir."""
    repos: list[Path] = []

    proj = home / "dev" / "app"
    _make_git_repo(
        proj,
        {
            "CLAUDE.md": "@AGENTS.md\n",
            "AGENTS.md": "# app\n\n## Overview\n\n## Commands\n\n## Conventions\n\n## Boundaries\n",
            ".mcp.json": json.dumps(
                {"mcpServers": {"github": {"type": "http", "url": "https://api.githubcopilot.com/mcp/"}}},
                indent=2,
            ),
            ".claude/settings.json": json.dumps(
                {"permissions": {"allow": ["Bash(git push:*)"], "deny": [], "ask": []}}, indent=2
            ),
            # project-scope duplicate of the user 'check' skill
            ".claude/skills/check/SKILL.md": "---\nname: check\ndescription: run the project's lint and test commands\n---\n\nRun lint then tests.\n",
            # project-scope duplicate of the user 'reviewer' subagent
            ".claude/agents/reviewer.md": "---\nname: reviewer\ndescription: review code changes for quality and correctness issues\n---\n\nReview diffs.\n",
            ".claude/commands/deploy.md": "---\ndescription: deploy the service to production\n---\n\nDeploy now.\n",
            "doctrine/rules/style.md": "Prefer clarity.\n",
        },
    )
    repos.append(proj)

    # a copied clone of the same repo (dedup / same-repo detection)
    copy = home / "dev" / "app-copy"
    _make_git_repo(
        copy,
        {
            "CLAUDE.md": (proj / "CLAUDE.md").read_text(),
            "AGENTS.md": (proj / "AGENTS.md").read_text(),
        },
    )
    repos.append(copy)

    # a git worktree under .claude/worktrees/
    wt = proj / ".claude" / "worktrees" / "feature"
    wt.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "-C", str(proj), "worktree", "add", "-q", str(wt)],
        check=True,
        capture_output=True,
    )

    # a plugins dir: padam-claude-skills/plugins/*
    _write(
        home / "padam-claude-skills" / "plugins" / "demo" / "plugin.json",
        json.dumps({"name": "demo", "version": "0.1.0"}, indent=2),
    )
    _write(
        home / "padam-claude-skills" / "plugins" / "demo" / "skills" / "hello" / "SKILL.md",
        "---\nname: hello\ndescription: say hello\n---\n\nHi.\n",
    )

    return repos


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Full miniature environment. Returns an object with home, cfg, repos and a
    run() helper that invokes the CLI as a subprocess with HOME/CLAUDE_CONFIG_DIR
    overridden."""
    home = tmp_path / "home"
    home.mkdir()
    cfg = home / ".claude-perso"
    cfg.mkdir()
    cache = home / ".cache"
    cache.mkdir()

    _build_user_scope(cfg)
    repos = _build_projects(home)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.delenv("RTK_CONFIG", raising=False)

    class Env:
        pass

    e = Env()
    e.home = home
    e.cfg = cfg
    e.cache = cache
    e.repos = repos

    def run(*args: str, expect_ok: bool = False):
        # Under coverage, launch the CLI through `coverage run --parallel` so the
        # subprocess is measured too; the outer `coverage combine` merges the data.
        if os.environ.get("COVERAGE_RUN"):
            cmd = [
                sys.executable,
                "-m",
                "coverage",
                "run",
                "--parallel-mode",
                "--rcfile",
                str(ROOT / "pyproject.toml"),
                str(SCRIPT),
                *args,
            ]
        else:
            cmd = [sys.executable, str(SCRIPT), *args]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "HOME": str(home),
                "CLAUDE_CONFIG_DIR": str(cfg),
                "XDG_CACHE_HOME": str(cache),
            },
            cwd=str(home),
        )
        if expect_ok:
            assert proc.returncode in (0, 1), (proc.returncode, proc.stdout, proc.stderr)
        assert "Traceback (most recent call last)" not in proc.stderr, proc.stderr
        return proc

    e.run = run
    return e
