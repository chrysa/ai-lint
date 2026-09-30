Warning: truncated output (original token count: 93244)
Total output lines: 9215

#!/usr/bin/env python3
"""ai-lint: validate, repair and optimize coding-agent configurations.

Single file, no third-party dependencies. Python >= 3.9 (>= 3.11 for policy files).

Rules follow the official Claude Code documentation (settings, permissions,
hooks, memory, skills, tools reference) as of 2026-09, plus known upstream
issues. The settings schema moves fast: unknown keys are reported as info,
never as errors, and every finding carries a reference link at -v.

Scopes checked:
  user     $CLAUDE_CONFIG_DIR or ~/.claude: settings, CLAUDE.md, rules, skills,
           agents, commands, auto-memory indexes; ~/.claude.json MCP servers (read-only)
  project  .claude/settings*.json, .mcp.json, CLAUDE.md / AGENTS.md / CLAUDE.local.md,
           .claude/rules, skills, agents, commands, git hooks, git history

Usage:
  ai-lint.py [PATH ...] [--user|--user-only] [--fix] [--no-scaffold]
                       [--format text|json] [--policy FILE] [--strict]
                       [--no-history] [--no-cli] [-v|-vv|-vvv|-q]
  ai-lint.py --print-policy

PATH may be a repository or a folder of repositories (searched 3 levels deep).
Default mode is read-only: findings + the unified diff --fix would apply.
--fix applies safe repairs in passes until stable, re-lints, and reports what was
fixed versus what needs manual action. Originals go to ~/.cache/ai-lint/.

Verbosity (stderr; --format json stays clean on stdout):
  -q  errors + summary   -v  progress, why/how hints, doc references
  -vv every transformation   -vvv debug (files scanned, git calls, resolved policy)

Guarded audit session (for an AI agent doing the judgment calls):
  ai-lint.py --session-settings FILE   write a --settings file that installs --guard
  claude --settings FILE                         agent edits are now checked by --guard:
      no widening of allow rules, no removal of deny/ask rules or hooks, no bypass modes,
      no new MCP servers/env/helpers, no attribution, protected files untouchable,
      .ai-lint.toml editable only in [reference]. Fails closed.
  ai-lint.py --dump-reference          built-in reference data, to diff against docs

Exit codes: 0 clean, 1 errors (or warnings with --strict), 2 usage error / guard block.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import difflib
import itertools
import json
import os
import re
import shlex

try:
    import yaml  # optional: only needed for --print-catalog / --catalog
except ModuleNotFoundError:
    yaml = None
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11: policy files unsupported, defaults apply
    tomllib = None


def _detect_version() -> str:
    """The version is computed, never typed (shared-standards CI-045): prefer the
    installed package metadata, else the git tag, else a dev placeholder."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("ai-lint")
        except PackageNotFoundError:
            pass
    except ImportError:
        pass
    try:
        import subprocess

        out = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parent), "describe", "--tags", "--always", "--dirty"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        tag = (out.stdout or "").strip().lstrip("v")
        if tag:
            return tag
    except (OSError, ValueError):
        pass
    return "0.0.0-dev"


VERSION = _detect_version()
DOCS = "https://code.claude.com/docs/en/"
ISSUES = "https://github.com/anthropics/claude-code/issues/"

# --------------------------------------------------------------------------- #
# Policy
# --------------------------------------------------------------------------- #

DEFAULT_POLICY: dict[str, Any] = {
    "instructions": {
        "user_max_lines": 150,  # user scope loads in every session of every project
        "project_warn_lines": 200,  # documented target: under 200 lines per file
        "warn_tokens": 5000,
        "max_import_depth": 4,  # documented maximum: four hops
        "doctrine_dir": "doctrine/rules",
        "generated_marker": "GENERATED",
        # Instruction files that mirror AGENTS.md for other agent tools. Index 0
        # (CLAUDE.md) and 1 (AGENTS.md) are the Claude Code / neutral pair; the
        # rest are extra renders, linted as always-loaded instructions and, when a
        # doctrine source exists, expected to be regenerated (RENDER_HAND_EDITED).
        # Covers GitHub Copilot, Cursor (legacy), Windsurf, and Gemini CLI. Codex /
        # ChatGPT read AGENTS.md directly, so they need no separate file.
        "rendered_files": [
            "CLAUDE.md",
            "AGENTS.md",
            ".github/copilot-instructions.md",
            ".cursorrules",
            ".windsurfrules",
            "GEMINI.md",
        ],
        "claude_md_import": True,  # keep CLAUDE.md = "@AGENTS.md" for CLIs < 2.1.277 / Bedrock
        "min_duplicate_line_len": 30,
        # Style levers for always-loaded instructions: an agent parses terse,
        # imperative, list-shaped text faster and cheaper than prose. All info-level.
        "style_checks": True,  # master switch for the style suggestions below
        "prose_block_lines": 4,  # a run of >= N non-list prose lines is flagged (bullet it)
        "prose_line_min_chars": 60,  # only count lines this long as prose (skip short ones)
        "filler_phrases": [  # polite / filler wording to drop for the imperative
            "please",
            "you should",
            "you must",
            "make sure to",
            "be sure to",
            "note that",
            "keep in mind",
            "in order to",
            "it is important to",
            "as a reminder",
            "feel free to",
        ],
    },
    "permissions": {
        "require_rtk": True,  # route Bash allow rules through rtk
        "rtk_twin_deny": True,  # mirror deny/ask rules with and without rtk (issue #79400)
        "rtk_exempt": ["rtk"],
        "rule_style": "keep",  # keep | space | colon  (trailing wildcard form)
        "external_action_prefixes": [  # must be "ask", never "allow"
            "git push",
            "gh pr create",
            "gh pr merge",
            "gh release",
            "gh repo",
            "kubectl apply",
            "kubectl delete",
            "kubectl patch",
            "helm install",
            "helm upgrade",
            "helm uninstall",
            "argocd",
            "terraform apply",
            "terraform destroy",
            "tofu apply",
            "tofu destroy",
            "bao write",
            "vault write",
            "docker push",
            "npm publish",
            "twine upload",
            "rm -rf",
        ],
        "forbidden_allow": [
            "Bash",
            "Bash(*)",
            "Bash(sudo:*)",
            "Bash(sudo *)",
            "Bash(rtk *)",
            "Bash(rtk:*)",
            "PowerShell",
            "PowerShell(*)",
        ],
        "exec_runners": [  # a wildcard right after these allows anything
            "npx",
            "bunx",
            "pnpm dlx",
            "yarn dlx",
            "uvx",
            "uv run",
            "poetry run",
            "pipenv run",
            "docker exec",
            "docker run",
            "docker compose exec",
            "docker compose run",
            "kubectl exec",
            "devbox run",
            "direnv exec",
            "mise exec",
            "nix run",
            "nix-shell",
            "sh -c",
            "bash -c",
            "zsh -c",
            "env",
            "eval",
            "exec",
            "xargs",
            "python -c",
            "python3 -c",
            "node -e",
            "sudo",
            "watch",
            "timeout",
            "rtk",
        ],
        "required_deny": [
            "Read(**/.env)",
            "Read(**/.env.*)",
            "Read(**/secrets/**)",
            "Read(**/*.pem)",
            "Read(**/*.key)",
            "Read(~/.ssh/**)",
            "Read(~/.aws/**)",
            "Read(~/.kube/**)",
            "Read(~/.vault-token)",
            "Read(!.env.example)",
        ],
    },
    "user_scope": {"context_only": True},
    "attribution": {
        "scan_history_commits": 200,
        "install_commit_msg_hook": True,
        "scan_extensions": [
            ".md",
            ".txt",
            ".rst",
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".yml",
            ".yaml",
            ".toml",
            ".json",
            ".cs",
            ".sh",
        ],
        "max_file_bytes": 1_000_000,
    },
    "scaffold": {
        "project_settings": True,
        "instructions": True,
        "user_settings": True,
        "schema_url": "https://json.schemastore.org/claude-code-settings.json",
    },
    "security": {
        # Propose (and, under --generate / -i, write) the files that harden a
        # config: a PreCompact hook referenced but missing, and a .gitignore
        # block keeping secrets out of git. Set false to skip that class.
        "scaffold_missing_hooks": True,
        "scaffold_gitignore": True,
    },
    "skills": {
        "portable": True,  # stay within the Agent Skills spec (agentskills.io)
        "max_listing_chars": 1536,  # description + when_to_use truncation in the listing
        "portable_description_chars": 1024,
        "max_lines": 500,
        "name_pattern": r"^[a-z0-9][a-z0-9-]{0,63}$",
        "gate_side_effects": True,  # add disable-model-invocation to deploy/release/... skills
        "side_effect_words": [
            "deploy",
            "release",
            "publish",
            "push",
            "send",
            "delete",
            "drop",
            "destroy",
            "migrate",
            "rollback",
            "merge",
        ],
    },
    "mcp": {"max_servers": 6},
    # Reference data extensions: the ONLY table an audit agent may edit (the guard enforces it).
    # Lets the linter follow new docs (keys, events, tools, fields) without code changes.
    "reference": {
        "extra_settings_keys": [],
        "extra_hook_events": [],
        "extra_tools": [],
        "extra_skill_fields": [],
        "extra_agent_fields": [],
        "docs_checked": "",
    },
    "memory": {"max_lines": 200, "max_bytes": 25_000},
}

# --------------------------------------------------------------------------- #
# Reference data (docs snapshot 2026-09)
# --------------------------------------------------------------------------- #

