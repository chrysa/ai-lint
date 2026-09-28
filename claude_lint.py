#!/usr/bin/env python3
"""claude-lint: validate, repair and optimize coding-agent configurations.

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
  claude-lint.py [PATH ...] [--user|--user-only] [--fix] [--no-scaffold]
                       [--format text|json] [--policy FILE] [--strict]
                       [--no-history] [--no-cli] [-v|-vv|-vvv|-q]
  claude-lint.py --print-policy

PATH may be a repository or a folder of repositories (searched 3 levels deep).
Default mode is read-only: findings + the unified diff --fix would apply.
--fix applies safe repairs in passes until stable, re-lints, and reports what was
fixed versus what needs manual action. Originals go to ~/.cache/claude-lint/.

Verbosity (stderr; --format json stays clean on stdout):
  -q  errors + summary   -v  progress, why/how hints, doc references
  -vv every transformation   -vvv debug (files scanned, git calls, resolved policy)

Guarded audit session (for an AI agent doing the judgment calls):
  claude-lint.py --session-settings FILE   write a --settings file that installs --guard
  claude --settings FILE                         agent edits are now checked by --guard:
      no widening of allow rules, no removal of deny/ask rules or hooks, no bypass modes,
      no new MCP servers/env/helpers, no attribution, protected files untouchable,
      .claude-lint.toml editable only in [reference]. Fails closed.
  claude-lint.py --dump-reference          built-in reference data, to diff against docs

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

VERSION = "2026.09.29-28"
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
        "rendered_files": ["CLAUDE.md", "AGENTS.md", ".github/copilot-instructions.md"],
        "claude_md_import": True,  # keep CLAUDE.md = "@AGENTS.md" for CLIs < 2.1.277 / Bedrock
        "min_duplicate_line_len": 30,
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
SECRET_KEY_RE = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|PRIVATE_KEY|AUTHORIZATION)", re.I
)

COMMIT_MSG_HOOK = """#!/usr/bin/env sh
# Strip AI-assistant attribution trailers from commit messages.
# Installed by claude-lint. Deterministic and agent-agnostic.
sed -i -E \\
  -e '/^Co-Authored-By:.*(claude|anthropic)/Id' \\
  -e '/Generated with \\[?Claude Code/Id' \\
  "$1"
sed -i -e :a -e '/^\\n*$/{$d;N;ba' -e '}' "$1"
"""
HOOK_SIGNATURE = "claude-lint"

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
        "Settings files are strict JSON: comments or trailing commas make Claude Code "
        "reject the file.",
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
        "disableAllHooks in project settings overrides your user value and silences every "
        "guard hook.",
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
        "The model can write the trailer itself in 'git commit -m'; a commit-msg hook "
        "removes it deterministically.",
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
        "':*' is only a wildcard at the end; elsewhere the colon is literal and the rule "
        "never matches.",
        DOCS + "permissions#wildcard-patterns",
    ),
    "PERM_ABS_PATH": (
        "A single leading slash anchors at the settings source, not the filesystem root; "
        "use // for absolute paths.",
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
        "Bash deny rules miss /usr/bin/curl or sh -c 'curl'; the sandbox network allowlist "
        "is the real boundary.",
        DOCS + "permissions#bash-rule-limits",
    ),
    "SECRET_INLINE": (
        "Committed or plaintext config is readable by anyone with access; reference ${VAR} "
        "or the vault.",
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
        "Hooks run in the current directory, which moves with cd; anchor on "
        "${CLAUDE_PROJECT_DIR} in exec form.",
        DOCS + "hooks#reference-scripts-by-path",
    ),
    "HOOK_EXEC_FORM": (
        "Exec form (command + args) passes paths without shell quoting issues.",
        DOCS + "hooks#exec-form-and-shell-form",
    ),
    "HOOK_EXIT1": (
        "Only exit 2 (or a JSON decision) blocks; exit 1 is a non-blocking error and the "
        "action proceeds.",
        DOCS + "hooks#exit-code-2",
    ),
    "HOOK_ASYNC_GATE": (
        "An async PreToolUse hook runs in the background and cannot block the call.",
        DOCS + "hooks#command-hook-fields",
    ),
    "HOOK_TIMEOUT": (
        "A PreToolUse hook that times out does not block; the call continues to the normal "
        "permission flow.",
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
        "Personal overrides must stay out of commits; a tracked local file also waits for "
        "workspace trust.",
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
    "AGENTS_IGNORED": (
        "With a CLAUDE.md present, AGENTS.md is not read by default; import it.",
        DOCS + "memory#agents-md",
    ),
    "AGENTS_MENTION": (
        "A sentence asking to read AGENTS.md only works if Claude decides to open it; use "
        "@AGENTS.md.",
        DOCS + "memory#remove-an-earlier-agents-md-workaround",
    ),
    "AGENTS_SHADOWED_LOCAL": (
        "CLAUDE.local.md counts as a CLAUDE.md: AGENTS.md stops loading.",
        DOCS + "memory#when-claude-code-reads-agents-md",
    ),
    "AGENTS_OLD_CLI": (
        "Reading AGENTS.md natively needs v2.1.277+ (v2.1.281+ on Bedrock); keep a "
        "CLAUDE.md import.",
        DOCS + "memory#when-agents-md-support-is-unavailable",
    ),
    "AGENTS_SYMLINK": (
        "A symlinked CLAUDE.md breaks on Windows clones without core.symlinks; prefer the "
        "@AGENTS.md import.",
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
        "A rule symlinked outside the project needs external-import approval; "
        "~/.claude/rules/ doesn't.",
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
        "The command comes from the directory; the spec expects name == directory, "
        "lowercase-hyphen, max 64.",
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
        "An unknown tool is dropped; if none match, the subagent is refused.",
        DOCS + "errors#agent-would-be-spawned-with-zero-tools",
    ),
    "COMMAND_FRONTMATTER": ("A description makes the command readable in the / menu.", ""),
    "SCAFFOLD_SETTINGS": (
        "Baseline: attribution off, secrets denied, external actions on ask.",
        "",
    ),
    "SCAFFOLD_USER_SETTINGS": ("Baseline user settings: attribution off only.", ""),
    "SCAFFOLD_INSTRUCTIONS": (
        "AGENTS.md is the neutral source; CLAUDE.md only imports it.",
        DOCS + "memory#share-one-file-with-other-coding-tools",
    ),
    "SCAFFOLD_CLAUDE_IMPORT": (
        "Import kept for CLIs before v2.1.277 and sessions without native AGENTS.md.",
        DOCS + "memory#when-agents-md-support-is-unavailable",
    ),
    "SCAFFOLD_RENDER_MISSING": ("doctrine/rules exists: run your renderer.", ""),
    "USER_SCOPE_ABSENT": ("Nothing to check at user scope.", ""),
    "WRITE_FAILED": (
        "Permissions, read-only mount, or a symlink to a generated file.",
        DOCS + "settings#a-change-you-made-in-claude-code-is-lost-in-new-sessions",
    ),
    "CLI_VERSION": ("Detected with 'claude --version'.", DOCS + "changelog"),
}

# --------------------------------------------------------------------------- #
# Logging and findings
# --------------------------------------------------------------------------- #

VERBOSITY = 0
SCAFFOLD = True
CLI_VERSION: tuple[int, ...] | None = None
LANG = "fr"  # brief-report language: "fr" or "en" (set from --lang / $LANG)


def _loc(fr: str, en: str) -> str:
    """Pick the brief-report string for the active language."""
    return en if LANG == "en" else fr


_COLOR_ERR = sys.stderr.isatty()
LEVELS = ("error", "warn", "info")


def log(level: int, msg: str, indent: int = 0) -> None:
    if VERBOSITY >= level:
        line = f"{'  ' * indent}{ {1: '·', 2: '»', 3: 'debug'}.get(level, '·') } {msg}"
        print(f"\033[2m{line}\033[0m" if _COLOR_ERR else line, file=sys.stderr)


# Progress bar on stderr for the repo scan: only on an interactive stderr, at the
# default verbosity (a -v run prints per-repo lines instead, and -q / a pipe / CI
# stay silent). It writes to stderr so stdout (the report, JSON) is never polluted.
PROGRESS = False  # set in main() once flags are known


def progress(done: int, total: int, label: str = "") -> None:
    if not PROGRESS or total <= 0:
        return
    width = 24
    filled = int(width * done / total)
    bar = "█" * filled + "░" * (width - filled)
    end = "\n" if done >= total else ""
    lbl = (label[:40] + "…") if len(label) > 41 else label
    print(
        f"\r\033[2m  scan [{bar}] {done}/{total} {lbl}\033[0m\033[K{end}",
        end=end or "",
        file=sys.stderr,
        flush=True,
    )


@dataclass
class Finding:
    level: str
    code: str
    path: str
    message: str
    fixable: bool = False


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    edits: dict[Path, tuple[str, str]] = field(default_factory=dict)
    new_files: dict[Path, tuple[str, int]] = field(default_factory=dict)
    chmods: list[Path] = field(default_factory=list)
    moves: list[tuple[Path, Path]] = field(default_factory=list)
    seen: set = field(default_factory=set)
    budget: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    agent_unknown: dict = field(default_factory=dict)
    proposals: list = field(default_factory=list)

    def add(self, level: str, code: str, path: Path | str, msg: str, fixable: bool = False) -> None:
        if code in DISABLED_CODES:  # silenced in the catalog
            return
        level = SEVERITY_OVERRIDES.get(code, level)  # catalog can re-rank a code
        self.findings.append(Finding(level, code, str(path), msg, fixable))
        log(3, f"finding {level}:{code} @ {path}")

    def count(self, level: str) -> int:
        return sum(1 for f in self.findings if f.level == level)

    def edit(self, path: Path, old: str, new: str) -> None:
        """Register a text change, chaining with an earlier change to the same file."""
        if path in self.new_files:
            self.new_files[path] = (new, self.new_files[path][1])
        elif path in self.edits:
            self.edits[path] = (self.edits[path][0], new)
        elif old != new:
            self.edits[path] = (old, new)

    def current(self, path: Path) -> str | None:
        if path in self.new_files:
            return self.new_files[path][0]
        if path in self.edits:
            return self.edits[path][1]
        return read_text(path)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        out[k] = (
            deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
        )
    return out


def load_policy(path: Path | None, repos: list[Path]) -> dict:
    # Prefer .claude-lint.toml; accept the former .agent-lint.toml name too.
    candidates = (
        [path]
        if path
        else [r / n for r in repos for n in (".claude-lint.toml", ".agent-lint.toml")]
    )
    policy, source = copy.deepcopy(DEFAULT_POLICY), "built-in defaults"
    for c in candidates:
        if c and c.is_file():
            if tomllib is None:
                print(f"warning: {c} ignored (needs Python >= 3.11)", file=sys.stderr)
                break
            with c.open("rb") as fh:
                policy = deep_merge(policy, tomllib.load(fh))
            source = str(c)
            break
    ref = policy.get("reference", {})
    KNOWN_SETTINGS_KEYS.update(ref.get("extra_settings_keys", []))
    KNOWN_HOOK_EVENTS.update(ref.get("extra_hook_events", []))
    KNOWN_TOOLS.update(ref.get("extra_tools", []))
    SKILL_FIELDS.update(ref.get("extra_skill_fields", []))
    AGENT_FIELDS.update(ref.get("extra_agent_fields", []))
    log(
        1,
        f"policy: {source}"
        + (f" (reference data checked {ref['docs_checked']})" if ref.get("docs_checked") else ""),
    )
    log(3, "resolved policy: " + json.dumps(policy, ensure_ascii=False))
    return policy


_READ_CACHE: dict = {}  # (path, mtime_ns, size) -> text; keyed on stat so a write misses


def read_text(p: Path) -> str | None:
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
    except OSError:
        return None
    hit = _READ_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if len(_READ_CACHE) > 20000:  # bound memory on huge scans
        _READ_CACHE.clear()
    _READ_CACHE[key] = text
    return text


def dump_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def config_dir() -> Path:
    return Path(os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"))


def lenient_json(raw: str) -> tuple[Any, bool]:
    """Parse JSON; on failure retry without BOM, comments and trailing commas."""
    try:
        return json.loads(raw), False
    except json.JSONDecodeError as first_error:
        text = raw.lstrip("\ufeff")
        out, i, n, in_str = [], 0, len(text), False
        while i < n:
            c = text[i]
            if in_str:
                out.append(c)
                if c == "\\" and i + 1 < n:
                    out.append(text[i + 1])
                    i += 1
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
                out.append(c)
            elif text.startswith("//", i):
                while i < n and text[i] != "\n":
                    i += 1
                continue
            elif text.startswith("/*", i):
                end = text.find("*/", i + 2)
                i = n if end == -1 else end + 2
                continue
            else:
                out.append(c)
            i += 1
        try:
            return json.loads(re.sub(r",(\s*[}\]])", r"\1", "".join(out))), True
        except json.JSONDecodeError:
            raise first_error from None


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:64] or "unnamed"


def yaml_scalar(value: str) -> str:
    if re.search(r"(:\s|^[\s\-?\[\]{}#&*!|>'\"%@`]|\s#|\s$)", value):
        return json.dumps(value, ensure_ascii=False)
    return value


def split_frontmatter(text: str) -> tuple[dict[str, str] | None, int]:
    """Return (flat top-level keys, offset). offset > 0 means the block doesn't start on line 1."""
    stripped = text.lstrip("\ufeff \t\r\n")
    offset = len(text) - len(stripped)
    if not stripped.startswith("---"):
        return None, 0
    end = stripped.find("\n---", 3)
    if end == -1:
        return None, 0
    meta: dict[str, str] = {}
    for line in stripped[3:end].splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if m:
            meta[m.group(1)] = m.group(2).strip().strip("'\"")
    return meta, offset


def frontmatter_block(text: str) -> str:
    stripped = text.lstrip("\ufeff \t\r\n")
    end = stripped.find("\n---", 3)
    return stripped[3:end] if stripped.startswith("---") and end != -1 else ""


def set_frontmatter(
    text: str, updates: dict[str, str], renames: dict[str, str] | None = None
) -> str:
    text = text.lstrip("\ufeff \t\r\n") if text.lstrip("\ufeff \t\r\n").startswith("---") else text
    if text.startswith("---") and (end := text.find("\n---", 3)) != -1:
        head, body = text[3:end].strip("\n").splitlines(), text[end + 4 :]
        for old, new in (renames or {}).items():
            head = [re.sub(rf"^{re.escape(old)}(\s*:)", rf"{new}\1", l) for l in head]
        for key, val in updates.items():
            line = f"{key}: {yaml_scalar(val)}"
            idx = next(
                (i for i, l in enumerate(head) if re.match(rf"^{re.escape(key)}\s*:", l)), None
            )
            if idx is None:
                head.insert(0 if key == "name" else len(head), line)
            else:
                head[idx] = line
        return "---\n" + "\n".join(head) + "\n---" + body
    lines = [f"{k}: {yaml_scalar(v)}" for k, v in updates.items()]
    return "---\n" + "\n".join(lines) + "\n---\n\n" + text.lstrip("\n")


def strip_code(text: str) -> str:
    """Remove fenced blocks and inline code spans (imports inside them are literal)."""
    text = re.sub(r"(?ms)^(```|~~~).*?^\1", "", text)
    return re.sub(r"`[^`\n]*`", "", text)


def strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def derive_description(text: str) -> str | None:
    body = text
    stripped = body.lstrip("\ufeff \t\r\n")
    if stripped.startswith("---") and (end := stripped.find("\n---", 3)) != -1:
        body = stripped[end + 4 :]
    body = strip_html_comments(strip_code(body))
    for para in re.split(r"\n\s*\n", body):
        para = " ".join(
            l.strip()
            for l in para.splitlines()
            if l.strip() and not l.lstrip().startswith(("#", "|", ">", "!"))
        )
        para = re.sub(r"[*_`]", "", para).strip(" -")
        if len(para) >= 20:
            return re.split(r"(?<=[.!?])\s", para)[0][:300]
    return None


def git(repo: Path, *args: str) -> str | None:
    log(3, "git -C " + str(repo) + " " + " ".join(args))
    try:
        res = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return res.stdout if res.returncode == 0 else None


def is_ignored(repo: Path, rel: str) -> bool:
    return git(repo, "check-ignore", "-q", rel) is not None


def is_tracked(repo: Path, rel: str) -> bool:
    return git(repo, "ls-files", "--error-unmatch", rel) is not None


def add_gitignore(repo: Path, entry: str, rep: Report) -> None:
    gi = repo / ".gitignore"
    cur = rep.current(gi) or ""
    if entry in cur.splitlines():
        return
    new = cur + ("" if not cur or cur.endswith("\n") else "\n") + entry + "\n"
    if gi.exists() or gi in rep.edits:
        rep.edit(gi, read_text(gi) or "", new)
    else:
        rep.new_files[gi] = (new, 0o644)
    log(2, f".gitignore: add {entry}", 2)


def detect_cli_version() -> tuple[int, ...] | None:
    exe = shutil.which("claude")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
    return tuple(int(x) for x in m.groups()) if m else None


# --------------------------------------------------------------------------- #
# Permission rules
# --------------------------------------------------------------------------- #

RULE_RE = re.compile(r"^(?P<tool>[A-Za-z_*][\w*-]*)(?:\((?P<spec>.*)\))?$", re.S)
LOOSE_RE = re.compile(r"^([A-Za-z_*][\w*-]*)\s*(?:\((.*?)(\))?|:\s*(.+)|\s+(.+))?$", re.S)
SHELL_TOOLS = {"Bash", "PowerShell", "Monitor"}
_TOOL_CASE = {t.lower(): t for t in KNOWN_TOOLS | RULE_ONLY_TOOLS | set(LEGACY_TOOLS)}


def split_rule(rule: str) -> tuple[str, str | None] | None:
    m = RULE_RE.match(rule.strip()) if isinstance(rule, str) else None
    return (m.group("tool"), m.group("spec")) if m else None


def trailing_wildcard(spec: str) -> tuple[str, str | None]:
    """(prefix, kind) where kind is 'space' (' *'), 'colon' (':*'), 'glued' ('x*') or None."""
    s = spec.strip()
    if s.endswith(":*"):
        return s[:-2].rstrip(), "colon"
    if s.endswith(" *"):
        return s[:-2].rstrip(), "space"
    if s.endswith("*") and "*" not in s[:-1]:
        return s[:-1], "glued"
    return s, None


def covers(a: str, b: str) -> bool:
    """True if rule a matches everything rule b matches (a != b)."""
    if a == b:
        return False
    pa, pb = split_rule(a), split_rule(b)
    if not pa or not pb:
        return False
    ta, sa = pa
    tb, sb = pb
    if ta.startswith("mcp__") and tb.startswith("mcp__") and sa is None and sb is None:
        base = ta[:-1] if ta.endswith("*") else ta + "__"
        return tb.startswith(base) and ta.count("__") <= 2
    if ta != tb:
        return False
    if sa is None or sa.strip() in ("*", ":*"):
        return True
    if sb is None or ta not in SHELL_TOOLS:
        return False
    prefix_a, kind_a = trailing_wildcard(sa)
    if kind_a is None or "*" in prefix_a:
        return False
    prefix_b, _ = trailing_wildcard(sb)
    if kind_a == "glued":
        return prefix_b.startswith(prefix_a)
    return prefix_b == prefix_a or prefix_b.startswith(prefix_a + " ")


def command_of(rule: str) -> str | None:
    """Command prefix of a Bash/PowerShell rule, without rtk and trailing wildcard."""
    parsed = split_rule(rule)
    if not parsed or parsed[0] not in SHELL_TOOLS or not parsed[1]:
        return None
    cmd, _ = trailing_wildcard(parsed[1])
    return cmd[4:] if cmd.startswith("rtk ") else cmd


def matches_prefix(rule: str, prefixes: list[str]) -> str | None:
    cmd = command_of(rule)
    if cmd is None:
        return None
    for p in prefixes:
        if cmd == p or cmd.startswith(p + " ") or cmd.startswith(p + ":"):
            return p
    return None


def rtk_wrap(rule: str, exempt: list[str]) -> str:
    parsed = split_rule(rule)
    if not parsed or parsed[0] != "Bash" or not parsed[1]:
        return rule
    spec = parsed[1].strip()
    first = re.split(r"[\s:]", spec, maxsplit=1)[0]
    if not first or first in exempt or first.startswith("*") or spec.startswith("rtk "):
        return rule
    return f"Bash(rtk {spec})"


def rtk_twin(rule: str, exempt: list[str]) -> str | None:
    parsed = split_rule(rule)
    if not parsed or parsed[0] != "Bash" or not parsed[1]:
        return None
    spec = parsed[1].strip()
    if spec.startswith("rtk "):
        return f"Bash({spec[4:]})"
    first = re.split(r"[\s:]", spec, maxsplit=1)[0]
    if not first or first in exempt or first.startswith("*"):
        return None
    return f"Bash(rtk {spec})"


