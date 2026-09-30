"""Read-only project contract conversion plans; never write critical files."""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Callable

from ai_lint.agent_contract import AgentContract
from ai_lint.agents_adapter import AgentsAdapter
from ai_lint.claude_adapter import ClaudeAdapter
from ai_lint.codex_adapter import CodexAdapter

ADAPTERS = {a.name: a for a in (ClaudeAdapter(), CodexAdapter(), AgentsAdapter())}


class AgentConverter:
    def __init__(self, redact: Callable[[str], str]) -> None:
        self.redact = redact

    @staticmethod
    def _read(root: Path, path: Path, contract: AgentContract) -> str | None:
        rel = path.relative_to(root).as_posix()
        if any(part.is_symlink() for part in [path, *path.parents]):
            contract.warn("UNSAFE_SOURCE", rel, "Symlinked paths are not read.")
            return None
        if not path.exists():
            return None
        try:
            with path.open(encoding="utf-8", newline="") as stream:
                return stream.read()
        except (OSError, UnicodeError):
            contract.warn("UNREADABLE_SOURCE", rel, "Cannot read UTF-8 instruction content.")
            return None

    @staticmethod
    def _inspect(contract: AgentContract, rel: str, content: str) -> None:
        if re.search(r"(?m)^---\s*$", content):
            contract.warn(
                "UNMAPPED_METADATA", rel, "Frontmatter or separators need review; conditional scope is not mapped."
            )
        if re.search(r"(?:^|\s)@[^\s`]+", content):
            contract.warn("UNRESOLVED_IMPORT", rel, "Imports are preserved verbatim but not expanded or translated.")

    def _contract(self, root: Path, source: str) -> AgentContract:
        contract = AgentContract()
        if source == "claude":
            for rel in (".claude", ".claude/rules"):
                if (root / rel).is_symlink():
                    contract.warn("UNSAFE_SOURCE", rel, "Symlinked instruction directories are not scanned.")
        for path in ADAPTERS[source].sources(root):
            content = self._read(root, path, contract)
            if content is None:
                continue
            rel = path.relative_to(root).as_posix()
            contract.add(rel, content)
            self._inspect(contract, rel, content)
        if source == "claude":
            for name in ("settings.json", "settings.local.json"):
                path = root / ".claude" / name
                if path.exists() or path.is_symlink():
                    contract.warn(
                        "UNMAPPED_CONFIG",
                        path.relative_to(root).as_posix(),
                        "Permissions, hooks and settings are not translated; source configuration is retained.",
                    )
        if not contract.documents:
            contract.warn("NO_SOURCE", ".", "No readable source instruction documents found.")
        self._duplicates(contract)
        return contract

    @staticmethod
    def _duplicates(contract: AgentContract) -> None:
        seen: dict[str, str] = {}
        for doc in contract.documents:
            for line in doc["content"].splitlines():
                rule = line.strip()
                if len(rule) < 20 or rule.startswith(("#", "<!--")):
                    continue
                if rule in seen and seen[rule] != doc["path"]:
                    contract.warn(
                        "DUPLICATE_RULE",
                        doc["path"],
                        f"Repeated instruction also appears in {seen[rule]}; retained verbatim.",
                    )
                seen[rule] = doc["path"]

    def plan(self, root: Path, source: str, target: str) -> dict:
        root = root.absolute()
        contract = self._contract(root, source)
        output = contract.render()
        if target == "codex" and ((root / "AGENTS.override.md").exists() or (root / "AGENTS.override.md").is_symlink()):
            contract.warn(
                "TARGET_OVERRIDE",
                "AGENTS.override.md",
                "Codex override takes precedence over the proposed AGENTS.md; resolve manually.",
            )
        target_path = root / ADAPTERS[target].target
        existing = self._read(root, target_path, contract)
        if existing is not None and existing != output:
            contract.warn(
                "TARGET_CONFLICT",
                target_path.name,
                "Existing target differs; no automatic merge or replacement is proposed.",
            )
        return {
            "repository": str(root),
            "source": source,
            "target": target,
            "mapping": {
                "instruction_documents": ADAPTERS[target].target,
                "permissions_hooks_settings": "unmapped",
                "imports_conditional_scope": "manual_review",
            },
            "canonical": {
                "documents": [{"path": d["path"], "content": self.redact(d["content"])} for d in contract.documents]
            },
            "diagnostics": contract.diagnostics,
            "complete": not contract.diagnostics,
            "requires_human_validation": True,
            "applied": False,
            "output": {
                "path": target_path.name,
                "content": self.redact(output),
                "diff": self.redact(
                    "".join(
                        difflib.unified_diff(
                            (existing or "").splitlines(True),
                            output.splitlines(True),
                            fromfile=target_path.name,
                            tofile=target_path.name,
                        )
                    )
                ),
            },
            "scope": "Selected root project documents only; user, ancestor and nested directory contracts are not converted.",
        }

    def render_text(self, plans: list[dict]) -> str:
        lines = ["AGENT CONVERSION PREVIEW (read-only)"]
        for plan in plans:
            lines += [f"\n{plan['repository']}: {plan['source']} -> {plan['target']}", plan["scope"]]
            for d in plan["diagnostics"]:
                lines.append(f"  {d['code']} [{d['path']}]: {d['message']}")
            lines += ["Human validation required; no files were written.", plan["output"]["diff"]]
        return "\n".join(lines)