KNOWN_SETTINGS_KEYS = {
    "$schema",
    "additionalDirectories",
    "agent",
    "allowManagedHooksOnly",
    "allowManagedPermissionRulesOnly",
    "allowedHttpHookUrls",
    "alwaysThinkingEnabled",
    "apiKeyHelper",
    "askUserQuestionTimeout",
    "attribution",
    "autoMemoryDirectory",
    "autoMemoryEnabled",
    "autoMode",
    "autoUpdates",
    "autoUpdatesChannel",
    "availableModels",
    "awsAuthRefresh",
    "awsCredentialExport",
    "bashOutputMaxChars",
    "claudeMd",
    "claudeMdExcludes",
    "cleanupPeriodDays",
    "companyAnnouncements",
    "crossSessionInbound",
    "defaultShell",
    "deniedMcpServers",
    "allowedMcpServers",
    "disableAllHooks",
    "disableArtifact",
    "disableBundledSkills",
    "disableClaudeAiConnectors",
    "disableCommandPluginSources",
    "disableSkillShellExecution",
    "disabledMcpjsonServers",
    "effortLevel",
    "enableAllProjectMcpServers",
    "enableArtifact",
    "enabledMcpjsonServers",
    "enabledPlugins",
    "env",
    "extraKnownMarketplaces",
    "fallbackModel",
    "feedbackDrafts",
    "fileSuggestion",
    "forceLoginMethod",
    "forceLoginOrgUUID",
    "hooks",
    "httpHookAllowedEnvVars",
    "includeCoAuthoredBy",
    "includeGitInstructions",
    "isolatePeerMachines",
    "language",
    "maxEffortLevel",
    "model",
    "modelOverrides",
    "modelPicker",
    "modelSettings",
    "otelHeadersHelper",
    "outputStyle",
    "permissions",
    "pluginConfigs",
    "processWrapper",
    "remoteControlAtStartup",
    "requiredMinimumVersion",
    "respectGitignore",
    "sandbox",
    "skillListingBudgetFraction",
    "skillListingMaxDescChars",
    "skillOverrides",
    "spinnerTipsEnabled",
    "statusLine",
    "strictPluginOnlyCustomization",
    "subagentStatusLine",
    "syncClaudeAiPlugins",
    "syncClaudeAiSkills",
    "theme",
    "useAutoModeDuringPlan",
    "autoContinueAtUsageLimit",
    "agentPushNotifEnabled",
    "inputNeededNotifEnabled",
    "tui",
    "skipWorkflowUsageWarning",
    "workflowSizeGuideline",
    "modelPricing",
    "disableBypassPermissionsMode",
    "disableWorkflows",
    "ultracode",
    "subagentPromptCacheTtl",
    "strictKnownMarketplaces",
    "blockedMarketplaces",
}
# Keys a repository file cannot set (dead config in .claude/settings*.json).
PROJECT_DEAD_KEYS = {
    "autoMode": "not read from shared project settings",
    "modelPicker": "ignored in project and local settings",
    "claudeMd": "honored only in managed settings",
    "allowManagedPermissionRulesOnly": "managed settings only",
    "allowManagedHooksOnly": "managed settings only",
    "forceLoginMethod": "managed settings only",
    "forceLoginOrgUUID": "managed settings only",
}
KNOWN_TOOLS = {
    "Agent",
    "Artifact",
    "AskUserQuestion",
    "Bash",
    "CronCreate",
    "CronDelete",
    "CronList",
    "Edit",
    "EndConversation",
    "EnterPlanMode",
    "EnterWorktree",
    "ExitPlanMode",
    "ExitWorktree",
    "Glob",
    "Grep",
    "ListAgents",
    "ListMcpResourcesTool",
    "LSP",
    "Monitor",
    "NotebookEdit",
    "PowerShell",
    "PushNotification",
    "Read",
    "ReadMcpResourceTool",
    "RemoteTrigger",
    "ReportFindings",
    "ScheduleWakeup",
    "SendFeedback",
    "SendMessage",
    "SendUserFile",
    "ShareOnboardingGuide",
    "Skill",
    "SubagentHandback",
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskOutput",
    "TaskStop",
    "TaskUpdate",
    "TodoWrite",
    "ToolSearch",
    "WaitForMcpServers",
    "WebFetch",
    "WebSearch",
    "Workflow",
    "Write",
}
RULE_ONLY_TOOLS = {"Cd"}
LEGACY_TOOLS = {
    "Task": "Agent",
    "MultiEdit": "Edit",
    "KillShell": "TaskStop",
    "BashOutput": "TaskOutput",
    "NotebookRead": "Read",
    "LS": "Read",
}
SPECIFIER_TOOLS = {
    "Bash",
    "Monitor",
    "PowerShell",
    "Read",
    "Grep",
    "Glob",
    "LSP",
    "Edit",
    "Write",
    "NotebookEdit",
    "Skill",
    "Agent",
    "WebFetch",
    "Cd",
}
# Path rules are only consulted for Read and Edit (docs: permissions#read-and-edit).
PATH_TOOL_REMAP = {
    "Write": "Edit",
    "NotebookEdit": "Edit",
    "MultiEdit": "Edit",
    "Glob": "Read",
    "Grep": "Read",
    "LSP": "Read",
}
PRIMARY_PARAMS = {"command", "file_path", "path", "notebook_path", "url"}
READONLY_BUILTINS = {
    "ls",
    "cat",
    "echo",
    "pwd",
    "head",
    "tail",
    "grep",
    "find",
    "wc",
    "which",
    "diff",
    "stat",
    "du",
    "cd",
}
ABS_ROOTS = {
    "home",
    "Users",
    "etc",
    "tmp",
    "var",
    "opt",
    "mnt",
    "srv",
    "root",
    "usr",
    "private",
    "Volumes",
    "media",
    "run",
    "data",
}

KNOWN_HOOK_EVENTS = {
    "SessionStart",
    "Setup",
    "UserPromptSubmit",
    "UserPromptExpansion",
    "PreToolUse",
    "PermissionRequest",
    "PermissionDenied",
    "PostToolUse",
    "PostToolUseFailure",
    "PostToolBatch",
    "Notification",
    "MessageDisplay",
    "SubagentStart",
    "SubagentStop",
    "TaskCreated",
    "TaskCompleted",
    "Stop",
    "StopFailure",
    "TeammateIdle",
    "InstructionsLoaded",
    "ConfigChange",
    "CwdChanged",
    "DirectoryAdded",
    "FileChanged",
    "WorktreeCreate",
    "WorktreeRemove",
    "PreCompact",
    "PostCompact",
    "PreModelSwitch",
    "PostModelSwitch",
    "Elicitation",
    "ElicitationResult",
    "SessionEnd",
}
TOOL_EVENTS = {
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PermissionRequest",
    "PermissionDenied",
}
NO_MATCHER_EVENTS = {
    "UserPromptSubmit",
    "PostToolBatch",
    "Stop",
    "TeammateIdle",
    "TaskCreated",
    "TaskCompleted",
    "WorktreeCreate",
    "WorktreeRemove",
    "MessageDisplay",
    "CwdChanged",
}
HOOK_TYPES = {
    "command": ("command",),
    "http": ("url",),
    "mcp_tool": ("server", "tool"),
    "prompt": ("prompt",),
    "agent": ("prompt",),
}
SHELL_META = re.compile(r"[|&;<>`()]|\$\((?!\s)|\s&&\s|\|\|")

SKILL_FIELDS = {
    "name",
    "description",
    "when_to_use",
    "argument-hint",
    "arguments",
    "disable-model-invocation",
    "user-invocable",
    "allowed-tools",
    "disallowed-tools",
    "model",
    "effort",
    "context",
    "agent",
    "background",
    "hooks",
    "paths",
    "shell",
    "metadata",
    "license",
    "compatibility",
}
SKILL_SPEC_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
SKILL_TYPOS = {
    "allowed_tools": "allowed-tools",
    "allowedTools": "allowed-tools",
    "disallowed_tools": "disallowed-tools",
    "disallowedTools": "disallowed-tools",
    "disable_model_invocation": "disable-model-invocation",
    "disableModelInvocation": "disable-model-invocation",
    "user_invocable": "user-invocable",
    "userInvocable": "user-invocable",
    "when-to-use": "when_to_use",
    "whenToUse": "when_to_use",
    "argument_hint": "argument-hint",
    "argumentHint": "argument-hint",
}
AGENT_FIELDS = {
    "name",
    "description",
    "tools",
    "disallowedTools",
    "model",
    "permissionMode",
    "maxTurns",
    "skills",
    "mcpServers",
    "hooks",
    "memory",
    "background",
    "effort",
    "isolation",
    "color",
    "initialPrompt",
}
AGENT_TYPOS = {
    "allowed-tools": "tools",
    "allowed_tools": "tools",
    "allowedTools": "tools",
    "disallowed-tools": "disallowedTools",
    "disallowed_tools": "disallowedTools",
    "permission-mode": "permissionMode",
    "permission_mode": "permissionMode",
    "max-turns": "maxTurns",
    "max_turns": "maxTurns",
}
RULE_TYPOS = {
    "globs": "paths",
    "glob": "paths",
    "applyTo": "paths",
    "files": "paths",
    "include": "paths",
    "path": "paths",
}

ATTRIBUTION_PATTERNS = [  # written so this source file never matches itself
    re.compile(r"Co-Authored-By:\s*Claude", re.I),
    re.compile(r"Generated with \[?Claude Code", re.I),
    re.compile(r"noreply@anthropic\.com", re.I),
]
# A line that forbids attribution ("NEVER add Co-Authored-By...", "strip the
# Generated-with line") is documentation, not a trace: don't flag it.
ATTR_NEGATION = re.compile(
    r"\b(never|do ?n['o]t|no|without|strip|remove|forbid|avoid|jamais|sans|ne "
    r"pas|retire|supprime|interdit)\b",
    re.I,
)


def _is_attribution(line: str) -> bool:
    for p in ATTRIBUTION_PATTERNS:
        m = p.search(line)
        if not m:
            continue
        if ATTR_NEGATION.search(line):
            return False
        # A match inside an inline-code span (`...Co-Authored-By...`) is quoting the
        # trailer as an example in prose/plans, not committing it. A real trailer
        # sits on its own line, unquoted.
        before, after = line[: m.start()], line[m.end() :]
        if before.count("`") % 2 == 1 and "`" in after:
            return False
        return True
    return False