def dedupe(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    return [x for x in seq if not (x in seen or seen.add(x))]  # type: ignore[func-returns-value]


def repair_rule(
    rule: Any, key: str, scope: str, path: Path, rep: Report, policy: dict
) -> str | None:
    """Normalize one rule; report each repair. Returns the new rule or None to drop it."""

    def note(level: str, code: str, msg: str, fixable: bool = True) -> None:
        rep.add(level, code, path, f"{key}: {msg}", fixable)
        log(2, f"{key}: {msg}", 2)

    if not isinstance(rule, str) or not rule.strip():
        note("error", "PERM_SYNTAX", f"non-string or empty rule {rule!r} (dropped)")
        return None
    r = rule.strip()

    # 1. loose syntax: "Tool: spec", "Tool spec", "tool(...)", unbalanced parenthesis
    m = LOOSE_RE.match(r)
    if not m:
        note("error", "PERM_SYNTAX", f"invalid rule {r!r} (dropped)")
        return None
    tool, spec_p, closed, spec_colon, spec_space = m.groups()
    if spec_p is not None and closed is None and not spec_p.strip():
        note(
            "error", "PERM_SYNTAX", f"{r!r} has an unbalanced parenthesis; intent unknown (dropped)"
        )
        return None
    spec = spec_p if spec_p is not None else (spec_colon or spec_space)
    if not tool.startswith("mcp__") and "*" not in tool:
        tool = _TOOL_CASE.get(tool.lower(), tool)
    fixed = tool if spec is None else f"{tool}({spec.strip()})"
    if fixed != r:
        note("warn", "PERM_SYNTAX", f"{r!r} rewritten as {fixed!r}")
    r = fixed
    tool, spec = split_rule(r) or (tool, spec)

    # 2. legacy tool names
    if tool in LEGACY_TOOLS and not (tool == "MultiEdit" and spec):
        new_tool = LEGACY_TOOLS[tool]
        new = new_tool if spec is None else f"{new_tool}({spec})"
        note("warn", "PERM_LEGACY_TOOL", f"{r!r} uses legacy tool {tool!r}; rewritten as {new!r}")
        r, tool = new, new_tool

    # 3. MCP rules with parentheses are skipped at load
    if tool.startswith("mcp__") and spec is not None:
        note("error", "PERM_MCP_PARENS", f"{r!r} is skipped by Claude Code (dropped)")
        return None

    # 4. parameter rules on a primary field are ignored
    if (
        spec is not None
        and (pm := re.match(r"^\s*(\w+)\s*:(.*)$", spec))
        and pm.group(1) in PRIMARY_PARAMS
    ):
        value = pm.group(2).strip()
        if tool == "WebFetch":
            host = urlparse(value if "://" in value else "https://" + value).hostname or value
            new = f"WebFetch(domain:{host})"
        else:
            new = f"{tool}({value})" if value else tool
        note(
            "error", "PERM_PRIMARY_PARAM", f"{r!r} is ignored by Claude Code; rewritten as {new!r}"
        )
        r, spec = new, (split_rule(new) or (tool, None))[1]

    # 5. path rules on tools whose path rules are never consulted
    if tool in PATH_TOOL_REMAP and spec:
        new_tool = PATH_TOOL_REMAP[tool]
        new = f"{new_tool}({spec})"
        note("warn", "PERM_PATH_TOOL", f"{r!r} is never consulted; rewritten as {new!r}")
        r, tool = new, new_tool

    # 6. WebFetch needs domain:
    if (
        tool == "WebFetch"
        and spec
        and not spec.startswith("domain:")
        and not re.match(r"^\s*\w+\s*:(?!//)", spec)
    ):
        host = urlparse(spec if "://" in spec else "https://" + spec).hostname
        if host:
            new = f"WebFetch(domain:{host})"
            note("warn", "PERM_WEBFETCH", f"{r!r} rewritten as {new!r}")
            r, spec = new, f"domain:{host}"

    # 7. tools without specifier
    if (
        spec is not None
        and tool in KNOWN_TOOLS
        and tool not in SPECIFIER_TOOLS
        and not (key in ("deny", "ask") and re.match(r"^\s*\w+\s*:", spec))
    ):
        note(
            "warn", "PERM_NO_SPECIFIER", f"{r!r}: {tool} takes no specifier; rewritten as {tool!r}"
        )
        r, spec = tool, None

    # 8. ':*' in the middle is a literal colon
    if tool in SHELL_TOOLS and spec and re.search(r":\*(?=\s*\S)", spec):
        new_spec = re.sub(r"\s*:\*(?=\s*\S)", " *", spec)
        new = f"{tool}({new_spec})"
        note("error", "PERM_COLON_MID", f"{r!r} never matches; rewritten as {new!r}")
        r, spec = new, new_spec

    # 9. path anchors
    if tool in ("Read", "Edit") and spec and spec.startswith("/") and not spec.startswith("//"):
        first = spec.lstrip("/").split("/", 1)[0]
        if first in ABS_ROOTS:
            new = f"{tool}(/{spec})"
            note(
                "warn",
                "PERM_ABS_PATH",
                f"{r!r} anchors at the settings source; rewritten as {new!r}",
            )
            r, spec = new, "/" + spec
        elif scope == "user":
            note(
                "info",
                "PERM_USER_ANCHOR",
                f"{r!r} resolves under ~/.claude/ in user settings",
                False,
            )

    # 10. unknown tools / unanchored globs
    if "*" in tool:
        anchored = re.match(r"^mcp__[^*_][^*]*?__", tool)
        if key == "allow" and not anchored:
            note("warn", "PERM_UNANCHORED_GLOB", f"{r!r} is skipped for allow rules (dropped)")
            return None
    elif not tool.startswith("mcp__") and tool not in KNOWN_TOOLS | RULE_ONLY_TOOLS:
        note("warn", "PERM_UNKNOWN_TOOL", f"unknown tool {tool!r} in {r!r}", False)

    # 11. trailing wildcard style
    style = policy["permissions"].get("rule_style", "keep")
    if tool in SHELL_TOOLS and spec and style in ("space", "colon"):
        prefix, kind = trailing_wildcard(spec)
        if kind in ("space", "colon") and kind != style:
            new = f"{tool}({prefix}{' *' if style == 'space' else ':*'})"
            note("info", "PERM_STYLE", f"{r!r} -> {new!r} (rule_style={style})")
            r = new
    return r


def optimize_permissions(
    perms: dict, policy: dict, path: Path, rep: Report, scope: str, sandbox_on: bool
) -> dict:
    pol = policy["permissions"]
    out = copy.deepcopy(perms)
    lists = {k: list(out.get(k, []) or []) for k in ("allow", "ask", "deny")}
    log(
        1,
        "permissions: "
        + ", ".join(f"{len(v)} {k}" for k, v in lists.items())
        + f", mode={out.get('defaultMode', 'default')}",
        1,
    )

    for key in lists:
        repaired = [repair_rule(r, key, scope, path, rep, policy) for r in lists[key]]
        repaired = [r for r in repaired if r]
        dup = len(repaired) - len(dedupe(repaired))
        if dup:
            rep.add("warn", "PERM_DUPLICATE", path, f"{key}: {dup} duplicate rule(s)", True)
        lists[key] = dedupe(repaired)
    allow, ask, deny = lists["allow"], lists["ask"], lists["deny"]

    mode = out.get("defaultMode")
    if mode in ("bypassPermissions", "auto") and scope == "project":
        rep.add(
            "warn", "PERM_MODE_DEAD", path, f"defaultMode={mode} has no effect here (removed)", True
        )
        out.pop("defaultMode")
    elif mode == "bypassPermissions":
        rep.add(
            "error",
            "PERM_BYPASS",
            path,
            "defaultMode=bypassPermissions disables every prompt; "
            'consider "disableBypassPermissionsMode": "disable"',
        )

    for r in list(allow):
        if r in pol["forbidden_allow"]:
            rep.add(
                "error",
                "PERM_TOO_BROAD",
                path,
                f"allow: {r!r} grants unrestricted execution (dropped)",
                True,
            )
            log(2, f"allow: drop {r}", 2)
            allow.remove(r)
    for r in allow:
        cmd = command_of(r)
        if cmd is None:
            continue
        parsed = split_rule(r)
        spec = (parsed[1] if parsed else None) or ""
        _, kind = trailing_wildcard(spec)
        via_rtk = spec.startswith("rtk ")
        runners = [x for x in pol["exec_runners"] if not (via_rtk and x == "env")]
        if via_rtk:
            runners += ["proxy", "test", "err", "summary"]  # rtk wrappers that run any command
        runner = next((x for x in runners if cmd == x), None)
        if runner and kind:
            rep.add(
                "warn",
                "PERM_EXEC_RUNNER",
                path,
                f"allow: {r!r} allows any command run through {runner!r}; list exact inner "
                f"commands",
            )
        tokens = cmd.split()
        if tokens and (tokens[0].startswith("*") or (len(tokens) >= 2 and "*" in tokens[1])):
            rep.add(
                "warn",
                "PERM_WILDCARD_EARLY",
                path,
                f"allow: {r!r} has a wildcard before the subcommand",
            )
    for r in list(allow):
        hit = matches_prefix(r, pol["external_action_prefixes"])
        if hit:
            rep.add(
                "warn",
                "PERM_EXTERNAL_ACTION",
                path,
                f"allow: {r!r} is an external action ({hit}); moved to 'ask'",
                True,
            )
            log(2, f"allow -> ask: {r}", 2)
            allow.remove(r)
            if r not in ask:
                ask.append(r)

    if pol["require_rtk"]:
        unwrapped = []
        for r in allow:
            parsed = split_rule(r) or ("", None)
            spec = parsed[1] or ""
            if parsed[0] == "Bash" and spec.startswith("rtk "):
                inner = trailing_wildcard(spec[4:])[0]
                if (
                    inner.split()
                    and inner.split()[0] not in pol["rtk_exempt"]
                    and rtk_authoritative()
                    and inner.split()[0] not in RTK_NATIVE
                    and not rtk_rewrites(inner)
                ):
                    plain = f"Bash({spec[4:]})"
                    rep.add(
                        "warn",
                        "RTK_DEAD_RULE",
                        path,
                        f"allow: {r!r} never matches (rtk does not rewrite "
                        f"{inner.split()[0]!r}); rewritten as {plain!r}",
                        True,
                    )
                    unwrapped.append(plain)
                    continue
            unwrapped.append(r)
        allow[:] = dedupe(unwrapped)
        wrapped = [
            rtk_wrap(r, pol["rtk_exempt"]) if (c := command_of(r)) is None or rtk_rewrites(c) else r
            for r in allow
        ]
        changed = [(a, b) for a, b in zip(allow, wrapped) if a != b]
        for a, b in changed:
            log(2, f"rtk: {a} -> {b}", 2)
        if changed:
            rep.add(
                "warn",
                "PERM_RTK",
                path,
                f"allow: {len(changed)} Bash rule(s) not routed through rtk",
                True,
            )
        allow[:] = dedupe(wrapped)
    else:
        redundant = [
            r
            for r in allow
            if (c := command_of(r))
            and c.split()[0] in READONLY_BUILTINS
            and not ((split_rule(r) or ("", None))[1] or "").startswith("rtk ")
        ]
        if redundant:
            rep.add(
                "info",
                "PERM_READONLY",
                path,
                "allow: built-in read-only commands need no rule: " + ", ".join(redundant[:5]),
                True,
            )
            allow[:] = [r for r in allow if r not in redundant]

    for r in list(allow):
        by = next((d for d in deny if d == r or covers(d, r)), None)
        if by:
            rep.add(
                "warn",
                "PERM_DEAD_ALLOW",
                path,
                f"allow: {r!r} can never apply (denied by {by!r}; removed)",
                True,
            )
            allow.remove(r)
            continue
        by = next((a for a in ask if covers(a, r)), None)
        if by:
            rep.add(
                "info", "PERM_ASK_SHADOW", path, f"allow: {r!r} still prompts because of ask {by!r}"
            )

    for key, rules in (("allow", allow), ("ask", ask), ("deny", deny)):
        shadowed = [
            b
            for b in rules
            if not b.split("(", 1)[-1].startswith("!") and any(covers(a, b) for a in rules)
        ]
        if shadowed:
            rep.add(
                "info",
                "PERM_SHADOWED",
                path,
                f"{key}: {len(shadowed)} rule(s) covered by broader ones: "
                + ", ".join(shadowed[:5])
                + (" ..." if len(shadowed) > 5 else ""),
                True,
            )
            for b in shadowed:
                log(2, f"{key}: drop {b} (covered by {next(a for a in rules if covers(a, b))})", 2)
            rules[:] = [r for r in rules if r not in shadowed]

    if scope == "project" and path.name == "settings.json":
        missing = [d for d in pol["required_deny"] if d not in deny]
        if missing:
            rep.add(
                "warn",
                "PERM_MISSING_DENY",
                path,
                "deny: sensitive paths not protected: " + ", ".join(missing),
                True,
            )
            positive = [d for d in missing if "(!" not in d]
            negative = [d for d in missing if "(!" in d]
            first_neg = next((i for i, d in enumerate(deny) if "(!" in d), len(deny))
            deny[first_neg:first_neg] = positive
            deny.extend(negative)

    if pol["require_rtk"] and pol.get("rtk_twin_deny", True):
        for key, rules in (("deny", deny), ("ask", ask)):
            twins = [t for r in rules if (t := rtk_twin(r, pol["rtk_exempt"])) and t not in rules]
            if twins:
                rep.add(
                    "warn",
                    "PERM_RTK_TWIN",
                    path,
                    f"{key}: add rtk/non-rtk twins: "
                    + ", ".join(twins[:4])
                    + (" ..." if len(twins) > 4 else ""),
                    True,
                )
                rules.extend(dedupe(twins))

    if not sandbox_on and any(command_of(d) in ("curl", "wget") for d in deny):
        rep.add(
            "info",
            "PERM_NET_DENY",
            path,
            "deny rules on curl/wget are not a network boundary; "
            "enable sandbox.network.allowedDomains",
        )

    for key, rules in (("allow", allow), ("ask", ask), ("deny", deny)):
        if rules:
            out[key] = rules
        else:
            out.pop(key, None)
    return out


# --------------------------------------------------------------------------- #
# Hooks
# --------------------------------------------------------------------------- #

PLACEHOLDER_RE = re.compile(r"^[\"']?\$\{?CLAUDE_(PROJECT_DIR|PLUGIN_ROOT|PLUGIN_DATA)\}?[\"']?")


def resolve_script(first: str, base: Path) -> Path | None:
    token = first.strip("\"'")
    token = re.sub(r"\$\{?CLAUDE_PROJECT_DIR\}?", str(base), token)
    if "$" in token:
        return None
    token = os.path.expanduser(token)
    if "/" not in token:
        return None
    p = Path(token)
    return p if p.is_absolute() else base / p


def to_exec_form(command: str, scope: str) -> tuple[str, list[str]] | None:
    """Split a simple shell-form command into exec form, anchoring relative paths."""
    body = PLACEHOLDER_RE.sub(lambda m: "${CLAUDE_" + m.group(1) + "}", command.strip())
    if SHELL_META.search(
        body.replace("${CLAUDE_PROJECT_DIR}", "")
        .replace("${CLAUDE_PLUGIN_ROOT}", "")
        .replace("${CLAUDE_PLUGIN_DATA}", "")
    ) or "$" in re.sub(r"\$\{CLAUDE_\w+\}", "", body):
        return None
    try:
        tokens = shlex.split(body)
    except ValueError:
        return None
    if not tokens:
        return None
    exe = tokens[0]
    if scope == "project" and "/" in exe and not exe.startswith(("/", "~", "$")):
        exe = "${CLAUDE_PROJECT_DIR}/" + exe.removeprefix("./")
    return exe, tokens[1:]


def check_matcher(event: str, matcher: Any, path: Path, rep: Report) -> Any:
    if matcher in (None, "", "*"):
        return matcher
    if event in NO_MATCHER_EVENTS:
        rep.add(
            "info",
            "HOOK_MATCHER_IGNORED",
            path,
            f"{event}: matcher {matcher!r} is ignored (removed)",
            True,
        )
        return None
    if not isinstance(matcher, str) or event not in TOOL_EVENTS:
        return matcher
    if re.fullmatch(r"[\w\s,|-]*", matcher):
        tokens = [t.strip() for t in re.split(r"[|,]", matcher) if t.strip()]
        fixed = []
        for t in tokens:
            if t.startswith("mcp__"):
                if t.count("__") == 1:
                    rep.add(
                        "warn",
                        "HOOK_MATCHER_MCP",
                        path,
                        f"{event}: {t!r} matches no tool; use {t}__.*",
                        True,
                    )
                    fixed.append(t + "__.*")
                    continue
            elif t in LEGACY_TOOLS:
                rep.add(
                    "warn",
                    "PERM_LEGACY_TOOL",
                    path,
                    f"{event}: matcher {t!r} renamed to {LEGACY_TOOLS[t]!r}",
                    True,
                )
                t = LEGACY_TOOLS[t]
            elif t not in KNOWN_TOOLS:
                rep.add(
                    "warn", "HOOK_MATCHER_TOOL", path, f"{event}: matcher {t!r} is not a tool name"
                )
            fixed.append(t)
        new = "|".join(dedupe(fixed))
        return new if new != "|".join(tokens) else matcher
    head = re.match(r"^([A-Z][A-Za-z]+)\.\*", matcher)
    if head and head.group(1) in KNOWN_TOOLS:
        rep.add(
            "info",
            "HOOK_MATCHER_REGEX",
            path,
            f"{event}: {matcher!r} is unanchored and also matches other tools",
        )
    return matcher


def check_handler(
    event: str, h: dict, base: Path, path: Path, rep: Report, scope: str
) -> dict | None:
    rep.stats["hook handlers"] = rep.stats.get("hook handlers", 0) + 1
    h = dict(h)
    htype = h.get("type")
    if htype is None and h.get("command"):
        rep.add(
            "warn", "HOOK_NO_TYPE", path, f"{event}: handler without 'type' (set to command)", True
        )
        h = {"type": "command", **h}
        htype = "command"
    if htype not in HOOK_TYPES:
        rep.add(
            "error", "HOOK_TYPE", path, f"{event}: unknown handler type {htype!r} (dropped)", True
        )
        return None
    missing = [f for f in HOOK_TYPES[htype] if not h.get(f)]
    if missing:
        rep.add(
            "error",
            "HOOK_SHAPE",
            path,
            f"{event}: {htype} handler missing {', '.join(missing)} (dropped)",
            True,
        )
        return None
    if "if" in h and event not in TOOL_EVENTS:
        rep.add(
            "error", "HOOK_IF_DEAD", path, f"{event}: handler with 'if' never runs on this event"
        )
    if "once" in h:
        rep.add(
            "warn", "HOOK_ONCE", path, f"{event}: 'once' is ignored in settings (removed)", True
        )
        h.pop("once")
    if "timeout" in h and not isinstance(h["timeout"], (int, float)):
        rep.add("error", "HOOK_SHAPE", path, f"{event}: timeout must be a number of seconds")

    if htype == "command":
        cmd = str(h["command"]).strip()
        if event == "PreToolUse" and h.get("async"):
            rep.add(
                "warn", "HOOK_ASYNC_GATE", path, f"{event}: async hook cannot block ({cmd[:40]})"
            )
        if event == "SessionStart" and re.search(
            r"\b(cat|type|Get-Content)\b.*\b(AGENTS|CLAUDE)\.md", cmd
        ):
            rep.add(
                "warn",
                "HOOK_DUP_CONTEXT",
                path,
                f"{event}: prints instruction files already loaded natively",
            )
        if "args" not in h:
            first = cmd.split()[0] if cmd.split() else ""
            relative = "/" in first and not first.strip("\"'").startswith(("/", "~", "$"))
            unquoted_ph = bool(re.match(r"^\$\{?CLAUDE_\w+\}?/", cmd))
            if relative or unquoted_ph:
                conv = to_exec_form(cmd, scope)
                if conv and scope == "project":
                    code = "HOOK_RELATIVE_PATH" if relative else "HOOK_EXEC_FORM"
                    rep.add(
                        "warn", code, path, f"{event}: {cmd[:60]!r} -> exec form {conv[0]!r}", True
                    )
                    h["command"], h["args"] = conv
                elif relative:
                    rep.add(
                        "warn",
                        "HOOK_RELATIVE_PATH",
                        path,
                        f"{event}: {cmd[:60]!r} depends on the current directory",
                    )
        script = resolve_script(
            str(h["command"]).split()[0] if "args" not in h else h["command"], base
        )
        if script is not None:
            if not script.exists():
                rep.add(
                    "error", "HOOK_MISSING_SCRIPT", path, f"{event}: script not found: {script}"
                )
            else:
                if not os.access(script, os.X_OK) and script not in rep.chmods:
                    rep.add(
                        "warn",
                        "HOOK_NOT_EXECUTABLE",
                        path,
                        f"{event}: {script} is not executable",
                        True,
                    )
                    rep.chmods.append(script)
                body = read_text(script) or ""
                if (
                    event == "PreToolUse"
                    and re.search(r"\bexit\s+1\b", body)
                    and not re.search(r"\bexit\s+2\b|permissionDecision|\"decision\"", body)
                ):
                    rep.add(
                        "warn",
                        "HOOK_EXIT1",
                        path,
                        f"{event}: {script.name} uses exit 1, which does not block",
                    )
        if (
            event in ("PreToolUse", "UserPromptSubmit")
            and not h.get("timeout")
            and not h.get("async")
            and not re.match(r"^rtk\b", cmd)
        ):
            rep.add(
                "info",
                "HOOK_TIMEOUT",
                path,
                f"{event}: no timeout (default 600s) on a gating hook ({cmd[:40]})",
            )
    elif htype == "http":
        allowed = list(h.get("allowedEnvVars") or [])
        for k, v in (h.get("headers") or {}).items():
            missing_vars = sorted(set(re.findall(r"\$\{?(\w+)\}?", str(v))) - set(allowed))
            if missing_vars:
                rep.add(
                    "error",
                    "HOOK_HTTP_ENV",
                    path,
                    f"{event}: header {k} uses {', '.join(missing_vars)} "
                    "without allowedEnvVars (added)",
                    True,
                )
                allowed += missing_vars
        if allowed:
            h["allowedEnvVars"] = dedupe(allowed)
        h["headers"] = check_env_secrets(
            h.get("headers") or {}, path, rep, f"hooks.{event}.headers"
        ) or h.get("headers")
        if not h["headers"]:
            h.pop("headers")
    elif htype == "mcp_tool" and event in ("SessionStart", "Setup"):
        rep.add("warn", "HOOK_MCP_LAUNCH", path, f"{event}: mcp_tool hook is skipped at launch")
    return h


def normalize_hook_entries(event: str, entries: Any, path: Path, rep: Report) -> list | None:
    def as_group(obj: Any) -> dict | None:
        if isinstance(obj, str):
            return {"hooks": [{"type": "command", "command": obj}]}
        if isinstance(obj, dict) and isinstance(obj.get("hooks"), list):
            return obj
        if isinstance(obj, dict) and (obj.get("command") or obj.get("type")):
            return {"hooks": [obj]}
        return None

    legacy = False
    groups: list[dict] = []
    if isinstance(entries, dict):
        legacy = True
        for matcher, cmds in entries.items():
            items = cmds if isinstance(cmds, list) else [cmds]
            hooks = [c if isinstance(c, dict) else {"type": "command", "command": c} for c in items]
            groups.append({"matcher": matcher, "hooks": hooks})
    elif isinstance(entries, str):
        legacy = True
        groups.append({"hooks": [{"type": "command", "command": entries}]})
    elif isinstance(entries, list):
        for g in entries:
            ng = as_group(g)
            if ng is None:
                rep.add("error", "HOOK_SHAPE", path, f"{event}: unusable hook group dropped", True)
                continue
            legacy |= ng is not g
            groups.append(ng)
    else:
        rep.add("error", "HOOK_SHAPE", path, f"{event}: expected a list of matcher groups")
        return None
    if legacy:
        rep.add("warn", "HOOK_LEGACY_FORMAT", path, f"{event}: legacy hook format converted", True)
        log(2, f"hooks.{event}: converted to {len(groups)} matcher group(s)", 2)
    return groups


def check_hooks(hooks: Any, base: Path, path: Path, rep: Report, scope: str) -> Any:
    if not isinstance(hooks, dict):
        rep.add("error", "HOOK_SHAPE", path, "hooks must be an object keyed by event name")
        return hooks
    log(
        1,
        "hooks: "
        + ", ".join(
            f"{e}({len(v) if isinstance(v, (list, dict)) else 1})" for e, v in hooks.items()
        ),
        1,
    )
    fixed: dict[str, Any] = {}
    for event, raw in hooks.items():
        if event not in KNOWN_HOOK_EVENTS:
            rep.add("warn", "HOOK_EVENT", path, f"unknown hook event {event!r}")
        groups = normalize_hook_entries(event, raw, path, rep)
        if groups is None:
            fixed[event] = raw
            continue
        out_groups = []
        for g in groups:
            g = dict(g)
            if "matcher" in g:
                m = check_matcher(event, g["matcher"], path, rep)
                if m is None:
                    g.pop("matcher")
                else:
                    g["matcher"] = m
            handlers = [
                h2
                for h in g["hooks"]
                if isinstance(h, dict) and (h2 := check_handler(event, h, base, path, rep, scope))
            ]
            if handlers:
                out_groups.append({**g, "hooks": handlers})
        if out_groups:
            fixed[event] = out_groups
    return fixed


# --------------------------------------------------------------------------- #
# Secrets, settings.json
# --------------------------------------------------------------------------- #


def check_env_secrets(env: dict, path: Path, rep: Report, ctx: str, mode: str = "report") -> dict:
    """mode: report | reference (-> ${VAR}) | remove."""
    out = dict(env or {})
    for k, v in (env or {}).items():
        if not isinstance(v, str):
            continue
        bare = re.sub(r"^(bearer|token|basic)\s+", "", v, flags=re.I)
        if bare.startswith("$"):
            continue
        if any(p.search(bare) for p in SECRET_VALUE_PATTERNS) or (
            SECRET_KEY_RE.search(k) and len(bare) >= 12
        ):
            var = re.sub(r"[^A-Z0-9]+", "_", k.upper()).strip("_")
            if k.lower() == "authorization" and "." in ctx:
                var = re.sub(r"[^A-Z0-9]+", "_", ctx.split(".")[1].upper()) + "_TOKEN"
            if mode == "reference":
                prefix = (
                    v.split(" ")[0] + " "
                    if v.lower().startswith(("bearer ", "token ", "basic "))
                    else ""
                )
                out[k] = f"{prefix}${{{var}}}"
                action = f"replaced by {out[k]}; export {var} (or inject it from the vault)"
            elif mode == "remove":
                out.pop(k)
                action = f"removed; export {var} in your shell profile or inject it from the vault"
            else:
                action = "reference an env var or the vault instead"
            rep.add(
                "error" if mode != "report" or ".claude.json" not in str(path) else "warn",
                "SECRET_INLINE",
                path,
                f"{ctx}: {k} holds a literal secret; {action}",
                mode != "report",
            )
    return out


def check_settings(path: Path, base: Path, scope: str, policy: dict, rep: Report) -> dict | None:
    raw = read_text(path)
    if raw is None:
        log(2, f"{path}: absent", 1)
        return None
    log(1, f"{path} ({len(raw)} bytes)", 1)
    rep.stats["settings files"] = rep.stats.get("settings files", 0) + 1
    try:
        data, repaired = lenient_json(raw)
    except json.JSONDecodeError as e:
        rep.add("error", "JSON_INVALID", path, f"invalid JSON, not auto-repairable: {e}")
        return None
    if repaired:
        rep.add(
            "error", "JSON_REPAIRED", path, "comments, trailing commas or BOM in strict JSON", True
        )
    if not isinstance(data, dict):
        rep.add("error", "JSON_INVALID", path, "top level must be an object")
        return None
    log(2, "keys: " + (", ".join(data) or "(none)"), 2)
    new = copy.deepcopy(data)
    local = path.name == "settings.local.json"

    for k in data:
        if k not in KNOWN_SETTINGS_KEYS and k != "mcpServers":
            rep.add(
                "info",
                "SETTINGS_UNKNOWN_KEY",
                path,
                f"unrecognised key {k!r} (schema may be newer)",
            )
        if scope == "project" and k in PROJECT_DEAD_KEYS:
            rep.add("warn", "SETTINGS_DEAD_KEY", path, f"{k}: {PROJECT_DEAD_KEYS[k]}")
    plugin_cfg = (
        (data.get("pluginConfigs") or {}).get("agents-md@builtin")
        if isinstance(data.get("pluginConfigs"), dict)
        else None
    )
    if scope == "project" and plugin_cfg:
        rep.add(
            "warn",
            "SETTINGS_DEAD_KEY",
            path,
            "pluginConfigs.agents-md@builtin is ignored in project/local settings",
        )

    if not local and "$schema" not in new:
        rep.add("info", "SETTINGS_SCHEMA", path, "no $schema (added)", True)
        new = {"$schema": policy["scaffold"]["schema_url"], **new}

    attr = new.get("attribution")
    if "includeCoAuthoredBy" in new:
        rep.add(
            "warn",
            "ATTR_DEPRECATED",
            path,
            "includeCoAuthoredBy is deprecated (migrated to attribution)",
            True,
        )
        new.pop("includeCoAuthoredBy")
        attr = attr if isinstance(attr, dict) else {}
    if not local:
        wanted = {"commit": "", "pr": ""}
        if (
            not isinstance(attr, dict)
            or any(attr.get(k) not in ("", None) for k in wanted)
            or not all(k in attr for k in wanted)
        ) and (scope == "user" or attr is not None):
            rep.add(
                "warn", "ATTR_ENABLED", path, "attribution not fully disabled (commit/pr)", True
            )
            new["attribution"] = {**(attr if isinstance(attr, dict) else {}), **wanted}

    if scope == "project" and new.get("disableAllHooks") is True:
        rep.add(
            "warn",
            "SETTINGS_DISABLE_HOOKS",
            path,
            "disableAllHooks=true silences every hook, guards included",
        )
    if scope == "project" and not local and new.get("enableAllProjectMcpServers") is True:
        rep.add(
            "warn", "SETTINGS_MCP_AUTO", path, "enableAllProjectMcpServers=true in a committed file"
        )

    sandbox_on = isinstance(new.get("sandbox"), dict) and bool(new["sandbox"].get("enabled"))
    if isinstance(new.get("permissions"), dict):
        rep.stats["permission rules"] = rep.stats.get("permission rules", 0) + sum(
            len(new["permissions"].get(k) or []) for k in ("allow", "ask", "deny")
        )
        new["permissions"] = optimize_permissions(
            new["permissions"], policy, path, rep, scope, sandbox_on
        )
        if not new["permissions"]:
            new.pop("permissions")

    if "hooks" in new:
        new["hooks"] = check_hooks(new["hooks"], base, path, rep, scope)
        if (
            scope == "user"
            and policy["user_scope"]["context_only"]
            and isinstance(new["hooks"], dict)
        ):
            blocking = [
                e
                for e, groups in new["hooks"].items()
                if e in ("PreToolUse", "UserPromptSubmit", "Stop")
                and not all(
                    re.search(
                        r"\brtk\b",
                        " ".join([str(h.get("command", "")), *map(str, h.get("args") or [])]),
                    )
                    for g in groups
                    if isinstance(g, dict)
                    for h in g.get("hooks", [])
                    if isinstance(h, dict)
                )
            ]
            if blocking:
                rep.add(
                    "warn",
                    "USER_SCOPE_HOOKS",
                    path,
                    f"blocking hooks at user scope: {', '.join(blocking)}",
                )
        if not new["hooks"]:
            new.pop("hooks")

    check_helpers(new, base, path, rep, scope)
    check_plugin_settings(new, path, rep, scope)
    new = move_settings_mcp(new, base, path, rep, scope)

    if isinstance(new.get("env"), dict):
        new["env"] = check_env_secrets(new["env"], path, rep, "env", "remove")
        if not new["env"] and data.get("env"):
            new.pop("env")

    if local and scope == "project" and (base / ".git").exists():
        rel = str(path.relative_to(base))
        tracked = is_tracked(base, rel)
        if tracked:
            rep.add(
                "warn",
                "LOCAL_NOT_IGNORED",
                path,
                f"{rel} is committed: run git rm --cached {rel} (its allow rules then wait "
                f"for trust)",
            )
        elif not is_ignored(base, rel):
            rep.add("warn", "LOCAL_NOT_IGNORED", path, f"{rel} is not gitignored", True)
            add_gitignore(base, ".claude/settings.local.json", rep)

    new_text = dump_json(new)
    if new != data or repaired or (new_text != raw and raw.strip() != new_text.strip()):
        if new == data and not repaired:
            rep.add("info", "JSON_FORMAT", path, "non-canonical formatting", True)
        rep.edit(path, raw, new_text)
    return new


# --------------------------------------------------------------------------- #
# MCP configuration
# --------------------------------------------------------------------------- #


def check_servers(servers: dict, path: Path, rep: Report, ctx: str, writable: bool) -> dict:
    out = {}
    for name, cfg in servers.items():
        rep.stats["MCP servers"] = rep.stats.get("MCP servers", 0) + 1
        if not isinstance(cfg, dict) or not (cfg.get("command") or cfg.get("url")):
            rep.add("error", "MCP_SHAPE", path, f"{ctx}.{name}: needs 'command' or 'url'")
            out[name] = cfg
            continue
        cfg = dict(cfg)
        kind = cfg.get("type") or ("http" if cfg.get("url") else "stdio")
        log(
            2,
            f"{name}: {kind} {cfg.get('url') or cfg.get('command')}, "
            f"{len(cfg.get('env') or {})} env var(s)",
            2,
        )
        if cfg.get("url") and "type" not in cfg:
            rep.add(
                "warn", "MCP_TYPE", path, f"{ctx}.{name}: url without type (set to http)", writable
            )
            if writable:
                cfg = {"type": "http", **cfg}
        elif cfg.get("type") == "sse":
            rep.add("info", "MCP_SSE", path, f"{ctx}.{name}: SSE transport is deprecated")
        elif cfg.get("type") not in (None, "stdio", "http", "sse", "ws"):
            rep.add("error", "MCP_TYPE", path, f"{ctx}.{name}: unknown type {cfg.get('type')!r}")
        if (
            cfg.get("command")
            and " " in str(cfg["command"]).strip()
            and not cfg.get("args")
            and not os.path.exists(str(cfg["command"]))
        ):
            parts = shlex.split(str(cfg["command"]))
            rep.add(
                "warn",
                "MCP_COMMAND_ARGS",
                path,
                f"{ctx}.{name}: command contains arguments (split into args)",
                writable,
            )
            if writable:
                cfg["command"], cfg["args"] = parts[0], parts[1:]
        mode = "reference" if writable else "report"
        for sect in ("env", "headers"):
            if isinstance(cfg.get(sect), dict):
                cfg[sect] = check_env_secrets(cfg[sect], path, rep, f"{ctx}.{name}.{sect}", mode)
        for a in cfg.get("args", []) or []:
            if isinstance(a, str) and any(p.search(a) for p in SECRET_VALUE_PATTERNS):
                rep.add(
                    "error",
                    "SECRET_INLINE",
                    path,
                    f"{ctx}.{name}: literal secret in args (move it to env)",
                )
        out[name] = cfg
    return out


def check_mcp(path: Path, rep: Report, policy: dict) -> None:
    raw = read_text(path)
    if raw is None:
        log(2, f"{path}: absent", 1)
        return
    log(1, f"{path}", 1)
    try:
        data, repaired = lenient_json(raw)
    except json.JSONDecodeError as e:
        rep.add("error", "JSON_INVALID", path, f"invalid JSON, not auto-repairable: {e}")
        return
    if repaired:
        rep.add(
            "error", "JSON_REPAIRED", path, "comments, trailing commas or BOM in strict JSON", True
        )
    if not isinstance(data, dict):
        rep.add("error", "MCP_SHAPE", path, "top level must be an object")
        return
    new = copy.deepcopy(data)
    if (
        "mcpServers" not in data
        and data
        and all(isinstance(v, dict) and (v.get("command") or v.get("url")) for v in data.values())
    ):
        rep.add(
            "warn",
            "MCP_MISPLACED",
            path,
            "servers declared at top level (moved under mcpServers)",
            True,
        )
        new = {"mcpServers": copy.deepcopy(data)}
    servers = new.get("mcpServers")
    if not isinstance(servers, dict):
        rep.add("error", "MCP_SHAPE", path, "missing 'mcpServers' object")
        return
    log(1, f"{len(servers)} MCP server(s): " + ", ".join(servers), 2)
    if len(servers) > policy["mcp"]["max_servers"]:
        rep.add("warn", "MCP_TOO_MANY", path, f"{len(servers)} servers; each one costs context")
    new["mcpServers"] = check_servers(servers, path, rep, "mcpServers", True)
    if new != data or repaired:
        rep.edit(path, raw, dump_json(new))


def check_claude_json(rep: Report, repos: list[Path]) -> None:
    """~/.claude.json is written by Claude Code itself: validate, never edit."""
    path = Path(os.path.expanduser("~/.claude.json"))
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        path = config_dir() / ".claude.json"
    raw = read_text(path)
    if raw is None:
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        rep.add(
            "error", "JSON_INVALID", path, f"invalid JSON ({e}); restore from ~/.claude/backups/"
        )
        return
    log(1, f"{path} (read-only)", 1)
    if isinstance(data.get("mcpServers"), dict):
        check_servers(data["mcpServers"], path, rep, "mcpServers", False)
    for proj, cfg in (data.get("projects") or {}).items():
        if isinstance(cfg, dict) and isinstance(cfg.get("mcpServers"), dict) and cfg["mcpServers"]:
            if not repos or any(str(r) == proj for r in repos):
                check_servers(cfg["mcpServers"], path, rep, f"projects[{proj}].mcpServers", False)


# --------------------------------------------------------------------------- #
# Instruction files, rules, auto memory
# --------------------------------------------------------------------------- #

IMPORT_RE = re.compile(r"(?<![\w@`])@((?:~/|\.{1,2}/|/)?[\w.\-/]+[\w/])")


def import_targets(path: Path, text: str) -> list[tuple[str, Path]]:
    refs = []
    for m in IMPORT_RE.finditer(strip_html_comments(strip_code(text))):
        ref = m.group(1)
        target = Path(os.path.expanduser(ref))
        if not target.is_absolute():
            target = path.parent / target
        explicit = ref.startswith(("~/", "./", "../", "/")) or re.search(r"\.\w{1,6}$", ref)
        if target.exists() or explicit:
            refs.append((ref, target))
    return refs


def check_imports(
    path: Path,
    text: str,
    rep: Report,
    policy: dict,
    root: Path | None,
    depth: int = 1,
    seen: set | None = None,
) -> None:
    seen = seen if seen is not None else {path.resolve()}
    for ref, target in import_targets(path, text):
        log(2, f"import @{ref} (depth {depth})", 2)
        if not target.exists():
            rep.add("error", "IMPORT_MISSING", path, f"@{ref} does not resolve")
            continue
        if depth > policy["instructions"]["max_import_depth"]:
            rep.add(
                "error", "IMPORT_DEPTH", path, f"@{ref} is {depth} hops deep (max 4): not loaded"
            )
            continue
        if root is not None:
            try:
                target.resolve().relative_to(root.resolve())
            except ValueError:
                rep.add(
                    "info",
                    "IMPORT_EXTERNAL",
                    path,
                    f"@{ref} is outside the project (approval prompt)",
                )
        resolved = target.resolve()
        if resolved in seen or target.is_dir():
            continue
        seen.add(resolved)
        sub = read_text(target)
        if sub:
            check_imports(target, sub, rep, policy, root, depth + 1, seen)


def check_instruction_file(
    path: Path, scope: str, policy: dict, rep: Report, root: Path | None
) -> str | None:
    try:
        size = path.stat().st_size
    except OSError:
        log(2, f"{path}: absent", 1)
        return None
    if size > 4 * 1024 * 1024:
        rep.add("error", "INSTR_TOO_LARGE", path, f"{size} bytes: skipped entirely by Claude Code")
        return None
    text = read_text(path)
    if text is None:
        return None
    rep.stats["instruction files"] = rep.stats.get("instruction files", 0) + 1
    pol = policy["instructions"]
    effective = strip_html_comments(text)
    lines, tokens = effective.count("\n") + 1, len(effective.encode()) // 4
    log(1, f"{path}: {lines} lines, ~{tokens} tokens (HTML comments excluded)", 1)
    if scope == "user" and lines > pol["user_max_lines"]:
        rep.add(
            "warn",
            "INSTR_USER_TOO_LONG",
            path,
            f"{lines} lines (~{tokens} tokens) in every session",
        )
    elif lines > pol["project_warn_lines"] or tokens > pol["warn_tokens"]:
        rep.add("warn", "INSTR_LONG", path, f"{lines} lines (~{tokens} tokens)")
    check_imports(path, text, rep, policy, root)
    return text


def check_agents_md(repo: Path, policy: dict, rep: Report) -> None:
    agents = next((p for p in (repo / "AGENTS.md", repo / ".claude/AGENTS.md") if p.exists()), None)
    claude = next((p for p in (repo / "CLAUDE.md", repo / ".claude/CLAUDE.md") if p.exists()), None)
    local = repo / "CLAUDE.local.md"
    doctrine = (repo / policy["instructions"]["doctrine_dir"]).is_dir()
    marker = policy["instructions"]["generated_marker"]
    if local.exists() and (repo / ".git").exists():
        if is_tracked(repo, "CLAUDE.local.md"):
            rep.add(
                "warn",
                "LOCAL_MD_NOT_IGNORED",
                local,
                "CLAUDE.local.md is committed: git rm --cached CLAUDE.local.md",
            )
        elif not is_ignored(repo, "CLAUDE.local.md"):
            rep.add(
                "warn", "LOCAL_MD_NOT_IGNORED", local, "CLAUDE.local.md is not gitignored", True
            )
            add_gitignore(repo, "CLAUDE.local.md", rep)
    if not agents:
        return
    if claude is None:
        if local.exists():
            rep.add(
                "warn",
                "AGENTS_SHADOWED_LOCAL",
                repo,
                "CLAUDE.local.md stops AGENTS.md from loading (CLAUDE.md importing it created)",
                SCAFFOLD,
            )
            if SCAFFOLD:
                rep.new_files[repo / "CLAUDE.md"] = ("@AGENTS.md\n", 0o644)
        elif CLI_VERSION and CLI_VERSION < (2, 1, 277):
            rep.add(
                "warn",
                "AGENTS_OLD_CLI",
                repo,
                f"claude {'.'.join(map(str, CLI_VERSION))} does not read AGENTS.md",
            )
        return
    if claude.is_symlink():
        rep.add("info", "AGENTS_SYMLINK", claude, "CLAUDE.md is a symlink")
        return
    text = read_text(claude) or ""
    rel = os.path.relpath(agents, claude.parent)
    imports = {ref for ref, _ in import_targets(claude, text)}
    if rel in imports or "AGENTS.md" in imports or f"./{rel}" in imports:
        return
    if doctrine or marker in "\n".join(text.splitlines()[:5]):
        return  # both are renders of the same source
    code = "AGENTS_MENTION" if "AGENTS.md" in text else "AGENTS_IGNORED"
    rep.add("warn", code, claude, f"AGENTS.md is not imported (added @{rel} at the top)", True)
    rep.edit(claude, text, f"@{rel}\n\n{text}")


def check_rendered(repo: Path, policy: dict, rep: Report) -> None:
    pol = policy["instructions"]
    if not (repo / pol["doctrine_dir"]).is_dir():
        return
    for rel in pol["rendered_files"]:
        f = repo / rel
        head = "\n".join((read_text(f) or "").splitlines()[:5])
        if f.exists() and pol["generated_marker"] not in head and head.strip() != "@AGENTS.md":
            rep.add(
                "warn",
                "RENDER_HAND_EDITED",
                f,
                f"no '{pol['generated_marker']}' header: hand-edited render",
            )


def check_rules(root: Path, rep: Report, project_root: Path | None) -> None:
    rules = root / "rules"
    if not rules.is_dir():
        return
    files = sorted(rules.rglob("*.md"))
    log(1, f"{rules}: {len(files)} rule file(s)", 1)
    for f in files:
        rep.stats["rules"] = rep.stats.get("rules", 0) + 1
        if f.is_symlink() and project_root is not None:
            try:
                f.resolve().relative_to(project_root.resolve())
            except ValueError:
                rep.add("info", "RULE_EXTERNAL", f, "symlinked outside the project")
        text = read_text(f) or ""
        meta, offset = split_frontmatter(text)
        if meta is None:
            rep.add("info", "RULE_UNSCOPED", f, "no 'paths': loads in every session")
            continue
        new = text
        if offset:
            rep.add(
                "warn",
                "FRONTMATTER_OFFSET",
                f,
                "frontmatter not on line 1 (leading lines removed)",
                True,
            )
            new = text.lstrip("\ufeff \t\r\n")
        renames = {k: RULE_TYPOS[k] for k in meta if k in RULE_TYPOS and "paths" not in meta}
        if renames:
            rep.add("warn", "RULE_FIELD", f, f"{', '.join(renames)} renamed to 'paths'", True)
            new = set_frontmatter(new, {}, renames)
        ignored = [k for k in meta if k != "paths" and k not in renames]
        if ignored:
            rep.add("info", "RULE_FIELD", f, f"ignored field(s): {', '.join(ignored)}")
        block = frontmatter_block(new)
        for pat in re.findall(r"[\"']([^\"']+)[\"']", block):
            if pat.count("[") != pat.count("]") and "\\[" not in pat:
                rep.add(
                    "error",
                    "RULE_PATTERN",
                    f,
                    f"pattern {pat!r} has an unbalanced '[': matches nothing",
                )
        if "paths" not in meta and not renames:
            rep.add("info", "RULE_UNSCOPED", f, "no 'paths': loads in every session")
        if new != text:
            rep.edit(f, text, new)


def check_auto_memory(cfg: Path, policy: dict, rep: Report) -> None:
    proj = cfg / "projects"
    if not proj.is_dir():
        return
    pol = policy["memory"]
    for idx in sorted(proj.glob("*/memory/MEMORY.md")):
        try:
            size = idx.stat().st_size
        except OSError:
            continue
        lines = (read_text(idx) or "").count("\n") + 1
        if lines > pol["max_lines"] or size > pol["max_bytes"]:
            rep.add(
                "warn",
                "MEMORY_INDEX",
                idx,
                f"{lines} lines / {size} bytes: content past the limit is not loaded",
            )


# --------------------------------------------------------------------------- #
# Skills, agents, commands
# --------------------------------------------------------------------------- #


def frontmatter_values(text: str, key: str) -> list[str]:
    """Values of a top-level frontmatter key: inline list, scalar or '- item' block."""
    block = frontmatter_block(text).splitlines()
    for i, line in enumerate(block):
        m = re.match(rf"^{re.escape(key)}\s*:\s*(.*)$", line)
        if not m:
            continue
        val = m.group(1).strip()
        if val.startswith("["):
            return [v.strip().strip("'\"") for v in val.strip("[]").split(",") if v.strip()]
        if val:
            return [val.strip("'\"")]
        items = []
        for nxt in block[i + 1 :]:
            if re.match(r"^\s*-\s+", nxt):
                items.append(re.sub(r"^\s*-\s+", "", nxt).strip().strip("'\""))
            elif nxt.startswith((" ", "\t")):
                continue
            else:
                break
        return items
    return []


def move_to_metadata(text: str, keys: list[str]) -> str:
    """Move top-level frontmatter entries (with their indented continuation) under metadata:."""
    stripped = text.lstrip("\ufeff \t\r\n")
    end = stripped.find("\n---", 3)
    if not stripped.startswith("---") or end == -1:
        return text
    lines, body = stripped[3:end].strip("\n").splitlines(), stripped[end + 4 :]
    entries: list[list[str]] = []
    for line in lines:
        if entries and (
            line.startswith((" ", "\t"))
            or line.lstrip().startswith("- ")
            and not re.match(r"^[\w-]+\s*:", line)
        ):
            entries[-1].append(line)
        else:
            entries.append([line])
    keep, moved, meta_idx = [], [], None
    for e in entries:
        key = (re.match(r"^([\w-]+)\s*:", e[0]) or [None, None])[1]
        if key in keys:
            moved.append(e)
        else:
            if key == "metadata":
                meta_idx = len(keep)
            keep.append(e)
    if not moved:
        return text
    block = ["  " + l for e in moved for l in e]
    if meta_idx is None:
        keep.append(["metadata:"] + block)
    else:
        keep[meta_idx] = (
            [re.sub(r"^metadata\s*:.*$", "metadata:", keep[meta_idx][0])]
            + keep[meta_idx][1:]
            + block
        )
    return "---\n" + "\n".join(l for e in keep for l in e) + "\n---" + body


def check_skill(d: Path, policy: dict, rep: Report) -> str | None:
    rep.stats["skills"] = rep.stats.get("skills", 0) + 1
    pol = policy["skills"]
    name_re = re.compile(pol["name_pattern"])
    sk = d / "SKILL.md"
    if not sk.is_file():
        alt = next((f for f in d.iterdir() if f.is_file() and f.name.lower() == "skill.md"), None)
        if not alt:
            # A grouping directory (holds nested skill subdirs, e.g. gitnexus/gitnexus-cli/
            # or ui-styling/ui-styling/) is not itself a skill: don't flag it.
            try:
                if any((sub / "SKILL.md").is_file() for sub in d.iterdir() if sub.is_dir()):
                    return None
            except OSError:
                pass
            rep.add("error", "SKILL_MISSING", d, "directory without SKILL.md")
            return None
        rep.add("error", "SKILL_MISSING", d, f"{alt.name} must be named SKILL.md (copied)", True)
        rep.new_files[sk] = (read_text(alt) or "", 0o644)
    text = rep.current(sk) or ""
    meta, offset = split_frontmatter(text)
    new = text
    if offset:
        rep.add(
            "warn",
            "FRONTMATTER_OFFSET",
            sk,
            "frontmatter not on line 1 (leading lines removed)",
            True,
        )
        new = text.lstrip("\ufeff \t\r\n")
    if meta is None:
        meta = {}
    renames = {k: SKILL_TYPOS[k] for k in meta if k in SKILL_TYPOS and SKILL_TYPOS[k] not in meta}
    if renames:
        rep.add(
            "warn",
            "SKILL_FIELD",
            sk,
            "renamed: " + ", ".join(f"{a} -> {b}" for a, b in renames.items()),
            True,
        )
        meta = {renames.get(k, k): v for k, v in meta.items()}
    trig_key = next((k for k in ("triggers", "trigger") if k in meta), None)
    if trig_key and not meta.get("when_to_use"):
        phrases = frontmatter_values(new, trig_key)
        if phrases:
            updates_trig = "Use when the user says: " + "; ".join(phrases)
            rep.add(
                "info",
                "SKILL_FIELD",
                sk,
                f"{trig_key} is ignored by Claude Code (copied into when_to_use, original "
                f"kept under metadata)",
                True,
            )
            meta = {**meta, "when_to_use": updates_trig}
            pending_when = updates_trig
        else:
            pending_when = None
    else:
        pending_when = None
    unknown = [k for k in meta if k not in SKILL_FIELDS]
    move_meta: list[str] = []
    if pending_when:
        unknown = [k for k in unknown if k not in ("trigger", "triggers")] + [trig_key]
    if unknown:
        movable = [k for k in unknown if k not in ("trigger", "triggers") or pending_when]
        can_move = bool(movable) and ("metadata" not in meta or meta.get("metadata", "") == "")
        rep.add(
            "info",
            "SKILL_FIELD",
            sk,
            f"custom field(s) ignored by Claude Code: {', '.join(unknown)}"
            + (" (moved under metadata:)" if can_move else "")
            + (
                "; put trigger phrases in description or when_to_use"
                if len(movable) < len(unknown)
                else ""
            ),
            can_move,
        )
        if can_move:
            move_meta = movable
    if pol["portable"]:
        extra = [k for k in meta if k in SKILL_FIELDS and k not in SKILL_SPEC_FIELDS]
        if extra:
            rep.add(
                "info", "SKILL_PORTABILITY", sk, f"Claude Code-only field(s): {', '.join(extra)}"
            )
    updates: dict[str, str] = {}
    if pending_when:
        updates["when_to_use"] = pending_when
    name, desc = meta.get("name", ""), meta.get("description", "")
    dir_ok = bool(name_re.match(d.name))
    if name and name != d.name:
        rep.add(
            "info" if not pol["portable"] else "warn",
            "SKILL_NAME",
            sk,
            f"name {name!r} differs from directory {d.name!r} (the command is /{d.name})"
            + (" (aligned)" if dir_ok else ""),
            dir_ok,
        )
        if dir_ok:
            updates["name"] = d.name
    elif not name and pol["portable"] and dir_ok:
        rep.add(
            "info",
            "SKILL_NAME",
            sk,
            "no name (the spec requires one; set to the directory name)",
            True,
        )
        updates["name"] = d.name
    if not dir_ok:
        rep.add(
            "warn",
            "SKILL_NAME",
            d,
            f"directory {d.name!r} is not a valid skill name; rename to {slugify(d.name)!r}",
        )
    if not desc:
        derived = derive_description(new)
        rep.add(
            "warn",
            "SKILL_DESCRIPTION",
            sk,
            "no description" + (" (derived from body)" if derived else ""),
            bool(derived),
        )
        if derived:
            updates["description"] = desc = derived
    listing = len(desc) + len(meta.get("when_to_use", ""))
    if listing > pol["max_listing_chars"]:
        rep.add(
            "warn",
            "SKILL_DESCRIPTION",
            sk,
            f"description + when_to_use = {listing} chars (truncated at "
            f"{pol['max_listing_chars']})",
        )
    elif pol["portable"] and len(desc) > pol["portable_description_chars"]:
        rep.add(
            "info",
            "SKILL_PORTABILITY",
            sk,
            f"description {len(desc)} chars (> {pol['portable_description_chars']})",
        )
    body_lines = new.count("\n") + 1
    if body_lines > pol["max_lines"]:
        ro = "" if _writable(sk) else " (read-only: synced/symlinked store — edit it upstream)"
        rep.add("warn", "SKILL_LONG", sk, f"{body_lines} lines{ro}")
    if meta.get("context") != "fork":
        stray = [k for k in ("agent", "background") if k in meta]
        if stray:
            rep.add(
                "warn", "SKILL_FORK_FIELD", sk, f"{', '.join(stray)} ignored without context: fork"
            )
    words = "|".join(map(re.escape, pol["side_effect_words"]))
    dmi = meta.get("disable-model-invocation", "").lower() in ("true", "yes", "on", "1")
    if (
        re.search(rf"\b({words})\b", f"{d.name} {name}".replace("_", " ").replace("-", " "), re.I)
        and not dmi
    ):
        gate = pol.get("gate_side_effects", True)
        rep.add(
            "warn",
            "SKILL_SIDE_EFFECT",
            sk,
            "side-effect workflow can be auto-invoked by the model"
            + (" (disable-model-invocation: true added)" if gate else ""),
            gate,
        )
        if gate:
            updates["disable-model-invocation"] = "true"
    tools = meta.get("allowed-tools", "")
    if re.search(r"(^|[\s,\[])(Bash|PowerShell)(\(\*\)|(?=[\s,\]]|$))|Bash\(\*", tools):
        rep.add(
            "warn", "SKILL_BROAD_TOOLS", sk, f"allowed-tools grants unrestricted shell: {tools}"
        )
    if renames or updates or new != text or move_meta:
        out = set_frontmatter(new, updates, renames) if (renames or updates) else new
        if move_meta:
            out = move_to_metadata(out, move_meta)
        if sk in rep.new_files:
            rep.new_files[sk] = (out, 0o644)
        else:
            rep.edit(sk, text, out)
        log(2, f"skill {d.name}: " + ", ".join([*renames.values(), *updates]), 2)
    return d.name


def check_agent_assets(
    root: Path, policy: dict, rep: Report, scope: str, project_root: Path | None
) -> None:
    skills = root / "skills"
    names: set[str] = set()
    if skills.is_dir():
        if scope == "user" and (skills / "manifest.json").exists():
            rep.add(
                "warn",
                "SKILL_MANIFEST_BUG",
                skills / "manifest.json",
                "may move skills to .trash on CLIs < 2.1.280",
            )
        dirs = sorted(p for p in skills.iterdir() if p.is_dir() and not p.name.startswith("."))
        log(1, f"{skills}: {len(dirs)} skill dir(s)", 1)
        for d in dirs:
            if d.name.lower() == "synced":
                if scope != "user":
                    rep.add("error", "SKILL_RESERVED", d, "reserved directory name")
                continue  # downloaded from claude.ai: never edited here
            n = check_skill(d, policy, rep)
            if n:
                names.add(n)
    agents = root / "agents"
    if agents.is_dir():
        files = sorted(agents.rglob("*.md"))
        log(1, f"{agents}: {len(files)} subagent(s)", 1)
        rep.agent_unknown = {}
        for f in files:
            check_subagent(f, rep)
        for field_name, paths in sorted(rep.agent_unknown.items()):
            if len(paths) >= 10:
                log(
                    1,
                    f"pack convention field {field_name!r} in {len(paths)} subagents "
                    f"(ignored by Claude Code, harmless)",
                    1,
                )
            else:
                for p in paths:
                    rep.add("info", "AGENT_FIELD", p, f"unrecognised field: {field_name}")
    commands = root / "commands"
    if commands.is_dir():
        files = sorted(commands.rglob("*.md"))
        log(1, f"{commands}: {len(files)} command(s)", 1)
        for f in files:
            rep.stats["commands"] = rep.stats.get("commands", 0) + 1
            cmd_name = ":".join(f.relative_to(commands).with_suffix("").parts)
            if cmd_name in names:
                rep.add(
                    "warn", "COMMAND_SHADOWED", f, f"skill '{cmd_name}' has the same name and wins"
                )
            meta, _ = split_frontmatter(read_text(f) or "")
            if not (meta or {}).get("description"):
                rep.add("info", "COMMAND_FRONTMATTER", f, "no description (first line is used)")
    check_rules(root, rep, project_root)


def check_subagent(f: Path, rep: Report) -> None:
    rep.stats["subagents"] = rep.stats.get("subagents", 0) + 1
    text = read_text(f) or ""
    meta, offset = split_frontmatter(text)
    meta = meta or {}
    new = text.lstrip("\ufeff \t\r\n") if offset else text
    if offset:
        rep.add(
            "warn",
            "FRONTMATTER_OFFSET",
            f,
            "frontmatter not on line 1 (leading lines removed)",
            True,
        )
    renames = {k: AGENT_TYPOS[k] for k in meta if k in AGENT_TYPOS and AGENT_TYPOS[k] not in meta}
    if renames:
        rep.add(
            "warn",
            "AGENT_FIELD",
            f,
            "renamed: " + ", ".join(f"{a} -> {b}" for a, b in renames.items()),
            True,
        )
        meta = {renames.get(k, k): v for k, v in meta.items()}
    for k in meta:
        if k not in AGENT_FIELDS:
            rep.agent_unknown.setdefault(k, []).append(f)
    updates = {}
    if not meta.get("name"):
        updates["name"] = slugify(f.stem)
    if not meta.get("description") and (derived := derive_description(new)):
        updates["description"] = derived
    missing = [k for k in ("name", "description") if not meta.get(k)]
    if missing:
        still = [k for k in missing if k not in updates]
        rep.add(
            "error",
            "AGENT_FRONTMATTER",
            f,
            "missing: "
            + ", ".join(missing)
            + (f" (filled: {', '.join(updates)})" if updates else "")
            + (
                f" (cannot derive: {', '.join(still)}; if this file is not a subagent, move "
                f"it out of agents/)"
                if still
                else ""
            ),
            bool(updates),
        )
    tools = meta.get("tools", "")
    tool_renames = {}
    if tools:
        names = [
            re.sub(r"\(.*", "", t).strip() for t in re.split(r"[,\s\[\]]+", tools) if t.strip()
        ]
        bad = [t for t in names if t and not t.startswith("mcp__") and t not in KNOWN_TOOLS]
        for t in bad:
            if t in LEGACY_TOOLS:
                tool_renames[t] = LEGACY_TOOLS[t]
        still_bad = [t for t in bad if t not in tool_renames]
        if tool_renames:
            rep.add(
                "warn",
                "PERM_LEGACY_TOOL",
                f,
                "tools: " + ", ".join(f"{a} -> {b}" for a, b in tool_renames.items()),
                True,
            )
        if still_bad:
            level = "error" if len(still_bad) == len(names) else "warn"
            rep.add(level, "AGENT_TOOLS", f, f"unknown tool(s): {', '.join(still_bad)}")
    if renames or updates or tool_renames or new != text:
        out = set_frontmatter(new, updates, renames) if (renames or updates) else new
        if tool_renames:
            key = "tools"

            def fix_line(m: re.Match) -> str:
                line = m.group(0)
                for a, b in tool_renames.items():
                    line = re.sub(rf"\b{a}\b", b, line)
                return line

            out = re.sub(rf"(?m)^{key}\s*:.*$", fix_line, out, count=1)
        rep.edit(f, text, out)


# --------------------------------------------------------------------------- #
# Beyond agent settings: plugins, marketplaces, output styles, helpers,
# Desktop, CI workflows, misplaced files, credentials
# --------------------------------------------------------------------------- #

PLUGIN_COMPONENT_KEYS = (
    "commands",
    "agents",
    "skills",
    "hooks",
    "mcpServers",
    "outputStyles",
    "lspServers",
    "monitors",
    "channels",
)
PLUGIN_KNOWN_KEYS = {
    "name",
    "displayName",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "userConfig",
    "dependencies",
    *PLUGIN_COMPONENT_KEYS,
}
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[\w.]+)?(?:\+[\w.]+)?$")
KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ANTHROPIC_KEY_RE = re.compile(r"sk-ant-(?:api|admin|oat)\d{2}-[A-Za-z0-9_-]{20,}")
HELPER_STRING_KEYS = ("apiKeyHelper", "awsAuthRefresh", "awsCredentialExport", "otelHeadersHelper")
HELPER_OBJECT_KEYS = ("statusLine", "subagentStatusLine", "fileSuggestion")

