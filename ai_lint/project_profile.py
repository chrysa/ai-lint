"""Project stack and profile detection."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ai_lint.desktop_checker import DesktopChecker


class ProjectProfiler:
    def __init__(self, repo: Path) -> None:
        self.repo = repo

    def detect_stack(self) -> dict[str, Any]:
        stack: dict[str, Any] = {"make": [], "scripts": {}, "pm": None}
        stack["python"] = self._exists("pyproject.toml", "requirements.txt", "setup.py", "uv.lock", "poetry.lock")
        stack["uv"] = self._exists("uv.lock")
        self._detect_node(stack)
        py_blob = " ".join(
            filter(None, (self._read_text(self.repo / f) for f in ("pyproject.toml", "requirements.txt")))
        ).lower()
        stack["sentry"] = stack.get("sentry") or "sentry-sdk" in py_blob or "sentry_sdk" in py_blob
        stack["supabase"] = stack.get("supabase") or "supabase" in py_blob or (self.repo / "supabase").is_dir()
        stack["unity"] = (self.repo / "ProjectSettings" / "ProjectVersion.txt").exists()
        stack["docker"] = self._exists(
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        )
        stack["compose"] = self._exists("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
        stack["k8s"] = self._exists("k8s", "kubernetes", "manifests", "kustomization.yaml", "deploy/k8s")
        stack["helm"] = self._exists("Chart.yaml", "charts", "helm")
        stack["terraform"] = any(self.repo.glob("*.tf")) or any(self.repo.glob("*/*.tf"))
        stack["tofu"] = stack["terraform"] and bool(shutil.which("tofu")) and not shutil.which("terraform")
        makefile = self._read_text(self.repo / "Makefile") or ""
        stack["make"] = sorted(set(re.findall(r"^([a-zA-Z][\w-]*):(?!=)", makefile, re.M)))
        remote = self._git("remote", "get-url", "origin") or ""
        stack["github"] = "github.com" in remote
        stack["gh"] = stack["github"] and bool(shutil.which("gh"))
        return stack

    def detect_profile(self, stack: dict[str, Any] | None = None) -> dict[str, Any]:
        stack = stack or self.detect_stack()
        pyproject = self._read_text(self.repo / "pyproject.toml") or ""
        make_targets = stack.get("make") or []
        signals = self._signals(stack, make_targets)

        standards = (self.repo / "standards" / "STANDARDS.chrysa.md").exists() or (
            self.repo / "standards" / "rules"
        ).is_dir()
        self._note(signals, standards, "shared-standards")
        workflows = (self.repo / ".github" / "workflows").is_dir()
        self._note(signals, workflows, "github-actions")
        agent_config = (
            (self.repo / ".claude").exists() or (self.repo / "CLAUDE.md").exists() or (self.repo / "AGENTS.md").exists()
        )
        self._note(signals, agent_config, "agent-config")

        kind, confidence = self._classify(stack, pyproject, standards)
        desktop = DesktopChecker(self.repo).detect()
        if desktop["detected"]:
            kind, confidence = "desktop-app", "medium"
            signals.extend("desktop:" + framework for framework in desktop["frameworks"])
        return {
            "path": str(self.repo),
            "kind": kind,
            "confidence": confidence,
            "signals": self._dedupe(signals),
            "desktop": desktop,
            "adaptation": {
                "generate_only_detected_artifacts": True,
                "prefer_info_when_intent_unclear": True,
                "never_loosen": True,
            },
        }

    def _detect_node(self, stack: dict[str, Any]) -> None:
        pkg = self._read_text(self.repo / "package.json")
        if not pkg:
            return
        try:
            package = json.loads(pkg)
        except json.JSONDecodeError:
            package = {}
        stack["scripts"] = package.get("scripts") or {}
        deps = {**(package.get("dependencies") or {}), **(package.get("devDependencies") or {})}
        stack["pm"] = self._package_manager()
        stack["web_ui"] = any(d in deps for d in ("react", "next", "vue", "svelte", "vite", "@angular/core"))
        stack["sentry"] = any(d.startswith("@sentry/") for d in deps)
        stack["supabase"] = "@supabase/supabase-js" in deps

    def _package_manager(self) -> str:
        if self._exists("pnpm-lock.yaml"):
            return "pnpm"
        if self._exists("yarn.lock"):
            return "yarn"
        if self._exists("bun.lockb", "bun.lock"):
            return "bun"
        return "npm"

    def _signals(self, stack: dict[str, Any], make_targets: list[str]) -> list[str]:
        signals: list[str] = []
        self._note(signals, bool(stack.get("python")), "python")
        self._note(signals, bool(stack.get("pm")), f"node:{stack.get('pm')}")
        self._note(signals, bool(stack.get("web_ui")), "web-ui")
        self._note(signals, bool(stack.get("docker")), "docker")
        self._note(signals, bool(stack.get("compose")), "compose")
        self._note(signals, bool(stack.get("k8s")), "kubernetes")
        self._note(signals, bool(stack.get("helm")), "helm")
        self._note(signals, bool(stack.get("terraform")), "terraform")
        self._note(signals, bool(stack.get("unity")), "unity")
        self._note(signals, bool(make_targets), "make:" + ",".join(make_targets[:5]))
        return signals

    def _classify(self, stack: dict[str, Any], pyproject: str, standards: bool) -> tuple[str, str]:
        has_cli_entry = "[project.scripts]" in pyproject or any(
            p.name.endswith(".py") and "-" in p.stem for p in self.repo.glob("*.py")
        )
        has_src_layout = (self.repo / "src").is_dir()
        has_app_dirs = any((self.repo / n).is_dir() for n in ("app", "apps", "backend", "frontend", "services"))
        has_package_dir = any(
            p.is_dir() and (p / "__init__.py").exists() for p in self.repo.iterdir() if not p.name.startswith(".")
        )
        has_python = bool(stack.get("python"))
        has_node = bool(stack.get("pm"))
        has_infra = bool(stack.get("terraform") or stack.get("k8s") or stack.get("helm"))
        config_files = any(
            (self.repo / n).exists() for n in (".claude", ".github", ".mcp.json", "repos.yml", "templates")
        )

        if standards:
            return "standards-repo", "high"
        if stack.get("unity"):
            return "game-or-unity", "high"
        if has_infra and not (has_python or has_node):
            return "infrastructure", "high"
        if has_python and stack.get("web_ui"):
            return "full-stack", "high"
        if has_node and stack.get("web_ui") and not has_python:
            return "frontend", "high"
        if has_python and has_cli_entry:
            return "python-cli", "high"
        if has_python and (has_src_layout or has_package_dir) and not has_app_dirs:
            return "python-library", "medium"
        if has_python:
            return "python-project", "medium"
        if config_files and not (has_python or has_node or has_infra):
            return "config-only", "medium"
        return "generic", "low"

    def _exists(self, *names: str) -> bool:
        return any((self.repo / n).exists() for n in names)

    def _git(self, *args: str) -> str | None:
        try:
            res = subprocess.run(
                ["git", "-C", str(self.repo), *args],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return res.stdout if res.returncode == 0 else None

    @staticmethod
    def _read_text(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    @staticmethod
    def _note(signals: list[str], enabled: bool, signal: str) -> None:
        if enabled:
            signals.append(signal)

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))