SECRET_VALUE_PATTERNS = [
    re.compile(r"^gh[pousr]_[A-Za-z0-9]{20,}$"),
    re.compile(r"^github_pat_[A-Za-z0-9_]{20,}$"),
    re.compile(r"^sk-[A-Za-z0-9_-]{20,}$"),
    re.compile(r"^xox[abpr]-[A-Za-z0-9-]{10,}$"),
    re.compile(r"^AKIA[0-9A-Z]{16}$"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"^(ntn|secret|hvs|s)\.?_?[A-Za-z0-9]{20,}$"),
    re.compile(r"^glpat-[\w-]{20,}$"),
]
SECRET_REDACT_RE = re.compile(
    r"(gh[pousr]_|github_pat_|sk-|xox[abpr]-|AKIA|ntn_|secret_|hvs\.|glpat-)[A-Za-z0-9_-]{8,}"
)
SECRET_KEY_RE = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|PRIVATE_KEY|AUTHORIZATION)", re.I)

COMMIT_MSG_HOOK = """#!/usr/bin/env sh
# Strip AI-assistant attribution trailers from commit messages.
# Installed by ai-lint. Deterministic and agent-agnostic.
sed -i -E \\
  -e '/^Co-Authored-By:.*(claude|anthropic)/Id' \\
  -e '/Generated with \\[?Claude Code/Id' \\
  "$1"
sed -i -e :a -e '/^\\n*$/{$d;N;ba' -e '}' "$1"
"""
HOOK_SIGNATURE = "ai-lint"

# Portable, tool-agnostic PreCompact hook. No project-specific coupling: it writes
# a small session snapshot (git state + working dir) so context survives a compact.
# Referenced by settings that declare a PreCompact hook but ship no script.
PRE_COMPACT_HOOK = """#!/usr/bin/env bash
# PreCompact hook — snapshot session state before context compaction.
# Portable scaffold written by ai-lint. Safe to edit or extend.
set -uo pipefail
SNAP_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/pre-compact-snapshots"
mkdir -p "$SNAP_DIR"
SNAP="$SNAP_DIR/snapshot-$(date +%Y%m%d-%H%M%S).md"
{
  echo "# Pre-compact snapshot · $(date -Iseconds)"
  echo "working_dir: $(pwd)"
  if git rev-parse --git-dir >/dev/null 2>&1; then
    echo "branch: $(git branch --show-current 2>/dev/null || echo DETACHED)"
    echo "## Uncommitted changes (preserve)"
    git status --porcelain 2>/dev/null | head -50
    echo "## Recent commits"
    git log --oneline -5 2>/dev/null
  fi
} > "$SNAP" 2>/dev/null || true
exit 0
"""

# Lines a repo should git-ignore so secrets never get committed. Appended (never
# overwritten) to .gitignore under a labelled block when any are missing.
SECRETS_GITIGNORE = [
    ".env",
    ".env.*",
    "!.env.example",
    "*.pem",
    "*.key",
    "secrets/",
    ".claude/settings.local.json",
]
SECRETS_GITIGNORE_HEADER = "# ai-lint: keep secrets and local config out of git"

AGENTS_SKELETON = """# {name}

<!-- Neutral agent instructions. Tool-specific files (e.g. CLAUDE.md) only import this one.
     HTML comments are stripped before loading: they cost no context. -->

## Overview

<!-- One paragraph: what this project is, who uses it, current maturity. -->

## Commands

{commands}

## Conventions

- Everything written to disk is in English (identifiers, commits, docs).
- Configuration comes from environment variables; no committed secrets.
<!-- Only what differs from tool defaults; skip what the code already shows. -->

## Boundaries

- Ask before any action with external effects (push, release, deploy, DNS, secrets, messages).
- Never add assistant attribution to commits, PRs, files or docs.
"""

# --------------------------------------------------------------------------- #
# Hints and references
# --------------------------------------------------------------------------- #