HINTS.update(
    {
        "PLUGIN_MANIFEST": (
            "Only 'name' is required (kebab-case); version should be semver; unknown "
            "top-level fields are stripped.",
            DOCS + "plugins/manifest-reference",
        ),
        "PLUGIN_PATH": (
            "Component paths are relative with a ./ prefix and must stay inside the plugin root.",
            DOCS + "plugins/manifest-reference",
        ),
        "PLUGIN_LAYOUT": (
            "Only plugin.json goes in .claude-plugin/; skills/, commands/, hooks/ live at "
            "the plugin root.",
            DOCS + "plugins/manifest-reference",
        ),
        "PLUGIN_CLI": (
            "Result of 'claude plugin validate', the authoritative validator.",
            DOCS + "plugins/cli-reference",
        ),
        "MARKETPLACE": (
            "marketplace.json needs a name and a plugins list whose entries have name and source.",
            DOCS + "plugins/marketplace-reference",
        ),
        "ENABLED_PLUGINS": (
            "enabledPlugins keys are 'plugin@marketplace' with boolean values.",
            DOCS + "settings-reference",
        ),
        "OUTPUT_STYLE": (
            "Output styles are Markdown with name/description frontmatter.",
            DOCS + "output-styles",
        ),
        "HELPER_SCRIPT": (
            "Helpers (statusLine, apiKeyHelper, ...) run a command; a missing or "
            "non-executable script fails silently.",
            DOCS + "settings-reference",
        ),
        "HELPER_REPO": (
            "A repository-supplied helper runs code on your machine (before trust in -p runs).",
            DOCS + "permissions#what-runs-before-you-trust-a-folder",
        ),
        "MISPLACED": ("This file or key is not read at this location.", DOCS + "claude-directory"),
        "CLAUDEIGNORE": (
            "There is no .claudeignore; use permissions.deny Read(...) rules and the sandbox.",
            DOCS + "permissions#read-and-edit",
        ),
        "SETTINGS_MCP_SERVERS": (
            "MCP servers are declared in .mcp.json (project) or ~/.claude.json (user), not "
            "in settings.json.",
            DOCS + "mcp",
        ),
        "DESKTOP_CONFIG": (
            "Claude Desktop MCP configuration.",
            "https://modelcontextprotocol.io/quickstart/user",
        ),
        "CI_ACTION": ("claude-code-action workflow hardening.", DOCS + "github-actions"),
        "API_KEY_LEAK": (
            "An Anthropic API key in a file is readable by anyone with access: revoke and "
            "rotate it.",
            "https://console.anthropic.com/settings/keys",
        ),
        "MANAGED_SETTINGS": (
            "Managed settings: read-only here, reported for information.",
            DOCS + "managed-settings",
        ),
        "KEYBINDINGS": ("keybindings.json must be strict JSON.", DOCS + "keybindings"),
    }
)


def check_helpers(settings: dict, base: Path, path: Path, rep: Report, scope: str) -> None:
    for key in HELPER_STRING_KEYS + HELPER_OBJECT_KEYS:
        val = settings.get(key)
        if val is None:
            continue
        cmd = (
            val if isinstance(val, str) else (val.get("command") if isinstance(val, dict) else None)
        )
        if (
            key in HELPER_OBJECT_KEYS
            and isinstance(val, dict)
            and val.get("type") not in (None, "command")
        ):
            rep.add("error", "HELPER_SCRIPT", path, f"{key}.type must be 'command'")
        if not cmd:
            rep.add("error", "HELPER_SCRIPT", path, f"{key}: no command")
            continue
        if scope == "project" and path.name == "settings.json" and key in HELPER_STRING_KEYS:
            rep.add(
                "warn",
                "HELPER_REPO",
                path,
                f"{key} is supplied by the repository and executes code",
            )
        script = resolve_script(str(cmd).split()[0], base)
        if script is None:
            continue
        if not script.exists():
            rep.add("error", "HELPER_SCRIPT", path, f"{key}: script not found: {script}")
        elif not os.access(script, os.X_OK) and script not in rep.chmods:
            rep.add("warn", "HELPER_SCRIPT", path, f"{key}: {script} is not executable", True)
            rep.chmods.append(script)


def check_plugin_settings(settings: dict, path: Path, rep: Report, scope: str) -> None:
    ep = settings.get("enabledPlugins")
    if isinstance(ep, dict):
        for k, v in ep.items():
            if "@" not in k:
                rep.add(
                    "warn",
                    "ENABLED_PLUGINS",
                    path,
                    f"enabledPlugins key {k!r} lacks '@marketplace'",
                )
            if not isinstance(v, bool):
                rep.add(
                    "error", "ENABLED_PLUGINS", path, f"enabledPlugins[{k!r}] must be true or false"
                )
    elif ep is not None:
        rep.add("error", "ENABLED_PLUGINS", path, "enabledPlugins must be an object")
    mk = settings.get("extraKnownMarketplaces")
    if isinstance(mk, dict):
        for name, cfg in mk.items():
            if (
                not isinstance(cfg, dict)
                or not isinstance(cfg.get("source"), dict)
                or not cfg["source"].get("source")
            ):
                rep.add(
                    "error",
                    "MARKETPLACE",
                    path,
                    f"extraKnownMarketplaces.{name}: needs source.source (github, git, "
                    f"directory, url)",
                )


def move_settings_mcp(settings: dict, base: Path, path: Path, rep: Report, scope: str) -> dict:
    servers = settings.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        return settings
    if scope != "project":
        rep.add(
            "warn",
            "SETTINGS_MCP_SERVERS",
            path,
            "mcpServers in settings.json is not read; use 'claude mcp add --scope user'",
        )
        return settings
    target = base / ".mcp.json"
    if any(d == target for _, d in rep.moves):
        rep.add(
            "warn",
            "SETTINGS_MCP_SERVERS",
            path,
            "mcpServers in settings.json is not read (moved on the next --fix pass)",
            True,
        )
        return settings
    raw = rep.current(target)
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        rep.add(
            "warn",
            "SETTINGS_MCP_SERVERS",
            path,
            "mcpServers in settings.json is not read (.mcp.json unparsable: move by hand)",
        )
        return settings
    existing = data.setdefault("mcpServers", {})
    clash = [n for n in servers if n in existing]
    if clash:
        rep.add(
            "warn",
            "SETTINGS_MCP_SERVERS",
            path,
            f"mcpServers in settings.json is not read; names clash with .mcp.json: "
            f"{', '.join(clash)}",
        )
        return settings
    existing.update(servers)
    rep.add(
        "warn",
        "SETTINGS_MCP_SERVERS",
        path,
        f"{len(servers)} MCP server(s) moved to .mcp.json",
        True,
    )
    if raw is None:
        rep.new_files[target] = (dump_json(data), 0o644)
    else:
        rep.edit(target, read_text(target) or "", dump_json(data))
    return {k: v for k, v in settings.items() if k != "mcpServers"}


def check_plugin_dir(root: Path, rep: Report, policy: dict) -> None:
    mf = root / ".claude-plugin" / "plugin.json"
    if root.resolve() in rep.seen:
        return
    rep.seen.add(root.resolve())
    has_layout = any((root / d).is_dir() for d in ("skills", "commands", "agents", "hooks"))
    raw = read_text(mf)
    if raw is None:
        if has_layout:
            log(1, f"plugin without manifest: {root}", 1)
            check_agent_assets(root, policy, rep, "plugin", root)
        return
    log(1, f"plugin: {root}", 1)
    rep.stats["plugins"] = rep.stats.get("plugins", 0) + 1
    try:
        data, repaired = lenient_json(raw)
    except json.JSONDecodeError as e:
        rep.add("error", "JSON_INVALID", mf, f"invalid JSON: {e}")
        return
    new = copy.deepcopy(data)
    if repaired:
        rep.add(
            "error", "JSON_REPAIRED", mf, "comments, trailing commas or BOM in strict JSON", True
        )
    name = data.get("name")
    if not name:
        rep.add("error", "PLUGIN_MANIFEST", mf, "missing 'name'")
    elif not KEBAB_RE.match(str(name)):
        rep.add(
            "warn",
            "PLUGIN_MANIFEST",
            mf,
            f"name {name!r} is not kebab-case (use {slugify(str(name))!r})",
        )
    if "version" in data and not SEMVER_RE.match(str(data["version"])):
        rep.add("warn", "PLUGIN_MANIFEST", mf, f"version {data['version']!r} is not semver")
    for k in ("version", "description", "author"):
        if k not in data:
            rep.add("info", "PLUGIN_MANIFEST", mf, f"no {k}")
    unknown = [k for k in data if k not in PLUGIN_KNOWN_KEYS]
    if unknown:
        rep.add(
            "warn",
            "PLUGIN_MANIFEST",
            mf,
            f"unknown field(s) stripped at load: {', '.join(unknown)}",
        )
    for key in PLUGIN_COMPONENT_KEYS:
        val = data.get(key)
        paths = (
            [val]
            if isinstance(val, str)
            else [p for p in val if isinstance(p, str)]
            if isinstance(val, list)
            else []
        )
        fixed = []
        for p in paths:
            q = p
            if not p.startswith("./") and not p.startswith(("/", "$", "~")):
                q = "./" + p
                rep.add("warn", "PLUGIN_PATH", mf, f"{key}: {p!r} needs a ./ prefix ({q!r})", True)
            elif p.startswith(("/", "~")):
                rep.add("error", "PLUGIN_PATH", mf, f"{key}: {p!r} is absolute")
            target = (root / q).resolve()
            try:
                target.relative_to(root.resolve())
            except ValueError:
                rep.add("error", "PLUGIN_PATH", mf, f"{key}: {p!r} escapes the plugin root")
            if not q.startswith("$") and not target.exists():
                rep.add("error", "PLUGIN_PATH", mf, f"{key}: {p!r} does not exist")
            fixed.append(q)
        if paths and fixed != paths:
            new[key] = fixed[0] if isinstance(val, str) else fixed
    for sub in ("skills", "commands", "agents", "hooks", "output-styles"):
        if (root / ".claude-plugin" / sub).exists():
            rep.add(
                "error",
                "PLUGIN_LAYOUT",
                root / ".claude-plugin" / sub,
                f"{sub}/ must be at the plugin root, not in .claude-plugin/",
            )
    hooks_file = root / "hooks" / "hooks.json"
    hraw = read_text(hooks_file)
    if hraw is not None:
        try:
            hdata, hrep = lenient_json(hraw)
            if hrep:
                rep.add(
                    "error",
                    "JSON_REPAIRED",
                    hooks_file,
                    "comments, trailing commas or BOM in strict JSON",
                    True,
                )
            fixed_hooks = check_hooks(hdata.get("hooks", {}), root, hooks_file, rep, "plugin")
            if fixed_hooks != hdata.get("hooks") or hrep:
                rep.edit(hooks_file, hraw, dump_json({**hdata, "hooks": fixed_hooks}))
        except json.JSONDecodeError as e:
            rep.add("error", "JSON_INVALID", hooks_file, f"invalid JSON: {e}")
    if (root / ".mcp.json").exists():
        check_mcp(root / ".mcp.json", rep, policy)
    if any((root / sub).is_dir() for sub in ("skills", "agents", "commands")):
        check_agent_assets(root, policy, rep, "plugin", root)
    check_output_styles(root, rep)
    if new != data or repaired:
        rep.edit(mf, raw, dump_json(new))
    if CLI_VERSION and shutil.which("claude"):
        try:
            res = subprocess.run(
                ["claude", "plugin", "validate", str(root)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if res.returncode != 0:
                msg = (res.stdout + res.stderr).strip().splitlines()
                rep.add(
                    "error",
                    "PLUGIN_CLI",
                    root,
                    "claude plugin validate: " + (msg[-1] if msg else f"exit {res.returncode}"),
                )
            else:
                log(1, f"claude plugin validate {root}: ok", 1)
        except (OSError, subprocess.TimeoutExpired):
            pass


def check_marketplace(root: Path, rep: Report, policy: dict) -> None:
    mf = root / ".claude-plugin" / "marketplace.json"
    raw = read_text(mf)
    if raw is None:
        return
    try:
        data, repaired = lenient_json(raw)
    except json.JSONDecodeError as e:
        rep.add("error", "JSON_INVALID", mf, f"invalid JSON: {e}")
        return
    if repaired:
        rep.add(
            "error", "JSON_REPAIRED", mf, "comments, trailing commas or BOM in strict JSON", True
        )
        rep.edit(mf, raw, dump_json(data))
    if not data.get("name"):
        rep.add("error", "MARKETPLACE", mf, "missing 'name'")
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        rep.add("error", "MARKETPLACE", mf, "missing 'plugins' list")
        return
    names = set()
    for i, p in enumerate(plugins):
        if not isinstance(p, dict) or not p.get("name") or not p.get("source"):
            rep.add("error", "MARKETPLACE", mf, f"plugins[{i}]: needs name and source")
            continue
        if p["name"] in names:
            rep.add("error", "MARKETPLACE", mf, f"duplicate plugin name {p['name']!r}")
        names.add(p["name"])
        src = p["source"]
        if isinstance(src, str) and src.startswith("./"):
            target = (root / src).resolve()
            if not target.exists():
                rep.add(
                    "error",
                    "MARKETPLACE",
                    mf,
                    f"plugins[{p['name']}]: source {src!r} does not exist",
                )
            else:
                check_plugin_dir(target, rep, policy)


def check_output_styles(root: Path, rep: Report) -> None:
    d = root / "output-styles"
    if not d.is_dir():
        return
    for f in sorted(d.glob("*.md")):
        meta, offset = split_frontmatter(read_text(f) or "")
        if offset:
            rep.add(
                "warn",
                "FRONTMATTER_OFFSET",
                f,
                "frontmatter not on line 1 (leading lines removed)",
                True,
            )
            t = read_text(f) or ""
            rep.edit(f, t, t.lstrip("\ufeff \t\r\n"))
        if not meta or not meta.get("description"):
            rep.add("info", "OUTPUT_STYLE", f, "no description in frontmatter")
        unknown = [
            k for k in (meta or {}) if k not in ("name", "description", "keep-coding-instructions")
        ]
        if unknown:
            rep.add("info", "OUTPUT_STYLE", f, f"unrecognised field(s): {', '.join(unknown)}")


def check_misplaced(repo: Path, rep: Report) -> None:
    def rename(src: Path, dst: Path, code: str, why: str) -> None:
        if dst.exists() or any(d == dst for _, d in rep.moves):
            rep.add(
                "warn", code, src, f"{why}; {dst.relative_to(repo)} already exists: merge by hand"
            )
            return
        rep.add("warn", code, src, f"{why} (moved to {dst.relative_to(repo)})", True)
        rep.moves.append((src, dst))

    names = {p.name: p for p in repo.iterdir()} if repo.is_dir() else {}
    for n, p in names.items():
        if n.lower() == "claude.md" and n != "CLAUDE.md" and p.is_file():
            rename(
                p,
                repo / "CLAUDE.md",
                "MISPLACED",
                f"{n}: file names are case-sensitive on Linux; not loaded",
            )
        if n.lower() == "agents.md" and n != "AGENTS.md" and p.is_file():
            rename(p, repo / "AGENTS.md", "MISPLACED", f"{n}: not loaded (expected AGENTS.md)")
        if n == "mcp.json":
            rename(
                p,
                repo / ".mcp.json",
                "MISPLACED",
                "mcp.json is not read (project servers live in .mcp.json)",
            )
    if (repo / ".claudeignore").exists():
        rep.add(
            "warn",
            "CLAUDEIGNORE",
            repo / ".claudeignore",
            ".claudeignore is not a Claude Code feature: nothing reads it",
        )
    dot = repo / ".claude"
    for n in (".mcp.json", "mcp.json"):
        if (dot / n).is_file():
            rename(
                dot / n,
                repo / ".mcp.json",
                "MISPLACED",
                f".claude/{n} is not read (use .mcp.json at the project root)",
            )
    for n in ("settings.yaml", "settings.yml", "settings.toml", "config.json", "claude.json"):
        if (dot / n).exists():
            rep.add(
                "warn",
                "MISPLACED",
                dot / n,
                f".claude/{n} is not read (settings live in .claude/settings.json)",
            )
    if (repo / ".claude.json").exists() and repo != Path.home():
        rep.add(
            "warn",
            "MISPLACED",
            repo / ".claude.json",
            ".claude.json in a repository is not read (it belongs in your home directory)",
        )
    skills = dot / "skills"
    if skills.is_dir():
        for f in skills.glob("*.md"):
            dst = skills / f.stem / "SKILL.md"
            rename(
                f,
                dst,
                "MISPLACED",
                f"flat skill file {f.name} is not loaded (needs {f.stem}/SKILL.md)",
            )


def check_workflows(repo: Path, rep: Report) -> None:
    wf_dir = repo / ".github" / "workflows"
    if not wf_dir.is_dir():
        return
    for wf in sorted([*wf_dir.glob("*.yml"), *wf_dir.glob("*.yaml")]):
        text = read_text(wf) or ""
        if "claude-code-action" not in text and "claude-code-base-action" not in text:
            continue
        log(1, f"CI workflow: {wf}", 1)
        for m in re.finditer(r"uses:\s*anthropics/claude-code(?:-base)?-action@([\w.\-/]+)", text):
            ref = m.group(1)
            if ref in ("main", "master", "beta", "latest"):
                rep.add(
                    "warn",
                    "CI_ACTION",
                    wf,
                    f"action pinned to moving ref @{ref}: pin a release tag or commit SHA",
                )
            elif not re.fullmatch(r"[0-9a-f]{40}", ref):
                rep.add(
                    "info",
                    "CI_ACTION",
                    wf,
                    f"action pinned to tag @{ref}; a commit SHA is immutable",
                )
        if re.search(
            r"(anthropic_api_key|claude_code_oauth_token)\s*:\s*['\"]?(?!\$\{\{)\S{12,}", text
        ):
            rep.add(
                "error", "CI_ACTION", wf, "credential written literally: use ${{ secrets.NAME }}"
            )
        if re.search(r"dangerously-skip-permissions|permission-mode\W+bypassPermissions", text):
            rep.add(
                "warn", "CI_ACTION", wf, "permissions bypassed in CI: list allowed tools instead"
            )
        if re.search(r"(allowed_tools|allowedTools)\W+[^\n]*\bBash(\(\*\))?(?=[\s,\"']|$)", text):
            rep.add("warn", "CI_ACTION", wf, "unrestricted Bash allowed in CI")
        if re.search(r"(?m)^\s*pull_request_target\s*:", text):
            rep.add(
                "warn",
                "CI_ACTION",
                wf,
                "pull_request_target exposes secrets to fork PR content (prompt injection)",
            )
        if not re.search(r"(?m)^\s*permissions\s*:", text):
            rep.add(
                "warn",
                "CI_ACTION",
                wf,
                "no 'permissions:' block: the token gets the repository default scopes",
            )
        if re.search(r"(?m)^\s*issue_comment\s*:", text) and "author_association" not in text:
            rep.add(
                "info",
                "CI_ACTION",
                wf,
                "issue_comment trigger without author_association filter: anyone who can "
                "comment can trigger it",
            )


def check_repo_secrets(repo: Path, rep: Report) -> None:
    skip = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".cache"}
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in skip and not (d == "worktrees" and Path(dirpath).name == ".claude")
        ]
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                if p.stat().st_size > 1_000_000:
                    continue
            except OSError:
                continue
            text = read_text(p)
            if text and ANTHROPIC_KEY_RE.search(text):
                rel = str(p.relative_to(repo))
                tracked = (repo / ".git").exists() and is_tracked(repo, rel)
                ignored = (repo / ".git").exists() and is_ignored(repo, rel)
                level = "error" if tracked or not ignored else "warn"
                rep.add(
                    level,
                    "API_KEY_LEAK",
                    p,
                    "Anthropic API key in file" + (" (committed: rotate it)" if tracked else ""),
                )


