"""--generate: preview is read-only; --generate --fix scaffolds a detected stack
without crashing and produces valid JSON settings."""

from __future__ import annotations

import json
import subprocess


def _py_repo(tmp_path):
    repo = tmp_path / "svc"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='svc'\n")
    (repo / "app.py").write_text("print('hi')\n")
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(repo), "init", "-q"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(repo), "commit", "-qm", "i"],
        check=True,
        capture_output=True,
    )
    return repo


def test_generate_preview_is_readonly(env, tmp_path):
    repo = _py_repo(tmp_path)
    before = sorted(p.name for p in repo.rglob("*"))
    proc = env.run(str(repo), "--generate", "--no-cli", "--no-history", expect_ok=True)
    after = sorted(p.name for p in repo.rglob("*"))
    assert before == after, "preview must not write anything"
    assert proc.stdout


def test_generate_fix_scaffolds_valid_settings(env, tmp_path):
    repo = _py_repo(tmp_path)
    env.run(str(repo), "--generate", "--fix", "--no-cli", "--no-history", expect_ok=True)
    settings = repo / ".claude" / "settings.json"
    assert settings.is_file(), "generation should create .claude/settings.json"
    data = json.loads(settings.read_text())  # must be valid JSON
    assert "permissions" in data
    # a second lint pass over the generated result stays clean of write errors
    proc = env.run(str(repo), "--no-cli", "--no-history", "--format", "json", expect_ok=True)
    findings = json.loads(proc.stdout)["findings"]
    assert not any(f["code"] == "WRITE_FAILED" for f in findings)