HINTS: dict[str, tuple[str, str]] = {  # code -> (why/how, reference)
    "JSON_INVALID": (
        "The file is rejected as a whole: none of its settings apply.",
        DOCS + "settings#fix-a-broken-settings-file",
    ),
    "JSON_REPAIRED": (
        "Settings files are strict JSON: comments or trailing commas make Claude Code reject the file.",
        DOCS + "settings#edit-a-settings-file",
    ),
    "SETTINGS_SCHEMA": (
        "$schema gives editor autocomplete and inline validation.",
        DOCS + "settings#edit-a-settings-file",
    ),
    "SETTINGS_UNKNOWN_KEY": (
        "Typo, or a key newer than this script: check the settings reference.",
        DOCS + "settings-reference",
    ),
    "SETTINGS_DEAD_KEY": (
        "A repository file cannot set this key; it has no effect there.",
        DOCS + "settings#a-committed-key-doesnt-reach-teammates",
    ),
    "SETTINGS_DISABLE_HOOKS": (
        "disableAllHooks in project settings overrides your user value and silences every guard hook.",
        DOCS + "hooks#disable-or-remove-hooks",
    ),
    "SETTINGS_MCP_AUTO": (
        "Auto-approves any MCP server a repository adds to .mcp.json.",
        DOCS + "permissions#what-runs-before-you-trust-a-folder",
    ),
    "SETTINGS_BUG_55507": (
        "Known issue: a project permissions block can drop a user-level defaultMode.",
        ISSUES + "55507",
    ),
    "ATTR_DEPRECATED": ("Replaced by the 'attribution' key.", DOCS + "settings-reference"),
    "ATTR_ENABLED": (
        "Empty strings for commit and pr stop the CLI from adding its byline.",
        DOCS + "settings-reference",
    ),
    "ATTR_TRACE": ("Generated files and docs must carry no assistant signature.", ""),
    "ATTR_HISTORY": (
        "Published commits: rewriting history is an explicit decision (force-push).",
        "",
    ),
    "ATTR_HOOK_MISSING": (
        "The model can write the trailer itself in 'git commit -m'; a commit-msg hook removes it deterministically.",
        "",
    ),
    "ATTR_HOOK_CONFLICT": (
        "Merge the two sed lines of the attribution guard into your existing commit-msg hook.",
        "",
    ),
    "PERM_SYNTAX": (
        "Rules are Tool or Tool(specifier); a malformed rule is skipped with a startup warning.",
        DOCS + "permissions#permission-rule-syntax",
    ),
    "PERM_LEGACY_TOOL": (
        "Renamed or removed tool: rules and matchers use canonical names only.",
        DOCS + "tools-reference",
    ),
    "PERM_PATH_TOOL": (
        "Path rules on Write, NotebookEdit, Glob, Grep or MultiEdit are accepted but never "
        "consulted: use Edit(...) or Read(...).",
        DOCS + "permissions#read-and-edit",
    ),
    "PERM_PRIMARY_PARAM": (
        "Parameter rules on a primary field (command, file_path, path, url) are ignored: "
        "bypassable by compound commands.",
        DOCS + "permissions#match-by-input-parameter",
    ),
    "PERM_MCP_PARENS": (
        "mcp__ rules with parentheses are skipped when a settings file loads; use "
        "--disallowedTools for parameter rules.",
        DOCS + "permissions#match-by-input-parameter",
    ),
    "PERM_COLON_MID": (
        "':*' is only a wildcard at the end; elsewhere the colon is literal and the rule never matches.",
        DOCS + "permissions#wildcard-patterns",
    ),
    "PERM_ABS_PATH": (
        "A single leading slash anchors at the settings source, not the filesystem root; use // for absolute paths.",
        DOCS + "permissions#read-and-edit",
    ),
    "PERM_USER_ANCHOR": (
        "In user settings, /path resolves under ~/.claude, not the project.",
        DOCS + "permissions#read-and-edit",
    ),
    "PERM_WEBFETCH": (
        "WebFetch rules match hostnames through the domain: prefix.",
        DOCS + "permissions#webfetch",
    ),
    "PERM_NO_SPECIFIER": (
        "This tool accepts only the bare name.",
        DOCS + "tools-reference#configure-tools-with-permission-rules-and-hooks",
    ),
    "PERM_UNKNOWN_TOOL": (
        "The rule matches nothing; check the canonical tool name.",
        DOCS + "tools-reference",
    ),
    "PERM_DUPLICATE": ("Harmless but noisy; removed.", ""),
    "PERM_TOO_BROAD": (
        "Unrestricted shell (or rtk, which runs its argument) removes every guard.",
        DOCS + "permissions#bash",
    ),
    "PERM_UNANCHORED_GLOB": (
        "Allow rules accept tool-name globs only after mcp__<server>__; this one is skipped.",
        DOCS + "permissions#tool-name-wildcards",
    ),
    "PERM_WILDCARD_EARLY": (
        "A * before the subcommand allows every subcommand, including options like git -c.",
        DOCS + "permissions#wildcard-patterns",
    ),
    "PERM_EXEC_RUNNER": (
        "Environment runners execute their arguments: the rule allows any command after them.",
        DOCS + "permissions#process-wrappers",
    ),
    "PERM_EXTERNAL_ACTION": (
        "Effects outside the sandbox need human approval: 'ask', not 'allow'.",
        "",
    ),
    "PERM_DEAD_ALLOW": (
        "Deny is evaluated first; an allow can never carve an exception out of it.",
        DOCS + "permissions#manage-permissions",
    ),
    "PERM_ASK_SHADOW": (
        "A matching ask rule prompts even when a narrower allow matches.",
        DOCS + "permissions#manage-permissions",
    ),
    "PERM_READONLY": (
        "Built-in read-only commands already run without a prompt.",
        DOCS + "permissions#read-only-commands",
    ),
    "PERM_RTK": ("Routing through rtk compresses command output and saves context tokens.", ""),
    "PERM_RTK_TWIN": (
        "Known issue: deny rules do not reliably block rtk-prefixed commands; mirror both forms.",
        ISSUES + "79400",
    ),
    "PERM_STYLE": (
        "':*' and ' *' are equivalent at the end; the permission dialog writes the space form.",
        DOCS + "permissions#wildcard-patterns",
    ),
    "PERM_SHADOWED": ("A broader rule already covers this one.", ""),
    "PERM_MISSING_DENY": (
        "Blocks secret files for the file tools and recognised Bash readers (cat, head, "
        "...). Not an OS boundary: use the sandbox for that.",
        DOCS + "settings-reference#exclude-sensitive-files",
    ),
    "PERM_BYPASS": (
        "Every tool call runs without confirmation, including writes to .git and .claude.",
        DOCS + "permissions#permission-modes",
    ),
    "PERM_MODE_DEAD": (
        "auto and bypassPermissions don't take effect from project or local settings.",
        DOCS + "settings#a-value-you-set-is-ignored",
    ),
    "PERM_NET_DENY": (
        "Bash deny rules miss /usr/bin/curl or sh -c 'curl'; the sandbox network allowlist is the real boundary.",
        DOCS + "permissions#bash-rule-limits",
    ),
    "SECRET_INLINE": (
        "Committed or plaintext config is readable by anyone with access; reference ${VAR} or the vault.",
        "",
    ),
    "HOOK_SHAPE": (
        "Expected {Event: [{matcher?, hooks: [{type, ...}]}]}.",
        DOCS + "hooks#configuration",
    ),
    "HOOK_EVENT": (
        "Unknown events never fire and are skipped with a warning.",
        DOCS + "hooks#hook-lifecycle",
    ),
    "HOOK_LEGACY_FORMAT": (
        "Old or flattened shape; converted to matcher groups.",
        DOCS + "hooks#configuration",
    ),
    "HOOK_NO_TYPE": ("Each handler needs a type; set to command.", DOCS + "hooks#common-fields"),
    "HOOK_TYPE": (
        "Handler types: command, http, mcp_tool, prompt, agent.",
        DOCS + "hooks#hook-handler-fields",
    ),
    "HOOK_IF_DEAD": (
        "'if' is only evaluated on tool events; elsewhere the handler never runs.",
        DOCS + "hooks#common-fields",
    ),
    "HOOK_MATCHER_IGNORED": (
        "This event has no matcher support; the field is silently ignored.",
        DOCS + "hooks#matcher-patterns",
    ),
    "HOOK_MATCHER_MCP": (
        "mcp__server is compared as an exact tool name and matches nothing; append __.*",
        DOCS + "hooks#match-mcp-tools",
    ),
    "HOOK_MATCHER_TOOL": (
        "Matchers use canonical tool names; this one never fires.",
        DOCS + "hooks#matcher-patterns",
    ),
    "HOOK_MATCHER_REGEX": (
        "Regex matchers are unanchored: Edit.* also matches NotebookEdit. Anchor with ^...$.",
        DOCS + "hooks#matcher-patterns",
    ),
    "HOOK_ONCE": ("'once' is only honored in skill frontmatter.", DOCS + "hooks#common-fields"),
    "HOOK_MISSING_SCRIPT": (
        "A missing script exits 127: non-blocking, so the guard is silently disabled.",
        DOCS + "hooks#other-exit-codes",
    ),
    "HOOK_NOT_EXECUTABLE": (
        "chmod +x the script, or the hook fails as non-blocking.",
        DOCS + "hooks#other-exit-codes",
    ),
    "HOOK_RELATIVE_PATH": (
        "Hooks run in the current directory, which moves with cd; anchor on ${CLAUDE_PROJECT_DIR} in exec form.",
        DOCS + "hooks#reference-scripts-by-path",
    ),
    "HOOK_EXEC_FORM": (
        "Exec form (command + args) passes paths without shell quoting issues.",
        DOCS + "hooks#exec-form-and-shell-form",
    ),
    "HOOK_EXIT1": (
        "Only exit 2 (or a JSON decision) blocks; exit 1 is a non-blocking error and the action proceeds.",
        DOCS + "hooks#exit-code-2",
    ),
    "HOOK_ASYNC_GATE": (
        "An async PreToolUse hook runs in the background and cannot block the call.",
        DOCS + "hooks#command-hook-fields",
    ),
    "HOOK_TIMEOUT": (
        "A PreToolUse hook that times out does not block; the call continues to the normal permission flow.",
        DOCS + "hooks#timeouts",
    ),
    "HOOK_HTTP_ENV": (
        "Header variables resolve only when listed in allowedEnvVars; otherwise they become empty.",
        DOCS + "hooks#http-hook-fields",
    ),
    "HOOK_MCP_LAUNCH": (
        "mcp_tool hooks are skipped at launch on SessionStart and always on Setup.",
        DOCS + "hooks#mcp-tool-hook-fields",
    ),
    "HOOK_DUP_CONTEXT": (
        "AGENTS.md is read natively since v2.1.277; printing it from a hook adds a second copy.",
        DOCS + "memory#remove-an-earlier-agents-md-workaround",
    ),
    "USER_SCOPE_HOOKS": (
        "Blocking hooks belong to each project; user scope carries context only.",
        "",
    ),
    "LOCAL_NOT_IGNORED": (
        "Personal overrides must stay out of commits; a tracked local file also waits for workspace trust.",
        DOCS + "permissions#when-your-local-settings-file-needs-trust",
    ),
    "JSON_FORMAT": ("Canonical 2-space formatting keeps diffs readable.", ""),
    "MCP_SHAPE": ("Each server needs 'command' (stdio) or 'url' with a type (http).", DOCS + "mcp"),
    "MCP_TYPE": (
        "A url server without 'type' is treated as stdio and fails to connect.",
        DOCS + "mcp",
    ),
    "MCP_SSE": ("The SSE transport is deprecated; prefer http.", DOCS + "mcp"),
    "MCP_COMMAND_ARGS": ("'command' is the executable; arguments go in 'args'.", DOCS + "mcp"),
    "MCP_MISPLACED": ("Servers must live under 'mcpServers'.", DOCS + "mcp"),
    "MCP_TOO_MANY": (
        "Each server's tools cost context; keep what this project uses.",
        DOCS + "mcp#scale-with-mcp-tool-search",
    ),
    "IMPORT_MISSING": (
        "The @import silently loads nothing.",
        DOCS + "memory#import-additional-files",
    ),
    "IMPORT_DEPTH": (
        "Imports recurse at most four hops; deeper files are not loaded.",
        DOCS + "memory#import-additional-files",
    ),
    "IMPORT_EXTERNAL": (
        "Imports outside the working directory need a one-time approval dialog.",
        DOCS + "memory#import-additional-files",
    ),
    "INSTR_USER_TOO_LONG": (
        "Loaded in every session of every project; import bulk on demand instead.",
        DOCS + "memory#write-effective-instructions",
    ),
    "INSTR_TOO_LARGE": (
        "Files over 4 MiB are skipped entirely.",
        DOCS + "memory#my-claude-md-is-too-large",
    ),
    "INSTR_LONG": (
        "Target under 200 lines; move procedures to skills and scoped content to .claude/rules/.",
        DOCS + "memory#write-effective-instructions",
    ),
    "INSTR_DUPLICATED": ("Same lines in user and project instructions are paid twice.", ""),
    "INSTR_PROSE": (
        "An agent parses a bulleted rule faster than a paragraph, and bullets cost fewer tokens.",
        DOCS + "memory#write-effective-instructions",
    ),
    "INSTR_FILLER": (
        "Politeness and hedging add tokens without changing behaviour; write direct imperatives.",
        DOCS + "memory#write-effective-instructions",
    ),
    "AGENTS_IGNORED": (
        "With a CLAUDE.md present, AGENTS.md is not read by default; import it.",
        DOCS + "memory#agents-md",
    ),
    "AGENTS_MENTION": (
        "A sentence asking to read AGENTS.md only works if Claude decides to open it; use @AGENTS.md.",
        DOCS + "memory#remove-an-earlier-agents-md-workaround",
    ),
    "AGENTS_SHADOWED_LOCAL": (
        "CLAUDE.local.md counts as a CLAUDE.md: AGENTS.md stops loading.",
        DOCS + "memory#when-claude-code-reads-agents-md",
    ),
    "AGENTS_OLD_CLI": (
        "Reading AGENTS.md natively needs v2.1.277+ (v2.1.281+ on Bedrock); keep a CLAUDE.md import.",
        DOCS + "memory#when-agents-md-support-is-unavailable",
    ),
    "AGENTS_SYMLINK": (
        "A symlinked CLAUDE.md breaks on Windows clones without core.symlinks; prefer the @AGENTS.md import.",
        DOCS + "memory#share-one-file-with-other-coding-tools",
    ),
    "RENDER_HAND_EDITED": ("Edit doctrine/rules/ and re-render; hand edits are lost.", ""),
    "LOCAL_MD_NOT_IGNORED": (
        "CLAUDE.local.md holds personal notes; keep it out of commits.",
        DOCS + "memory#import-additional-files",
    ),
    "RULE_UNSCOPED": (
        "Rules without 'paths' load in every session.",
        DOCS + "memory#path-specific-rules",
    ),
    "RULE_FIELD": (
        "'paths' is the only field read from a rule; others are ignored.",
        DOCS + "memory#rules-frontmatter-reference",
    ),
    "RULE_PATTERN": (
        "An unbalanced [ makes the pattern invalid: it matches nothing.",
        DOCS + "memory#path-specific-rules",
    ),
    "RULE_EXTERNAL": (
        "A rule symlinked outside the project needs external-import approval; ~/.claude/rules/ doesn't.",
        DOCS + "memory#share-rules-across-projects-with-symlinks",
    ),
    "FRONTMATTER_OFFSET": (
        "Frontmatter is read only when '---' is the first line; otherwise it becomes content.",
        DOCS + "skills#frontmatter-reference",
    ),
    "MEMORY_INDEX": (
        "Only the first 200 lines / 25KB of MEMORY.md load; the rest is dropped.",
        DOCS + "memory#how-it-works",
    ),
    "SKILL_MISSING": (
        "A skill directory must contain SKILL.md.",
        DOCS + "skills#where-skills-live",
    ),
    "SKILL_RESERVED": (
        "'synced' is reserved for claude.ai sync; the skill is skipped.",
        DOCS + "skills#where-skills-live",
    ),
    "SKILL_FIELD": (
        "Unknown frontmatter fields are ignored without error.",
        DOCS + "skills#frontmatter-reference",
    ),
    "SKILL_PORTABILITY": (
        "Outside the Agent Skills spec: claude.ai upload and the Skills API reject it.",
        DOCS + "skills#using-skill-frontmatter-outside-claude-code",
    ),
    "SKILL_NAME": (
        "The command comes from the directory; the spec expects name == directory, lowercase-hyphen, max 64.",
        DOCS + "skills#how-a-skill-gets-its-command-name",
    ),
    "SKILL_DESCRIPTION": (
        "The description decides when the skill triggers; key use case first.",
        DOCS + "skills#frontmatter-reference",
    ),
    "SKILL_LONG": (
        "Keep SKILL.md under 500 lines; move reference material to supporting files.",
        DOCS + "skills#add-supporting-files",
    ),
    "SKILL_FORK_FIELD": (
        "'agent' and 'background' only apply with context: fork.",
        DOCS + "skills#frontmatter-reference",
    ),
    "SKILL_SIDE_EFFECT": (
        "Side-effect workflows should be user-triggered: disable-model-invocation: true.",
        DOCS + "skills#control-who-invokes-a-skill",
    ),
    "SKILL_BROAD_TOOLS": (
        "allowed-tools is not gated by workspace trust; a broad grant runs unprompted.",
        DOCS + "skills#pre-approve-tools-for-a-skill",
    ),
    "SKILL_MANIFEST_BUG": (
        "Before v2.1.280 a manifest.json here moved listed skills to .trash.",
        DOCS + "skills#personal-skills-disappeared",
    ),
    "COMMAND_SHADOWED": (
        "A skill with the same name wins; the command file never runs.",
        DOCS + "skills#resolve-skills-that-share-a-name",
    ),
    "AGENT_FRONTMATTER": (
        "Subagents need name and description to be selectable.",
        DOCS + "sub-agents",
    ),
    "AGENT_FIELD": (
        "Unrecognised subagent field (may be newer than this script).",
        DOCS + "sub-agents",
    ),
    "AGENT_TOOLS": (
     …73244 tokens truncated…b|"
    r"\btruncate\b|\bdd\b|\binstall\b|\bpython3?\b|\bnode\b|\bruby\b|\bjq\b.*>|\bgit\s+(checkout|restore|apply|stash))"
)


def _norm_handlers(hooks: Any) -> set[str]:
    sigs: set[str] = set()
    if not isinstance(hooks, dict):
        return sigs
    for event, groups in hooks.items():
        for g in groups if isinstance(groups, list) else []:
            for h in (g or {}).get("hooks", []) if isinstance(g, dict) else []:
                if not isinstance(h, dict):
                    continue
                target = h.get("command") or h.get("url") or f"{h.get('server')}:{h.get('tool')}" or h.get("prompt")
                target = " ".join([str(target), *map(str, h.get("args") or [])])
                target = re.sub(r"[\"']?\$\{?CLAUDE_PROJECT_DIR\}?[\"']?/|^\./", "", target.strip())
                sigs.add(f"{event}:{target}")
    return sigs


def settings_violations(old: dict, new: dict) -> list[str]:
    v: list[str] = []
    po, pn = old.get("permissions") or {}, new.get("permissions") or {}
    ao, an = list(po.get("allow") or []), list(pn.get("allow") or [])
    for r in an:
        if r in ao or any(covers(o, r) for o in ao):
            continue
        parsed = split_rule(r)
        if parsed and parsed[0] == "Bash" and (parsed[1] or "").startswith("rtk "):
            plain = f"Bash({parsed[1][4:]})"
            if plain in ao or any(covers(o, plain) for o in ao):
                continue  # rtk routing of an existing rule: same scope
        v.append(f"new allow rule {r!r}")
    for key, stricter in (("deny", ()), ("ask", ("deny",))):
        for r in po.get(key) or []:
            pools = [pn.get(key) or []] + [pn.get(k) or [] for k in stricter]
            if not any(r in pool or any(covers(n, r) for n in pool) for pool in pools):
                v.append(f"{key} rule removed {r!r}")
    if pn.get("defaultMode") in ("bypassPermissions", "auto", "acceptEdits") and pn.get("defaultMode") != po.get(
        "defaultMode"
    ):
        v.append(f"defaultMode set to {pn.get('defaultMode')!r}")
    for k in ("disableBypassPermissionsMode", "disableAutoMode"):
        if po.get(k) and pn.get(k) != po.get(k):
            v.append(f"{k} relaxed")
    if set(pn.get("additionalDirectories") or []) - set(po.get("additionalDirectories") or []):
        v.append("additionalDirectories extended")
    removed = _norm_handlers(old.get("hooks")) - _norm_handlers(new.get("hooks"))
    if removed:
        v.append("hook(s) removed: " + ", ".join(sorted(removed)[:3]))
    if new.get("disableAllHooks") and not old.get("disableAllHooks"):
        v.append("disableAllHooks enabled")
    if new.get("enableAllProjectMcpServers") and not old.get("enableAllProjectMcpServers"):
        v.append("enableAllProjectMcpServers enabled")
    if set(new.get("enabledMcpjsonServers") or []) - set(old.get("enabledMcpjsonServers") or []):
        v.append("enabledMcpjsonServers extended")
    so, sn = old.get("sandbox") or {}, new.get("sandbox") or {}
    if so.get("enabled") and not sn.get("enabled"):
        v.append("sandbox disabled")
    if sn.get("allowUnsandboxedCommands") and not so.get("allowUnsandboxedCommands"):
        v.append("allowUnsandboxedCommands enabled")
    if set((new.get("env") or {})) - set((old.get("env") or {})):
        v.append("env variable(s) added")
    for k in (
        "apiKeyHelper",
        "awsAuthRefresh",
        "awsCredentialExport",
        "otelHeadersHelper",
        "statusLine",
        "fileSuggestion",
        "processWrapper",
        "extraKnownMarketplaces",
        "enabledPlugins",
    ):
        if new.get(k) not in (None, old.get(k)):
            v.append(f"{k} added or changed (executes code)")
    attr = new.get("attribution")
    if isinstance(attr, dict) and any(attr.get(k) for k in ("commit", "pr")):
        v.append("attribution re-enabled")
    return v


def mcp_violations(old: dict, new: dict) -> list[str]:
    so = old.get("mcpServers", old) if isinstance(old, dict) else {}
    sn = new.get("mcpServers", new) if isinstance(new, dict) else {}
    v = [f"new MCP server {n!r}" for n in set(sn) - set(so)]
    for n in set(sn) & set(so):
        a, b = so[n] if isinstance(so[n], dict) else {}, sn[n] if isinstance(sn[n], dict) else {}
        old_cmd = " ".join([str(a.get("command") or a.get("url") or ""), *map(str, a.get("args") or [])]).split()
        new_cmd = " ".join([str(b.get("command") or b.get("url") or ""), *map(str, b.get("args") or [])]).split()
        if old_cmd != new_cmd:
            v.append(f"MCP server {n!r} command/url changed")
        if set(b.get("env") or {}) - set(a.get("env") or {}):
            v.append(f"MCP server {n!r} env extended")
    return v


def frontmatter_violations(old: str, new: str) -> list[str]:
    mo, _ = split_frontmatter(old)
    mn, _ = split_frontmatter(new)
    mo, mn = mo or {}, mn or {}
    v = []
    tok = lambda s: {t for t in re.split(r"[\s,\[\]]+", s or "") if t}
    for key in ("allowed-tools", "tools", "allowed_tools", "allowedTools"):
        if tok(mn.get(key)) - tok(mo.get(key)):
            v.append(f"{key} extended")
    if mo.get("disable-model-invocation", "").lower() in ("true", "yes", "on", "1") and mn.get(
        "disable-model-invocation", ""
    ).lower() not in ("true", "yes", "on", "1"):
        v.append("disable-model-invocation removed")
    if set(tok(mo.get("disallowed-tools"))) - tok(mn.get("disallowed-tools")) or set(
        tok(mo.get("disallowedTools"))
    ) - tok(mn.get("disallowedTools")):
        v.append("disallowed tools reduced")
    if ("hooks" in frontmatter_block(new)) and "hooks" not in frontmatter_block(old):
        v.append("frontmatter hooks added")
    if mn.get("permissionMode") in ("bypassPermissions", "auto", "acceptEdits") and mn.get("permissionMode") != mo.get(
        "permissionMode"
    ):
        v.append("permissionMode loosened")
    if (mn.get("mcpServers") or "mcpServers" in frontmatter_block(new)) and "mcpServers" not in frontmatter_block(old):
        v.append("inline mcpServers added")
    if re.search(r"(?m)^\s*!`|^```!", new) and not re.search(r"(?m)^\s*!`|^```!", old):
        v.append("shell injection (!`cmd`) added")
    return v


def lint_toml_violations(old: str, new: str) -> list[str]:
    if tomllib is None:
        return ["cannot verify .ai-lint.toml without Python 3.11"]
    try:
        o = tomllib.loads(old) if old.strip() else {}
        n = tomllib.loads(new)
    except Exception as e:  # noqa: BLE001
        return [f"invalid TOML: {e}"]
    o.pop("reference", None)
    n.pop("reference", None)
    return [] if o == n else ["only the [reference] table may change"]


def protected_path(p: Path) -> str | None:
    rp = p.resolve()
    s = str(rp)
    if rp == Path(__file__).resolve():
        return "the linter itself"
    if rp.name == ".claude.json":
        return "~/.claude.json is written by Claude Code"
    if s.startswith(
        (
            "/etc/claude-code",
            "/Library/Application Support/ClaudeCode",
            "C:\\Program Files\\ClaudeCode",
        )
    ):
        return "managed settings"
    if "/skills/synced/" in s:
        return "skills synced from claude.ai"
    if "/.claude/plugins/" in s and str(config_dir()) in s:
        return "installed plugins (managed by the CLI)"
    if "/.git/hooks/" in s or s.endswith("/.git/hooks"):
        return "git hooks (installed by the linter only)"
    existing = read_text(rp) or ""
    if f'"{GUARD_MARKER}"' in existing:
        return "the guarded session settings"
    return None


def _guard_json(old: str, new: str, label: str) -> tuple[dict, dict] | str:
    """Parse the pre/post contents of a guarded JSON file. The old text is
    read leniently (a malformed file on disk must not block a repair); the new
    text must be strict JSON, else a guard block reason is returned. Non-object
    JSON is normalised to an empty dict so callers can treat both as mappings."""
    try:
        o = lenient_json(old)[0] if old.strip() else {}
    except json.JSONDecodeError:
        o = {}
    try:
        n = json.loads(new)
    except json.JSONDecodeError as e:
        return f"guard: {label} must stay strict JSON ({e})"
    return (o if isinstance(o, dict) else {}), (n if isinstance(n, dict) else {})


def guard_check(data: dict) -> str | None:
    """Return a block reason, or None to let the normal permission flow decide."""
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    cwd = Path(data.get("cwd") or os.getcwd())
    if tool in ("Bash", "PowerShell", "Monitor"):
        cmd = str(ti.get("command", ""))
        if re.fullmatch(r"\s*(rtk\s+)?(python3?\s+)?\S*ai-lint\.py(\s+[\w\-./=~:]+)*\s*", cmd):
            if re.search(r"--session-settings\b|--policy\b|\s-i\b|--interactive\b", cmd) or (
                re.search(r"--generate\b", cmd) and re.search(r"--fix\b", cmd)
            ):
                return "guard: --generate --fix, --session-settings and --policy add permissions: the human runs them (a --generate preview is allowed)"
            return None  # the linter only tightens
        if CONFIG_HINT.search(cmd) and BASH_WRITE_HINT.search(cmd):
            return (
                "guard: agent configuration files may only be changed with Edit/Write "
                "(so the change can be inspected), or by running ai-lint.py"
            )
        for pat in ATTRIBUTION_PATTERNS:
            if pat.search(cmd):
                return "guard: assistant attribution is forbidden"
        return None
    if tool not in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return None
    raw = ti.get("file_path") or ti.get("notebook_path")
    if not raw:
        return None
    path = Path(os.path.expanduser(raw))
    path = path if path.is_absolute() else cwd / path
    why = protected_path(path)
    if why:
        return f"guard: {path} is protected ({why})"
    old = read_text(path) or ""
    if tool == "Write":
        new = str(ti.get("content", ""))
    elif tool == "Edit":
        a, b = str(ti.get("old_string", "")), str(ti.get("new_string", ""))
        new = old.replace(a, b) if ti.get("replace_all") else old.replace(a, b, 1)
    elif tool == "MultiEdit":
        new = old
        for e in ti.get("edits") or []:
            a, b = str(e.get("old_string", "")), str(e.get("new_string", ""))
            new = new.replace(a, b) if e.get("replace_all") else new.replace(a, b, 1)
    else:
        return None
    for pat in ATTRIBUTION_PATTERNS:
        if pat.search(new) and not pat.search(old):
            return "guard: assistant attribution is forbidden"
    name = path.name
    violations: list[str] = []
    if name in ("settings.json", "settings.local.json") or re.search(r"settings.*\.json$", name):
        parsed = _guard_json(old, new, "settings")
        if isinstance(parsed, str):
            return parsed
        o, n = parsed
        violations = settings_violations(o, n)
    elif name == ".mcp.json":
        parsed = _guard_json(old, new, ".mcp.json")
        if isinstance(parsed, str):
            return parsed
        o, n = parsed
        violations = mcp_violations(o, n)
    elif name == "claude_desktop_config.json":
        parsed = _guard_json(old, new, "Desktop config")
        if isinstance(parsed, str):
            return parsed
        o, n = parsed
        violations = mcp_violations(o, n)
    elif name == "plugin.json" and path.parent.name == ".claude-plugin":
        parsed = _guard_json(old, new, "plugin.json")
        if isinstance(parsed, str):
            return parsed
        o, n = parsed
        violations = [
            f"plugin {k} added or changed (executes code)"
            for k in ("hooks", "mcpServers", "lspServers", "monitors", "channels", "userConfig")
            if n.get(k) not in (None, o.get(k))
        ]
    elif name == "marketplace.json" and path.parent.name == ".claude-plugin":
        parsed = _guard_json(old, new, "marketplace.json")
        if isinstance(parsed, str):
            return parsed
        o, n = parsed
        on = {p.get("name") for p in o.get("plugins") or [] if isinstance(p, dict)}
        nn = {p.get("name") for p in n.get("plugins") or [] if isinstance(p, dict)}
        violations = [f"new marketplace plugin {x!r}" for x in sorted(nn - on)]
    elif name == "hooks.json" and path.parent.name == "hooks":
        parsed = _guard_json(old, new, "hooks.json")
        if isinstance(parsed, str):
            return parsed
        o, n = parsed
        violations = settings_violations({"hooks": o.get("hooks")}, {"hooks": n.get("hooks")})
    elif path.suffix in (".yml", ".yaml") and "/.github/workflows/" in str(path) and "claude-code" in new:
        risky = [
            (
                r"dangerously-skip-permissions|permission-mode\W+bypassPermissions",
                "permissions bypass added",
            ),
            (r"(?m)^\s*pull_request_target\s*:", "pull_request_target trigger added"),
            (
                r"(allowed_tools|allowedTools)\W+[^\n]*\bBash(\(\*\))?(?=[\s,\"']|$)",
                "unrestricted Bash added",
            ),
        ]
        violations = [msg for pat, msg in risky if re.search(pat, new) and not re.search(pat, old)]
        if re.search(r"(?m)^\s*permissions\s*:", old) and not re.search(r"(?m)^\s*permissions\s*:", new):
            violations.append("workflow permissions block removed")
    elif name in (".ai-lint.toml", ".claude-lint.toml", ".agent-lint.toml"):
        violations = lint_toml_violations(old, new)
    elif name.endswith(".md") and (
        "/.claude/skills/" in str(path) or "/.claude/agents/" in str(path) or "/.claude/commands/" in str(path)
    ):
        violations = frontmatter_violations(old, new)
    if violations:
        return (
            "guard: this change would loosen the configuration: "
            + "; ".join(violations)
            + ". Leave it for the human and list it under 'not fixed'."
        )
    return None


def run_guard() -> int:
    try:
        data = json.load(sys.stdin)
        reason = guard_check(data if isinstance(data, dict) else {})
    except Exception as e:  # noqa: BLE001 - fail closed: any internal error blocks
        reason = f"guard: internal error, blocking by default ({e.__class__.__name__}: {e})"
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


def session_settings(policy: dict) -> dict:
    exe, script = sys.executable, str(Path(__file__).resolve())
    perms = policy["permissions"]
    deny = [f"Bash({p} *)" for p in perms["external_action_prefixes"]]
    deny += [t for r in deny if (t := rtk_twin(r, perms["rtk_exempt"]))]
    deny += [
        "Bash(git commit *)",
        "Bash(rtk git commit *)",
        "Bash(git reset *)",
        "Bash(rtk git reset *)",
        "Bash(rtk init *)",
        "Bash(rtk telemetry enable *)",
        "Bash(rtk hook *)",
        "Edit(~/.claude.json)",
        "Edit(//etc/claude-code/**)",
    ]
    return {
        "$schema": policy["scaffold"]["schema_url"],
        "disableAllHooks": False,
        "permissions": {
            "allow": [
                f"Bash({exe} {script} *)",
                f"Bash(rtk {exe} {script} *)",
                "WebFetch(domain:code.claude.com)",
                "WebFetch(domain:github.com)",
                "WebFetch(domain:agentskills.io)",
            ],
            "deny": dedupe(deny),
        },
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell|Monitor",
                    "hooks": [
                        {
                            "type": "command",
                            "command": exe,
                            "args": [script, GUARD_MARKER],
                            "timeout": 30,
                        }
                    ],
                }
            ]
        },
    }