def check_user_extras(rep: Report) -> None:
    home = Path.home()
    for rc in (
        ".bashrc",
        ".zshrc",
        ".profile",
        ".bash_profile",
        ".zprofile",
        ".config/fish/config.fish",
    ):
        text = read_text(home / rc)
        if text and ANTHROPIC_KEY_RE.search(text):
            rep.add(
                "warn",
                "API_KEY_LEAK",
                home / rc,
                "Anthropic API key in plaintext shell startup file (prefer a secret manager "
                "/ vault)",
            )
    kb = config_dir() / "keybindings.json"
    raw = read_text(kb)
    if raw is not None:
        try:
            data, repaired = lenient_json(raw)
            if repaired:
                rep.add(
                    "error", "KEYBINDINGS", kb, "comments or trailing commas in strict JSON", True
                )
                rep.edit(kb, raw, dump_json(data))
        except json.JSONDecodeError as e:
            rep.add("error", "KEYBINDINGS", kb, f"invalid JSON: {e}")
    check_output_styles(config_dir(), rep)
    candidates = [
        home / ".config/Claude/claude_desktop_config.json",
        home / "Library/Application Support/Claude/claude_desktop_config.json",
    ]
    if os.environ.get("APPDATA"):
        candidates.append(Path(os.environ["APPDATA"]) / "Claude/claude_desktop_config.json")
    for dc in candidates:
        raw = read_text(dc)
        if raw is None:
            continue
        log(1, f"Desktop config: {dc}", 1)
        try:
            data, repaired = lenient_json(raw)
        except json.JSONDecodeError as e:
            rep.add("error", "JSON_INVALID", dc, f"invalid JSON: {e}")
            continue
        if repaired:
            rep.add(
                "error", "JSON_REPAIRED", dc, "comments or trailing commas in strict JSON", True
            )
            rep.edit(dc, raw, dump_json(data))
        if isinstance(data.get("mcpServers"), dict):
            check_servers(data["mcpServers"], dc, rep, "mcpServers", False)
    for managed in (
        Path("/etc/claude-code/managed-settings.json"),
        Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
    ):
        raw = read_text(managed)
        if raw is None:
            continue
        try:
            json.loads(raw)
            log(1, f"managed settings: {managed} (valid JSON)", 1)
        except json.JSONDecodeError as e:
            rep.add(
                "error",
                "MANAGED_SETTINGS",
                managed,
                f"invalid JSON: {e} (Claude Code keeps the stricter fallback)",
            )


def find_plugin_roots(repo: Path, max_depth: int = 4) -> list[Path]:
    roots: list[Path] = []
    base = len(repo.parts)
    skip = {".git", "node_modules", ".venv", "venv", "dist", "build", ".cache"}
    for dirpath, dirnames, _ in os.walk(repo):
        p = Path(dirpath)
        if p.name == ".claude-plugin":
            roots.append(p.parent)
            dirnames[:] = []
            continue
        depth = len(p.parts) - base
        dirnames[:] = [d for d in dirnames if d not in skip] if depth < max_depth else []
    return sorted(set(roots))


# --------------------------------------------------------------------------- #
# rtk (Rust Token Killer) integration
# --------------------------------------------------------------------------- #

# Commands rtk rewrites (README, 2026-09). Used when `rtk rewrite` is unavailable.
RTK_SUPPORTED = {
    "ls",
    "tree",
    "cat",
    "read",
    "grep",
    "rg",
    "find",
    "diff",
    "ast-grep",
    "git",
    "gh",
    "jest",
    "vitest",
    "playwright",
    "pytest",
    "go",
    "cargo",
    "rake",
    "rspec",
    "npm",
    "npx",
    "eslint",
    "tsc",
    "next",
    "prettier",
    "ruff",
    "golangci-lint",
    "rubocop",
    "mvn",
    "mvnd",
    "sbt",
    "pnpm",
    "uv",
    "pip",
    "bundle",
    "prisma",
    "bun",
    "bunx",
    "deno",
    "aws",
    "docker",
    "kubectl",
    "oc",
    "pulumi",
    "curl",
    "wget",
    "sqlfluff",
    "head",
    "tail",
    "log",
    "env",
}
RTK_NATIVE_HOOK = (0, 37, 2)
RTK: dict[str, Any] = {
    "path": None,
    "version": None,
    "genuine": None,
    "config": None,
    "config_path": None,
    "exclude": set(),
    "rewrite_cache": {},
    "rewrite_cli": None,
    "help_commands": set(),
}
RTK_NATIVE = {
    "read",
    "smart",
    "summary",
    "proxy",
    "err",
    "test",
    "json",
    "deps",
    "env",
    "log",
    "gain",
    "discover",
    "session",
    "init",
    "hook",
    "rewrite",
    "recall",
    "telemetry",
    "lint",
}

# llmtrim: a companion CLI that owns "route" subagents (llmtrim-codex-*, llmtrim-grok-*...).
# They carry an HTML marker and delegate to the llmtrim binary; without it on PATH those
# subagents load into every session but route nowhere.
LLMTRIM: dict[str, Any] = {"path": None, "version": None, "checked_cli": False}
LLMTRIM_ROUTE_MARKER = re.compile(r"llmtrim-(owned-route-agent|route-v\d+)", re.I)

HINTS.update(
    {
        "LLMTRIM_MISSING": (
            "These subagents are managed by the llmtrim CLI and delegate to it; without "
            "llmtrim on PATH they load into every session but their routes are dead. Install "
            "llmtrim, or remove the route agents (-i offers to park them).",
            "https://github.com/llmtrim/llmtrim#install",
        ),
        "RTK_MISSING": (
            "rtk-prefixed allow rules only match once the rtk hook rewrites commands; "
            "without rtk they never match.",
            "https://github.com/rtk-ai/rtk#installation",
        ),
        "RTK_WRONG_PACKAGE": (
            "'rtk' on PATH is another project (Rust Type Kit): 'rtk gain' does not exist.",
            "https://github.com/rtk-ai/rtk#verify-installation",
        ),
        "RTK_OLD": (
            "Since v0.37.2 the hook is a native binary (rtk hook claude): no bash or jq needed.",
            "https://github.com/rtk-ai/rtk#windows",
        ),
        "RTK_NO_HOOK": (
            "Without the PreToolUse hook nothing is rewritten: no savings, and rtk-prefixed "
            "rules never match.",
            "https://github.com/rtk-ai/rtk#auto-rewrite-hook",
        ),
        "RTK_LEGACY_HOOK": (
            "The legacy rtk-rewrite.sh hook needs a Unix shell and jq; the native hook "
            "replaces it.",
            "https://github.com/rtk-ai/rtk#windows",
        ),
        "RTK_HOOK_MATCHER": (
            "The rtk hook must match the Bash tool.",
            "https://github.com/rtk-ai/rtk#auto-rewrite-hook",
        ),
        "RTK_DEAD_RULE": (
            "rtk does not rewrite this command (unsupported or excluded): the rtk-prefixed "
            "rule never matches and the plain command keeps prompting.",
            "https://github.com/rtk-ai/rtk#configuration",
        ),
        "RTK_CONFIG": (
            "~/.config/rtk/config.toml (macOS: ~/Library/Application Support/rtk/config.toml).",
            "https://github.com/rtk-ai/rtk#configuration",
        ),
        "RTK_AWARENESS": (
            "awareness 'full' is for agents without hook support; with the hook it only "
            "adds context.",
            "https://github.com/rtk-ai/rtk#setup",
        ),
        "RTK_RETRIEVER": (
            "With the retriever disabled, full output of failed commands can't be recalled "
            "(rtk recall): the agent re-runs them.",
            "https://github.com/rtk-ai/rtk#configuration",
        ),
        "RTK_TELEMETRY": (
            "Telemetry is opt-in; disable it with 'rtk telemetry disable' or "
            "RTK_TELEMETRY_DISABLED=1.",
            "https://github.com/rtk-ai/rtk#privacy--telemetry",
        ),
        "RTK_READ_TOOLS": (
            "The hook only sees Bash: Read/Grep/Glob output is never compressed.",
            "https://github.com/rtk-ai/rtk#quick-start",
        ),
    }
)


def _run(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def rtk_config_path() -> Path:
    if os.environ.get("RTK_CONFIG"):
        return Path(os.path.expanduser(os.environ["RTK_CONFIG"]))
    mac = Path.home() / "Library/Application Support/rtk/config.toml"
    if sys.platform == "darwin" and mac.exists():
        return mac
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "rtk" / "config.toml"


def detect_rtk(use_cli: bool) -> None:
    cfg_path = rtk_config_path()
    RTK["config_path"] = cfg_path
    raw = read_text(cfg_path)
    if raw is not None and tomllib is not None:
        try:
            RTK["config"] = tomllib.loads(raw)
            RTK["exclude"] = set((RTK["config"].get("hooks") or {}).get("exclude_commands") or [])
        except Exception as e:  # noqa: BLE001
            RTK["config"] = {"__error__": str(e)}
    if not use_cli:
        return
    RTK["path"] = shutil.which("rtk")
    if not RTK["path"]:
        return
    res = _run(["rtk", "--version"])
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", (res.stdout if res else "") or "")
    RTK["version"] = tuple(int(x) for x in m.groups()) if m else None
    gain = _run(["rtk", "gain", "--help"])
    RTK["genuine"] = bool(gain and gain.returncode == 0)
    helptext = _run(["rtk", "--help"])
    cmds = set(
        re.findall(r"(?m)^\s{2,}([a-z][\w-]*)[\s,]", (helptext.stdout if helptext else "") or "")
    )
    RTK["help_commands"] = cmds if len(cmds) >= 10 else set()
    # `rtk rewrite` prints the rewritten command on stdout when it supports it and
    # nothing when it doesn't. Its exit code is unreliable (rtk 0.42.1 exits 3 on a
    # successful rewrite), so detection keys on stdout, not the return code.
    probe = _run(["rtk", "rewrite", "git status"])
    RTK["rewrite_cli"] = bool(probe and (probe.stdout or "").strip().startswith("rtk"))
    log(
        1,
        f"rtk: {RTK['path']} {'.'.join(map(str, RTK['version'] or ())) or '?'} "
        f"(genuine={RTK['genuine']}, rewrite probe={RTK['rewrite_cli']}, "
        f"commands from --help={len(RTK['help_commands'])}, excluded={sorted(RTK['exclude'])})",
    )


def rtk_rewrites(cmd: str) -> bool:
    """Would the rtk hook rewrite this command prefix?"""
    first = cmd.split()[0] if cmd.split() else ""
    if (
        not first
        or first in RTK["exclude"]
        or any(cmd == e or cmd.startswith(e + " ") for e in RTK["exclude"])
    ):
        return False
    if RTK["rewrite_cli"]:
        cache = RTK["rewrite_cache"]
        if cmd not in cache:
            res = _run(["rtk", "rewrite", cmd], timeout=5)
            cache[cmd] = bool(res and (res.stdout or "").strip().startswith("rtk"))
            log(3, f"rtk rewrite {cmd!r}: {cache[cmd]}")
        return cache[cmd]
    if RTK["help_commands"]:
        return first in RTK["help_commands"] and first not in RTK_NATIVE
    return first in RTK_SUPPORTED


def rtk_authoritative() -> bool:
    """Only unwrap existing rtk rules when rtk itself told us what it supports."""
    return bool(RTK["rewrite_cli"] or RTK["help_commands"])


def rtk_settings_hooks(policy: dict, repos: list[Path]) -> list[tuple[Path, str, str]]:
    """(settings file, matcher, command) for every hook that mentions rtk."""
    found = []
    files = [config_dir() / "settings.json", config_dir() / "settings.local.json"]
    files += [r / ".claude" / n for r in repos for n in ("settings.json", "settings.local.json")]
    for f in files:
        raw = read_text(f)
        if not raw:
            continue
        try:
            data = lenient_json(raw)[0]
        except json.JSONDecodeError:
            continue
        for g in (
            ((data.get("hooks") or {}).get("PreToolUse") or []) if isinstance(data, dict) else []
        ):
            for h in (g or {}).get("hooks", []) if isinstance(g, dict) else []:
                cmd = (
                    " ".join([str(h.get("command", "")), *map(str, h.get("args") or [])])
                    if isinstance(h, dict)
                    else ""
                )
                if re.search(r"\brtk\b|rtk-rewrite", cmd):
                    found.append((f, str(g.get("matcher", "")), cmd))
    return found


def check_rtk(policy: dict, rep: Report, repos: list[Path], user_scope: bool) -> None:
    pol = policy["permissions"]
    if not pol["require_rtk"]:
        return
    if RTK["config"] and "__error__" in RTK["config"]:
        rep.add(
            "error", "RTK_CONFIG", RTK["config_path"], f"invalid TOML: {RTK['config']['__error__']}"
        )
    if RTK["path"] is None and RTK["genuine"] is None:
        if shutil.which("rtk") is None and RTK.get("checked_cli"):
            rep.add(
                "warn",
                "RTK_MISSING",
                "rtk",
                "require_rtk is on but rtk is not installed: "
                "install it (see hint) or set permissions.require_rtk = false to skip rtk routing",
            )
        return
    if RTK["genuine"] is False:
        rep.add("error", "RTK_WRONG_PACKAGE", RTK["path"], "this 'rtk' is not Rust Token Killer")
        return
    version = RTK["version"]
    if version and version < RTK_NATIVE_HOOK:
        rep.add(
            "info",
            "RTK_OLD",
            RTK["path"],
            f"rtk {'.'.join(map(str, version))}: upgrade, then rerun 'rtk init -g'",
        )
    hooks = rtk_settings_hooks(policy, repos)
    user_settings = config_dir() / "settings.json"
    native_ok = version is None or version >= RTK_NATIVE_HOOK
    if not hooks:
        fixable = user_scope and native_ok
        rep.add(
            "error",
            "RTK_NO_HOOK",
            user_settings,
            "no rtk PreToolUse hook"
            + (
                " (native hook added to user settings)"
                if fixable
                else ": run 'rtk init -g --hook-only'"
            ),
            fixable,
        )
        if fixable:
            raw = rep.current(user_settings) or "{}"
            try:
                data = lenient_json(raw)[0]
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                pre = data.setdefault("hooks", {}).setdefault("PreToolUse", [])
                pre.append(
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "rtk",
                                "args": ["hook", "claude"],
                                "timeout": 10,
                            }
                        ],
                    }
                )
                if user_settings.exists() or user_settings in rep.edits:
                    rep.edit(user_settings, read_text(user_settings) or "", dump_json(data))
                else:
                    rep.new_files[user_settings] = (
                        dump_json({"$schema": policy["scaffold"]["schema_url"], **data}),
                        0o644,
                    )
    for f, matcher, cmd in hooks:
        if "rtk-rewrite" in cmd:
            rep.add(
                "warn",
                "RTK_LEGACY_HOOK",
                f,
                f"legacy shell hook ({cmd[:50]}): rerun 'rtk init -g' to migrate",
            )
        if matcher not in ("", "*") and not re.search(r"(^|[|,\s])Bash($|[|,\s])|\.\*", matcher):
            rep.add(
                "warn", "RTK_HOOK_MATCHER", f, f"rtk hook matcher {matcher!r} does not match Bash"
            )
    cfg = RTK["config"] or {}
    level = str((cfg.get("awareness") or {}).get("level", "")).lower()
    if hooks and level == "full":
        rep.add(
            "warn",
            "RTK_AWARENESS",
            RTK["config_path"],
            "awareness level 'full' duplicates what the hook already does",
        )
    if (
        str((cfg.get("retriever") or {}).get("mode", "")).lower() == "disabled"
        or (cfg.get("tee") or {}).get("enabled") is False
    ):
        rep.add("info", "RTK_RETRIEVER", RTK["config_path"], "failure output recovery disabled")
    user_env = {}
    try:
        user_env = (
            lenient_json(rep.current(config_dir() / "settings.json") or "{}")[0].get("env") or {}
        )
    except (json.JSONDecodeError, AttributeError):
        pass
    if (
        RTK["path"]
        and not os.environ.get("RTK_TELEMETRY_DISABLED")
        and not user_env.get("RTK_TELEMETRY_DISABLED")
    ):
        res = _run(["rtk", "telemetry", "status"], timeout=5)
        out = ((res.stdout or "") + (res.stderr or "")).lower() if res else ""
        if re.search(r"\b(enabled|granted|consent: yes|opted in)\b", out) and "disabled" not in out:
            rep.add(
                "info",
                "RTK_TELEMETRY",
                "rtk",
                "telemetry enabled: 'rtk telemetry disable' (or RTK_TELEMETRY_DISABLED=1)",
            )


def detect_llmtrim(use_cli: bool) -> None:
    LLMTRIM["checked_cli"] = use_cli
    if not use_cli:
        return
    LLMTRIM["path"] = shutil.which("llmtrim")
    if LLMTRIM["path"]:
        res = _run(["llmtrim", "--version"], timeout=5)
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", (res.stdout if res else "") or "")
        LLMTRIM["version"] = tuple(int(x) for x in m.groups()) if m else None
    log(1, f"llmtrim: {LLMTRIM['path'] or 'not found'}")


def check_llmtrim(rep: Report, repos: list[Path], user_scope: bool) -> None:
    """If llmtrim owns route subagents but the CLI is absent, propose installing it
    (or removing the dead routes). Skipped entirely when --no-cli is set."""
    if not LLMTRIM["checked_cli"] or LLMTRIM["path"]:
        return  # llmtrim installed, or CLI probing skipped: nothing to propose
    roots = ([config_dir()] if user_scope else []) + [r / ".claude" for r in repos]
    routes: list[Path] = []
    for root in roots:
        for ag in sorted(root.glob("agents/**/*.md")):
            if LLMTRIM_ROUTE_MARKER.search(read_text(ag) or ""):
                routes.append(ag)
    if routes:
        rep.add(
            "warn",
            "LLMTRIM_MISSING",
            routes[0].parent,
            f"{len(routes)} llmtrim route subagent(s) but llmtrim is not installed: "
            f"install it or remove them (they load every session, their routes are dead)",
        )


def rtk_report() -> str:
    if not RTK["path"] or not RTK["genuine"]:
        return ""
    parts = []
    for args in (["rtk", "gain"], ["rtk", "discover", "--since", "7"]):
        res = _run(args, timeout=30)
        if res and (res.stdout or "").strip():
            parts.append(f"$ {' '.join(args)}\n{res.stdout.rstrip()}")
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# Generation: rtk config, Claude settings, hooks, skills, subagents, MCP servers
# --------------------------------------------------------------------------- #

GENERATE_POLICY = {
    "project_settings": True,
    "user_settings": True,
    "rtk_config": True,
    "format_hook": True,
    "skills": ["check", "review-changes"],
    "agents": ["code-reviewer", "test-runner", "security-auditor", "infra-reviewer"],
    "mcp": [
        "github",
        "sentry",
        "supabase",
        "playwright",
    ],  # generated only when the stack uses them
    "user_mcp": ["notion"],  # printed as 'claude mcp add --scope user' commands
    "extra_allow": [],
    "extra_ask": [],
    "extra_deny": [],
    "rtk_exclude_commands": [],
    "safe_make_targets": [
        "test",
        "lint",
        "fmt",
        "format",
        "check",
        "build",
        "typecheck",
        "up",
        "down",
        "logs",
        "ps",
        "dev",
        "run",
        "help",
        "doctor",
        "validate",
    ],
    "gated_make_targets": ["deploy", "release", "publish", "push", "promote", "rollback"],
}
DEFAULT_POLICY["generate"] = GENERATE_POLICY
MCP_CATALOG = {
    "github": {
        "type": "http",
        "url": "https://api.githubcopilot.com/mcp/",
        "headers": {"Authorization": "Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}"},
    },
    "sentry": {"type": "http", "url": "https://mcp.sentry.dev/mcp"},
    "supabase": {"type": "http", "url": "https://mcp.supabase.com/mcp"},
    "notion": {"type": "http", "url": "https://mcp.notion.com/mcp"},
    "playwright": {"type": "stdio", "command": "npx", "args": ["-y", "@playwright/mcp@latest"]},
}
GENERATED_DENY_READS = [
    "Read(**/node_modules/**)",
    "Read(**/.venv/**)",
    "Read(**/__pycache__/**)",
    "Read(**/.mypy_cache/**)",
    "Read(**/.ruff_cache/**)",
    "Read(**/.terraform/**)",
]
UNITY_DENY = [
    "Read(Library/**)",
    "Read(Temp/**)",
    "Read(Logs/**)",
    "Read(obj/**)",
    "Edit(Library/**)",
    "Edit(Temp/**)",
    "Edit(Logs/**)",
    "Edit(obj/**)",
]
HINTS.update(
    {
        "GENERATE": ("Generated from the detected stack; review the diff before --fix.", ""),
        "GENERATE_USER_MCP": (
            "User-scope MCP servers live in ~/.claude.json, written by the CLI only.",
            DOCS + "mcp",
        ),
    }
)

