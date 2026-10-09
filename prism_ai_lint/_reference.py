"""Reference data: docs snapshot (2026-09), attribution patterns and scaffold templates.

Pure data plus one predicate, no engine imports. Sets are extended in place by
`load_policy` / `load_catalog`, so every module shares the same objects."""

from __future__ import annotations

import re

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
# Installed by prism-ai-lint. Deterministic and agent-agnostic.
sed -i -E \\
  -e '/^Co-Authored-By:.*(claude|anthropic)/Id' \\
  -e '/Generated with \\[?Claude Code/Id' \\
  "$1"
sed -i -e :a -e '/^\\n*$/{$d;N;ba' -e '}' "$1"
"""
HOOK_SIGNATURE = "prism-ai-lint"

# Portable, tool-agnostic PreCompact hook. No project-specific coupling: it writes
# a small session snapshot (git state + working dir) so context survives a compact.
# Referenced by settings that declare a PreCompact hook but ship no script.
PRE_COMPACT_HOOK = """#!/usr/bin/env bash
# PreCompact hook — snapshot session state before context compaction.
# Portable scaffold written by prism-ai-lint. Safe to edit or extend.
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
SECRETS_GITIGNORE_HEADER = "# prism-ai-lint: keep secrets and local config out of git"

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


# Claude model lineup, docs snapshot 2026-10 (platform.claude.com models overview).
# Tier order is cost order, cheapest first. Anything pinned to an id outside CURRENT_MODELS
# is older: still available (LEGACY_MODELS) but not the recommended generation.
CURRENT_MODELS = {"claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1"}
LEGACY_MODELS = {
    "claude-fable-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-opus-4-5",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
}
MODEL_SNAPSHOT = "2026-10"


def model_status(name: str) -> str:
    """'current', 'legacy' or '' (an alias such as 'sonnet', or an id this snapshot does not know)."""
    base = re.sub(r"(\[1m\])?$", "", name.strip().lower())
    base = re.sub(r"-\d{8}$", "", base)
    if base in CURRENT_MODELS:
        return "current"
    return "legacy" if base in LEGACY_MODELS else ""


MODEL_ALIASES = {"sonnet", "opus", "haiku", "fable"}


def safe_model(value: object, fallback: str) -> str:
    """A model name that is safe to write into settings or frontmatter: a known alias or a known id.

    Policy files come from the scanned project and are untrusted: anything else (a route name, a
    string with a newline, a path) is replaced by `fallback`, so a repository cannot choose what is
    written into the user's own configuration."""
    name = str(value).strip().lower()
    if name in MODEL_ALIASES or model_status(name):
        return name
    return fallback