# --------------------------------------------------------------------------- #
# Plugin system: drop a .py file in a plugins directory to add checks without
# touching the engine. A plugin defines `register(api)` and calls
# `api.check(name, scope=...)` as a decorator on a function `fn(ctx)`; the
# function inspects `ctx.repo` / `ctx.path(...)` and reports via `ctx.add(...)`.
# Findings flow into the same report and honour the catalog (severity/enable).
# Discovery: <config dir>/plugins, <repo>/.ai-lint/plugins, and --plugin-dir.
# --------------------------------------------------------------------------- #

_PLUGIN_CHECKS: list = []  # list of (name, scope, fn); scope is "project" or "user"
_PLUGINS_LOADED: list = []  # names of loaded plugins, for --list-plugins


class CheckContext:
    """What a plugin check receives. Thin, stable surface over the internals."""

    def __init__(self, scope: str, root: Path, policy: dict, rep: Report) -> None:
        self.scope = scope
        self.root = Path(root)  # repo root (project) or config dir (user)
        self.policy = policy
        self._rep = rep

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def read(self, p: Path) -> str | None:
        return read_text(p)

    def glob(self, pattern: str) -> list[Path]:
        try:
            return sorted(self.root.glob(pattern))
        except OSError:
            return []

    def add(
        self,
        level: str,
        code: str,
        path,
        message: str,
        action_fr: str = "",
        action_en: str = "",
        fixable: bool = False,
    ) -> None:
        # A plugin action feeds the same "-> fix" line as built-in checks.
        if action_fr or action_en:
            BRIEF_FR.setdefault(code, ("other", "", action_fr or action_en))
            BRIEF_EN.setdefault(code, ("other", "", action_en or action_fr))
        self._rep.add(level, code, path, message, fixable)