FORMAT_HOOK = r'''#!/usr/bin/env python3
"""PostToolUse formatter: formats the edited file with the project's own tools. Never blocks."""
import json, os, shutil, subprocess, sys

def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    path = (data.get("tool_input") or {}).get("file_path") or ""
    if not path or not os.path.isfile(path):
        return 0
    root = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    ext = os.path.splitext(path)[1].lower()
    local_prettier = os.path.join(root, "node_modules", ".bin", "prettier")
    cmd = None
    if ext in (".py", ".pyi") and shutil.which("ruff"):
        cmd = ["ruff", "format", "--quiet", path]
    elif ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css", ".scss", ".json", ".vue") and os.path.exists(local_prettier):
        cmd = [local_prettier, "--write", "--log-level", "warn", path]
    elif ext in (".tf", ".tfvars") and shutil.which("terraform"):
        cmd = ["terraform", "fmt", path]
    elif ext == ".go" and shutil.which("gofmt"):
        cmd = ["gofmt", "-w", path]
    if cmd:
        try:
            subprocess.run(cmd, cwd=root, timeout=25, capture_output=True)
        except Exception:
            pass
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''


def detect_stack(repo: Path) -> dict:
    s: dict[str, Any] = {"make": [], "scripts": {}, "pm": None}
    exists = lambda *names: any((repo / n).exists() for n in names)
    s["python"] = exists("pyproject.toml", "requirements.txt", "setup.py", "uv.lock", "poetry.lock")
    s["uv"] = exists("uv.lock")
    pkg = read_text(repo / "package.json")
    if pkg:
        try:
            pj = json.loads(pkg)
        except json.JSONDecodeError:
            pj = {}
        s["scripts"] = pj.get("scripts") or {}
        deps = {**(pj.get("dependencies") or {}), **(pj.get("devDependencies") or {})}
        s["pm"] = (
            "pnpm"
            if exists("pnpm-lock.yaml")
            else "yarn"
            if exists("yarn.lock")
            else "bun"
            if exists("bun.lockb", "bun.lock")
            else "npm"
        )
        s["web_ui"] = any(
            d in deps for d in ("react", "next", "vue", "svelte", "vite", "@angular/core")
        )
        s["sentry"] = any(d.startswith("@sentry/") for d in deps)
        s["supabase"] = "@supabase/supabase-js" in deps
    py_blob = " ".join(
        filter(None, (read_text(repo / f) for f in ("pyproject.toml", "requirements.txt")))
    ).lower()
    s["sentry"] = s.get("sentry") or "sentry-sdk" in py_blob or "sentry_sdk" in py_blob
    s["supabase"] = s.get("supabase") or "supabase" in py_blob or (repo / "supabase").is_dir()
    s["unity"] = (repo / "ProjectSettings" / "ProjectVersion.txt").exists()
    s["docker"] = exists(
        "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"
    )
    s["compose"] = exists(
        "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"
    )
    s["k8s"] = exists("k8s", "kubernetes", "manifests", "kustomization.yaml", "deploy/k8s")
    s["helm"] = exists("Chart.yaml", "charts", "helm")
    s["terraform"] = any(repo.glob("*.tf")) or any(repo.glob("*/*.tf"))
    s["tofu"] = s["terraform"] and bool(shutil.which("tofu")) and not shutil.which("terraform")
    mk = read_text(repo / "Makefile") or ""
    s["make"] = sorted(set(re.findall(r"^([a-zA-Z][\w-]*):(?!=)", mk, re.M)))
    remote = git(repo, "remote", "get-url", "origin") or ""
    s["github"] = "github.com" in remote
    s["gh"] = s["github"] and bool(shutil.which("gh"))
    return s


def generated_permissions(stack: dict, policy: dict) -> dict:
    g, perms = policy["generate"], policy["permissions"]
    allow = [
        "Bash(git status *)",
        "Bash(git diff *)",
        "Bash(git log *)",
        "Bash(git show *)",
        "Bash(git branch *)",
        "Bash(git add *)",
        "Bash(git commit *)",
    ]
    ask: list[str] = []
    for t in stack["make"]:
        if t in g["safe_make_targets"]:
            allow.append(f"Bash(make {t})")
        elif t in g["gated_make_targets"]:
            ask.append(f"Bash(make {t} *)")
    if stack["python"]:
        allow += [
            "Bash(pytest *)",
            "Bash(python -m pytest *)",
            "Bash(ruff check *)",
            "Bash(ruff format *)",
            "Bash(mypy *)",
        ]
        if stack["uv"]:
            allow += [
                "Bash(uv run pytest *)",
                "Bash(uv run ruff *)",
                "Bash(uv run mypy *)",
                "Bash(uv sync *)",
            ]
    if stack["pm"]:
        pm = stack["pm"]
        for name in ("test", "lint", "build", "typecheck", "check", "format"):
            if name in stack["scripts"]:
                allow.append(
                    f"Bash({pm} test *)"
                    if name == "test" and pm == "npm"
                    else f"Bash({pm} run {name} *)"
                )
        allow += ["Bash(npx tsc --noEmit *)", "Bash(npx prettier --check *)"]
    if stack["docker"]:
        allow += ["Bash(docker ps *)", "Bash(docker images *)"]
    if stack["compose"]:
        allow += [
            "Bash(docker compose ps *)",
            "Bash(docker compose logs *)",
            "Bash(docker compose config *)",
            "Bash(docker compose up *)",
            "Bash(docker compose down *)",
        ]
    if stack["k8s"] or stack["helm"]:
        allow += [
            "Bash(kubectl get *)",
            "Bash(kubectl describe *)",
            "Bash(kubectl logs *)",
            "Bash(kubectl diff *)",
            "Bash(kubectl kustomize *)",
            "Bash(kustomize build *)",
        ]
    if stack["helm"]:
        allow += ["Bash(helm template *)", "Bash(helm lint *)", "Bash(helm dependency build *)"]
    if stack["terraform"]:
        tf = "tofu" if stack["tofu"] else "terraform"
        allow += [f"Bash({tf} fmt *)", f"Bash({tf} validate *)", f"Bash({tf} plan *)"]
    if stack["gh"]:
        allow += [
            "Bash(gh pr view *)",
            "Bash(gh pr list *)",
            "Bash(gh pr diff *)",
            "Bash(gh pr checks *)",
            "Bash(gh issue view *)",
            "Bash(gh issue list *)",
            "Bash(gh run list *)",
            "Bash(gh run view *)",
        ]
    allow += g["extra_allow"]
    ask += [f"Bash({p} *)" for p in perms["external_action_prefixes"]] + g["extra_ask"]
    deny = (
        list(perms["required_deny"])
        + GENERATED_DENY_READS
        + (UNITY_DENY if stack["unity"] else [])
        + g["extra_deny"]
    )
    if perms["require_rtk"]:
        allow = [
            rtk_wrap(r, perms["rtk_exempt"]) if (c := command_of(r)) and rtk_rewrites(c) else r
            for r in allow
        ]
        if perms.get("rtk_twin_deny", True):
            ask += [t for r in ask if (t := rtk_twin(r, perms["rtk_exempt"]))]
            deny += [t for r in deny if (t := rtk_twin(r, perms["rtk_exempt"]))]
    return {"allow": dedupe(allow), "ask": dedupe(ask), "deny": dedupe(deny)}


def merge_rules(existing: list[str], wanted: list[str]) -> list[str]:
    out = list(existing)
    for r in wanted:
        if r not in out and not any(covers(e, r) for e in out):
            out.append(r)
    return out


def write_json_merged(path: Path, wanted: dict, rep: Report, what: str) -> None:
    raw = rep.current(path)
    try:
        data = lenient_json(raw)[0] if raw else {}
    except json.JSONDecodeError:
        rep.add(
            "error",
            "GENERATE",
            path,
            f"{what}: existing file is not valid JSON; run a lint --fix first",
        )
        return
    new = copy.deepcopy(data) if isinstance(data, dict) else {}
    for k, v in wanted.items():
        if k == "permissions":
            p = new.setdefault("permissions", {})
            for lst in ("allow", "ask", "deny"):
                if v.get(lst):
                    p[lst] = merge_rules(p.get(lst) or [], v[lst])
            for k2, v2 in v.items():
                if k2 not in ("allow", "ask", "deny"):
                    p.setdefault(k2, v2)
        elif k == "hooks":
            hooks = new.setdefault("hooks", {})
            have = _norm_handlers(hooks)
            for event, groups in v.items():
                for grp in groups:
                    if not (_norm_handlers({event: [grp]}) <= have):
                        hooks.setdefault(event, []).append(grp)
        elif k == "env":
            new.setdefault("env", {})
            for ek, ev in v.items():
                new["env"].setdefault(ek, ev)
        elif k == "mcpServers":
            servers = new.setdefault("mcpServers", {})
            for name, cfg in v.items():
                servers.setdefault(name, cfg)
        else:
            new.setdefault(k, v)
    if new == data:
        return
    added = []
    for lst in ("allow", "ask", "deny"):
        n = len((new.get("permissions") or {}).get(lst) or []) - len(
            ((data or {}).get("permissions") or {}).get(lst) or []
        )
        if n:
            added.append(f"{n} {lst}")
    detail = f" ({', '.join(added)})" if added else ""
    if raw is None:
        rep.add("info", "GENERATE", path, f"{what} created{detail}", True)
        rep.new_files[path] = (dump_json(new), 0o644)
    else:
        rep.add("info", "GENERATE", path, f"{what} completed{detail}", True)
        rep.edit(path, read_text(path) or "", dump_json(new))


def gen_new_file(path: Path, content: str, rep: Report, what: str, mode: int = 0o644) -> None:
    if path.exists() or path in rep.new_files:
        return
    rep.add("info", "GENERATE", path, f"{what} created", True)
    rep.new_files[path] = (content, mode)


def check_commands_for(stack: dict) -> list[str]:
    cmds = [f"make {t}" for t in ("lint", "test", "check") if t in stack["make"]]
    if not cmds and stack["python"]:
        cmds = [("uv run " if stack["uv"] else "") + c for c in ("ruff check .", "pytest -q")]
    if not cmds and stack["pm"]:
        cmds = [f"{stack['pm']} run {n}" for n in ("lint", "typecheck") if n in stack["scripts"]]
        if "test" in stack["scripts"]:
            cmds.append(f"{stack['pm']} test")
    return cmds


def gen_skills(repo: Path, stack: dict, policy: dict, rep: Report) -> None:
    root = repo / ".claude" / "skills"
    wanted = policy["generate"]["skills"]
    cmds = check_commands_for(stack)
    if "check" in wanted and cmds:
        tools = " ".join(f"Bash({c} *)" if " " in c else f"Bash({c})" for c in cmds)
        body = "\n".join(f"{i}. `{c}`" for i, c in enumerate(cmds, 1))
        gen_new_file(
            root / "check" / "SKILL.md",
            f"""---
name: check
description: Run this project's lint and test commands and report only what fails, with file and line. Use before committing or when asked whether the change is done.
allowed-tools: {tools}
---

Run, in order, stopping at the first failing step:

{body}

Report failures only: command, file:line, one-line cause. Do not fix anything unless asked.
If everything passes, say so in one line.
""",
            rep,
            "skill /check",
        )
    if "review-changes" in wanted:
        gen_new_file(
            root / "review-changes" / "SKILL.md",
            """---
name: review-changes
description: Review the uncommitted diff for bugs, missing tests, security issues and violations of this repository's AGENTS.md conventions. Use when asked to review changes before a commit or PR.
allowed-tools: Bash(git diff *) Bash(git status *) Read Grep Glob
---

## Changes

!`git diff HEAD --stat`

## Instructions

1. Read the full diff (`git diff HEAD`) and the files it touches.
2. Check against AGENTS.md conventions, then: correctness, error handling, tests covering
   the change, secrets or credentials, injection, performance traps.
3. Output a list ordered by severity: `file:line - problem - suggested fix`.
   No praise, no restating the diff. If nothing is wrong, say so in one line.
""",
            rep,
            "skill /review-changes",
        )


AGENT_TEMPLATES = {
    "code-reviewer": (
        "Read, Grep, Glob",
        "Reviews code changes for correctness, readability and adherence to AGENTS.md "
        "conventions. Use proactively after significant edits.",
        "Review the requested code. Report issues ordered by severity as `file:line - "
        "problem - fix`. "
        "Never edit files. Never repeat code that is fine.",
    ),
    "test-runner": (
        "Read, Grep, Glob, Bash",
        "Runs the project's test and lint commands and summarizes failures. Use when tests "
        "need to be run or diagnosed.",
        "Run the project's checks (see AGENTS.md > Commands). Return only failing tests or "
        "lint errors with "
        "file:line and the probable cause. Do not modify source files.",
    ),
    "security-auditor": (
        "Read, Grep, Glob",
        "Audits code and configuration for secrets, injection, unsafe deserialization, weak "
        "auth and risky dependencies. Use before releases or on security-sensitive changes.",
        "Audit the requested scope. Report findings as `severity - file:line - issue - "
        "remediation`. "
        "Never print secret values; name the variable or file instead.",
    ),
    "infra-reviewer": (
        "Read, Grep, Glob",
        "Reviews Kubernetes manifests, Helm charts, Dockerfiles and Terraform for security, "
        "resource limits, probes and drift from conventions. Use on infrastructure changes.",
        "Review the infrastructure files in scope: pinned images, non-root users, resource "
        "requests and limits, "
        "probes, secrets from the vault (never inline), least-privilege RBAC. Report "
        "`file:line - issue - fix`. Never apply anything.",
    ),
}


def gen_agents(repo: Path, stack: dict, policy: dict, rep: Report) -> None:
    for name in policy["generate"]["agents"]:
        if name not in AGENT_TEMPLATES:
            continue
        if name == "infra-reviewer" and not (
            stack["k8s"] or stack["helm"] or stack["terraform"] or stack["docker"]
        ):
            continue
        if name == "test-runner" and not check_commands_for(stack):
            continue
        tools, desc, body, *model = AGENT_TEMPLATES[name]
        model_line = f"model: {model[0]}\n" if model else ""
        gen_new_file(
            repo / ".claude" / "agents" / f"{name}.md",
            f"---\nname: {name}\ndescription: {desc}\ntools: {tools}\n{model_line}---\n\n{body}\n",
            rep,
            f"subagent {name}",
        )


def gen_mcp(repo: Path, stack: dict, policy: dict, rep: Report) -> None:
    want = policy["generate"]["mcp"]
    servers = {}
    prefer_cli = policy.get("tokens", {}).get("prefer_cli_over_mcp", True)
    if "github" in want and stack["github"] and not (prefer_cli and shutil.which("gh")):
        servers["github"] = MCP_CATALOG["github"]
    if "sentry" in want and stack.get("sentry") and not (prefer_cli and shutil.which("sentry-cli")):
        servers["sentry"] = MCP_CATALOG["sentry"]
    if "supabase" in want and stack.get("supabase"):
        servers["supabase"] = MCP_CATALOG["supabase"]
    if "playwright" in want and stack.get("web_ui"):
        servers["playwright"] = MCP_CATALOG["playwright"]
    servers = dict(list(servers.items())[: policy["mcp"]["max_servers"]])
    if servers:
        write_json_merged(
            repo / ".mcp.json", {"mcpServers": servers}, rep, "MCP servers " + ", ".join(servers)
        )


def generate_project(repo: Path, policy: dict, rep: Report) -> None:
    g = policy["generate"]
    stack = detect_stack(repo)
    log(
        1,
        "stack: "
        + ", ".join(k for k, v in stack.items() if v is True)
        + (f"; make: {' '.join(stack['make'])}" if stack["make"] else ""),
        1,
    )
    if g["project_settings"]:
        wanted: dict[str, Any] = {
            "$schema": policy["scaffold"]["schema_url"],
            "attribution": {"commit": "", "pr": ""},
            "permissions": generated_permissions(stack, policy),
        }
        if g["format_hook"] and (stack["python"] or stack["pm"] or stack["terraform"]):
            gen_new_file(
                repo / ".claude" / "hooks" / "format.py", FORMAT_HOOK, rep, "formatter hook", 0o755
            )
            wanted["hooks"] = {
                "PostToolUse": [
                    {
                        "matcher": "Edit|Write",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "python3",
                                "args": ["${CLAUDE_PROJECT_DIR}/.claude/hooks/format.py"],
                                "timeout": 30,
                            }
                        ],
                    }
                ]
            }
        write_json_merged(repo / ".claude" / "settings.json", wanted, rep, "project settings")
    gen_skills(repo, stack, policy, rep)
    gen_agents(repo, stack, policy, rep)
    gen_mcp(repo, stack, policy, rep)
    for entry in (".claude/settings.local.json", "CLAUDE.local.md"):
        if (repo / ".git").exists() and not is_ignored(repo, entry):
            add_gitignore(repo, entry, rep)


def generate_user(policy: dict, rep: Report) -> None:
    g, perms = policy["generate"], policy["permissions"]
    if g["user_settings"]:
        wanted: dict[str, Any] = {
            "$schema": policy["scaffold"]["schema_url"],
            "attribution": {"commit": "", "pr": ""},
            "permissions": {
                "deny": [
                    "Read(~/.ssh/**)",
                    "Read(~/.aws/**)",
                    "Read(~/.kube/**)",
                    "Read(~/.gnupg/**)",
                    "Read(~/.vault-token)",
                    "Read(~/.config/gh/hosts.yml)",
                ],
                "disableBypassPermissionsMode": "disable",
            },
        }
        if policy.get("tokens", {}).get("hold_cross_session", True):
            wanted["crossSessionInbound"] = "hold"
        if (
            perms["require_rtk"]
            and RTK["genuine"]
            and (RTK["version"] is None or RTK["version"] >= RTK_NATIVE_HOOK)
        ):
            wanted["hooks"] = {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "rtk",
                                "args": ["hook", "claude"],
                                "timeout": 10,
                            }
                        ],
                    }
                ]
            }
            wanted["env"] = {"RTK_TELEMETRY_DISABLED": "1"}
        write_json_merged(config_dir() / "settings.json", wanted, rep, "user settings")
    if g["rtk_config"] and perms["require_rtk"]:
        cfg = RTK["config_path"] or rtk_config_path()
        if not cfg.exists() and cfg not in rep.new_files:
            excl = ", ".join(json.dumps(c) for c in g["rtk_exclude_commands"])
            gen_new_file(
                cfg,
                f"""# rtk configuration (generated). Reference: https://github.com/rtk-ai/rtk#configuration

[hooks]
# Commands whose full output matters more than the tokens saved.
exclude_commands = [{excl}]

[retriever]
# Keep the full output of failed or truncated commands for 'rtk recall'.
mode = "sqlite"
""",
                rep,
                "rtk config",
            )
    have = set()
    raw = read_text(Path.home() / ".claude.json")
    if raw:
        try:
            have = set((json.loads(raw).get("mcpServers") or {}))
        except json.JSONDecodeError:
            pass
    for name in g["user_mcp"]:
        spec = MCP_CATALOG.get(name)
        if spec and name not in have and spec.get("type") == "http":
            rep.add(
                "info",
                "GENERATE_USER_MCP",
                "~/.claude.json",
                f"user MCP server {name}: claude mcp add --scope user --transport http "
                f"{name} {spec['url']}",
            )


# --------------------------------------------------------------------------- #
# Token budget: what is loaded into every session, and levers to shrink it
# --------------------------------------------------------------------------- #

DEFAULT_POLICY["tokens"] = {
    "max_always_loaded": 10000,  # warn above this estimate (tokens, bytes/4)
    "skill_description_chars": 400,  # listing cost per skill, every turn
    "prefer_cli_over_mcp": True,  # docs: gh / sentry-cli beat an MCP server's tool listing
    "hold_cross_session": True,  # generated user settings: crossSessionInbound = hold
    "compact_instructions": True,  # generated CLAUDE.md gets a compaction section
    "mcp_server_estimate": 150,  # deferred tool listing: names + server instructions, per server
    "agent_pack_tokens": 1000,  # warn when one agents/ subdirectory lists more than this
}
GENERATED_DENY_READS.extend(
    [
        "Read(**/coverage/**)",
        "Read(**/.next/**)",
        "Read(**/dist/**)",
        "Read(**/*.min.js)",
        "Read(**/*.map)",
    ]
)
AGENT_TEMPLATES["test-runner"] = AGENT_TEMPLATES["test-runner"] + ("haiku",)
COMPACT_SECTION = """
## Compact instructions

When compacting, keep: the task goal, decisions taken, files changed, failing test names
and error lines. Drop: full command output, file listings, passing test logs.
"""
HINTS.update(
    {
        "TOKEN_AGENT_PACK": (
            "Every subagent's name and description is listed to the main agent in every "
            "request. Move rarely used packs into a plugin you enable per project (/plugin), "
            "or out of the agents directory.",
            DOCS + "plugins/overview",
        ),
        "TOKEN_BUDGET": (
            "Everything here is re-sent with every request: trim CLAUDE.md, scope rules "
            "with paths:, move procedures to skills.",
            DOCS + "costs#reduce-token-usage",
        ),
        "TOKEN_SKILL_DESC": (
            "Skill descriptions are listed every turn; keep the key use case in a sentence or two.",
            DOCS + "skills#skill-descriptions-are-cut-short",
        ),
        "MCP_PREFER_CLI": (
            "A CLI adds no per-tool listing: prefer it to the MCP server when installed.",
            DOCS + "costs#reduce-mcp-server-overhead",
        ),
        "TOKEN_MODEL": (
            "Sonnet handles most coding tasks; reserve Opus for complex reasoning.",
            DOCS + "costs#choose-the-right-model",
        ),
        "TOKEN_LSP": (
            "Code intelligence plugins replace grep + multiple file reads with one symbol lookup.",
            DOCS + "costs#install-code-intelligence-plugins-for-typed-languages",
        ),
        "TOKEN_IMPORTS": (
            "Imported files load at launch too: splitting into @imports organizes, it does "
            "not save tokens.",
            DOCS + "memory#my-claude-md-is-too-large",
        ),
        "TOKEN_SUBAGENT_MODEL": (
            "Verbose, mechanical subagents (test runs, log triage) can run on a smaller model.",
            DOCS + "costs#delegate-verbose-operations-to-subagents",
        ),
    }
)


def est(text: str) -> int:
    return len(strip_html_comments(text).encode()) // 4


def _with_imports(path: Path, seen: set, depth: int = 0) -> list[tuple[Path, int]]:
    rp = path.resolve()
    if rp in seen or depth > 4 or not path.is_file():
        return []
    seen.add(rp)
    text = read_text(path) or ""
    out = [(path, est(text))]
    for _, target in import_targets(path, text):
        out += _with_imports(target, seen, depth + 1)
    return out


def _unscoped_rules(root: Path, seen: set) -> list[tuple[Path, int]]:
    out = []
    for f in sorted((root / "rules").rglob("*.md")) if (root / "rules").is_dir() else []:
        meta, _ = split_frontmatter(read_text(f) or "")
        if not meta or "paths" not in meta:
            out += _with_imports(f, seen)
    return out


def _skill_listing(roots: list[Path], rep: Report, policy: dict) -> list[tuple[Path, int]]:
    out = []
    limit = policy["tokens"]["skill_description_chars"]
    for root in roots:
        for sk in sorted(root.glob("skills/*/SKILL.md")):
            if "synced" in sk.parts:
                continue
            meta, _ = split_frontmatter(read_text(sk) or "")
            meta = meta or {}
            if meta.get("disable-model-invocation", "").lower() in ("true", "yes", "on", "1"):
                continue
            desc = meta.get("description", "") + meta.get("when_to_use", "")
            if len(desc) > limit:
                rep.add(
                    "info",
                    "TOKEN_SKILL_DESC",
                    sk,
                    f"description {len(desc)} chars, listed every turn (target <= {limit})",
                )
            out.append((sk, (len(sk.parent.name) + min(len(desc), 1536) + 20) // 4))
        for ag in sorted(root.glob("agents/**/*.md")):
            meta, _ = split_frontmatter(read_text(ag) or "")
            out.append(
                (
                    ag,
                    (
                        len((meta or {}).get("name", ""))
                        + len((meta or {}).get("description", ""))
                        + 20
                    )
                    // 4,
                )
            )
    return out


def listing_group(p: Path) -> str:
    parts = p.parts
    if "agents" in parts:
        i = len(parts) - 1 - parts[::-1].index("agents")
        sub = parts[i + 1] if len(parts) > i + 2 else ""
        base = short_path(str(Path(*parts[: i + 1])))
        return f"{base}/{sub}" if sub else base
    if "skills" in parts:
        i = len(parts) - 1 - parts[::-1].index("skills")
        return short_path(str(Path(*parts[: i + 1])))
    return short_path(str(p))


def token_budget(repo: Path | None, user: bool, policy: dict, rep: Report) -> dict:
    seen: set = set()
    parts: dict[str, list[tuple[Path, int]]] = {
        "instructions": [],
        "rules": [],
        "listing": [],
        "memory": [],
        "mcp": [],
    }
    cfg = config_dir()
    parts["instructions"] += _with_imports(cfg / "CLAUDE.md", seen)
    parts["rules"] += _unscoped_rules(cfg, seen)
    roots = [cfg]
    if repo is not None:
        claude_files = [
            repo / "CLAUDE.md",
            repo / ".claude" / "CLAUDE.md",
            repo / "CLAUDE.local.md",
        ]
        present = [f for f in claude_files if f.exists()]
        if not present:
            present = [
                f for f in (repo / "AGENTS.md", repo / ".claude" / "AGENTS.md") if f.exists()
            ]
        for f in present:
            parts["instructions"] += _with_imports(f, seen)
        parts["rules"] += _unscoped_rules(repo / ".claude", seen)
        roots.append(repo / ".claude")
        roots += [p for p in find_plugin_roots(repo)]
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(repo.resolve()))
        mem = cfg / "projects" / slug / "memory" / "MEMORY.md"
        if mem.exists():
            text = read_text(mem) or ""
            clipped = "\n".join(text.splitlines()[:200])[:25_000]
            parts["memory"].append((mem, est(clipped)))
        servers = {}
        try:
            servers.update(
                (json.loads(read_text(repo / ".mcp.json") or "{}").get("mcpServers") or {})
            )
        except json.JSONDecodeError:
            pass
        try:
            cj = json.loads(read_text(Path.home() / ".claude.json") or "{}")
            servers.update(cj.get("mcpServers") or {})
            servers.update(
                ((cj.get("projects") or {}).get(str(repo.resolve())) or {}).get("mcpServers") or {}
            )
        except json.JSONDecodeError:
            pass
        per = policy["tokens"]["mcp_server_estimate"]
        parts["mcp"] = [(Path(f"mcp:{n}"), per) for n in servers]
    parts["listing"] += _skill_listing(roots, rep, policy)
    total = sum(t for items in parts.values() for _, t in items)
    groups: dict[str, list[int]] = {}
    for p, t in parts["instructions"] + parts["rules"] + parts["memory"]:
        groups.setdefault(short_path(str(p)), []).append(t)
    for p, t in parts["listing"]:
        groups.setdefault(listing_group(p), []).append(t)
    if parts["mcp"]:
        groups["MCP servers"] = [t for _, t in parts["mcp"]]
    grouped = sorted(((g, len(v), sum(v)) for g, v in groups.items()), key=lambda x: -x[2])
    pack_limit = policy["tokens"].get("agent_pack_tokens", 1000)
    for g, n, t in grouped:
        if "/agents" in g and n >= 5 and t >= pack_limit:
            rep.add(
                "warn", "TOKEN_AGENT_PACK", g, f"{n} subagents ~{t} tokens listed in every request"
            )
    imported = [
        (p, t)
        for p, t in parts["instructions"]
        if p.name not in ("CLAUDE.md", "AGENTS.md", "CLAUDE.local.md")
    ]
    if imported and sum(t for _, t in imported) > 1500:
        rep.add(
            "info",
            "TOKEN_IMPORTS",
            imported[0][0],
            f"{len(imported)} imported file(s), ~{sum(t for _, t in imported)} tokens loaded "
            f"at launch",
        )
    if total > policy["tokens"]["max_always_loaded"]:
        rep.add(
            "warn",
            "TOKEN_BUDGET",
            repo or cfg,
            f"~{total} tokens loaded in every session (limit "
            f"{policy['tokens']['max_always_loaded']}); "
            "top: " + ", ".join(f"{g} ({n}) ~{t}" for g, n, t in grouped[:3]),
        )
    return {
        "total": total,
        "parts": {k: [(str(p), t) for p, t in v] for k, v in parts.items()},
        "sums": {k: sum(t for _, t in v) for k, v in parts.items()},
        "groups": [{"group": g, "items": n, "tokens": t} for g, n, t in grouped],
        "counts": {
            "skills": sum(1 for p, _ in parts["listing"] if p.name == "SKILL.md"),
            "subagents": sum(1 for p, _ in parts["listing"] if p.name != "SKILL.md"),
        },
    }


def check_token_levers(repo: Path, policy: dict, rep: Report, stack: dict | None = None) -> None:
    if policy["tokens"]["prefer_cli_over_mcp"]:
        try:
            servers = json.loads(read_text(repo / ".mcp.json") or "{}").get("mcpServers") or {}
        except json.JSONDecodeError:
            servers = {}
        for name, cli in (
            ("github", "gh"),
            ("sentry", "sentry-cli"),
            ("aws", "aws"),
            ("gcloud", "gcloud"),
        ):
            if any(name in n.lower() for n in servers) and shutil.which(cli):
                rep.add(
                    "info",
                    "MCP_PREFER_CLI",
                    repo / ".mcp.json",
                    f"{cli} is installed: the '{name}' MCP server adds a tool listing the "
                    f"CLI doesn't",
                )
    for sub in (
        sorted((repo / ".claude" / "agents").glob("*.md"))
        if (repo / ".claude" / "agents").is_dir()
        else []
    ):
        meta, _ = split_frontmatter(read_text(sub) or "")
        text = f"{sub.stem} {(meta or {}).get('description', '')}".lower()
        if re.search(r"\b(test|lint|log|triage|format)", text) and not (meta or {}).get("model"):
            rep.add(
                "info",
                "TOKEN_SUBAGENT_MODEL",
                sub,
                "mechanical subagent without 'model': consider model: haiku",
            )
    user_s = read_text(config_dir() / "settings.json")
    try:
        model = str((json.loads(user_s) if user_s else {}).get("model", ""))
    except json.JSONDecodeError:
        model = ""
    if "opus" in model.lower() and not any(f.code == "TOKEN_MODEL" for f in rep.findings):
        rep.add(
            "info",
            "TOKEN_MODEL",
            config_dir() / "settings.json",
            f"default model {model!r}: Opus for every session and inheriting subagents",
        )
    stack = stack or detect_stack(repo)
    typed = stack["python"] or bool(stack["pm"])
    enabled = []
    for f in (config_dir() / "settings.json", repo / ".claude" / "settings.json"):
        try:
            enabled += list((json.loads(read_text(f) or "{}").get("enabledPlugins") or {}))
        except json.JSONDecodeError:
            pass
    if typed and not any(
        re.search(r"lsp|pyright|typescript|pylsp|basedpyright|vtsls|gopls", p, re.I)
        for p in enabled
    ):
        rep.add(
            "info",
            "TOKEN_LSP",
            repo,
            "no code intelligence plugin enabled for this typed stack (see /plugin)",
        )


def render_token_budget(budget: dict, color: bool, before: dict | None = None) -> str:
    if not budget:
        return ""
    b, r0, g = ("\033[1m", "\033[0m", "\033[32m") if color else ("", "", "")
    sums, counts = budget["sums"], budget.get("counts", {})
    labels = {
        "instructions": "instruction files + imports",
        "rules": "unscoped rules",
        "listing": f"listing: {counts.get('skills', 0)} skills, {counts.get('subagents', 0)} subagents",
        "memory": "auto memory index",
        "mcp": "MCP servers (deferred, est.)",
    }
    # Before/after: when a --fix pass changed the budget, show the delta actually
    # realised; otherwise show the potential gain still on the table.
    head = f"{b}TOKENS{r0}  ~{budget['total']} tokens loaded in every session (estimate, bytes/4)"
    if before and before.get("total") is not None:
        delta = before["total"] - budget["total"]
        if delta > 0:
            head += f"  {g}(was ~{before['total']} before --fix: -{delta} tokens/session){r0}"
        elif delta < 0:
            head += f"  (was ~{before['total']} before: +{-delta})"
    lines = [head]
    for k, label in labels.items():
        if sums.get(k):
            lines.append(f"  {label:40} ~{sums[k]}")
    groups = budget.get("groups", [])[:6]
    if groups:
        lines.append("  biggest groups:")
        lines += [
            f"    {g_['group']:52} {g_['items']:>4} item(s)  ~{g_['tokens']}" for g_ in groups
        ]
    if budget.get("potential"):
        lines.append(
            f"  {g}potential: ~{budget['potential']} tokens/session reclaimable"
            f"{r0} (act with --fix / -i; see --details)"
        )
    lines.append(
        "  habits: /clear between tasks, /context and /usage to check, /skill-doctor for "
        "unused skills,"
        " Sonnet by default, subagents for verbose work"
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Duplicates and interactive review (-i)
# --------------------------------------------------------------------------- #

STOPWORDS = set(
    """a an and are as at be by for from in into is it its of on or that the this to use used using
when with without you your via across any all can will should must who what which also more most very
agent agents skill skills specialist specialists expert experts helps help assistant claude code tasks task
based work works working user users project projects""".split()
)
HINTS.update(
    {
        "DUP_EXACT": (
            "Identical content in several places: every copy is listed (and paid for) separately.",
            "",
        ),
        "DUP_NAME": (
            "Same name in several places: only one wins, the others are dead weight or confusing.",
            DOCS + "skills#resolve-skills-that-share-a-name",
        ),
        "DUP_SIMILAR": (
            "Very similar name and description: the model has to pick between "
            "near-duplicates. Keep one.",
            "",
        ),
        "DUP_FAMILY": (
            "Items generated from one template are not duplicates, but each one is listed "
            "in every request.",
            "",
        ),
        "DUP_ACROSS_PROJECTS": (
            "The same skill copied in many repositories drifts over time; one shared source "
            "is easier to maintain.",
            "",
        ),
        "INTERACTIVE": (
            "Run with -i to review duplicates, packs and long descriptions one by one.",
            "",
        ),
    }
)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOPWORDS}


def _body_hash(text: str) -> str:
    import hashlib

    stripped = text.lstrip("\ufeff \t\r\n")
    if stripped.startswith("---") and (end := stripped.find("\n---", 3)) != -1:
        stripped = stripped[end + 4 :]
    norm = re.sub(r"\s+", " ", stripped).strip()
    return hashlib.sha1(norm.encode()).hexdigest() if len(norm) > 200 else ""


def collect_items(roots: list[Path]) -> list[dict]:
    items = []
    for root in roots:
        for sk in sorted(root.glob("skills/*/SKILL.md")):
            if "synced" in sk.parts:
                continue
            text = read_text(sk) or ""
            meta, _ = split_frontmatter(text)
            meta = meta or {}
            items.append(
                {
                    "kind": "skill",
                    "name": sk.parent.name,
                    "path": sk.parent,
                    "file": sk,
                    "desc": meta.get("description", ""),
                    "hash": _body_hash(text),
                    "lines": text.count("\n") + 1,
                }
            )
        for ag in sorted(root.glob("agents/**/*.md")):
            text = read_text(ag) or ""
            meta, _ = split_frontmatter(text)
            meta = meta or {}
            items.append(
                {
                    "kind": "agent",
                    "name": meta.get("name") or ag.stem,
                    "path": ag,
                    "file": ag,
                    "desc": meta.get("description", ""),
                    "hash": _body_hash(text),
                    "lines": text.count("\n") + 1,
                }
            )
        for cm in sorted(root.glob("commands/**/*.md")):
            text = read_text(cm) or ""
            meta, _ = split_frontmatter(text)
            items.append(
                {
                    "kind": "command",
                    "name": cm.stem,
                    "path": cm,
                    "file": cm,
                    "desc": (meta or {}).get("description", ""),
                    "hash": _body_hash(text),
                    "lines": text.count("\n") + 1,
                }
            )
    for it in items:
        it["words"] = _words(it["name"].replace("-", " ") + " " + it["desc"])
    return items


def find_duplicates(
    items: list[dict], threshold: float = 0.6, focus: set | None = None
) -> list[tuple[str, list[dict]]]:
    """Cluster duplicates. With focus (item indexes), only pairs touching a focus item count."""
    parent = list(range(len(items)))
    reason: dict[int, str] = {}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int, why: str) -> None:
        if focus is not None and i not in focus and j not in focus:
            return
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri
        rank = {"DUP_EXACT": 0, "DUP_NAME": 1, "DUP_SIMILAR": 2}
        cur = reason.get(find(i))
        if cur is None or rank[why] < rank[cur]:
            reason[find(i)] = why

    by_hash: dict[str, list[int]] = {}
    by_name: dict[tuple[str, str], list[int]] = {}
    for i, it in enumerate(items):
        if it["hash"]:
            by_hash.setdefault(it["hash"], []).append(i)
        kind = "skill" if it["kind"] in ("skill", "command") else it["kind"]
        by_name.setdefault((kind, it["name"].lower()), []).append(i)
    # Label each group by its own source: identical body -> EXACT, same name -> NAME.
    # union() keeps the strongest (lowest-rank) reason per cluster, so a cluster that
    # is both an exact and a name match ends up labeled EXACT.
    for why, groups in (("DUP_EXACT", by_hash.values()), ("DUP_NAME", by_name.values())):
        for group in groups:
            for a, b in itertools.combinations(group, 2):
                union(a, b, why)
    # Similarity is O(n^2) within a kind; bucket by kind so it stays quadratic per
    # kind instead of over every item (13s -> sub-second on large user scopes).
    by_kind: dict[str, list[int]] = {}
    for i, it in enumerate(items):
        if len(it["words"]) >= 4:
            by_kind.setdefault(it["kind"], []).append(i)
    for bucket in by_kind.values():
        for a_pos, i in enumerate(bucket):
            wi = items[i]["words"]
            ni = len(wi)
            for j in bucket[a_pos + 1 :]:
                if focus is not None and i not in focus and j not in focus:
                    continue
                wj = items[j]["words"]
                # Jaccard >= threshold is impossible unless the sizes are within
                # the threshold ratio; this prune skips the set ops for most pairs.
                nj = len(wj)
                if (ni if ni < nj else nj) < threshold * (ni if ni > nj else nj):
                    continue
                inter = len(wi & wj)
                if inter and inter / (ni + nj - inter) >= threshold:
                    union(i, j, "DUP_SIMILAR")
    clusters: dict[int, list[dict]] = {}
    for i, it in enumerate(items):
        clusters.setdefault(find(i), []).append(it)
    return [
        (reason.get(r, "DUP_SIMILAR"), members)
        for r, members in clusters.items()
        if len(members) > 1
    ]


def session_duplicates(
    user_roots: list[Path], project_roots: list[Path]
) -> list[tuple[str, list[dict]]]:
    """Duplicates that coexist in one session: user scope alone, then user scope + each project."""
    user_items = collect_items([r for r in user_roots if r.is_dir()])
    seen: set = set()
    out: list[tuple[str, list[dict]]] = []

    def keep(clusters: list[tuple[str, list[dict]]]) -> None:
        for why, members in clusters:
            key = frozenset(str(m["path"]) for m in members)
            if key not in seen:
                seen.add(key)
                out.append((why, members))

    keep(find_duplicates(user_items))
    for pr in project_roots:
        proj = collect_items([pr] if pr.is_dir() else [])
        if not proj:
            continue
        both = proj + user_items
        keep(find_duplicates(both, focus=set(range(len(proj)))))
    return out


def check_duplicates(
    user_roots: list[Path], project_roots: list[Path], rep: Report
) -> list[tuple[str, list[dict]]]:
    dups = session_duplicates(user_roots, project_roots)
    rep.stats["duplicate groups"] = len(dups)
    for why, members in dups:
        names = ", ".join(f"{m['kind']}:{m['name']}" for m in members[:4]) + (
            " ..." if len(members) > 4 else ""
        )
        if why == "DUP_SIMILAR" and is_generated_family(members):
            stem = os.path.commonprefix([m["name"] for m in members]).rstrip("-_")
            toks = sum((len(m["desc"]) + 40) // 4 for m in members)
            rep.add(
                "info",
                "DUP_FAMILY",
                members[0]["path"],
                f"{stem}-*: {len(members)} {members[0]['kind']}s from one template "
                f"(~{toks} tokens/session); not duplicates, a plugin keeps them out of "
                f"unrelated sessions (-i)",
            )
            continue
        level = "warn" if why in ("DUP_EXACT", "DUP_NAME") else "info"
        rep.add(
            level,
            why,
            members[0]["path"],
            f"{len(members)} items loaded together: {names} (review with -i)",
        )
    copies: dict[str, int] = {}
    for pr in project_roots:
        for sk in pr.glob("skills/*/SKILL.md"):
            copies[sk.parent.name] = copies.get(sk.parent.name, 0) + 1
    for name, n in sorted(copies.items(), key=lambda kv: -kv[1]):
        if n >= 5:
            rep.add(
                "info",
                "DUP_ACROSS_PROJECTS",
                f"skill {name}",
                f"copied in {n} projects: a shared plugin or the user scope would keep one copy",
            )
    return dups


# ---- interactive session -------------------------------------------------- #


def _fr_plural(n: int, singular: str, plural: str | None = None) -> str:
    """French count phrase: '1 groupe', '3 groupes'. In French 0 takes the
    singular. Pass an explicit plural for irregular words."""
    word = singular if abs(n) < 2 else (plural if plural is not None else singular + "s")
    return f"{n} {word}"


def _writable(path: Path) -> bool:
    """True if this path (a file, or a dir to create inside) can be modified.
    Symlinked / synced skills point at a read-only store; editing them raises
    PermissionError, so the interactive review skips them instead of crashing."""
    try:
        # A skill reached through a symlink lives in a managed/synced store; treat it
        # as read-only whatever the file mode says, and check any symlinked ancestor
        # up to the skills root too (skills/<name> is often the link, not the file).
        probe = path
        for _ in range(6):
            if probe.is_symlink():
                return False
            if probe.name in ("skills", "agents", "commands") or probe == probe.parent:
                break
            probe = probe.parent
        return os.access(path.parent, os.W_OK)
    except OSError:
        return False


def _ask(prompt: str, choices: str = "yN") -> str:
    """Read one answer. Case is preserved so a prompt can offer both a
    lowercase key and its uppercase "...for all" variant (e.g. s vs S, a vs A)
    without the two collapsing together. An empty answer falls back to the
    default (the last letter of `choices`, lowercased)."""
    try:
        raw = input(prompt).strip()
    except EOFError:
        return "q"
    return raw or (choices[-1].lower() if choices else "")


def _trash(path: Path, trash_root: Path, log_lines: list[str]) -> None:
    dest = trash_root / str(path.resolve()).lstrip("/")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest))
    log_lines.append(f"mv '{dest}' '{path}'")


# --------------------------------------------------------------------------- #
# Restructuring proposals (plan in every run, applied one by one with -i)
# --------------------------------------------------------------------------- #

DEFAULT_POLICY["restructure"] = {
    "marketplace_name": "personal",  # local marketplace holding the generated plugins
    "min_pack_agents": 3,  # agents/<pack>/<group> with at least this many agents
    "min_skill_family": 3,  # skills sharing a name prefix
    "skill_keep_lines": 150,  # lines kept in SKILL.md when splitting a long skill
    "procedure_min_lines": 15,  # CLAUDE.md section long enough to become a skill
}
HINTS.update(
    {
        "RESTRUCTURE": (
            "A restructuring that makes the setup load less and work better; apply it with "
            "-i (reversible).",
            DOCS + "features-overview",
        ),
    }
)
LANG_PATHS = [
    (r"\b(python|pytest|django|fastapi|pydantic|\.py\b)", "**/*.py"),
    (r"\b(typescript|tsx|react|next\.js|\.ts\b)", "**/*.{ts,tsx}"),
    (r"\b(javascript|jsx|node\.js|\.js\b)", "**/*.{js,jsx,mjs}"),
    (r"\b(terraform|opentofu|\.tf\b)", "**/*.tf"),
    (r"\b(dockerfile|docker compose|compose\.ya?ml)", "**/{Dockerfile*,*compose*.y*ml}"),
    (r"\b(helm|kubernetes|k8s|kustomize|manifest)", "**/*.{yaml,yml}"),
    (r"\b(unity|monobehaviour|c#|\.cs\b)", "**/*.cs"),
    (r"\b(golang|go test|\.go\b)", "**/*.go"),
    (r"\b(sql|postgres|migration|alembic)", "**/*.sql"),
]


FILE_PATHS = [
    ("makefile", "**/Makefile*"),
    ("dockerfile", "**/Dockerfile*"),
    ("docker", "**/{Dockerfile*,*compose*.y*ml}"),
    ("terraform", "**/*.tf"),
    ("helm", "**/*.{yaml,yml,tpl}"),
    ("k8s", "**/*.{yaml,yml}"),
    ("python", "**/*.py"),
    ("django", "**/*.py"),
    ("typescript", "**/*.{ts,tsx}"),
    ("react", "**/*.{ts,tsx,jsx}"),
    ("sql", "**/*.sql"),
    ("migration", "**/migrations/**"),
    ("github-actions", ".github/workflows/**"),
    ("workflow", ".github/workflows/**"),
    ("unity", "**/*.cs"),
    ("csharp", "**/*.cs"),
    ("golang", "**/*.go"),
]


def _sections(text: str) -> list[tuple[str, list[str]]]:
    """Split Markdown into (H2 title, lines) sections, fence-aware. First item: preamble."""
    out: list[tuple[str, list[str]]] = [("", [])]
    fence = False
    for line in text.splitlines():
        if re.match(r"^\s*(```|~~~)", line):
            fence = not fence
        if not fence and re.match(r"^##\s+\S", line):
            out.append((line[3:].strip(), [line]))
        else:
            out[-1][1].append(line)
    return out


def compute_proposals(roots: list[Path], repos: list[Path], policy: dict) -> list[dict]:
    pol = policy["restructure"]
    props: list[dict] = []
    for root in [r for r in roots if r.is_dir()]:
        ad = root / "agents"
        if ad.is_dir():
            packs: dict[Path, list[Path]] = {}
            for f in ad.rglob("*.md"):
                rel = f.relative_to(ad).parts
                if len(rel) >= 2:
                    key = ad / Path(*rel[:2]) if len(rel) > 2 else ad / rel[0]
                    packs.setdefault(key, []).append(f)
            for p, fs in sorted(packs.items(), key=lambda kv: -len(kv[1])):
                if len(fs) >= pol["min_pack_agents"]:
                    tok = sum(
                        (
                            len(
                                ((split_frontmatter(read_text(f) or "")[0]) or {}).get(
                                    "description", ""
                                )
                            )
                            + 40
                        )
                        // 4
                        for f in fs
                    )
                    props.append(
                        {
                            "kind": "agent-pack",
                            "root": root,
                            "path": p,
                            "files": fs,
                            "gain": tok,
                            "title": f"turn {short_path(str(p))} ({len(fs)} agents) into an on-demand plugin",
                        }
                    )
        sd = root / "skills"
        if sd.is_dir():
            fams: dict[str, list[Path]] = {}
            for d in sorted(x for x in sd.iterdir() if x.is_dir() and (x / "SKILL.md").exists()):
                fams.setdefault(d.name.split("-")[0], []).append(d)
            for prefix, ds in fams.items():
                if len(ds) >= pol["min_skill_family"] and len(prefix) > 2:
                    tok = sum(
                        (
                            len(
                                ((split_frontmatter(read_text(d / "SKILL.md") or "")[0]) or {}).get(
                                    "description", ""
                                )
                            )
                            + 30
                        )
                        // 4
                        for d in ds
                    )
                    props.append(
                        {
                            "kind": "skill-family",
                            "root": root,
                            "prefix": prefix,
                            "dirs": ds,
                            "gain": tok,
                            "title": f"group {len(ds)} '{prefix}-*' skills into an on-demand plugin",
                        }
                    )
            for d in sorted(x for x in sd.iterdir() if x.is_dir()):
                sk = d / "SKILL.md"
                text = read_text(sk) or ""
                n = text.count("\n") + 1
                if n > policy["skills"]["max_lines"] and len(_sections(text)) >= 4:
                    props.append(
                        {
                            "kind": "split-skill",
                            "path": sk,
                            "gain": 0,
                            "lines": n,
                            "title": f"split {short_path(str(sk))} ({n} lines) into SKILL.md + references/",
                        }
                    )
        cd = root / "commands"
        if cd.is_dir():
            for f in sorted(cd.glob("*.md")):
                if not (root / "skills" / f.stem).exists():
                    props.append(
                        {
                            "kind": "command-to-skill",
                            "root": root,
                            "path": f,
                            "gain": 0,
                            "title": f"convert command {short_path(str(f))} into skill /{f.stem}",
                        }
                    )
        rd = root / "rules"
        if rd.is_dir():
            for f in sorted(rd.rglob("*.md")):
                text = read_text(f) or ""
                meta, _ = split_frontmatter(text)
                if meta and "paths" in meta:
                    continue
                low = text.lower()
                stem = f.stem.lower()
                by_name = next((g for key, g in FILE_PATHS if key in stem), None)
                if by_name:
                    props.append(
                        {
                            "kind": "rule-paths",
                            "path": f,
                            "glob": by_name,
                            "gain": est(text),
                            "title": f"scope rule {short_path(str(f))} to {by_name}",
                        }
                    )
                    continue
                if any(
                    k in stem
                    for k in (
                        "test",
                        "general",
                        "global",
                        "common",
                        "convention",
                        "guideline",
                        "style",
                    )
                ):
                    continue
                hits = [(glob, len(re.findall(pat, low))) for pat, glob in LANG_PATHS]
                hits = sorted([h for h in hits if h[1] >= 3], key=lambda h: -h[1])
                if hits and (len(hits) == 1 or hits[0][1] >= 2 * hits[1][1]):
                    props.append(
                        {
                            "kind": "rule-paths",
                            "path": f,
                            "glob": hits[0][0],
                            "gain": est(text),
                            "title": f"scope rule {short_path(str(f))} to {hits[0][0]}",
                        }
                    )
    cfgs = [config_dir() / "CLAUDE.md"] + [
        r / n for r in repos for n in ("CLAUDE.md", ".claude/CLAUDE.md")
    ]
    for c in cfgs:
        text = read_text(c) or ""
        for title, lines in _sections(text)[1:]:
            steps = sum(1 for l in lines if re.match(r"^\s*(\d+\.|-|\*)\s+", l))
            if len(lines) >= policy["restructure"]["procedure_min_lines"] and steps >= 6:
                props.append(
                    {
                        "kind": "procedure-to-skill",
                        "path": c,
                        "section": title,
                        "gain": est("\n".join(lines)),
                        "title": f"move procedure '{title}' from {short_path(str(c))} into a skill",
                    }
                )

    def _applicable(p: dict) -> bool:
        # Drop proposals whose targets can't be written (symlinked / synced stores),
        # so the interactive review never offers a move or edit that will fail.
        if p["kind"] in ("split-skill", "command-to-skill", "rule-paths", "procedure-to-skill"):
            return _writable(p["path"])
        if p["kind"] == "skill-family":
            return all(_writable(d) for d in p["dirs"])
        if p["kind"] == "agent-pack":
            return all(_writable(f) for f in p["files"])
        return True

    return sorted((p for p in props if _applicable(p)), key=lambda p: -p["gain"])


def _local_marketplace(policy: dict) -> tuple[Path, str]:
    name = policy["restructure"]["marketplace_name"]
    return config_dir() / "local-marketplace", name


def _register_plugin(plugin: str, desc: str, policy: dict, restore: list[str]) -> None:
    mk, name = _local_marketplace(policy)
    mf = mk / ".claude-plugin" / "marketplace.json"
    try:
        data = json.loads(read_text(mf) or "{}")
    except json.JSONDecodeError:
        data = {}
    data.setdefault("name", name)
    data.setdefault("owner", {"name": "local"})
    plugins = data.setdefault("plugins", [])
    if not any(p.get("name") == plugin for p in plugins):
        plugins.append({"name": plugin, "source": f"./plugins/{plugin}", "description": desc})
    mf.parent.mkdir(parents=True, exist_ok=True)
    mf.write_text(dump_json(data), encoding="utf-8")
    pdir = mk / "plugins" / plugin / ".claude-plugin"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "plugin.json").write_text(
        dump_json({"name": plugin, "version": "1.0.0", "description": desc}), encoding="utf-8"
    )
    us = config_dir() / "settings.json"
    try:
        udata = json.loads(read_text(us) or "{}")
    except json.JSONDecodeError:
        return
    km = udata.setdefault("extraKnownMarketplaces", {})
    if name not in km:
        backup([us])
        km[name] = {"source": {"source": "directory", "path": str(mk)}}
        us.write_text(dump_json(udata), encoding="utf-8")


def apply_proposal(p: dict, policy: dict, restore: list[str], trash_root: Path) -> str:
    kind = p["kind"]
    mk, mname = _local_marketplace(policy)
    if kind in ("agent-pack", "skill-family"):
        if kind == "agent-pack":
            plugin = slugify("-".join(p["path"].relative_to(p["root"] / "agents").parts))
            target = mk / "plugins" / plugin / "agents"
            target.mkdir(parents=True, exist_ok=True)
            for f in p["files"]:
                dest = target / f.name
                if dest.exists():
                    dest = target / f"{slugify(f.parent.name)}-{f.name}"
                shutil.move(str(f), str(dest))
                restore.append(f"mkdir -p '{f.parent}' && mv '{dest}' '{f}'")
            for d in sorted({f.parent for f in p["files"]}, key=lambda x: -len(x.parts)):
                try:
                    d.rmdir()
                except OSError:
                    pass
            desc = f"{len(p['files'])} subagents from {p['path'].name}"
        else:
            plugin = slugify(p["prefix"] + "-skills")
            target = mk / "plugins" / plugin / "skills"
            target.mkdir(parents=True, exist_ok=True)
            for d in p["dirs"]:
                dest = target / d.name
                if dest.exists():
                    dest = target / f"{slugify(d.parent.name)}-{d.name}"
                shutil.move(str(d), str(dest))
                restore.append(f"mv '{dest}' '{d}'")
            desc = f"{len(p['dirs'])} {p['prefix']} skills"
        _register_plugin(plugin, desc, policy, restore)
        return (
            f"plugin '{plugin}@{mname}' created, not loaded anywhere yet. In a project that "
            f"needs it: /plugin -> "
            f"marketplace '{mname}' -> install '{plugin}' with the project scope"
            + (
                " (its skills are then invoked as /"
                + plugin
                + ":<skill>, or by their bare name when unique)"
                if kind == "skill-family"
                else ""
            )
        )
    if kind == "split-skill":
        sk: Path = p["path"]
        text = read_text(sk) or ""
        backup([sk])
        stripped = text.lstrip("\ufeff \t\r\n")
        head, body = "", text
        if stripped.startswith("---") and (end := stripped.find("\n---", 3)) != -1:
            head, body = stripped[: end + 4] + "\n", stripped[end + 4 :]
        secs = _sections(body)
        keep, moved, count = [secs[0]], [], len(secs[0][1])
        for title, lines in secs[1:]:
            if count + len(lines) <= policy["restructure"]["skill_keep_lines"] and not moved:
                keep.append((title, lines))
                count += len(lines)
            else:
                moved.append((title, lines))
        if len(moved) < 1:
            return "nothing to split"
        refdir = sk.parent / "references"
        refdir.mkdir(exist_ok=True)
        links = []
        for title, lines in moved:
            name = slugify(title)[:40] + ".md"
            (refdir / name).write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
            links.append(f"- {title}: read [references/{name}](references/{name}) when needed")
        new = (
            head
            + "\n".join(l for _, ls in keep for l in ls).rstrip()
            + "\n\n## Additional resources\n\n"
            + "\n".join(links)
            + "\n"
        )
        sk.write_text(new, encoding="utf-8")
        return f"SKILL.md now {new.count(chr(10)) + 1} lines, {len(moved)} section(s) in references/ (backup in ~/.cache)"
    if kind == "command-to-skill":
        cmd_file: Path = p["path"]
        dest = p["root"] / "skills" / cmd_file.stem / "SKILL.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(cmd_file), str(dest))
        restore.append(f"mv '{dest}' '{cmd_file}'; rmdir '{dest.parent}'")
        return f"/{cmd_file.stem} is now a skill (same command name)"
    if kind == "rule-paths":
        f = p["path"]
        text = read_text(f) or ""
        backup([f])
        f.write_text(set_frontmatter(text, {"paths": p["glob"]}), encoding="utf-8")
        return f"rule loads only for {p['glob']}"
    if kind == "procedure-to-skill":
        c: Path = p["path"]
        text = read_text(c) or ""
        backup([c])
        secs = _sections(text)
        title = p["section"]
        lines = next(ls for t, ls in secs if t == title)
        slug = slugify(title)[:40]
        root = (
            config_dir()
            if c.parent == config_dir()
            else c.parent / ".claude"
            if c.parent.name != ".claude"
            else c.parent
        )
        skill = root / "skills" / slug / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(lines[1:]).strip()
        skill.write_text(
            f"---\nname: {slug}\ndescription: "
            f"{yaml_scalar('Procedure: ' + title + '. Use when this procedure is needed.')}\n---\n\n{body}\n",
            encoding="utf-8",
        )
        out = [
            l
            for t, ls in secs
            for l in (ls if t != title else [f"## {title}", "", f"Follow the /{slug} skill."])
        ]
        c.write_text("\n".join(out) + "\n", encoding="utf-8")
        restore.append(f"rm -r '{skill.parent}'  # and restore {c.name} from ~/.cache/claude-lint")
        return f"section moved to skill /{slug}; review its description"
    return "unsupported"


def render_proposals(props: list[dict], color: bool) -> str:
    if not props:
        return ""
    b, r0 = ("\033[1m", "\033[0m") if color else ("", "")
    total = sum(p["gain"] for p in props)
    lines = [
        f"{b}RESTRUCTURE{r0}  {len(props)} proposal(s), up to ~{total} tokens less per "
        f"session (apply with -i)"
    ]
    for p in props[:12]:
        gain = f"~{p['gain']} tok/session" if p["gain"] else "per-use"
        lines.append(f"  - {p['title']}  [{gain}]")
    if len(props) > 12:
        lines.append(f"  ... {len(props) - 12} more (all listed in --format json)")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Brief report: what matters, in plain language, in priority order
# --------------------------------------------------------------------------- #

BRIEF_FR = {
    # code: (section, what it means, what to do)
    "API_KEY_LEAK": (
        "security",
        "clé API Anthropic en clair",
        "révoquer la clé (console.anthropic.com) puis retirer la ligne",
    ),
    "SECRET_INLINE": (
        "security",
        "secret écrit en clair dans une config",
        "--fix le remplace par ${VAR} quand c'est possible",
    ),
    "ATTR_TRACE": (
        "security",
        "signature Claude/Anthropic dans des fichiers",
        "--fix retire les lignes dans .claude/, CLAUDE.md, AGENTS.md ; ailleurs à la main",
    ),
    "PERM_EXEC_RUNNER": (
        "security",
        "autorisation trop large (xargs, npx... lancent n'importe quelle commande)",
        "remplacer par des commandes précises",
    ),
    "PERM_TOO_BROAD": ("security", "autorisation qui laisse tout passer", "--fix la retire"),
    "PERM_BYPASS": ("security", "mode sans permissions dans un dépôt", "--fix le retire"),
    "CI_ACTION": ("security", "workflow GitHub Actions à durcir", "voir --details"),
    "CI_TRIGGER": ("security", "workflow déclenchable par des inconnus", "voir --details"),
    "HOOK_MISSING_SCRIPT": (
        "broken",
        "hook qui appelle un script absent : il ne fait rien",
        "corriger le chemin du script",
    ),
    "SKILL_MISSING": (
        "broken",
        "dossier de skill sans SKILL.md : ignoré",
        "ajouter SKILL.md ou supprimer le dossier",
    ),
    "IMPORT_MISSING": (
        "broken",
        "@import vers un fichier introuvable",
        "corriger ou retirer l'import",
    ),
    "AGENT_FRONTMATTER": (
        "broken",
        "fichier dans agents/ qui n'est pas un agent",
        "-i propose de le déplacer",
    ),
    "JSON_INVALID": (
        "broken",
        "fichier JSON illisible : ignoré entièrement",
        "corriger la syntaxe",
    ),
    "SETTINGS_DEAD_KEY": (
        "broken",
        "réglage sans effet à cet endroit (ex. forceLoginOrgUUID dans un dépôt)",
        "le retirer",
    ),
    "MISPLACED": (
        "broken",
        "fichier au mauvais endroit, jamais lu",
        "--fix le déplace quand c'est sûr",
    ),
    "SKILL_NAME": (
        "broken",
        "nom de dossier de skill invalide",
        "renommer le dossier en minuscules-tirets",
    ),
    "ATTR_HOOK_CONFLICT": (
        "broken",
        "hook commit-msg existant qui ne retire pas les signatures",
        "y ajouter les 2 lignes sed (voir --details)",
    ),
    "PLUGIN_MANIFEST": ("broken", "manifeste de plugin à corriger", "voir --details"),
    "HOOK_IF_DEAD": ("broken", "condition de hook jamais évaluée", "--fix la retire"),
    "RTK_NO_HOOK": ("broken", "rtk installé mais pas branché", "--fix --user l'ajoute"),
    "RTK_MISSING": (
        "broken",
        "rtk exigé mais pas installé",
        "installer rtk, ou require_rtk = false pour l'esquiver",
    ),
    "LLMTRIM_MISSING": (
        "broken",
        "subagents de routage llmtrim mais llmtrim absent",
        "installer llmtrim, ou -i pour retirer ces agents",
    ),
    "TOKEN_AGENT_PACK": (
        "tokens",
        "packs de subagents listés à chaque requête",
        "-i : les transformer en plugins à activer par projet",
    ),
    "DUP_FAMILY": (
        "tokens",
        "familles d'agents/skills générés sur un même modèle (pas des doublons)",
        "-i : en faire un plugin ou les mettre de côté",
    ),
    "TOKEN_SKILL_DESC": (
        "tokens",
        "descriptions de skills trop longues (relues à chaque tour)",
        "-i propose une version courte",
    ),
    "SKILL_LONG": (
        "tokens",
        "skills de plus de 500 lignes",
        "-i : découper en SKILL.md + references/",
    ),
    "INSTR_LONG": (
        "tokens",
        "fichiers d'instructions de plus de 200 lignes",
        "-i : sortir les procédures dans des skills",
    ),
    "RULE_UNSCOPED": (
        "tokens",
        "règles chargées partout faute de 'paths:'",
        "-i propose le bon filtre quand il est évident",
    ),
    "TOKEN_MODEL": (
        "tokens",
        "Opus par défaut pour toutes les sessions",
        "-i propose Sonnet par défaut (/model opus au besoin)",
    ),
    "MCP_PREFER_CLI": (
        "tokens",
        "serveur MCP alors que la CLI équivalente est installée",
        "retirer le serveur (gh fait le travail)",
    ),
    "TOKEN_SUBAGENT_MODEL": (
        "tokens",
        "subagents mécaniques sans modèle léger",
        "ajouter 'model: haiku'",
    ),
    "DUP_EXACT": ("dups", "copies identiques chargées ensemble", "-i : choisir celle à garder"),
    "DUP_NAME": ("dups", "même nom chargé deux fois (un seul sert)", "-i : choisir celle à garder"),
    "DUP_SIMILAR": (
        "dups",
        "quasi-doublons (nom et description très proches)",
        "-i : garder la meilleure",
    ),
    "DUP_ACROSS_PROJECTS": (
        "dups",
        "même skill copié dans beaucoup de dépôts",
        "le mettre dans un plugin partagé",
    ),
}
SECTION_TITLES = {
    "security": "1. SÉCURITÉ ET RÈGLES DU PORTEFEUILLE (à traiter d'abord)",
    "broken": "2. CASSÉ : configuré mais ne fonctionne pas",
    "tokens": "3. TOKENS : ce qui alourdit chaque session",
    "dups": "4. DOUBLONS",
}
BRIEF_EN = {
    "API_KEY_LEAK": (
        "security",
        "plaintext Anthropic API key",
        "revoke the key (console.anthropic.com), then remove the line",
    ),
    "SECRET_INLINE": (
        "security",
        "secret written in cleartext in a config",
        "--fix replaces it with ${VAR} where possible",
    ),
    "ATTR_TRACE": (
        "security",
        "Claude/Anthropic signature in files",
        "--fix strips lines in .claude/, CLAUDE.md, AGENTS.md; elsewhere by hand",
    ),
    "PERM_EXEC_RUNNER": (
        "security",
        "over-broad allow rule (xargs, npx... run any command)",
        "replace with specific commands",
    ),
    "PERM_TOO_BROAD": ("security", "allow rule that lets everything through", "--fix removes it"),
    "PERM_BYPASS": ("security", "permission-bypass mode in a repository", "--fix removes it"),
    "CI_ACTION": ("security", "GitHub Actions workflow to harden", "see --details"),
    "CI_TRIGGER": ("security", "workflow triggerable by strangers", "see --details"),
    "HOOK_MISSING_SCRIPT": (
        "broken",
        "hook calling a missing script: it does nothing",
        "fix the script path",
    ),
    "SKILL_MISSING": (
        "broken",
        "skill folder without SKILL.md: ignored",
        "add SKILL.md or delete the folder",
    ),
    "IMPORT_MISSING": ("broken", "@import to a missing file", "fix or remove the import"),
    "AGENT_FRONTMATTER": (
        "broken",
        "file under agents/ that is not an agent",
        "-i offers to move it",
    ),
    "JSON_INVALID": ("broken", "unreadable JSON file: ignored entirely", "fix the syntax"),
    "SETTINGS_DEAD_KEY": (
        "broken",
        "setting with no effect here (e.g. forceLoginOrgUUID in a repo)",
        "remove it",
    ),
    "MISPLACED": ("broken", "file in the wrong place, never read", "--fix moves it when safe"),
    "SKILL_NAME": ("broken", "invalid skill folder name", "rename the folder to lowercase-dashes"),
    "ATTR_HOOK_CONFLICT": (
        "broken",
        "existing commit-msg hook that does not strip signatures",
        "add the 2 sed lines (see --details)",
    ),
    "PLUGIN_MANIFEST": ("broken", "plugin manifest to fix", "see --details"),
    "HOOK_IF_DEAD": ("broken", "hook condition never evaluated", "--fix removes it"),
    "RTK_NO_HOOK": ("broken", "rtk installed but not wired in", "--fix --user adds it"),
    "RTK_MISSING": (
        "broken",
        "rtk required but not installed",
        "install rtk, or set require_rtk = false to skip it",
    ),
    "LLMTRIM_MISSING": (
        "broken",
        "llmtrim route subagents but llmtrim not installed",
        "install llmtrim, or -i to remove those agents",
    ),
    "TOKEN_AGENT_PACK": (
        "tokens",
        "subagent packs listed on every request",
        "-i: turn them into per-project plugins",
    ),
    "DUP_FAMILY": (
        "tokens",
        "families of generated agents/skills from one template (not duplicates)",
        "-i: make a plugin or park them",
    ),
    "TOKEN_SKILL_DESC": (
        "tokens",
        "skill descriptions too long (re-read every turn)",
        "-i offers a short version",
    ),
    "SKILL_LONG": ("tokens", "skills over 500 lines", "-i: split into SKILL.md + references/"),
    "INSTR_LONG": ("tokens", "instruction files over 200 lines", "-i: move procedures into skills"),
    "RULE_UNSCOPED": (
        "tokens",
        "rules loaded everywhere for lack of 'paths:'",
        "-i offers the right filter when obvious",
    ),
    "TOKEN_MODEL": (
        "tokens",
        "Opus as the default for every session",
        "-i offers Sonnet by default (/model opus when needed)",
    ),
    "MCP_PREFER_CLI": (
        "tokens",
        "MCP server while the equivalent CLI is installed",
        "remove the server (gh does the job)",
    ),
    "TOKEN_SUBAGENT_MODEL": (
        "tokens",
        "mechanical subagents without a light model",
        "add 'model: haiku'",
    ),
    "DUP_EXACT": ("dups", "identical copies loaded together", "-i: pick the one to keep"),
    "DUP_NAME": ("dups", "same name loaded twice (only one runs)", "-i: pick the one to keep"),
    "DUP_SIMILAR": (
        "dups",
        "near-duplicates (very close name and description)",
        "-i: keep the best",
    ),
    "DUP_ACROSS_PROJECTS": (
        "dups",
        "same skill copied into many repositories",
        "put it in a shared plugin",
    ),
}
SECTION_TITLES_EN = {
    "security": "1. SECURITY AND PORTFOLIO RULES (handle first)",
    "broken": "2. BROKEN: configured but not working",
    "tokens": "3. TOKENS: what weighs on every session",
    "dups": "4. DUPLICATES",
}


def brief_table() -> dict:
    return BRIEF_EN if LANG == "en" else BRIEF_FR


def section_titles() -> dict:
    return SECTION_TITLES_EN if LANG == "en" else SECTION_TITLES


def home_path(p: str) -> str:
    home = str(Path.home())
    return "~" + p[len(home) :] if p.startswith(home) else p


def proposal_fr(p: dict) -> str:
    path = home_path(str(p.get("path", "")))
    k = p["kind"]
    if k == "agent-pack":
        return f"transformer {path} ({len(p['files'])} agents) en plugin à activer par projet"
    if k == "skill-family":
        return f"regrouper {len(p['dirs'])} skills '{p['prefix']}-*' en plugin"
    if k == "split-skill":
        return f"découper {path} ({p['lines']} lignes) en SKILL.md + references/"
    if k == "command-to-skill":
        return f"convertir la commande {path} en skill"
    if k == "rule-paths":
        return f"limiter la règle {path} aux fichiers {p['glob']}"
    if k == "procedure-to-skill":
        return f"sortir la section « {p['section']} » de {path} dans un skill"
    return p["title"]


def proposal_desc(p: dict) -> str:
    """Language-aware proposal description for the brief report."""
    if LANG != "en":
        return proposal_fr(p)
    path = home_path(str(p.get("path", "")))
    k = p["kind"]
    if k == "agent-pack":
        return f"turn {path} ({len(p['files'])} agents) into a per-project plugin"
    if k == "skill-family":
        return f"group {len(p['dirs'])} '{p['prefix']}-*' skills into a plugin"
    if k == "split-skill":
        return f"split {path} ({p['lines']} lines) into SKILL.md + references/"
    if k == "command-to-skill":
        return f"convert the command {path} into a skill"
    if k == "rule-paths":
        return f"scope the rule {path} to {p['glob']} files"
    if k == "procedure-to-skill":
        return f"move the '{p['section']}' section out of {path} into a skill"
    return p["title"]


def render_brief(
    rep: Report, fixed: list[Finding], fix: bool, repos_count: int, color: bool
) -> str:
    b, dim, r0 = ("\033[1m", "\033[2m", "\033[0m") if color else ("", "", "")
    red, yel, grn = ("\033[31m", "\033[33m", "\033[32m") if color else ("", "", "")
    out = [
        f"{b}claude-lint {VERSION}{r0} - "
        + _loc(f"{repos_count} dépôt(s) analysé(s)", f"{repos_count} repository(ies) scanned")
        + (
            _loc(" + configuration utilisateur", " + user configuration")
            if any("perso" in str(f.path) or ".claude" in str(f.path) for f in rep.findings)
            else ""
        )
    ]
    if fix:
        out.append(
            _loc(
                f"{grn}Corrigé automatiquement : {len(fixed)} point(s).{r0}",
                f"{grn}Fixed automatically: {len(fixed)} item(s).{r0}",
            )
            if fixed
            else _loc("Rien à corriger automatiquement.", "Nothing to fix automatically.")
        )
    budget = getattr(rep, "budget", None) or {}
    by_code: dict[str, list[Finding]] = {}
    for f in rep.findings:
        by_code.setdefault(f.code, []).append(f)
    shown: set[str] = set()
    for section in ("security", "broken", "tokens", "dups"):
        rows = []
        for code, (sec, what, todo) in brief_table().items():
            if sec != section or code not in by_code:
                continue
            items = by_code[code]
            shown.add(code)
            places = sorted({home_path(str(f.path).split(":")[0]) for f in items})
            where = ", ".join(places[:2]) + (f" (+{len(places) - 2})" if len(places) > 2 else "")
            fixable = sum(1 for f in items if f.fixable)
            n = len(items)
            if code == "TOKEN_AGENT_PACK":
                toks = sum(
                    int(m.group(1)) for f in items if (m := re.search(r"~(\d+) tokens", f.message))
                )
                what = f"{what} (~{toks} tokens)"
            level = max(items, key=lambda f: LEVELS.index(f.level) * -1).level
            mark = {"error": f"{red}●{r0}", "warn": f"{yel}●{r0}", "info": f"{dim}○{r0}"}[level]
            rows.append(f"  {mark} {n:>4} × {what}")
            rows.append(f"         {dim}{_loc('où', 'where')} :{r0} {where}")
            rows.append(
                f"         {dim}{_loc('que faire', 'what to do')} :{r0} {todo}"
                + (
                    f"  {grn}[{_loc(f'{fixable} corrigeable(s) par --fix', f'{fixable} fixable with --fix')}]{r0}"
                    if fixable and not fix
                    else ""
                )
            )
        if section == "tokens" and budget:
            rows.insert(
                0,
                "  "
                + _loc(
                    f"Total estimé : ~{budget.get('total', 0)} tokens renvoyés à chaque requête"
                    f" (objectif < {DEFAULT_POLICY['tokens']['max_always_loaded']}). Plus "
                    f"gros postes :",
                    f"Estimated total: ~{budget.get('total', 0)} tokens re-sent on every request"
                    f" (target < {DEFAULT_POLICY['tokens']['max_always_loaded']}). Biggest "
                    f"contributors:",
                ),
            )
            for k, g in enumerate(budget.get("groups", [])[:3], 1):
                rows.insert(
                    k,
                    "     - "
                    + _loc(
                        f"{home_path(g['group'])} : {g['items']} élément(s), ~{g['tokens']} tokens",
                        f"{home_path(g['group'])}: {g['items']} item(s), ~{g['tokens']} tokens",
                    ),
                )
            props = getattr(rep, "proposals", [])
            if props:
                gain = sum(p["gain"] for p in props)
                rows.append(
                    f"  {grn}→{r0} "
                    + _loc(
                        f"{len(props)} restructuration(s) proposée(s), jusqu'à ~{gain} "
                        f"tokens de moins par session. Les 3 plus rentables :",
                        f"{len(props)} restructuring(s) proposed, up to ~{gain} fewer tokens "
                        f"per session. Top 3:",
                    )
                )
                for p in props[:3]:
                    gain_txt = (
                        f"~{p['gain']} tokens"
                        if p["gain"]
                        else _loc("chargé seulement à l'usage", "loaded only when used")
                    )
                    rows.append(f"     - {proposal_desc(p)} ({gain_txt})")
        if rows:
            out += ["", f"{b}{section_titles()[section]}{r0}"] + rows
    rest = [f for f in rep.findings if f.code not in shown]
    if rest:
        cats: dict[str, int] = {}
        for f in rest:
            cats[category(f.code)] = cats.get(category(f.code), 0) + 1
        joined = ", ".join(f"{n} {c}" for c, n in sorted(cats.items(), key=lambda kv: -kv[1]))
        out += [
            "",
            f"{b}"
            + _loc("5. LE RESTE", "5. THE REST")
            + f"{r0} : "
            + _loc(
                f"{len(rest)} remarque(s) mineure(s) ({joined}) : voir --details",
                f"{len(rest)} minor note(s) ({joined}): see --details",
            ),
        ]
    auto = sum(1 for f in rep.findings if f.fixable)
    steps = []
    if auto and not fix:
        steps.append(
            _loc(
                f"lancer avec --fix : corrige {auto} point(s) sans rien demander (sauvegarde "
                f"automatique)",
                f"run with --fix: fixes {auto} item(s) with no prompts (automatic backup)",
            )
        )
    if any(
        c in by_code
        for c in (
            "DUP_EXACT",
            "DUP_NAME",
            "DUP_SIMILAR",
            "TOKEN_AGENT_PACK",
            "TOKEN_SKILL_DESC",
            "TOKEN_MODEL",
        )
    ) or getattr(rep, "proposals", []):
        steps.append(
            _loc(
                "lancer avec -i : doublons, packs et restructurations, un par un, réversible",
                "run with -i: duplicates, packs and restructurings, one by one, reversible",
            )
        )
    steps.append(
        _loc(
            "--details : la liste complète, fichier par fichier",
            "--details: the full list, file by file",
        )
    )
    out += ["", f"{b}" + _loc("ÉTAPES SUIVANTES", "NEXT STEPS") + f"{r0}"] + [
        f"  {i}. {s}" for i, s in enumerate(steps, 1)
    ]
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Interactive review, v2: sections menu, explanations, advice, batch actions
# --------------------------------------------------------------------------- #


class Tty:
    def __init__(self) -> None:
        on = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        c = lambda code: f"\033[{code}m" if on else ""
        self.b, self.dim, self.r, self.red, self.grn, self.yel, self.cyan = (
            c(1),
            c(2),
            c(0),
            c(31),
            c(32),
            c(33),
            c(36),
        )
        self.width = min(shutil.get_terminal_size((110, 40)).columns, 140)

    def rule(self, title: str = "") -> None:
        line = "─" * max(0, self.width - len(title) - 3)
        print(
            f"\n{self.b}── {title} {line}{self.r}"
            if title
            else f"{self.dim}{'─' * self.width}{self.r}"
        )

    def short(self, p: str, width: int) -> str:
        p = home_path(str(p))
        return p if len(p) <= width else p[: width // 3] + "…" + p[-(width - width // 3 - 1) :]


def _affixes(texts: list[str]) -> tuple[str, str]:
    if len(texts) < 2:
        return "", ""
    pre = os.path.commonprefix(texts)
    suf = os.path.commonprefix([t[::-1] for t in texts])[::-1]
    if len(pre) + len(suf) > min(len(t) for t in texts):
        suf = ""
    return pre, suf


def is_generated_family(members: list[dict]) -> bool:
    """Items built from one template (only names or model ids differ): a family, not duplicates."""
    if len(members) < 3:
        return False
    stem = os.path.commonprefix([m["name"] for m in members])
    if len(stem) < 3:
        return False
    bodies = []
    for m in members:
        text = read_text(m["file"]) or ""
        var = m["name"][len(stem) :]
        for v in sorted(
            {var, var.replace("-", "."), var.replace("-", " "), var.replace("-", "_")},
            key=len,
            reverse=True,
        ):
            if v:
                text = text.replace(v, "V")
        text = re.sub(r"\b[\w.-]*V[\w.-]*\b", "V", text)
        bodies.append(re.sub(r"\s+", " ", text))
    top = max(set(bodies), key=bodies.count)
    close = sum(1 for bd in bodies if bd == top or _similar_text(bd, top) >= 0.85)
    return close >= 0.8 * len(members)


def _similar_text(a: str, b: str) -> float:
    wa, wb = set(a.split()), set(b.split())
    return len(wa & wb) / max(1, len(wa | wb))


def _scope_of(m: dict) -> str:
    return "utilisateur" if str(m["path"]).startswith(str(config_dir())) else "projet"


def advice(why: str, members: list[dict]) -> tuple[list[int], str]:
    """Indexes (0-based) to remove and the reason. Never removes a user-scope item because of one
    project: the user copy also serves every other project."""
    scopes = {_scope_of(m) for m in members}
    kind = members[0]["kind"]
    if len(scopes) == 2:
        proj = [i for i, m in enumerate(members) if _scope_of(m) == "projet"]
        if kind in ("skill", "command"):
            return proj, (
                "dans ce projet, la version utilisateur passe avant : la copie du projet "
                "n'est jamais utilisée"
                if why != "DUP_SIMILAR"
                else "proches mais pas identiques : à toi de juger"
            )
        if why == "DUP_EXACT":
            return proj, "copie du projet identique à ta version utilisateur : elle n'apporte rien"
        return [], (
            "pour les agents, la version du projet remplace la tienne dans ce projet : "
            "surcharge probablement voulue, rien n'est proposé"
        )
    mt = [m["file"].stat().st_mtime for m in members]
    best = max(range(len(members)), key=lambda i: (members[i]["lines"], mt[i]))
    if why == "DUP_EXACT":
        return [
            i for i in range(len(members)) if i != best
        ], "contenu identique : une seule copie suffit"
    if why == "DUP_NAME":
        return [
            i for i in range(len(members)) if i != best
        ], "même nom au même niveau : Claude n'en voit qu'un, garder le plus complet"
    return [], "proches mais pas identiques : à toi de juger (rien n'est proposé par défaut)"


class RestoreLog(list):
    """Undo commands, written to restore.sh as soon as each move happens (survives a crash)."""

    def __init__(self, script: Path) -> None:
        super().__init__()
        self.script = script

    def append(self, line: str) -> None:
        super().append(line)
        self.script.parent.mkdir(parents=True, exist_ok=True)
        new = not self.script.exists()
        with self.script.open("a", encoding="utf-8") as fh:
            if new:
                fh.write("#!/bin/sh\n# Annule les déplacements de cette session\n")
            fh.write(line + "\n")
        self.script.chmod(0o755)


def _show_file(path: Path, t: Tty, lines: int = 25) -> None:
    f = path / "SKILL.md" if path.is_dir() else path
    text = (read_text(f) or "").splitlines()
    print(f"{t.dim}┌ {home_path(str(f))}{t.r}")
    for l in text[:lines]:
        print(f"{t.dim}│{t.r} {l[: t.width - 4]}")
    if len(text) > lines:
        print(f"{t.dim}└ … {len(text) - lines} ligne(s) de plus{t.r}")


def _family_to_plugin(members: list[dict], name: str, policy: dict, restore: list[str]) -> str:
    mk, mname = _local_marketplace(policy)
    plugin = slugify(name)
    target = mk / "plugins" / plugin / ("agents" if members[0]["kind"] == "agent" else "skills")
    target.mkdir(parents=True, exist_ok=True)
    for m in members:
        dest = target / Path(m["path"]).name
        shutil.move(str(m["path"]), str(dest))
        restore.append(f"mv '{dest}' '{m['path']}'")
    _register_plugin(plugin, f"{len(members)} {members[0]['kind']}s ({name})", policy, restore)
    return f"plugin '{plugin}@{mname}' créé ; à installer (portée projet) là où il sert : /plugin → {mname}"


def interactive(rep: Report, repos: list[Path], policy: dict, user_scope: bool) -> int:
    t = Tty()
    if not sys.stdin.isatty():
        print(
            "\n-i a besoin d'un vrai terminal (pas d'un pipe) : relance-le directement dans "
            "ton shell."
        )
        return 0
    cfg = config_dir()
    roots = ([cfg] if user_scope else []) + [r / ".claude" for r in repos]
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    trash_root = Path(os.path.expanduser(f"~/.cache/claude-lint/trash/{stamp}"))
    restore = RestoreLog(trash_root / "restore.sh")
    done: dict[str, int] = {}

    def count(action: str) -> None:
        done[action] = done.get(action, 0) + 1

    # ---- inventory
    groups = session_duplicates([cfg] if user_scope else [], [r / ".claude" for r in repos])
    families = [(w, m) for w, m in groups if w == "DUP_SIMILAR" and is_generated_family(m)]
    dups = [(w, m) for w, m in groups if (w, m) not in families]
    order = {"DUP_EXACT": 0, "DUP_NAME": 1, "DUP_SIMILAR": 2}
    dups.sort(key=lambda g: (order[g[0]], -len(g[1])))
    props = compute_proposals(roots, repos, policy)
    limit = policy["tokens"]["skill_description_chars"]
    long_desc = []
    long_desc_ro = 0  # read-only skills skipped (symlinked / synced stores)
    for r in roots:
        for sk in sorted(r.glob("skills/*/SKILL.md")):
            meta, _ = split_frontmatter(read_text(sk) or "")
            if len((meta or {}).get("description", "")) > limit and (meta or {}).get(
                "disable-model-invocation", ""
            ).lower() not in ("true", "yes", "on", "1"):
                if _writable(sk):
                    long_desc.append(sk)
                else:
                    long_desc_ro += 1
    try:
        udata = json.loads(read_text(cfg / "settings.json") or "{}")
    except json.JSONDecodeError:
        udata = {}
    misc = []
    if "opus" in str(udata.get("model", "")).lower():
        misc.append("model")
    misc += [f for f in rep.findings if f.code == "GENERATE_USER_MCP"]

    sections = [
        (
            "dups",
            f"Doublons chargés ensemble ({sum(1 for g in dups if g[0] != 'DUP_SIMILAR')} "
            f"sûrs, {sum(1 for g in dups if g[0] == 'DUP_SIMILAR')} à juger)",
            len(dups),
        ),
        (
            "families",
            f"Familles générées ({len(families)}) : même modèle, noms différents",
            len(families),
        ),
        (
            "restructure",
            f"Restructurations ({len(props)}), ~{sum(p['gain'] for p in props)} "
            f"tokens/session en jeu",
            len(props),
        ),
        ("descriptions", f"Descriptions de skills trop longues ({len(long_desc)})", len(long_desc)),
        ("misc", f"Modèle par défaut et serveurs MCP ({len(misc)})", len(misc)),
    ]
    sections = [s for s in sections if s[2]]
    if not sections:
        print(f"\n{t.grn}Rien à revoir.{t.r}")
        return 0
    t.rule("REVUE INTERACTIVE")
    print(
        f"Rien n'est supprimé : ce que tu retires part dans "
        f"{t.cyan}{home_path(str(trash_root))}{t.r},"
    )
    print("et un script restore.sh annule toute la session. À chaque question : ? pour l'aide.\n")
    for i, (_, label, _) in enumerate(sections, 1):
        print(f"  {t.b}{i}{t.r}. {label}")
    pick = _ask("\nSections à revoir (ex. 1,3 ; Entrée = toutes ; q = quitter) : ")
    if pick.lower() == "q":
        return 0
    chosen = [
        sections[int(x) - 1][0] for x in re.findall(r"\d+", pick) if 0 < int(x) <= len(sections)
    ] or [s[0] for s in sections]

    # ---- duplicates
    if "dups" in chosen:
        t.rule(f"DOUBLONS ({_fr_plural(len(dups), 'groupe')})")
        print(
            f"{t.dim}Un doublon, c'est deux éléments chargés dans la même session : Claude "
            f"n'en utilise qu'un,\n"
            f"ou hésite entre les deux. Les groupes sûrs viennent en premier.{t.r}"
        )
        auto_all = False
        for n, (why, members) in enumerate(dups, 1):
            members = [m for m in members if Path(m["path"]).exists()]
            if len(members) < 2:
                continue
            try:
                remove, reason = advice(why, members)
            except OSError:
                continue
            label = {
                "DUP_EXACT": "copies identiques",
                "DUP_NAME": "même nom",
                "DUP_SIMILAR": "quasi-doublons",
            }[why]
            # Once "apply to all" is on, don't reprint the full listing for every
            # group (dozens of identical project-vs-user pairs); one receipt line each.
            if auto_all and remove:
                for k in remove:
                    if Path(members[k]["path"]).exists():
                        _trash(Path(members[k]["path"]), trash_root, restore)
                        count("doublons retirés")
                        print(
                            f"  {t.grn}✓{t.r} [{n}/{len(dups)}] {label} · {members[0]['name']} → "
                            f"{t.dim}retiré {t.short(str(members[k]['path']), t.width - 24)}{t.r}"
                        )
                continue
            print(
                f"\n{t.b}[{n}/{len(dups)}] {label}{t.r} · "
                f"{_fr_plural(len(members), members[0]['kind'])}"
            )
            descs = [m["desc"] for m in members]
            pre, suf = _affixes(descs)
            if len(pre) + len(suf) > 30:
                print(f"  {t.dim}description commune : « {pre}…{suf} »{t.r}")
            wname = max(len(m["name"]) for m in members)
            for i, m in enumerate(members):
                mark = f"{t.red}✗{t.r}" if i in remove else f"{t.grn}✓{t.r}"
                mtime = dt.datetime.fromtimestamp(m["file"].stat().st_mtime).strftime("%d/%m/%y")
                var = (
                    m["desc"][len(pre) : len(m["desc"]) - len(suf) if suf else None]
                    if len(pre) + len(suf) > 30
                    else m["desc"]
                )
                print(
                    f"  {mark} {t.b}{i + 1:>2}{t.r} {m['name']:<{wname}}  {_scope_of(m):<11} "
                    f"{m['lines']:>4} l.  {mtime}  "
                    f"{t.dim}{t.short(str(m['path']), t.width - wname - 40)}{t.r}"
                )
                if var.strip():
                    print(f"       {t.dim}{var.strip()[: t.width - 8]}{t.r}")
            print(
                f"  {t.yel}Conseil :{t.r} {reason}"
                + (f" → retirer {', '.join(str(i + 1) for i in remove)}" if remove else "")
            )
            if auto_all and remove:
                ans = ""
            else:
                default = "appliquer le conseil" if remove else "tout garder"
                while True:
                    ans = _ask(
                        f"  Entrée = {default} · g = tout garder · 2,3 = retirer ces numéros "
                        f"· v2 = voir le n°2 · "
                        f"A = conseil pour tous les groupes sûrs · s = passer · q = fin des "
                        f"doublons : ",
                        "",
                    )
                    low = ans.lower()
                    if (
                        low.startswith("v")
                        and low[1:].isdigit()
                        and 0 < int(low[1:]) <= len(members)
                    ):
                        _show_file(Path(members[int(low[1:]) - 1]["path"]), t)
                        continue
                    if ans == "?":
                        print(
                            "  Retirer = déplacer dans la corbeille de la session "
                            "(restore.sh pour annuler)."
                        )
                        continue
                    break
            low = ans.lower()
            if low == "q":
                break
            if low in ("s", "g"):
                count("groupes gardés tels quels")
                continue
            if ans == "A":  # apply the advice to every safe group from here on
                auto_all = True
                ans = ""
            targets = (
                remove
                if ans == ""
                else [int(x) - 1 for x in re.findall(r"\d+", ans) if 0 < int(x) <= len(members)]
            )
            for k in targets:
                if not Path(members[k]["path"]).exists():
                    continue
                _trash(Path(members[k]["path"]), trash_root, restore)
                count("doublons retirés")
                print(f"     {t.grn}retiré{t.r} {t.short(str(members[k]['path']), t.width - 12)}")
            if not targets:
                count("groupes gardés tels quels")

    # ---- generated families
    if "families" in chosen:
        t.rule(f"FAMILLES GÉNÉRÉES ({len(families)})")
        print(
            f"{t.dim}Ces éléments suivent le même modèle (seuls le nom ou le modèle d'IA "
            f"changent) : ce ne sont pas des\n"
            f"doublons. Ils coûtent des tokens à chaque requête ; si tu ne t'en sers que "
            f"dans certains projets, un\n"
            f"plugin à activer là-bas est plus léger.{t.r}"
        )
        for n, (_, members) in enumerate(families, 1):
            members = [m for m in members if Path(m["path"]).exists()]
            if len(members) < 2:
                continue
            names = [m["name"] for m in members]
            stem = os.path.commonprefix(names).rstrip("-_") or names[0]
            toks = sum((len(m["desc"]) + 40) // 4 for m in members)
            print(
                f"\n{t.b}[{n}/{len(families)}] {stem}-*{t.r} · "
                f"{_fr_plural(len(members), members[0]['kind'])} · ~{toks} tokens/session"
            )
            print("  " + ", ".join(nm[len(stem) :].lstrip("-_") or nm for nm in names))
            ans = _ask(
                "  Entrée = garder · p = en faire un plugin · k = mettre de côté (parked/) "
                "· q = fin : ",
                "",
            ).lower()
            if ans == "q":
                break
            if ans == "p":
                print("     " + _family_to_plugin(members, stem, policy, restore))
                count("familles transformées en plugin")
            elif ans == "k":
                for m in members:
                    root = next(r for r in roots if str(m["path"]).startswith(str(r)))
                    dest = root / "parked" / Path(m["path"]).relative_to(root)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(m["path"]), str(dest))
                    restore.append(f"mv '{dest}' '{m['path']}'")
                count("familles mises de côté")

    # ---- restructuring
    if "restructure" in chosen:
        t.rule(f"RESTRUCTURATIONS ({len(props)})")
        explain = {
            "agent-pack": "Les agents d'un pack sont listés à chaque requête. En plugin, ils ne se chargent que dans les projets où tu l'installes.",
            "skill-family": "Des skills d'un même domaine, regroupés en plugin : chargés seulement là où ils servent.",
            "split-skill": "Un SKILL.md trop long est lu en entier à chaque usage ; les sections de référence iront dans references/, lues au besoin.",
            "command-to-skill": "Les commandes sont l'ancien format ; un skill garde le même /nom et gagne les options des skills.",
            "rule-paths": "Une règle sans 'paths:' se charge partout ; avec, seulement quand Claude touche ces fichiers.",
            "procedure-to-skill": "Une procédure dans CLAUDE.md est relue à chaque session ; en skill, seulement quand elle sert.",
        }
        accept_kind: set[str] = set()
        skip_kind: set[str] = set()
        last_kind = None
        for n, p in enumerate(props, 1):
            k = p["kind"]
            if k in skip_kind:
                continue
            if k != last_kind:
                print(f"\n{t.dim}{explain[k]}{t.r}")
                last_kind = k
            gain = f"~{p['gain']} tokens/session" if p["gain"] else "chargé seulement à l'usage"
            print(f"{t.b}[{n}/{len(props)}]{t.r} {proposal_fr(p)} {t.dim}({gain}){t.r}")
            if k in accept_kind:
                ans = "y"
            else:
                extra = " · k = mettre de côté" if k == "agent-pack" else ""
                ans = _ask(
                    f"  o = appliquer{extra} · Entrée = passer · A = appliquer tous les "
                    f"'{k}' · S = passer tous les '{k}' · q = fin : ",
                    "",
                )
                if ans == "A":  # apply every proposal of this kind
                    accept_kind.add(k)
                    ans = "o"
                elif ans == "S":  # skip every proposal of this kind
                    skip_kind.add(k)
                    continue
            if ans.lower() == "q":
                break
            if k == "agent-pack" and ans.lower() == "k":
                root = p["root"]
                dest = root / "parked" / p["path"].relative_to(root)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p["path"]), str(dest))
                restore.append(f"mv '{dest}' '{p['path']}'")
                count("packs mis de côté")
            elif ans.lower() in ("o", "y"):
                try:
                    print(f"     {t.grn}{apply_proposal(p, policy, restore, trash_root)}{t.r}")
                    count("restructurations appliquées")
                except (OSError, StopIteration) as e:
                    print(f"     {t.red}échec : {e}{t.r}")

    # ---- long descriptions
    if "descriptions" in chosen:
        t.rule(f"DESCRIPTIONS TROP LONGUES ({len(long_desc)})")
        print(
            f"{t.dim}La description de chaque skill est relue à chaque tour. Version courte "
            f"proposée ; le texte complet\n"
            f"reste dans metadata.full_description.{t.r}"
        )
        if long_desc_ro:
            print(
                f"{t.dim}({_fr_plural(long_desc_ro, 'skill')} en lecture seule "
                f"ignoré{'s' if long_desc_ro > 1 else ''} : liens vers un store synchronisé.){t.r}"
            )
        for n, sk in enumerate(long_desc, 1):
            text = read_text(sk) or ""
            desc = (split_frontmatter(text)[0] or {}).get("description", "")
            short, acc = [], 0
            for s in re.split(r"(?<=[.!?])\s+", desc):
                if acc + len(s) > limit and short:
                    break
                short.append(s)
                acc += len(s) + 1
            proposal = " ".join(short)[:limit]
            print(
                f"\n{t.b}[{n}/{len(long_desc)}] {sk.parent.name}{t.r} {t.dim}{len(desc)} → "
                f"{len(proposal)} caractères{t.r}"
            )
            print(f"  {t.dim}avant :{t.r} {desc[:200]}{'…' if len(desc) > 200 else ''}")
            print(f"  {t.grn}après :{t.r} {proposal}")
            ans = _ask("  o = appliquer · Entrée = passer · q = fin : ", "").lower()
            if ans == "q":
                break
            if ans == "o":
                new = set_frontmatter(text, {"description": proposal})
                new = move_to_metadata(
                    set_frontmatter(new, {"full_description": desc}), ["full_description"]
                )
                try:
                    backup([sk])
                    sk.write_text(new, encoding="utf-8")
                except OSError as e:
                    print(f"     {t.red}échec : {home_path(str(sk))} ({e}){t.r}")
                    continue
                count("descriptions raccourcies")

    # ---- model and MCP
    if "misc" in chosen:
        t.rule("MODÈLE ET MCP")
        for item in misc:
            if item == "model":
                print(
                    f"Modèle par défaut : {t.b}{udata['model']}{t.r}. Opus sert à chaque "
                    f"session et aux subagents qui en héritent."
                )
                if (
                    _ask(
                        "  o = passer à Sonnet par défaut (/model opus quand il le faut) · "
                        "Entrée = garder : ",
                        "",
                    ).lower()
                    == "o"
                ):
                    backup([cfg / "settings.json"])
                    udata["model"] = "sonnet"
                    (cfg / "settings.json").write_text(dump_json(udata), encoding="utf-8")
                    count("modèle changé")
            elif m := re.search(r"(claude mcp add .+)$", item.message):
                print(f"Serveur MCP proposé : {t.b}{m.group(1)}{t.r}")
                if _ask("  o = lancer la commande · Entrée = passer : ", "").lower() == "o":
                    subprocess.run(shlex.split(m.group(1)), check=False)
                    count("serveurs MCP ajoutés")

    # ---- summary
    t.rule("BILAN")
    if done:
        for action, n in done.items():
            print(f"  {n:>4}  {action}")
    else:
        print("  aucune modification")
    if restore:
        print(
            f"\n  Pour tout annuler : {t.cyan}{home_path(str(restore.script))}{t.r}"
            f"  (ou : claude-lint.py --restore)"
        )
    return sum(v for k, v in done.items() if "gardés" not in k)


def restore_trash(target: str | None) -> int:
    """Move every file of a trash session back where it came from (never overwrites).
    Returns 1 when the requested session is missing or nothing could be restored."""
    # Also read trash written under the tool's former name, so sessions from before
    # the rename stay restorable.
    bases = [
        Path(os.path.expanduser(p))
        for p in ("~/.cache/claude-lint/trash", "~/.cache/agent-config-lint/trash")
    ]
    sessions = sorted(d for b in bases if b.is_dir() for d in b.iterdir() if d.is_dir())
    if target:
        root = Path(target).expanduser()
        if not root.is_dir():
            print(f"Session introuvable : {home_path(str(root))}")
            return 1
    elif sessions:
        root = sessions[-1]
    else:
        print("Aucune session à restaurer.")
        return 0
    files = [f for f in sorted(root.rglob("*")) if f.is_file() and f.name != "restore.sh"]
    if not files:
        print(f"Session {root.name} : vide, rien à restaurer.")
        return 0
    moved = skipped = failed = 0
    for f in files:
        dest = Path("/") / f.relative_to(root)
        if dest.exists():
            skipped += 1
            print(f"  déjà présent, laissé dans la corbeille : {home_path(str(dest))}")
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dest))
        except OSError as e:
            failed += 1
            print(f"  échec : {home_path(str(dest))} ({e})")
            continue
        moved += 1
        print(f"  restauré : {home_path(str(dest))}")
    parts = [_fr_plural(moved, "fichier") + " restauré" + ("s" if moved >= 2 else "")]
    if skipped:
        parts.append(_fr_plural(skipped, "déjà présent", "déjà présents"))
    if failed:
        parts.append(_fr_plural(failed, "échec"))
    print(f"Session {root.name} : " + ", ".join(parts) + ".")
    if len(sessions) > 1 and not target:
        print(
            "Autres sessions : "
            + ", ".join(s.name for s in sessions[:-1])
            + " (--restore <dossier>)"
        )
    return 1 if (moved == 0 and failed) else 0


# --------------------------------------------------------------------------- #
# Attribution traces
# --------------------------------------------------------------------------- #


def hooks_dir(repo: Path) -> Path:
    custom = (git(repo, "config", "--get", "core.hooksPath") or "").strip()
    return (repo / custom) if custom else repo / ".git" / "hooks"


def check_attribution(repo: Path, policy: dict, rep: Report, history: bool) -> None:
    pol = policy["attribution"]
    exts = set(pol["scan_extensions"])
    skip = {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        "__pycache__",
        "Library",
        "Temp",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        ".next",
        ".nuxt",
        ".svelte-kit",
        "coverage",
        "target",
        "vendor",
        ".terraform",
        ".gradle",
        ".tox",
        "Pods",
        ".obj",
    }
    self_path = Path(__file__).resolve()
    self_name = self_path.name
    max_bytes = pol["max_file_bytes"]
    scanned = skipped = 0
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in skip and not (d == "worktrees" and Path(dirpath).name == ".claude")
        ]
        for fn in filenames:
            # Suffix check first (a string test), and resolve() only for a file
            # whose name could be this script: resolve() is a syscall per file and
            # dominates the walk on large repos otherwise.
            dot = fn.rfind(".")
            if dot < 0 or fn[dot:] not in exts:
                continue
            p = Path(dirpath) / fn
            if fn == self_name and p.resolve() == self_path:
                continue
            try:
                if p.stat().st_size > max_bytes:
                    skipped += 1
                    continue
            except OSError:
                continue
            text = read_text(p)
            if not text:
                continue
            scanned += 1
            log(3, f"scan {p}")
            # Cheap whole-file test first; only the rare file that matches pays for
            # the per-line scan. This keeps a 12k-file repo well under the 30s budget.
            if not any(pat.search(text) for pat in ATTRIBUTION_PATTERNS):
                continue
            bad = [i for i, line in enumerate(text.splitlines(), 1) if _is_attribution(line)]
            if bad:
                rel_parts = p.relative_to(repo).parts
                agent_file = rel_parts[0] == ".claude" or p.name in (
                    "CLAUDE.md",
                    "AGENTS.md",
                    "CLAUDE.local.md",
                )
                rep.add(
                    "error",
                    "ATTR_TRACE",
                    f"{p}:{bad[0]}",
                    f"assistant attribution on {len(bad)} line(s)"
                    + (" (lines removed)" if agent_file else ""),
                    agent_file,
                )
                if agent_file:
                    kept = [l for l in text.splitlines(True) if not _is_attribution(l)]
                    rep.edit(p, text, "".join(kept))
    log(1, f"attribution scan: {scanned} file(s), {skipped} skipped (size)", 1)
    if not (repo / ".git").exists():
        log(1, "not a git repository: history and hook checks skipped", 1)
        return
    if history:
        out = git(repo, "log", f"-n{pol['scan_history_commits']}", "--format=%H%x00%B%x01")
        entries = [e for e in (out or "").split("\x01") if "\x00" in e]
        log(1, f"history: {len(entries)} commit(s) scanned", 1)
        tainted = [
            e.strip().split("\x00", 1)[0][:10]
            for e in entries
            if any(p.search(e.split("\x00", 1)[1]) for p in ATTRIBUTION_PATTERNS)
        ]
        if tainted:
            rep.add(
                "info",
                "ATTR_HISTORY",
                repo,
                f"{len(tainted)} of the last {len(entries)} commits carry attribution "
                f"(e.g. {tainted[0]}); rewriting published history is your decision",
            )
    hook = hooks_dir(repo) / "commit-msg"
    log(1, f"commit-msg hook: {hook} ({'present' if hook.exists() else 'absent'})", 1)
    precommit = read_text(repo / ".pre-commit-config.yaml") or ""
    hook_text = (read_text(hook) or "") if hook.is_file() else ""
    # Recognise the guard by what it does, not by which tool wrote it: any hook that
    # strips a Co-Authored-By / Generated-with trailer counts (covers hooks installed
    # under this tool's former name too).
    strips = bool(hook_text) and (
        HOOK_SIGNATURE in hook_text
        or re.search(r"[Cc]o-[Aa]uthored-[Bb]y|[Gg]enerated with|attribution", hook_text)
    )
    guarded = strips or ("commit-msg" in precommit and "attribution" in precommit.lower())
    if guarded:
        return
    if hook.exists():
        rep.add(
            "warn",
            "ATTR_HOOK_CONFLICT",
            hook,
            "existing commit-msg hook without attribution stripping",
        )
    elif pol["install_commit_msg_hook"]:
        rep.add(
            "warn", "ATTR_HOOK_MISSING", repo, "no commit-msg guard stripping attribution", True
        )
        rep.new_files[hook] = (COMMIT_MSG_HOOK, 0o755)


# --------------------------------------------------------------------------- #
# Scaffolding
# --------------------------------------------------------------------------- #


def detect_commands(repo: Path) -> str:
    cmds: list[str] = []
    mk = read_text(repo / "Makefile") or ""
    targets = re.findall(r"^([a-zA-Z][\w-]*):(?!=)", mk, re.M)
    cmds += [
        f"- `make {t}`"
        for t in ("up", "down", "build", "test", "lint", "fmt", "run", "dev")
        if t in targets
    ]
    pkg = read_text(repo / "package.json")
    if pkg:
        try:
            scripts = json.loads(pkg).get("scripts", {}) or {}
            cmds += [f"- `npm run {k}`" for k in ("dev", "build", "test", "lint") if k in scripts]
        except json.JSONDecodeError:
            pass
    if (repo / "pyproject.toml").is_file() and not cmds:
        cmds.append("<!-- Python project: document the test/lint commands. -->")
    return "\n".join(cmds) or "<!-- Build, run, test and lint commands, one per line. -->"


def scaffold_project(repo: Path, policy: dict, rep: Report) -> None:
    pol = policy["scaffold"]
    settings = repo / ".claude" / "settings.json"
    if pol["project_settings"] and not settings.exists() and (repo / ".git").exists():
        perms = policy["permissions"]
        ask = [f"Bash({p} *)" for p in perms["external_action_prefixes"]]
        if perms["require_rtk"] and perms.get("rtk_twin_deny", True):
            ask += [t for r in ask if (t := rtk_twin(r, perms["rtk_exempt"]))]
        data = {
            "$schema": pol["schema_url"],
            "attribution": {"commit": "", "pr": ""},
            "permissions": {"ask": ask, "deny": list(perms["required_deny"])},
        }
        rep.add(
            "warn",
            "SCAFFOLD_SETTINGS",
            settings,
            "missing project settings (baseline created)",
            True,
        )
        rep.new_files[settings] = (dump_json(data), 0o644)
    if not pol["instructions"]:
        return
    agents, claude = repo / "AGENTS.md", repo / "CLAUDE.md"
    if (repo / policy["instructions"]["doctrine_dir"]).is_dir():
        missing = [
            f for f in policy["instructions"]["rendered_files"][:2] if not (repo / f).exists()
        ]
        if missing:
            rep.add(
                "warn",
                "SCAFFOLD_RENDER_MISSING",
                repo,
                f"doctrine source present but {', '.join(missing)} not rendered",
            )
        return
    has_claude = claude.exists() or (repo / ".claude/CLAUDE.md").exists()
    has_agents = agents.exists() or (repo / ".claude/AGENTS.md").exists()
    if not has_claude and not has_agents:
        rep.add(
            "warn",
            "SCAFFOLD_INSTRUCTIONS",
            repo,
            "no agent instructions (AGENTS.md skeleton created)",
            True,
        )
        rep.new_files[agents] = (
            AGENTS_SKELETON.format(name=repo.name, commands=detect_commands(repo)),
            0o644,
        )
        if policy["instructions"]["claude_md_import"]:
            extra = (
                COMPACT_SECTION
                if policy.get("tokens", {}).get("compact_instructions", True)
                else ""
            )
            rep.new_files[claude] = ("@AGENTS.md\n" + extra, 0o644)
    elif (
        has_agents
        and not has_claude
        and policy["instructions"]["claude_md_import"]
        and not (repo / "CLAUDE.local.md").exists()
    ):
        rep.add(
            "info",
            "SCAFFOLD_CLAUDE_IMPORT",
            repo,
            "AGENTS.md without CLAUDE.md (import created)",
            True,
        )
        rep.new_files[claude] = ("@AGENTS.md\n", 0o644)


def scaffold_user(policy: dict, rep: Report) -> None:
    settings = config_dir() / "settings.json"
    if policy["scaffold"]["user_settings"] and not settings.exists():
        data = {
            "$schema": policy["scaffold"]["schema_url"],
            "attribution": {"commit": "", "pr": ""},
        }
        rep.add(
            "warn",
            "SCAFFOLD_USER_SETTINGS",
            settings,
            "missing user settings (baseline created)",
            True,
        )
        rep.new_files[settings] = (dump_json(data), 0o644)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def lint_user(policy: dict, rep: Report, repos: list[Path]) -> str | None:
    home = config_dir()
    log(1, f"user scope: {home}")
    if SCAFFOLD:
        scaffold_user(policy, rep)
    if not home.is_dir():
        rep.add("info", "USER_SCOPE_ABSENT", home, "no user-scope configuration")
        return None
    user_settings = None
    for name in ("settings.json", "settings.local.json"):
        s = check_settings(home / name, home, "user", policy, rep)
        user_settings = user_settings or s
    check_agent_assets(home, policy, rep, "user", None)
    check_auto_memory(home, policy, rep)
    check_claude_json(rep, repos)
    check_user_extras(rep)
    return check_instruction_file(home / "CLAUDE.md", "user", policy, rep, None)


def lint_repo(repo: Path, policy: dict, rep: Report, history: bool, user_text: str | None) -> None:
    log(1, f"project scope: {repo}")
    check_misplaced(repo, rep)
    if SCAFFOLD and (repo / ".git").exists():
        scaffold_project(repo, policy, rep)
    dot = repo / ".claude"
    project_perms = False
    for name in ("settings.json", "settings.local.json"):
        s = check_settings(dot / name, repo, "project", policy, rep)
        project_perms |= bool(s and s.get("permissions"))
    user_mode = None
    user_s = read_text(config_dir() / "settings.json")
    if user_s:
        try:
            user_mode = (json.loads(user_s).get("permissions") or {}).get("defaultMode")
        except (json.JSONDecodeError, AttributeError):
            pass
    if user_mode and project_perms:
        rep.add(
            "info",
            "SETTINGS_BUG_55507",
            repo,
            f"user defaultMode={user_mode} may be dropped by this project's permissions block",
        )
    check_mcp(repo / ".mcp.json", rep, policy)
    check_agent_assets(dot, policy, rep, "project", repo)
    check_output_styles(dot, rep)
    for proot in find_plugin_roots(repo):
        if (proot / ".claude-plugin" / "plugin.json").exists():
            check_plugin_dir(proot, rep, policy)
        check_marketplace(proot, rep, policy)
    check_workflows(repo, rep)
    check_repo_secrets(repo, rep)
    texts = []
    for rel in [
        "CLAUDE.md",
        ".claude/CLAUDE.md",
        "AGENTS.md",
        ".claude/AGENTS.md",
        "CLAUDE.local.md",
        *policy["instructions"]["rendered_files"][2:],
    ]:
        t = check_instruction_file(repo / rel, "project", policy, rep, repo)
        if t:
            texts.append(t)
    check_agents_md(repo, policy, rep)
    check_rendered(repo, policy, rep)
    if user_text and texts:
        min_len = policy["instructions"]["min_duplicate_line_len"]
        norm = lambda t: {
            l.strip().lower() for l in strip_code(t).splitlines() if len(l.strip()) >= min_len
        }
        dup = norm(user_text) & set().union(*(norm(t) for t in texts))
        log(1, f"{len(dup)} line(s) shared with user instructions", 1)
        if len(dup) >= 3:
            rep.add(
                "warn",
                "INSTR_DUPLICATED",
                repo,
                f"{len(dup)} lines repeated from user instructions",
            )
    check_attribution(repo, policy, rep, history)
    run_plugin_checks("project", repo, policy, rep)


def discover_repos(root: Path, max_depth: int = 3) -> list[Path]:
    if (root / ".git").exists():
        return [root]
    found: list[Path] = []
    skip = {"node_modules", ".venv", "venv", ".cache", "Library", "dist", "build"}
    base = len(root.parts)
    for dirpath, dirnames, _ in os.walk(root):
        p = Path(dirpath)
        if p != root and (p / ".git").exists():
            found.append(p)
            dirnames[:] = []
            continue
        depth = len(p.parts) - base
        dirnames[:] = (
            [d for d in dirnames if d not in skip and not d.startswith(".")]
            if depth < max_depth
            else []
        )
    if found:
        log(1, f"{root} is not a git repository: {len(found)} repositories found below it")
        return sorted(found)
    return [root]


def run_lint(repos: list[Path], policy: dict, args: argparse.Namespace, history: bool) -> Report:
    rep = Report()
    user_text = lint_user(policy, rep, repos) if (args.user or args.user_only) else None
    if args.user or args.user_only:
        run_plugin_checks("user", config_dir(), policy, rep)
    check_rtk(policy, rep, repos, bool(args.user or args.user_only))
    check_llmtrim(rep, repos, bool(args.user or args.user_only))
    rep.budget = token_budget(
        repos[0] if repos else None, bool(args.user or args.user_only), policy, rep
    )
    user_roots = [config_dir()] if (args.user or args.user_only) else []
    dup_roots = user_roots + [r / ".claude" for r in repos]
    check_duplicates(user_roots, [r / ".claude" for r in repos], rep)
    rep.proposals = compute_proposals(dup_roots, repos, policy)
    for r in repos:
        check_token_levers(r, policy, rep)
    if getattr(args, "generate", False):
        if args.user or args.user_only:
            generate_user(policy, rep)
        for r in repos:
            if (r / ".git").exists():
                generate_project(r, policy, rep)
            else:
                log(1, f"{r}: not a git repository, nothing generated")
    for n, r in enumerate(repos, 1):
        progress(n - 1, len(repos), r.name)
        t0, before = time.perf_counter(), len(rep.findings)
        lint_repo(r, policy, rep, history, user_text)
        log(1, f"{r}: {len(rep.findings) - before} finding(s) in {time.perf_counter() - t0:.2f}s")
    progress(len(repos), len(repos), "done")
    if isinstance(rep.budget, dict):
        rep.budget["potential"] = sum(_finding_gain(f) for f in rep.findings) + sum(
            p["gain"] for p in rep.proposals
        )
    return rep


def log_dir() -> Path:
    return Path(os.path.expanduser("~/.cache/claude-lint/logs"))


def write_run_log(
    argv: list[str],
    repos: list[Path],
    rep: Report,
    fixed: list,
    applied: list[str],
    elapsed: float,
    code: int,
) -> None:
    """Append one JSON line per run to ~/.cache/claude-lint/logs/<date>.log.
    Best-effort: a logging failure never affects the run's exit code, and no file
    contents or secrets are recorded, only counts and finding codes."""
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        codes: dict[str, int] = {}
        for f in rep.findings:
            codes[f.code] = codes.get(f.code, 0) + 1
        record = {
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            "version": VERSION,
            "args": argv,
            "repos": len(repos),
            "elapsed_s": round(elapsed, 2),
            "findings": {lvl: rep.count(lvl) for lvl in LEVELS},
            "fixed": len(fixed),
            "applied": len(applied),
            "exit": code,
            "codes": codes,
        }
        with (d / f"{dt.date.today().isoformat()}.log").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        log(2, f"run log skipped: {e}")


def backup(paths: list[Path]) -> Path:
    root = Path(os.path.expanduser(f"~/.cache/claude-lint/{dt.datetime.now():%Y%m%dT%H%M%S%f}"))
    for p in paths:
        if p.exists():
            dest = root / str(p.resolve()).lstrip("/")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
    return root


def apply(rep: Report) -> tuple[Path | None, list[str], list[tuple[str, str]]]:
    applied: list[str] = []
    failures: list[tuple[str, str]] = []
    targets = list(rep.edits) + list(rep.new_files) + [s for s, _ in rep.moves]
    where = backup(targets) if targets else None
    for src, dst in rep.moves:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                raise OSError(f"{dst} already exists")
            os.replace(src, dst)
            applied.append(f"moved {src} -> {dst}")
        except OSError as e:
            failures.append((str(src), f"move failed: {e}"))
    if where:
        log(1, f"backup: {where}")
    for p in rep.chmods:
        try:
            p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            applied.append(f"chmod+x {p}")
        except OSError as e:
            failures.append((str(p), f"chmod failed: {e}"))
    for p, (_, new) in rep.edits.items():
        try:
            p.write_text(new, encoding="utf-8")
            if read_text(p) != new:
                raise OSError("content not persisted (read-only mount or generated file?)")
            applied.append(f"updated {p}")
            log(1, f"wrote {p}", 1)
        except OSError as e:
            failures.append((str(p), f"write failed: {e}"))
    for p, (content, mode) in rep.new_files.items():
        if p.exists():  # appeared since the lint (e.g. a move): the next pass merges instead
            log(1, f"deferred {p} (now exists)", 1)
            continue
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            p.chmod(mode | stat.S_IRUSR)
            applied.append(f"created {p}")
            log(1, f"created {p}", 1)
        except OSError as e:
            failures.append((str(p), f"create failed: {e}"))
    return where, applied, failures


COLORS = {"error": "\033[31m", "warn": "\033[33m", "info": "\033[36m"}


def redact(text: str) -> str:
    return SECRET_REDACT_RE.sub(lambda m: m.group(1) + "***REDACTED***", text)


FIRST_REPORT: Report | None = None
INTERACTIVE_RAN = False


def _action_for(code: str) -> str:
    """A concise, solution-oriented action for a finding code, in the active
    language: the brief table's advice when the code has one, else the HINTS
    'why/how' sentence. Empty when neither is known."""
    entry = brief_table().get(code)
    if entry:
        return entry[2]
    return HINTS[code][0] if code in HINTS else ""


def _finding_gain(f: Finding) -> int:
    """Estimated tokens saved per session if this finding is acted on. Uses the
    figure already in the message when present, else a per-code estimate. Only the
    context-cost codes carry a gain; everything else returns 0."""
    # Only always-loaded context counts. A token figure already in the message
    # (e.g. an instruction file, an agent pack) is authoritative.
    m = re.search(r"~(\d+)\s*tokens?", f.message)
    if m and f.code in ("TOKEN_AGENT_PACK", "INSTR_LONG", "INSTR_TOO_LARGE", "TOKEN_IMPORTS"):
        return int(m.group(1))
    if f.code == "TOKEN_SKILL_DESC":  # the listing description is re-sent every turn
        m = re.search(r"(\d+)\s*chars", f.message)
        return max(0, (int(m.group(1)) - 400) // 4) if m else 0
    if f.code in (
        "RULE_UNSCOPED",
        "DUP_EXACT",
        "DUP_NAME",
        "DUP_SIMILAR",
        "DUP_ACROSS_PROJECTS",
        "DUP_FAMILY",
    ):
        return 60  # small per-item listing cost removed
    # SKILL_LONG is deliberately 0: a skill body is loaded on demand, not every
    # session, so splitting it does not reduce per-session tokens.
    return 0


def render_text(
    rep: Report,
    fix: bool,
    color: bool,
    quiet: bool,
    fixed: list[Finding],
    applied: list[str],
    failures: list[tuple[str, str]],
    backups: list[str],
) -> str:
    out: list[str] = []
    g, r0, dim = ("\033[32m", "\033[0m", "\033[2m") if color else ("", "", "")
    if fix and applied and not quiet:
        out.append(f"{g}== Files changed ({len(applied)}){r0}")
        for a in applied:
            verb, _, rest = a.partition(" ")
            parts = [short_path(x) for x in rest.split(" -> ")]
            out.append(f"  {verb} {' -> '.join(parts)}")
    # Detailed findings: always in read-only mode; with --fix only at -v (the summary lists them).
    if not fix or VERBOSITY >= 1:
        if fix and rep.findings:
            out.append("== Remaining findings (details)")
        lvl_c = {k: (COLORS[k] if color else "") for k in LEVELS}
        for kind, items in grouped_findings(
            [f for f in rep.findings if not quiet or f.level == "error"]
        ):
            if kind == "group":
                out += render_group(items, lvl_c, r0, indent="", mark="")
                f = items[0]
            else:
                f = items[0]
                tag = f"{COLORS[f.level] if color else ''}{f.level.upper():5}{r0}"
                gain = sum(_finding_gain(x) for x in items) if kind == "group" else _finding_gain(f)
                gtxt = f"{dim} · ~{gain} tokens/session{r0}" if gain else ""
                out.append(
                    f"{tag} {f.code:24} {short_path(f.path)}\n      "
                    f"{f.message}{' [fixable]' if f.fixable else ''}{gtxt}"
                )
            action = _action_for(f.code)
            if action:
                out.append(f"{g}      {_loc('→ solution', '→ fix')} : {r0}{action}")
            if VERBOSITY >= 1 and f.code in HINTS:
                why, ref = HINTS[f.code]
                if not _action_for(f.code) or ref:
                    out.append(f"{dim}      ref: {HINTS[f.code][1]}{r0}")
        total_gain = sum(_finding_gain(f) for f in rep.findings)
        props_gain = sum(p["gain"] for p in getattr(rep, "proposals", []))
        if total_gain or props_gain:
            out.append(
                f"{g}Potential savings: ~{total_gain + props_gain} tokens/session{r0} "
                f"{dim}(~{total_gain} from findings + ~{props_gain} from restructurings; "
                f"acted on with --fix / -i){r0}"
            )
    if not fix and not quiet:
        for p, (old, new) in rep.edits.items():
            out.append(
                redact(
                    "".join(
                        difflib.unified_diff(
                            old.splitlines(True), new.splitlines(True), f"a{p}", f"b{p}"
                        )
                    )
                )
            )
        for p, (content, _) in rep.new_files.items():
            out.append(
                redact(
                    "".join(
                        difflib.unified_diff([], content.splitlines(True), "/dev/null", f"b{p}")
                    )
                )
            )
        out += [f"chmod +x {p}" for p in rep.chmods]
        out += [f"mv {short_path(str(s))} {short_path(str(d))}" for s, d in rep.moves]
    out.append(render_summary(rep, fix, color, quiet, fixed, applied, failures, backups))
    return "\n".join(out)


def short_path(p: str) -> str:
    try:
        rel = os.path.relpath(p.split(":")[0] if re.search(r":\d+$", p) else p)
        rel = rel + p[len(p.split(":")[0]) :] if re.search(r":\d+$", p) else rel
        return rel if not rel.startswith("../../..") else p
    except ValueError:
        return p


GROUP_THRESHOLD = 5
SHOW_ALL = False
CATEGORIES = [
    ("PERM_", "permissions"),
    ("HOOK_", "hooks"),
    ("HELPER_", "hooks"),
    ("SKILL_", "skills"),
    ("COMMAND_", "skills"),
    ("AGENT_", "subagents"),
    ("MCP_", "mcp"),
    ("DESKTOP_", "mcp"),
    ("RTK_", "rtk"),
    ("TOKEN_", "tokens"),
    ("ATTR_", "attribution"),
    ("INSTR_", "instructions"),
    ("IMPORT_", "instructions"),
    ("AGENTS_", "instructions"),
    ("RULE_", "instructions"),
    ("MEMORY_", "instructions"),
    ("RENDER_", "instructions"),
    ("LOCAL_MD", "instructions"),
    ("FRONTMATTER_", "instructions"),
    ("SECRET_", "secrets"),
    ("API_KEY", "secrets"),
    ("CI_", "ci"),
    ("PLUGIN_", "plugins"),
    ("MARKETPLACE", "plugins"),
    ("ENABLED_PLUGINS", "plugins"),
    ("OUTPUT_", "plugins"),
    ("SETTINGS_", "settings"),
    ("JSON_", "settings"),
    ("LOCAL_NOT", "settings"),
    ("KEYBINDINGS", "settings"),
    ("MANAGED_", "settings"),
    ("MISPLACED", "files"),
    ("CLAUDEIGNORE", "files"),
    ("GENERATE", "generation"),
    ("SCAFFOLD_", "generation"),
    ("USER_SCOPE", "settings"),
    ("DUP_", "duplicates"),
    ("WRITE_", "files"),
]


def category(code: str) -> str:
    return next((c for p, c in CATEGORIES if code.startswith(p)), "other")


def grouped_findings(findings: list[Finding]) -> list[tuple[str, list[Finding]]]:
    """Collapse codes that repeat more than GROUP_THRESHOLD times (unless --all)."""
    by: dict[tuple[str, str], list[Finding]] = {}
    for f in findings:
        by.setdefault((f.level, f.code), []).append(f)
    order = {lvl: i for i, lvl in enumerate(LEVELS)}
    out: list[tuple[str, list[Finding]]] = []
    for (_lvl, _code), items in sorted(
        by.items(), key=lambda kv: (order[kv[0][0]], -len(kv[1]), kv[0][1])
    ):
        if SHOW_ALL or len(items) <= GROUP_THRESHOLD:
            out += [("one", [f]) for f in sorted(items, key=lambda f: f.path)]
        else:
            out.append(("group", items))
    return out


def render_group(
    items: list[Finding], lvl_color: dict, r0: str, indent: str = "  ", mark: str = "✘ "
) -> list[str]:
    f0 = items[0]
    msgs: dict[str, int] = {}
    for f in items:
        msgs[re.sub(r"\d+", "N", f.message)] = msgs.get(re.sub(r"\d+", "N", f.message), 0) + 1
    common, n_common = max(msgs.items(), key=lambda kv: kv[1])
    files = sorted({short_path(f.path) for f in items})
    fixable = sum(1 for f in items if f.fixable)
    return [
        f"{indent}{lvl_color[f0.level]}{mark}{f0.level.upper():5}{r0} {f0.code:24} x{len(items)}"
        + (f"  ({fixable} fixable)" if fixable else ""),
        f"{indent}        most common ({n_common}): "
        f"{items[0].message if len(msgs) == 1 else common}",
        f"{indent}        in: {', '.join(files[:3])}"
        + (f" +{len(files) - 3} more" if len(files) > 3 else "")
        + ("  (--all to list every one)" if not SHOW_ALL else ""),
    ]


def render_stats(rep: Report, first: Report | None, fixed: list[Finding], color: bool) -> str:
    b, r0 = ("\033[1m", "\033[0m") if color else ("", "")
    lines = [f"{b}STATS{r0}"]
    if rep.stats:
        lines.append(
            "  checked: "
            + ", ".join(f"{v} {k}" for k, v in sorted(rep.stats.items(), key=lambda kv: -kv[1]))
        )
    cats: dict[str, dict[str, int]] = {}
    for f in rep.findings:
        c = cats.setdefault(
            category(f.code), {"error": 0, "warn": 0, "info": 0, "fixed": 0, "found": 0}
        )
        c[f.level] += 1
    for f in fixed:
        c = cats.setdefault(
            category(f.code), {"error": 0, "warn": 0, "info": 0, "fixed": 0, "found": 0}
        )
        c["fixed"] += 1
    if first is not None:
        for f in first.findings:
            cats.setdefault(
                category(f.code), {"error": 0, "warn": 0, "info": 0, "fixed": 0, "found": 0}
            )["found"] += 1
    if cats:
        lines.append(
            f"  {'category':14} {'found':>6} {'fixed':>6} {'error':>6} {'warn':>6} "
            f"{'info':>6}   (error/warn/info = remaining)"
        )
        for name, c in sorted(
            cats.items(),
            key=lambda kv: -(kv[1]["found"] or kv[1]["error"] + kv[1]["warn"] + kv[1]["info"]),
        ):
            found = c["found"] or c["error"] + c["warn"] + c["info"]
            lines.append(
                f"  {name:14} {found:>6} {c['fixed']:>6} {c['error']:>6} {c['warn']:>6} "
                f"{c['info']:>6}"
            )
    codes: dict[str, int] = {}
    for f in rep.findings:
        codes[f.code] = codes.get(f.code, 0) + 1
    top = sorted(codes.items(), key=lambda kv: -kv[1])[:5]
    if top:
        lines.append(
            "  noisiest checks: "
            + ", ".join(f"{c} x{n}" for c, n in top)
            + "  (silence with [reference] extra_*_fields or [tokens] thresholds)"
        )
    return "\n".join(lines)


def render_summary(
    rep: Report,
    fix: bool,
    color: bool,
    quiet: bool,
    fixed: list[Finding],
    applied: list[str],
    failures: list[tuple[str, str]],
    backups: list[str],
) -> str:
    """Final recap: what was (or would be) fixed, and what still needs a human."""
    g, red, yel, cyan, b, r0 = (
        ("\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[1m", "\033[0m")
        if color
        else ("",) * 6
    )
    lvl_color = {"error": red, "warn": yel, "info": cyan}
    rule = "=" * 72
    lines = ["", rule]
    if fix:
        lines.append(
            f"{b}SUMMARY{r0}  (claude-lint {VERSION})  {len(fixed)} issue(s) fixed, "
            f"{len(applied)} change(s) written"
            + (f", {len(failures)} write failure(s)" if failures else "")
        )
        done = fixed
        title_done, mark_done = "FIXED OR GENERATED", f"{g}✔{r0}"
    else:
        lines.append(
            f"{b}SUMMARY{r0}  read-only run: nothing was modified  (claude-lint {VERSION})"
        )
        done = [f for f in rep.findings if f.fixable]
        title_done, mark_done = "WOULD BE FIXED OR GENERATED by --fix", f"{g}○{r0}"
    manual = [f for f in rep.findings if not f.fixable or fix]

    groups: dict[str, list[Finding]] = {}
    for f in done:
        groups.setdefault(f.code, []).append(f)
    lines.append(rule)
    lines.append(f"{g}{title_done} ({len(done)}){r0}")
    if not done:
        lines.append("  (none)")
    for code, items in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        files = sorted({short_path(f.path) for f in items})
        where = ", ".join(files[:3]) + (f" +{len(files) - 3}" if len(files) > 3 else "")
        lines.append(f"  {mark_done} {code:24} x{len(items):<3} {where}")

    shown = [f for f in manual if not quiet or f.level == "error"]
    lines.append(
        f"{red if any(f.level == 'error' for f in manual) else yel}"
        f"NOT FIXED - manual action needed ({len(manual)}){r0}"
        + (" [errors only, -q]" if quiet and len(shown) != len(manual) else "")
    )
    if not manual:
        lines.append("  (none)")
    for kind, items in grouped_findings(shown):
        if kind == "group":
            lines += render_group(items, lvl_color, r0)
            continue
        f = items[0]
        lines.append(
            f"  {lvl_color[f.level]}✘ {f.level.upper():5}{r0} {f.code:24} {short_path(f.path)}"
        )
        lines.append(f"          {f.message}")
    if failures:
        lines.append(f"{red}NOT WRITTEN ({len(failures)}){r0}")
        lines += [f"  {red}✘{r0} {short_path(p)}: {m}" for p, m in failures]

    lines.append(rule)
    tb = render_token_budget(
        getattr(rep, "budget", None), color, getattr(FIRST_REPORT, "budget", None) if fix else None
    )
    if tb:
        lines += [tb, rule]
    rp = render_proposals(getattr(rep, "proposals", []), color)
    if rp:
        lines += [rp, rule]
    lines += [render_stats(rep, FIRST_REPORT, fixed if fix else [], color), rule]
    counts = (
        f"{rep.count('error')} error(s), {rep.count('warn')} warning(s), {rep.count('info')} info"
    )
    dups = sum(1 for f in rep.findings if f.code.startswith("DUP_"))
    packs = [f for f in rep.findings if f.code == "TOKEN_AGENT_PACK"]
    longdesc = sum(1 for f in rep.findings if f.code == "TOKEN_SKILL_DESC")
    if (dups or packs or longdesc or getattr(rep, "proposals", [])) and not INTERACTIVE_RAN:
        pack_tokens = sum(
            int(m.group(1)) for f in packs if (m := re.search(r"~(\d+) tokens", f.message))
        )
        lines.append(
            f"NEXT: run again with -i to review {dups} duplicate group(s), "
            f"{len(getattr(rep, 'proposals', []))} restructuring"
            f" proposal(s), {len(packs)} subagent pack(s) (~{pack_tokens} tokens) and "
            f"{longdesc} long description(s) one by one (reversible)."
        )
    if fix:
        lines.append(f"Remaining: {counts}")
        lines += [f"Backup of modified files: {bk}" for bk in backups]
    else:
        lines.append(f"Found: {counts}")
        if done:
            lines.append(f"Run again with --fix to apply the {len(done)} automatic repair(s).")
    return "\n".join(lines)


def to_toml(d: dict, prefix: str = "") -> str:
    lines, tables = [], []
    for k, v in d.items():
        (tables if isinstance(v, dict) else lines).append((k, v))
    out = "\n".join(f"{k} = {json.dumps(v)}" for k, v in lines)
    for k, v in tables:
        name = f"{prefix}.{k}" if prefix else k
        out += f"\n\n[{name}]\n" + to_toml(v, name)
    return out.strip() + ("\n" if not prefix else "")


# --------------------------------------------------------------------------- #
# Guard: PreToolUse hook that blocks any loosening edit (fails closed)
# --------------------------------------------------------------------------- #

GUARD_MARKER = "--guard"
CONFIG_HINT = re.compile(
    r"(settings(\.local)?\.json|\.mcp\.json|\.claude\.json|/\.claude/|\.claude/|"
    r"\.agent-lint\.toml|\.git/hooks|claude-lint|SKILL\.md|CLAUDE(\.local)?\.md|AGENTS\.md)"
)
BASH_WRITE_HINT = re.compile(
    r"(>|\btee\b|\bsed\s+-i|\bperl\s+-[a-z]*i|\bmv\b|\bcp\b|\brm\b|\bln\b|\bchmod\b|"
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
                target = (
                    h.get("command")
                    or h.get("url")
                    or f"{h.get('server')}:{h.get('tool')}"
                    or h.get("prompt")
                )
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
    if pn.get("defaultMode") in ("bypassPermissions", "auto", "acceptEdits") and pn.get(
        "defaultMode"
    ) != po.get("defaultMode"):
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
        old_cmd = " ".join(
            [str(a.get("command") or a.get("url") or ""), *map(str, a.get("args") or [])]
        ).split()
        new_cmd = " ".join(
            [str(b.get("command") or b.get("url") or ""), *map(str, b.get("args") or [])]
        ).split()
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
    if mn.get("permissionMode") in ("bypassPermissions", "auto", "acceptEdits") and mn.get(
        "permissionMode"
    ) != mo.get("permissionMode"):
        v.append("permissionMode loosened")
    if (
        mn.get("mcpServers") or "mcpServers" in frontmatter_block(new)
    ) and "mcpServers" not in frontmatter_block(old):
        v.append("inline mcpServers added")
    if re.search(r"(?m)^\s*!`|^```!", new) and not re.search(r"(?m)^\s*!`|^```!", old):
        v.append("shell injection (!`cmd`) added")
    return v


def lint_toml_violations(old: str, new: str) -> list[str]:
    if tomllib is None:
        return ["cannot verify .claude-lint.toml without Python 3.11"]
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


def guard_check(data: dict) -> str | None:
    """Return a block reason, or None to let the normal permission flow decide."""
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    cwd = Path(data.get("cwd") or os.getcwd())
    if tool in ("Bash", "PowerShell", "Monitor"):
        cmd = str(ti.get("command", ""))
        if re.fullmatch(r"\s*(rtk\s+)?(python3?\s+)?\S*claude-lint\.py(\s+[\w\-./=~:]+)*\s*", cmd):
            if re.search(r"--session-settings\b|--policy\b|\s-i\b|--interactive\b", cmd) or (
                re.search(r"--generate\b", cmd) and re.search(r"--fix\b", cmd)
            ):
                return "guard: --generate --fix, --session-settings and --policy add permissions: the human runs them (a --generate preview is allowed)"
            return None  # the linter only tightens
        if CONFIG_HINT.search(cmd) and BASH_WRITE_HINT.search(cmd):
            return (
                "guard: agent configuration files may only be changed with Edit/Write "
                "(so the change can be inspected), or by running claude-lint.py"
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
        try:
            o = lenient_json(old)[0] if old.strip() else {}
        except json.JSONDecodeError:
            o = {}
        try:
            n = json.loads(new)
        except json.JSONDecodeError as e:
            return f"guard: settings must stay strict JSON ({e})"
        violations = settings_violations(
            o if isinstance(o, dict) else {}, n if isinstance(n, dict) else {}
        )
    elif name == ".mcp.json":
        try:
            o = lenient_json(old)[0] if old.strip() else {}
            n = json.loads(new)
        except json.JSONDecodeError as e:
            return f"guard: .mcp.json must stay strict JSON ({e})"
        violations = mcp_violations(o, n)
    elif name == "claude_desktop_config.json":
        try:
            o = lenient_json(old)[0] if old.strip() else {}
            n = json.loads(new)
        except json.JSONDecodeError as e:
            return f"guard: Desktop config must stay strict JSON ({e})"
        violations = mcp_violations(o, n)
    elif name == "plugin.json" and path.parent.name == ".claude-plugin":
        try:
            o = lenient_json(old)[0] if old.strip() else {}
            n = json.loads(new)
        except json.JSONDecodeError as e:
            return f"guard: plugin.json must stay strict JSON ({e})"
        violations = [
            f"plugin {k} added or changed (executes code)"
            for k in ("hooks", "mcpServers", "lspServers", "monitors", "channels", "userConfig")
            if n.get(k) not in (None, o.get(k))
        ]
    elif name == "marketplace.json" and path.parent.name == ".claude-plugin":
        try:
            o = lenient_json(old)[0] if old.strip() else {}
            n = json.loads(new)
        except json.JSONDecodeError as e:
            return f"guard: marketplace.json must stay strict JSON ({e})"
        on = {p.get("name") for p in o.get("plugins") or [] if isinstance(p, dict)}
        nn = {p.get("name") for p in n.get("plugins") or [] if isinstance(p, dict)}
        violations = [f"new marketplace plugin {x!r}" for x in sorted(nn - on)]
    elif name == "hooks.json" and path.parent.name == "hooks":
        try:
            o = lenient_json(old)[0] if old.strip() else {}
            n = json.loads(new)
        except json.JSONDecodeError as e:
            return f"guard: hooks.json must stay strict JSON ({e})"
        violations = settings_violations({"hooks": o.get("hooks")}, {"hooks": n.get("hooks")})
    elif (
        path.suffix in (".yml", ".yaml")
        and "/.github/workflows/" in str(path)
        and "claude-code" in new
    ):
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
        if re.search(r"(?m)^\s*permissions\s*:", old) and not re.search(
            r"(?m)^\s*permissions\s*:", new
        ):
            violations.append("workflow permissions block removed")
    elif name in (".claude-lint.toml", ".agent-lint.toml"):
        violations = lint_toml_violations(old, new)
    elif name.endswith(".md") and (
        "/.claude/skills/" in str(path)
        or "/.claude/agents/" in str(path)
        or "/.claude/commands/" in str(path)
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
# Discovery: <config dir>/plugins, <repo>/.claude-lint/plugins, and --plugin-dir.
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
    dirs = [config_dir() / "plugins", Path.cwd() / ".claude-lint" / "plugins"]
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
                spec = _ilu.spec_from_file_location(f"claude_lint_plugin_{f.stem}", f)
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
        "# claude-lint catalog. Edit and pass with --catalog FILE.\n"
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
            "  claude-lint.py .                      read-only report for the current repo\n"
            "  claude-lint.py . --fix               apply safe repairs (backup kept)\n"
            "  claude-lint.py . --user              include user scope (~/.claude or "
            "$CLAUDE_CONFIG_DIR)\n"
            "  claude-lint.py ~/dev --user          every git repo under ~/dev, plus user scope\n"
            "  claude-lint.py . --generate          preview config to generate for the stack\n"
            "  claude-lint.py . -i                  interactive review (duplicates, packs, "
            "restructurings)\n"
            "  claude-lint.py --restore             undo the last interactive session\n"
            "  claude-lint.py . --strict --format json --no-cli   CI-friendly run\n"
            "\n"
            "read-only by default; --fix and -i are the only writing modes, both reversible.\n"
            "each run appends a JSON line to ~/.cache/claude-lint/logs/<date>.log.\n"
            "docs snapshot follows code.claude.com/docs; unknown keys are reported, never errors.\n"
            "\n"
            "defaults:\n"
            "  scope             current repo only (--user adds ~/.claude or $CLAUDE_CONFIG_DIR)\n"
            "  mode              read-only (no --fix, no --generate, no -i)\n"
            "  report            brief; language from $LANG (fr if it starts with 'fr', else en)\n"
            "  scaffolding       on (missing baseline files created; --no-scaffold to disable)\n"
            "  CLIs              claude and rtk are called when present (--no-cli to skip)\n"
            "  policy file       <repo>/.claude-lint.toml if present, else built-in defaults\n"
            "  instruction file  warns above 200 lines; user scope above 150\n"
            "  always-loaded     token budget warns above 10000 tokens/turn\n"
            "  skill description warns above 1024 chars in the listing\n"
            "  MCP servers       capped at 6\n"
            "  rtk routing       required (permissions.require_rtk = true)\n"
            "run with --print-policy to print every default as TOML."
        ),
    )
    ap.add_argument(
        "repos", nargs="*", type=Path, help="repositories or folders of repositories (default: cwd)"
    )
    ap.add_argument("--user", action="store_true", help="also check user scope")
    ap.add_argument("--user-only", action="store_true", help="check user scope only")
    ap.add_argument("--fix", action="store_true", help="apply repairs (with backup)")
    ap.add_argument("--no-scaffold", action="store_true", help="do not create missing files")
    ap.add_argument(
        "--format", choices=("text", "json"), default="text", help="output format (default: text)"
    )
    ap.add_argument("--policy", type=Path, help="policy TOML (default: <repo>/.claude-lint.toml)")
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
        help="review duplicates, subagent packs, long descriptions and model choice one by "
        "one (reversible)",
    )
    ap.add_argument(
        "--restore",
        nargs="?",
        const="",
        metavar="TRASH_DIR",
        help="move back everything removed by the last -i session (or the given trash folder)",
    )
    ap.add_argument(
        "--details", action="store_true", help="full per-file report instead of the brief one"
    )
    ap.add_argument(
        "--all", action="store_true", help="list every finding instead of grouping repeated ones"
    )
    ap.add_argument(
        "--rtk-report", action="store_true", help="append 'rtk gain' and 'rtk discover' output"
    )
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
    ap.add_argument("--version", action="version", version=f"claude-lint {VERSION}")
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
    ap.add_argument(
        "--dump-reference", action="store_true", help="print built-in reference data as JSON"
    )
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
        "<config dir>/plugins and <repo>/.claude-lint/plugins",
    )
    ap.add_argument(
        "--list-plugins", action="store_true", help="list discovered check plugins and exit"
    )
    # No arguments at all: show help (with defaults) instead of silently scanning cwd.
    if not (argv if argv is not None else sys.argv[1:]):
        ap.print_help()
        return 0
    args = ap.parse_args(argv)
    global VERBOSITY, SCAFFOLD, CLI_VERSION, SHOW_ALL, FIRST_REPORT, LANG, PROGRESS
    if args.restore is not None:
        return restore_trash(args.restore or None)
    VERBOSITY, SCAFFOLD, SHOW_ALL = args.verbose, not args.no_scaffold, args.all
    # Progress bar by default: interactive stderr, no -v (which logs per repo),
    # no -q, text output only. Keeps pipes, JSON and CI silent.
    PROGRESS = (
        sys.stderr.isatty() and args.verbose == 0 and not args.quiet and args.format == "text"
    )
    if args.catalog:
        load_catalog(args.catalog)
    LANG = args.lang or ("fr" if os.environ.get("LANG", "").lower().startswith("fr") else "en")
    load_plugins(args.plugin_dir)
    if args.list_plugins:
        dirs = ", ".join(str(d) for d in plugin_dirs(args.plugin_dir)) or "(none)"
        print(f"plugin dirs: {dirs}")
        print(
            f"loaded plugins ({len(_PLUGINS_LOADED)}): " + (", ".join(_PLUGINS_LOADED) or "(none)")
        )
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
    log(1, f"claude-lint {VERSION}")
    detect_rtk(not args.no_cli)
    detect_llmtrim(not args.no_cli)
    RTK["checked_cli"] = not args.no_cli
    if not args.no_cli:
        CLI_VERSION = detect_cli_version()
        log(1, "claude CLI: " + (".".join(map(str, CLI_VERSION)) if CLI_VERSION else "not found"))

    run_started = time.perf_counter()
    targets = (
        [] if args.user_only else [r.expanduser().resolve() for r in (args.repos or [Path.cwd()])]
    )
    for r in targets:
        if not r.is_dir():
            print(f"not a directory: {r}", file=sys.stderr)
            return 2
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
                    "repositories": [str(r) for r in repos],
                    "findings": [asdict(f) for f in rep.findings],
                    "fixed": [asdict(f) for f in fixed],
                    "not_fixed": [asdict(f) for f in rep.findings if args.fix or not f.fixable],
                    "would_fix": [] if args.fix else [asdict(f) for f in rep.findings if f.fixable],
                    "applied": applied,
                    "pending_changes": [str(p) for p in [*rep.edits, *rep.new_files, *rep.chmods]]
                    + [f"{s} -> {d}" for s, d in rep.moves],
                    "hints": {
                        c: {"why": HINTS[c][0], "ref": HINTS[c][1]}
                        for c in sorted(codes)
                        if c in HINTS
                    },
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
        if repos and (len(repos) > 1 or VERBOSITY):
            print("repositories: " + ", ".join(str(r) for r in repos))
        print(
            render_text(
                rep, args.fix, sys.stdout.isatty(), args.quiet, fixed, applied, failures, backups
            )
        )
        if args.rtk_report:
            report = rtk_report()
            print("\n== rtk report\n" + (report or "rtk not available"))
    code = 1 if rep.count("error") or (args.strict and rep.count("warn")) else 0
    write_run_log(
        argv or sys.argv[1:], repos, rep, fixed, applied, time.perf_counter() - run_started, code
    )
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # output piped into head/less that closed early
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
