"""Bounded, read-only desktop portability observations."""

from __future__ import annotations

import json
import re
from pathlib import Path

from prism_ai_lint.report import Report

OS_NAMES = ("linux", "macos", "windows")
PYTHON_FRAMEWORKS = ("pyside6", "pyside2", "pyqt6", "pyqt5", "tkinter", "wxpython", "kivy")
PATH_ASSUMPTIONS = {
    "linux": r"/home/|/usr/(?:bin|share)/|/etc/|\.config/",
    "macos": r"/Applications/|/Users/|Library/Application Support|\.app/Contents/",
    "windows": r"[A-Za-z]:\\|%APPDATA%|%LOCALAPPDATA%|%USERPROFILE%",
}


class DesktopChecker:
    """Report evidence rather than promising that an application runs on an OS."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo

    def _read(self, path: Path) -> str:
        if any(p.is_symlink() for p in [path, *path.parents]):
            return ""
        try:
            if path.stat().st_size > 256_000:
                return ""
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def _inputs(self) -> dict[str, str]:
        names = (
            "package.json",
            "pyproject.toml",
            "requirements.txt",
            "main.py",
            "app.py",
            "src/main.py",
            "src/app.py",
            "src-tauri/tauri.conf.json",
        )
        return {name: text for name in names if (text := self._read(self.repo / name))}

    @staticmethod
    def _package(text: str) -> dict:
        try:
            package = json.loads(text or "{}")
        except json.JSONDecodeError:
            return {}
        return package if isinstance(package, dict) else {}

    def detect(self) -> dict:
        inputs = self._inputs()
        frameworks: list[str] = []
        evidence: list[str] = []
        package = self._package(inputs.get("package.json", ""))
        deps: dict = {}
        for key in ("dependencies", "devDependencies"):
            if isinstance(package.get(key), dict):
                deps.update(package[key])
        for name in ("electron", "@tauri-apps/api", "@tauri-apps/cli"):
            if name in deps:
                frameworks.append("electron" if name == "electron" else "tauri")
                evidence.append(f"package.json dependency: {name}")
        if "src-tauri/tauri.conf.json" in inputs:
            frameworks.append("tauri")
            evidence.append("src-tauri/tauri.conf.json")
        for path, text in inputs.items():
            if not path.endswith((".py", ".toml", ".txt")):
                continue
            for framework in PYTHON_FRAMEWORKS:
                if re.search(r"\b" + framework + r"\b", text, re.I):
                    frameworks.append(framework)
                    evidence.append(f"{path}: {framework}")
        return {"detected": bool(frameworks), "frameworks": sorted(set(frameworks)), "evidence": sorted(set(evidence))}

    def check(self, rep: Report) -> dict:
        detected = self.detect()
        result = {
            "path": str(self.repo),
            **detected,
            "os": {},
            "runtime_verified": False,
            "scope": "Bounded project metadata and common Python entrypoints; no application commands executed.",
        }
        if not detected["detected"]:
            return result
        self._assumptions(rep)
        workflows = sorted((self.repo / ".github/workflows").glob("*"))[:20]
        ci_text = "\n".join(self._read(p) for p in workflows if p.suffix in (".yml", ".yaml"))
        package = self._package(self._read(self.repo / "package.json"))
        scripts = package.get("scripts") or {}
        if not isinstance(scripts, dict):
            scripts = {}
        commands = {str(k): str(v) for k, v in scripts.items() if re.search(r"test|build|pack|dist", str(k), re.I)}
        for os_name, runner in (("linux", "ubuntu-"), ("macos", "macos-"), ("windows", "windows-")):
            observed = runner in ci_text.lower()
            result["os"][os_name] = {
                "ci_runner_observed": observed,
                "commands": sorted(commands),
                "runtime_verified": False,
            }
            if not observed:
                rep.add(
                    "info",
                    "DESKTOP_CI_UNOBSERVED",
                    self.repo,
                    f"{os_name}: no literal hosted runner label observed; verify desktop build/test coverage (dynamic or external CI may exist)",
                )
        result["packaging"] = self._packaging()
        if not result["packaging"]:
            rep.add(
                "info",
                "DESKTOP_PACKAGING_UNOBSERVED",
                self.repo,
                "No bounded desktop packaging metadata observed; verify the intended distribution targets",
            )
        return result

    def _assumptions(self, rep: Report) -> None:
        for rel, text in self._inputs().items():
            for os_name, pattern in PATH_ASSUMPTIONS.items():
                if re.search(pattern, text):
                    rep.add(
                        "info",
                        "DESKTOP_PATH_ASSUMPTION",
                        self.repo / rel,
                        f"{os_name}: platform-specific path literal observed; check OS-specific configuration handling",
                    )
        package = self._package(self._read(self.repo / "package.json"))
        scripts = package.get("scripts") or {}
        if not isinstance(scripts, dict):
            scripts = {}
        for name, command in scripts.items():
            if not isinstance(command, str):
                continue
            if re.search(r"(?:^|[;&|]\s*|\s)(?:export\s|chmod\s|rm\s|cp\s|[A-Z_]+=[^\s]+|\./[^\s]+\.sh)", command):
                rep.add(
                    "info",
                    "DESKTOP_LAUNCH_ASSUMPTION",
                    self.repo / "package.json",
                    f"windows: script {name} contains POSIX shell syntax/tools; verify a portable launcher or explicit OS branch",
                )
            if re.search(r"(?:^|\s)(?:powershell|pwsh|cmd\.exe|\.\\[^\s]+\.bat)\b", command, re.I):
                rep.add(
                    "info",
                    "DESKTOP_LAUNCH_ASSUMPTION",
                    self.repo / "package.json",
                    f"linux/macos: script {name} uses a Windows/shell-specific launcher; verify platform availability",
                )

    def _packaging(self) -> list[str]:
        names = (
            "electron-builder.yml",
            "electron-builder.yaml",
            "electron-builder.json",
            "forge.config.js",
            "forge.config.ts",
            "src-tauri/tauri.conf.json",
        )
        found = [name for name in names if self._read(self.repo / name)]
        found += [p.name for p in sorted(self.repo.glob("*.spec"))[:20] if self._read(p)]
        found += [p.name for p in sorted(self.repo.glob("*.desktop"))[:20] if self._read(p)]
        package = self._package(self._read(self.repo / "package.json"))
        if isinstance(package.get("build"), dict):
            found.append("package.json:build")
        return found