class PluginAPI:
    """Passed to each plugin's register(); its .check decorator registers a check."""

    def __init__(self, name: str) -> None:
        self.name = name

    def check(self, code: str, scope: str = "project"):
        if scope not in ("project", "user"):
            raise ValueError("scope must be 'project' or 'user'")

        def deco(fn):
            _PLUGIN_CHECKS.append((code, scope, fn))
            return fn

        return deco


def plugin_dirs(extra: list[Path] | None = None) -> list[Path]:
    dirs = [config_dir() / "plugins", Path.cwd() / ".ai-lint" / "plugins"]
    dirs += list(extra or [])
    return [d for d in dirs if d.is_dir()]


def load_plugins(extra: list[Path] | None = None) -> None:
    """Import every *.py in the plugin dirs and call its register(api). Failures
    are isolated: a broken plugin is reported and skipped, never fatal."""
    import importlib.util as _ilu

    for d in plugin_dirs(extra):
        for f in sorted(d.glob("*.py")):
            if f.name.startswith("_"):
                continue
            try:
                spec = _ilu.spec_from_file_location(f"ai_lint_plugin_{f.stem}", f)
                if not spec or not spec.loader:
                    continue
                mod = _ilu.module_from_spec(spec)
                spec.loader.exec_module(mod)
                reg = getattr(mod, "register", None)
                if callable(reg):
                    reg(PluginAPI(f.stem))
                    _PLUGINS_LOADED.append(f.stem)
                else:
                    log(1, f"plugin {f.name}: no register(api), skipped")
            except Exception as e:  # noqa: BLE001 - never let a plugin crash the run
                log(1, f"plugin {f.name}: failed to load ({e.__class__.__name__}: {e})")


