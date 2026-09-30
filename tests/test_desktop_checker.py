"""Desktop observations distinguish detected evidence from runtime guarantees."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ai_lint.desktop_checker import DesktopChecker
from ai_lint.project_profile import ProjectProfiler
from ai_lint.report import Report

ROOT = Path(__file__).resolve().parents[1]


def package(root, data):
    (root / "package.json").write_text(json.dumps(data))


@pytest.mark.parametrize("framework", ["PySide6", "PyQt6", "kivy", "wxPython"])
def test_python_dependencies_detect_desktop(tmp_path, framework):
    (tmp_path / "requirements.txt").write_text(f"{framework}>=1\n")
    profile = ProjectProfiler(tmp_path).detect_profile()
    assert profile["kind"] == "desktop-app"
    assert framework.lower() in profile["desktop"]["frameworks"]


def test_tkinter_entrypoint(tmp_path):
    (tmp_path / "main.py").write_text("import tkinter as tk\n")
    assert DesktopChecker(tmp_path).detect()["frameworks"] == ["tkinter"]


@pytest.mark.parametrize("dependency,framework", [("electron", "electron"), ("@tauri-apps/api", "tauri")])
def test_javascript_desktop_beats_frontend_profile(tmp_path, dependency, framework):
    package(tmp_path, {"devDependencies": {dependency: "1", "react": "1"}})
    profile = ProjectProfiler(tmp_path).detect_profile()
    assert profile["kind"] == "desktop-app"
    assert profile["desktop"]["frameworks"] == [framework]


def test_web_project_has_no_desktop_noise(tmp_path):
    package(tmp_path, {"dependencies": {"react": "1"}})
    rep = Report()
    result = DesktopChecker(tmp_path).check(rep)
    assert not result["detected"]
    assert not rep.findings
    assert ProjectProfiler(tmp_path).detect_profile()["kind"] == "frontend"


def test_three_platform_assumptions(tmp_path):
    (tmp_path / "main.py").write_text(
        'import tkinter\nlinux="/home/name/config"\nmac="/Users/name/Library/Application Support/App"\nwindows=r"C:\\Users\\name"\n'
    )
    rep = Report()
    DesktopChecker(tmp_path).check(rep)
    messages = [f.message for f in rep.findings if f.code == "DESKTOP_PATH_ASSUMPTION"]
    assert len(messages) == 3
    assert {m.split(":")[0] for m in messages} == {"linux", "macos", "windows"}
    assert all(not f.fixable for f in rep.findings)
    assert not rep.edits and not rep.new_files


def test_launch_scripts_and_ci_are_observations(tmp_path):
    package(
        tmp_path,
        {
            "devDependencies": {"electron": "1"},
            "scripts": {"build": "NODE_ENV=prod electron-builder", "test": "powershell -File test.ps1"},
            "build": {"win": {"target": "nsis"}},
        },
    )
    workflows = tmp_path / ".github/workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("runs-on: ubuntu-latest\n# macos-latest pending\n")
    rep = Report()
    result = DesktopChecker(tmp_path).check(rep)
    assert result["os"]["linux"]["ci_runner_observed"]
    assert result["os"]["macos"]["ci_runner_observed"]  # Literal observation includes comments.
    assert not result["os"]["windows"]["ci_runner_observed"]
    assert not result["runtime_verified"]
    assert result["packaging"] == ["package.json:build"]
    assert len([f for f in rep.findings if f.code == "DESKTOP_LAUNCH_ASSUMPTION"]) == 2


@pytest.mark.parametrize("text", ["[]", "null", "{bad", '{"dependencies": [], "scripts": []}'])
def test_malformed_or_unexpected_package_shapes(tmp_path, text):
    (tmp_path / "package.json").write_text(text)
    rep = Report()
    assert not DesktopChecker(tmp_path).check(rep)["detected"]


def test_symlinked_entrypoint_is_not_read(tmp_path):
    outside = tmp_path / "external.py"
    outside.write_text("import tkinter\n")
    (tmp_path / "main.py").symlink_to(outside)
    assert not DesktopChecker(tmp_path).detect()["detected"]


def test_large_input_is_skipped(tmp_path):
    (tmp_path / "main.py").write_text("import tkinter\n" + "#" * 256_000)
    assert not DesktopChecker(tmp_path).detect()["detected"]


def test_tauri_metadata_and_linux_desktop_entry(tmp_path):
    (tmp_path / "src-tauri").mkdir()
    (tmp_path / "src-tauri/tauri.conf.json").write_text("{}")
    (tmp_path / "app.desktop").write_text("[Desktop Entry]\nExec=app\n")
    result = DesktopChecker(tmp_path).check(Report())
    assert result["frameworks"] == ["tauri"]
    assert "app.desktop" in result["packaging"]


def test_cli_json_exposes_desktop_and_categorized_findings(tmp_path):
    (tmp_path / "main.py").write_text("import tkinter\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ai-lint.py"),
            str(tmp_path),
            "--format",
            "json",
            "--no-cli",
            "--no-history",
            "--no-scaffold",
            "--no-update-check",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    data = json.loads(result.stdout)
    assert data["project_profiles"][0]["kind"] == "desktop-app"
    assert data["desktop_compatibility"][0]["detected"]
    findings = [f for f in data["findings"] if f["code"].startswith("DESKTOP_")]
    assert findings
    assert all(f["category"] == "desktop" for f in findings)
    assert all(f["fix_mode"] == "manual" for f in findings)


def test_tui_renders_os_readiness(tmp_path, capsys):
    from ai_lint import _engine

    (tmp_path / "main.py").write_text("import tkinter\n")
    rep = Report()
    rep.desktop_compatibility = [DesktopChecker(tmp_path).check(rep)]
    app = _engine._tui_app()
    app.repos = [tmp_path]
    app._overview(rep)
    text = capsys.readouterr().out
    assert "Desktop:" in text
    assert "linux:" in text and "windows:" in text and "macos:" in text
    assert "runtime compatibility unverified" in text
