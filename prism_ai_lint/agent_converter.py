"""Read-only project contract conversion plans; never write critical files."""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable
from pathlib import Path

from prism_ai_lint.agent_contract import AgentContract
from prism_ai_lint.agents_adapter import AgentsAdapter
from prism_ai_lint.claude_adapter import ClaudeAdapter
from prism_ai_lint.codex_adapter import CodexAdapter

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

    def apply(
        self,
        root: Path,
        source: str,
        target: str,
        *,
        approved: bool,
        preview_existing: str | None,
        backup: Callable[[Path, str], None] | None = None,
    ) -> dict:
        """Write the converted target file — only with explicit human approval and
        when the preview is still fresh. The target (CLAUDE.md / AGENTS.md) is a
        critical content file, so application requires approval (issue #16); it is
        never written silently. Returns an outcome dict (never raises on refusal).

        preview_existing is the target content the reviewer saw; if the file has
        changed since (stale preview), the write is refused. backup, when given, is
        called with (path, old_content) before overwriting so the change is undoable.
        """
        root = root.absolute()
        target_path = root / ADAPTERS[target].target
        if not approved:
            return {"applied": False, "reason": "human validation required (critical content); not approved"}
        # Recompute fresh so we never write redacted content and catch late changes.
        contract = self._contract(root, source)
        if contract.diagnostics:
            return {"applied": False, "reason": "unresolved diagnostics; resolve them before applying"}
        output = contract.render()
        current = self._read(root, target_path, AgentContract())
        if current == output:
            return {"applied": False, "reason": "target already matches the conversion; nothing to write"}
        if (current or "") != (preview_existing or ""):
            return {"applied": False, "reason": "stale preview: the target changed since it was shown; re-run"}
        try:
            if current is not None and backup is not None:
                backup(target_path, current)
            target_path.write_text(output, encoding="utf-8")
        except OSError as error:
            return {"applied": False, "reason": f"write failed: {error}"}
        return {"applied": True, "path": target_path.name, "created": current is None}

    def render_text(self, plans: list[dict]) -> str:
        lines = ["AGENT CONVERSION PREVIEW (read-only)"]
        for plan in plans:
            lines += [f"\n{plan['repository']}: {plan['source']} -> {plan['target']}", plan["scope"]]
            for d in plan["diagnostics"]:
                lines.append(f"  {d['code']} [{d['path']}]: {d['message']}")
            lines += ["Human validation required; no files were written.", plan["output"]["diff"]]
        return "\n".join(lines)