def run_plugin_checks(scope: str, root: Path, policy: dict, rep: Report) -> None:
    for code, sc, fn in _PLUGIN_CHECKS:
        if sc != scope:
            continue
        try:
            fn(CheckContext(scope, root, policy, rep))
        except Exception as e:  # noqa: BLE001 - isolate a misbehaving plugin check
            log(1, f"plugin check {code}: error ({e.__class__.__name__}: {e})")


def dump_reference() -> dict:
    return {
        "docs_snapshot": "2026-09",
        "settings_keys": sorted(KNOWN_SETTINGS_KEYS),
        "hook_events": sorted(KNOWN_HOOK_EVENTS),
        "tools": sorted(KNOWN_TOOLS),
        "legacy_tools": LEGACY_TOOLS,
        "skill_fields": sorted(SKILL_FIELDS),
        "agent_fields": sorted(AGENT_FIELDS),
        "project_dead_keys": PROJECT_DEAD_KEYS,
    }


# --------------------------------------------------------------------------- #
# Editable catalog: the reference sets and per-code metadata as one YAML file.
# Editing it (via --catalog FILE) extends the reference data and overrides a
# code's severity, message action or enabled flag, without touching the engine.
# --------------------------------------------------------------------------- #

# Codes turned off in the catalog: check_* still runs, but rep.add drops them.
DISABLED_CODES: set[str] = set()
# Per-code severity overrides from the catalog (code -> "error"/"warn"/"info"/"off").
SEVERITY_OVERRIDES: dict[str, str] = {}


def catalog_data() -> dict:
    """The full built-in catalog: reference sets plus one entry per known finding
    code (its default severity is filled in from where it is emitted, best-effort;
    an explicit severity in the catalog wins)."""
    src = ""
    try:
        src = read_text(Path(__file__)) or ""
    except OSError:
        pass
    emitted = {}
    for lvl, code in re.findall(r'rep\.add\(\s*"([a-z]+)",\s*"([A-Z_]+)"', src):
        emitted.setdefault(code, lvl)  # first-seen severity as the default
    checks = {}
    for code in sorted(set(emitted) | set(HINTS)):
        why, ref = HINTS.get(code, ("", ""))
        checks[code] = {
            "severity": SEVERITY_OVERRIDES.get(code, emitted.get(code, "info")),
            "category": category(code),
            "enabled": code not in DISABLED_CODES,
            "why": why,
            "ref": ref,
            "action_fr": (BRIEF_FR.get(code) or ("", "", ""))[2],
            "action_en": (BRIEF_EN.get(code) or ("", "", ""))[2],
        }
    return {
        "docs_snapshot": "2026-09",
        "reference": {
            "settings_keys": sorted(KNOWN_SETTINGS_KEYS),
            "project_dead_keys": PROJECT_DEAD_KEYS,
            "hook_events": sorted(KNOWN_HOOK_EVENTS),
            "no_matcher_events": sorted(NO_MATCHER_EVENTS),
            "tools": sorted(KNOWN_TOOLS),
            "legacy_tools": LEGACY_TOOLS,
            "skill_fields": sorted(SKILL_FIELDS),
            "agent_fields": sorted(AGENT_FIELDS),
        },
        "checks": checks,
    }


def dump_catalog() -> str:
    if yaml is None:
        return "# PyYAML not installed: run `pip install pyyaml` to use the catalog.\n"
    header = (
        "# ai-lint catalog. Edit and pass with --catalog FILE.\n"
        "# reference.*: extend the known keys/events/tools/fields the linter accepts.\n"
        "# checks.<CODE>.severity: error|warn|info|off  ·  enabled: false to silence.\n"
        "# checks.<CODE>.action_fr/action_en: the '-> fix' line shown in --details.\n\n"
    )
    return header + yaml.safe_dump(catalog_data(), sort_keys=True, allow_unicode=True, width=100)


