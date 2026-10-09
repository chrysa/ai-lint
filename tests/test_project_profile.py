"""Project profile detection drives adaptive feedback."""

from __future__ import annotations

import json

from prism_ai_lint.feedback_renderer import FeedbackRenderer
from prism_ai_lint.finding import Finding
from prism_ai_lint.project_profile import ProjectProfiler


def test_detect_project_profile_python_cli(tmp_path):
    repo = tmp_path / "tool"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'tool'\n\n[project.scripts]\ntool = 'tool:main'\n")
    (repo / "tool.py").write_text("def main():\n    return 0\n")

    profile = ProjectProfiler(repo).detect_profile()

    assert profile["kind"] == "python-cli"
    assert profile["confidence"] == "high"
    assert "python" in profile["signals"]
    assert profile["adaptation"]["never_loosen"] is True


def test_detect_project_profile_standards_repo(tmp_path):
    repo = tmp_path / "standards"
    (repo / "standards" / "rules").mkdir(parents=True)
    (repo / "standards" / "STANDARDS.example.md").write_text("# Standards\n")

    markers = ("standards/STANDARDS.example.md", "standards/rules")
    profile = ProjectProfiler(repo, markers).detect_profile()

    assert profile["kind"] == "standards-repo"
    assert profile["confidence"] == "high"
    assert "standards" in profile["signals"]


def test_standards_detection_is_off_without_policy_markers(tmp_path):
    repo = tmp_path / "standards"
    (repo / "standards" / "rules").mkdir(parents=True)
    (repo / "standards" / "STANDARDS.example.md").write_text("# Standards\n")
    profile = ProjectProfiler(repo).detect_profile()
    assert profile["kind"] != "standards-repo"
    assert "standards" not in profile["signals"]


def test_json_output_includes_project_profiles(env):
    proc = env.run(str(env.repos[0]), "--no-cli", "--no-history", "--format", "json", expect_ok=True)
    data = json.loads(proc.stdout)

    assert data["project_profiles"]
    assert data["project_profiles"][0]["kind"]
    assert "signals" in data["project_profiles"][0]


def test_finding_feedback_contract(linter_module):
    finding = linter_module.Finding(
        "warn",
        "DUP_EXACT",
        "CLAUDE.md",
        "duplicate always-loaded instruction",
        False,
    )

    data = linter_module.finding_feedback(finding)

    assert data["code"] == "DUP_EXACT"
    assert data["status"] == "open"
    assert data["fix_mode"] == "interactive"
    assert data["category"]
    assert data["evidence"] == {
        "path": "CLAUDE.md",
        "message": "duplicate always-loaded instruction",
    }
    assert data["next_action"]


def test_feedback_renderer_contract_directly():
    renderer = FeedbackRenderer("en", {}, {}, [("DUP_", "duplicates")])
    finding = Finding("warn", "DUP_NAME", "AGENTS.md", "duplicate name", False)

    data = renderer.finding_feedback(finding)

    assert data["category"] == "duplicates"
    assert data["fix_mode"] == "interactive"
    assert data["manual_reason"] is None
    assert data["next_action"].startswith("run with -i")
