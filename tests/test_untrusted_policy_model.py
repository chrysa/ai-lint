"""A scanned project's policy must never choose what is written into the user's configuration."""

from __future__ import annotations

import json
import subprocess

import pytest

from prism_ai_lint._reference import safe_model


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("sonnet", "sonnet"),
        ("Haiku", "haiku"),
        ("claude-opus-5-5", "claude-opus-5-5"),
        ("claude-opus-4-5-20251101", "claude-opus-4-5-20251101"),
        ("evil-route", "fb"),
        ("x\ndisable-model-invocation: false", "fb"),
        ("../../etc/passwd", "fb"),
        ("", "fb"),
        (None, "fb"),
    ],
)
def test_safe_model(value, expected):
    assert safe_model(value, "fb") == expected


def _project(tmp_path, preferred, sub="haiku"):
    repo = tmp_path / "repo"
    (repo / ".claude" / "agents").mkdir(parents=True)
    (repo / ".claude" / "agents" / "test-runner.md").write_text(
        "---\nname: test-runner\ndescription: Run the test suite\ntools: Read, Grep\n---\nbody\n"
    )
    (repo / ".prism-ai-lint.toml").write_text(
        f"[tokens]\npreferred_model = {json.dumps(preferred)}\nsubagent_model = {json.dumps(sub)}\n"
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def test_hostile_policy_cannot_set_the_global_model_even_with_full_yes(env, tmp_path):
    repo = _project(tmp_path, "evil-route")
    settings = env.cfg / "settings.json"
    settings.write_text(json.dumps({"model": "claude-fable-5-1"}))
    env.run(str(repo), "--user", "--fix", "--full-yes", "--no-cli", "--no-update-check")
    assert json.loads(settings.read_text())["model"] == "sonnet"


def test_hostile_subagent_model_cannot_inject_frontmatter(env, tmp_path):
    repo = _project(tmp_path, "sonnet", sub="x\ndisable-model-invocation: false")
    agent = repo / ".claude" / "agents" / "test-runner.md"
    before = agent.read_text()
    env.run(str(repo), "--fix", "--full-yes", "--no-cli", "--no-update-check")
    after = agent.read_text()
    assert "disable-model-invocation" not in after
    assert after == before or "model: haiku" in after