def load_catalog(path: Path) -> None:
    """Overlay an edited catalog onto the built-in defaults: extend reference sets,
    and record severity/enabled/action overrides for codes."""
    if yaml is None:
        log(1, "PyYAML not installed: --catalog ignored")
        return
    try:
        data = yaml.safe_load(read_text(path) or "") or {}
    except (OSError, yaml.YAMLError) as e:  # noqa: BLE001
        log(1, f"catalog {path}: unreadable ({e}); using built-in defaults")
        return
    ref = data.get("reference") or {}
    KNOWN_SETTINGS_KEYS.update(ref.get("settings_keys") or [])
    KNOWN_HOOK_EVENTS.update(ref.get("hook_events") or [])
    NO_MATCHER_EVENTS.update(ref.get("no_matcher_events") or [])
    KNOWN_TOOLS.update(ref.get("tools") or [])
    LEGACY_TOOLS.update(ref.get("legacy_tools") or {})
    SKILL_FIELDS.update(ref.get("skill_fields") or [])
    AGENT_FIELDS.update(ref.get("agent_fields") or [])
    if isinstance(ref.get("project_dead_keys"), dict):
        PROJECT_DEAD_KEYS.update(ref["project_dead_keys"])
    for code, meta in (data.get("checks") or {}).items():
        if not isinstance(meta, dict):
            continue
        sev = str(meta.get("severity", "")).lower()
        if meta.get("enabled") is False or sev == "off":
            DISABLED_CODES.add(code)
        elif sev in ("error", "warn", "info"):
            SEVERITY_OVERRIDES[code] = sev
        fr, en = meta.get("action_fr"), meta.get("action_en")
        if fr or en:
            base = BRIEF_FR.get(code) or ("other", "", "")
            if fr:
                BRIEF_FR[code] = (base[0], base[1], fr)
            baseen = BRIEF_EN.get(code) or ("other", "", "")
            if en:
                BRIEF_EN[code] = (baseen[0], baseen[1], en)
    log(1, f"catalog {path}: +{len(SEVERITY_OVERRIDES)} severity, {len(DISABLED_CODES)} disabled")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Validate, repair and optimize coding-agent configurations "
        "(Claude Code settings, permissions, hooks, MCP, skills, subagents, "
        "commands, rules, instruction files, plugins, CI and secrets).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  ai-lint.py .                      read-only report for the current repo\n"
            "  ai-lint.py . --fix               apply safe repairs (backup kept)\n"
            "  ai-lint.py . --user              include user scope (~/.claude or "
            "$CLAUDE_CONFIG_DIR)\n"
            "  ai-lint.py ~/dev --user          every git repo under ~/dev, plus user scope\n"
            "  ai-lint.py . --generate          preview config to generate for the stack\n"
            "  ai-lint.py . -i                  interactive review (duplicates, packs, "
            "restructurings)\n"
            "  ai-lint.py --restore             undo the last interactive session\n"
            "  ai-lint.py . --strict --format json --no-cli   CI-friendly run\n"
            "\n"
            "read-only by default; --fix and -i are the only writing modes, both reversible.\n"
            "each run appends a JSON line to ~/.cache/ai-lint/logs/<date>.log.\n"
            "docs snapshot follows code.claude.com/docs; unknown keys are reported, never errors.\n"
            "\n"
            "defaults:\n"
            "  scope             current repo only (--user adds ~/.claude or $CLAUDE_CONFIG_DIR)\n"
            "  mode              read-only (no --fix, no --generate, no -i)\n"
            "  report            brief; language from $LANG (fr if it starts with 'fr', else en)\n"
            "  scaffolding       on (missing baseline files created; --no-scaffold to disable)\n"
            "  CLIs              claude and rtk are called when present (--no-cli to skip)\n"
            "  policy file       <repo>/.ai-lint.toml if present, else built-in defaults\n"
            "  instruction file  warns above 200 lines; user scope above 150\n"
            "  always-loaded     token budget warns above 10000 tokens/turn\n"
            "  skill description warns above 1024 chars in the listing\n"
            "  MCP servers       capped at 6\n"
            "  rtk routing       required (permissions.require_rtk = true)\n"
            "run with --print-policy to print every default as TOML."
        ),
    )
    ap.add_argument("repos", nargs="*", type=Path, help="repositories or folders of repositories (default: cwd)")
    ap.add_argument("--user", action="store_true", help="also check user scope")
    ap.add_argument("--user-only", action="store_true", help="check user scope only")
    ap.add_argument("--fix", action="store_true", help="apply repairs (with backup)")
    ap.add_argument("--no-scaffold", action="store_true", help="do not create missing files")
    ap.add_argument("--format", choices=("text", "json"), default="text", help="output format (default: text)")
    ap.add_argument("--policy", type=Path, help="policy TOML (default: <repo>/.ai-lint.toml)")
    ap.add_argument("--strict", action="store_true", help="fail on warnings too")
    ap.add_argument("--no-history", action="store_true", help="skip git history scan")
    ap.add_argument("--no-cli", action="store_true", help="do not call the claude / rtk CLIs")
    ap.add_argument(
        "--generate",
        action="store_true",
        help="generate missing config for the detected stack: settings, hooks, skills, "
        "subagents, MCP, rtk (with --user: user scope too)",
    )
    ap.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="review duplicates, subagent packs, long descriptions and model choice one by one (reversible)",
    )
    ap.add_argument(
        "--restore",
        nargs="?",
        const="",
        metavar="TRASH_DIR",
        help="move back everything removed by the last -i session (or the given trash folder)",
    )
    ap.add_argument("--details", action="store_true", help="full per-file report instead of the brief one")
    ap.add_argument(
        "--diff", action="store_true", help="print a unified diff of every file --fix / -i / --generate changed"
    )
    ap.add_argument("--all", action="store_true", help="list every finding instead of grouping repeated ones")
    ap.add_argument(
        "--min-level",
        choices=("error", "warn", "info"),
        default="info",
        help="hide findings below this level (e.g. --min-level warn drops info noise)",
    )
    ap.add_argument("--rtk-report", action="store_true", help="append 'rtk gain' and 'rtk discover' output")
    ap.add_argument(
        "--lang",
        choices=("en", "fr"),
        default=None,
        help="brief-report language (default: fr when $LANG starts with 'fr', else en)",
    )
    vg = ap.add_mutually_exclusive_group()
    vg.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="-v progress+hints+refs, -vv transformations, -vvv debug",
    )
    vg.add_argument("-q", "--quiet", action="store_true", help="errors and summary only")
    ap.add_argument("--version", action="version", version=f"ai-lint {VERSION}")
    ap.add_argument("--print-policy", action="store_true", help="print the default policy as TOML")
    ap.add_argument(
        "--guard",
        action="store_true",
        help="PreToolUse hook mode: read hook JSON on stdin, exit 2 to block",
    )
    ap.add_argument(
        "--session-settings",
        type=Path,
        metavar="FILE",
        help="write guarded session settings for 'claude --settings FILE'",
    )
    ap.add_argument("--dump-reference", action="store_true", help="print built-in reference data as JSON")
    ap.add_argument(
        "--print-catalog",
        action="store_true",
        help="print the editable catalog (reference + checks) as YAML",
    )
    ap.add_argument(
        "--catalog",
        type=Path,
        metavar="FILE",
        help="load an edited catalog YAML (extends reference, overrides checks)",
    )
    ap.add_argument(
        "--plugin-dir",
        type=Path,
        action="append",
        metavar="DIR",
        help="extra directory of check plugins (repeatable); also loaded from "
        "<config dir>/plugins and <repo>/.ai-lint/plugins",
    )
    ap.add_argument("--list-plugins", action="store_true", help="list discovered check plugins and exit")
    # No arguments at all: show help (with defaults) instead of silently scanning cwd.
    if not (argv if argv is not None else sys.argv[1:]):
        ap.print_help()
        return 0
    args = ap.parse_args(argv)
    global VERBOSITY, SCAFFOLD, CLI_VERSION, SHOW_ALL, FIRST_REPORT, LANG, PROGRESS, MIN_LEVEL, SHOW_DIFF
    if args.restore is not None:
        return restore_trash(args.restore or None)
    VERBOSITY, SCAFFOLD, SHOW_ALL = args.verbose, not args.no_scaffold, args.all
    SHOW_DIFF = args.diff
    CHANGE_LOG.clear()
    MIN_LEVEL = args.min_level
    # Progress bar by default: interactive stderr, no -v (which logs per repo),
    # no -q, text output only. Keeps pipes, JSON and CI silent.
    PROGRESS = sys.stderr.isatty() and args.verbose == 0 and not args.quiet and args.format == "text"
    if args.catalog:
        load_catalog(args.catalog)
    LANG = args.lang or ("fr" if os.environ.get("LANG", "").lower().startswith("fr") else "en")
    load_plugins(args.plugin_dir)
    if args.list_plugins:
        dirs = ", ".join(str(d) for d in plugin_dirs(args.plugin_dir)) or "(none)"
        print(f"plugin dirs: {dirs}")
        print(f"loaded plugins ({len(_PLUGINS_LOADED)}): " + (", ".join(_PLUGINS_LOADED) or "(none)"))
        print(f"registered checks: {len(_PLUGIN_CHECKS)}")
        for code, scope, _ in _PLUGIN_CHECKS:
            print(f"  {scope:8} {code}")
        return 0

    if args.print_policy:
        print(to_toml(DEFAULT_POLICY))
        return 0
    if args.guard:
        load_policy(None, [Path(os.getcwd())])
        return run_guard()
    if args.print_catalog:
        if args.catalog:
            load_catalog(args.catalog)
        print(dump_catalog(), end="")
        return 0 if yaml is not None else 2
    if args.dump_reference:
        load_policy(args.policy, [Path.cwd()])
        print(json.dumps(dump_reference(), indent=2))
        return 0
    if args.session_settings:
        policy = load_policy(args.policy, [Path.cwd()])
        target = args.session_settings.expanduser().resolve()
        if target.exists():
            target.chmod(0o644)
        target.write_text(dump_json(session_settings(policy)), encoding="utf-8")
        target.chmod(0o444)
        print(f"wrote {target} (read-only). Start the audit with:\n  claude --settings {target}")
        return 0
    log(1, f"ai-lint {VERSION}")
    detect_rtk(not args.no_cli)
    detect_llmtrim(not args.no_cli)
    RTK["checked_cli"] = not args.no_cli
    if not args.no_cli:
        CLI_VERSION = detect_cli_version()
        log(1, "claude CLI: " + (".".join(map(str, CLI_VERSION)) if CLI_VERSION else "not found"))

    run_started = time.perf_counter()
    targets = [] if args.user_only else [r.expanduser().resolve() for r in (args.repos or [Path.cwd()])]
    for r in targets:
        if not r.is_dir():
            print(f"not a directory: {r}", file=sys.stderr)
            return 2
    DISCOVERY.clear()
    repos = [repo for t in targets for repo in discover_repos(t)]
    policy = load_policy(args.policy, repos)
    history = not args.no_history
    first = rep = run_lint(repos, policy, args, history)
    FIRST_REPORT = first
    applied: list[str] = []
    failures: list[tuple[str, str]] = []
    backups: list[str] = []
    fixed: list[Finding] = []

    if args.fix:
        for n in range(1, 6):
            if not (rep.edits or rep.new_files or rep.chmods or rep.moves):
                break
            log(
                1,
                f"fix pass {n}: {len(rep.edits) + len(rep.new_files) + len(rep.chmods)} change(s)",
            )
            where, done, failed = apply(rep)
            applied += done
            failures += failed
            if where:
                backups.append(str(where))
            rep = run_lint(repos, policy, args, history)
            if failed:
                break
        remaining = {(f.code, f.path) for f in rep.findings}
        seen: set[tuple[str, str, str]] = set()
        for f in first.findings:
            key = (f.code, f.path, f.message)
            if f.fixable and (f.code, f.path) not in remaining and key not in seen:
                fixed.append(f)
                seen.add(key)
        for p, msg in failures:
            rep.add("error", "WRITE_FAILED", p, msg)

    if args.interactive and args.format == "text":
        global INTERACTIVE_RAN
        INTERACTIVE_RAN = True
        if interactive(rep, repos, policy, bool(args.user or args.user_only)):
            rep = run_lint(repos, policy, args, history)
    if args.format == "text":
        disc = render_discovery(sys.stdout.isatty())
        if disc:
            print(disc + "\n")
    if args.format == "text" and not (args.details or args.all):
        print(render_brief(rep, fixed, args.fix, len(repos), sys.stdout.isatty()))
        for bk in sorted(set(backups)):
            print(_loc("Sauvegarde des fichiers modifiés : ", "Backup of modified files: ") + bk)
        code = 1 if rep.count("error") or (args.strict and rep.count("warn")) else 0
        write_run_log(
            argv or sys.argv[1:],
            repos,
            rep,
            fixed,
            applied,
            time.perf_counter() - run_started,
            code,
        )
        return code
    if args.format == "json":
        codes = {f.code for f in rep.findings} | {f.code for f in fixed}
        print(
            json.dumps(
                {
                    "cli_version": ".".join(map(str, CLI_VERSION)) if CLI_VERSION else None,
                    "feedback_schema_version": 1,
                    "repositories": [str(r) for r in repos],
                    "project_profiles": getattr(rep, "project_profiles", []),
                    "findings": [finding_feedback(f) for f in rep.findings],
                    "fixed": [finding_feedback(f, "fixed") for f in fixed],
                    "not_fixed": [finding_feedback(f) for f in rep.findings if args.fix or not f.fixable],
                    "would_fix": [] if args.fix else [finding_feedback(f, "would_fix") for f in rep.findings if f.fixable],
                    "applied": applied,
                    "pending_changes": [str(p) for p in [*rep.edits, *rep.new_files, *rep.chmods]]
                    + [f"{s} -> {d}" for s, d in rep.moves],
                    "hints": {c: {"why": HINTS[c][0], "ref": HINTS[c][1]} for c in sorted(codes) if c in HINTS},
                    "fix_mode": args.fix,
                    "backups": backups,
                    "token_budget": getattr(rep, "budget", None),
                    "restructure": [
                        {"kind": p["kind"], "title": p["title"], "tokens_per_session": p["gain"]}
                        for p in getattr(rep, "proposals", [])
                    ],
                    "stats": {
                        "checked": rep.stats,
                        "by_category": {
                            c: sum(1 for f in rep.findings if category(f.code) == c)
                            for c in {category(f.code) for f in rep.findings}
                        },
                    },
                    "rtk": {
                        "path": RTK["path"],
                        "version": ".".join(map(str, RTK["version"])) if RTK["version"] else None,
                        "genuine": RTK["genuine"],
                        "excluded": sorted(RTK["exclude"]),
                        "report": rtk_report() if args.rtk_report else None,
                    },
                },
                indent=2,
            )
        )
    else:
        print(render_text(rep, args.fix, sys.stdout.isatty(), args.quiet, fixed, applied, failures, backups))
        if args.rtk_report:
            report = rtk_report()
            print("\n== rtk report\n" + (report or "rtk not available"))
    code = 1 if rep.count("error") or (args.strict and rep.count("warn")) else 0
    write_run_log(argv or sys.argv[1:], repos, rep, fixed, applied, time.perf_counter() - run_started, code)
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # output piped into head/less that closed early
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)