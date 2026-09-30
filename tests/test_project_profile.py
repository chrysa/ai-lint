"""Project profile detection drives adaptive feedback."""

from __future__ import annotations

import json


def test_detect_project_profile_python_cli(tmp_path, linter_module):
    repo = tmp_path / "tool"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'tool'\n\n[project.scripts]\ntool = 'tool:main'\n")
    (repo / "tool.py").write_text("def main():\n    return 0\n")

    profile = linter_module.detect_project_profile(repo)

    assert profile["kind"] == "python-cli"
    assert profile["confidence"] == "high"
    assert "python" in profile["signals"]
    assert profile["adaptation"]["never_loosen"] is True


def test_detect_project_profile_standards_repo(tmp_path, linter_module):
    repo = tmp_path / "standards"
    (repo / "standards" / "rules").mkdir(parents=True)
    (repo / "standards" / "STANDARDS.chrysa.md").write_text("# Standards\n")

    profile = linter_module.detect_project_profile(repo)

    assert profile["kind"] == "standards-repo"
    assert profile["confidence"] == "high"
    assert "shared-standards" in profile["signals"]


def test_json_output_includes_project_profiles(env):
    proc = env.run(str(env.repos[0]), "--no-cli", "--no-history", "--format", "json", expect_ok=True)
    data = json.loads(proc.stdout)

    assert data["project_profiles"]
    assert data["project_profiles"][0]["kind"]
    assert "signals" in data["project_profiles"][0]
