# claude-lint

Validate, repair and harden everything Claude-related in a repository and on your
machine: Claude Code settings, permissions, hooks, helpers (status line, API key helper),
MCP servers, instruction files, rules, skills, subagents, commands, output styles,
plugins and marketplaces, keybindings, Claude Desktop MCP configuration, managed
settings, GitHub Actions workflows running the Claude action, misplaced or misnamed
files, and leaked Anthropic API keys. Rules follow the official documentation
(snapshot 2026-09) and known upstream issues.

Two layers:

| Layer | What it does | Safety |
|---|---|---|
| `claude-lint.py` | Deterministic checks and repairs, CI-friendly | Only tightens; never adds an allow rule |
| `skills/config-audit` | Guarded agent session for judgment calls and doc drift | Every agent edit is checked by `--guard`; loosening is blocked |

Single Python file, no dependencies. Python >= 3.9 (>= 3.11 to read a policy file).

## Contents

```
claude-lint.py          the linter / fixer / guard
skills/config-audit/SKILL.md  guarded audit workflow (user-invoked only)
claude-lint.example.toml       default policy, copy to <repo>/.claude-lint.toml to customize
README.md
```

## Install

`claude-lint.py` is a single file with no dependencies (Python >= 3.9). Copy it
anywhere on your `PATH` and make it executable:

```sh
curl -O https://raw.githubusercontent.com/chrysa/claude-lint/main/claude-lint.py
chmod +x claude-lint.py && ./claude-lint.py --help
# or drop it on your PATH:
install -m 0755 claude-lint.py ~/.local/bin/claude-lint
```

Running it with no arguments prints the help, including the effective defaults.
Optional companions it uses when present: the `claude` CLI (`--no-cli` to skip),
`rtk`, and `llmtrim`. Python >= 3.11 is only needed to read a policy file.

## Quick start

```sh
./claude-lint.py . --user --generate         # preview everything it would generate
./claude-lint.py . --user --generate --fix   # generate, then lint and repair the result
./claude-lint.py .                 # read-only: findings, diff, summary
./claude-lint.py . --fix           # apply repairs (backup in ~/.cache/claude-lint/)
./claude-lint.py . --user --fix    # include user scope (~/.claude or $CLAUDE_CONFIG_DIR)
./claude-lint.py ~/dev --fix       # every git repository under ~/dev (3 levels deep)
```

By default a run prints a **brief report**, in priority order and plain language:
security and portfolio rules, what is configured but broken, what weighs on every
session (tokens), duplicates, then a one-line count of the rest and the next steps.
`--details` (or `--all`) prints the full per-file report described below. During the
scan a progress bar is shown on stderr by default (interactive terminal only; `-v`
replaces it with per-repository logs, and `-q`, `--format json`, a pipe or CI stay
silent). Output on stdout is never affected.

In `--details`, every finding is printed with a `→ fix` (`→ solution` in French)
line proposing a concrete action — the fix to apply, or where to apply it when the
target is read-only — so the report is a to-do list, not just a list of problems.
`-v` additionally prints the documentation reference for each.

The full report ends with:

- **SUMMARY**: what was fixed or generated (or would be, in read-only mode) and what needs
  manual action. Findings repeated more than 5 times are grouped into one line with the
  count, the most common message and the first files (`--all` lists them one by one).
- **TOKENS**: estimated context loaded in every session, by kind and by biggest group
  (for example one `agents/<pack>` directory). In `--details`, each finding that
  weighs on context is annotated with its estimated `~N tokens/session`, and the
  block ends with a **Potential savings** total (findings + restructurings) — what
  you would reclaim per session by acting on them with `--fix` / `-i`.
- **STATS**: how many items were checked (settings files, permission rules, hook
  handlers, MCP servers, skills, subagents, commands, rules, instruction files, plugins),
  a per-category table (found, fixed, remaining errors / warnings / info) and the
  noisiest checks. Also in `--format json` under `stats`.

## Options

| Option | Effect |
|---|---|
| `--fix` | Apply repairs (and generation) in passes until stable, then re-lint |
| `--generate` | Generate missing configuration for the detected stack (see below) |
| `--user`, `--user-only` | Include / restrict to user scope |
| `--no-scaffold` | Do not create missing files |
| `--format json` | Machine-readable output (`findings`, `fixed`, `not_fixed`, `would_fix`, `hints`) |
| `--strict` | Exit 1 on warnings too (CI) |
| `--policy FILE` | Policy file (default `<repo>/.claude-lint.toml`) |
| `--no-history` | Skip the git history scan for attribution |
| `--no-cli` | Do not call the `claude` / `rtk` CLIs (static fallbacks are used) |
| `--rtk-report` | Append `rtk gain` and `rtk discover --since 7` output |
| `-v` / `-vv` / `-vvv` | Progress + why/how + doc link / every transformation / debug |
| `-q` | Errors and summary only |
| `-i`, `--interactive` | Review one by one, in a terminal: duplicates to remove, subagent packs to park, long skill descriptions to shorten, non-agent files in `agents/`, Opus as default model, user MCP commands to run. Every move is reversible (`restore.sh`) |
| `--restore [DIR]` | Move back everything removed by the last `-i` session (or the given trash folder); never overwrites an existing file |
| `--details` | Full per-file report instead of the brief one |
| `--lang en\|fr` | Language of the brief report. Defaults to French when `$LANG` starts with `fr`, English otherwise. The interactive review is always French |
| `--all` | List every finding (repeated findings are grouped by default, above 5 of the same kind) |
| `--min-level error\|warn\|info` | Hide findings below this level (e.g. `--min-level warn` drops the info noise) |
| `--print-policy` | Print the default policy as TOML |
| `--print-catalog` | Print the editable catalog (reference sets + per-check metadata) as YAML |
| `--catalog FILE` | Load an edited catalog: extend the known keys/events/tools/fields, and override any check's severity (`error`/`warn`/`info`/`off`), `enabled`, or `→ fix` action |
| `--plugin-dir DIR` | Extra directory of check plugins (repeatable). Also loaded from `<config dir>/plugins` and `<repo>/.claude-lint/plugins` |
| `--list-plugins` | List discovered plugins and the checks they register, then exit |
| `--dump-reference` | Print built-in reference data (keys, events, tools, fields) |
| `--session-settings FILE` | Write settings for a guarded agent session |
| `--guard` | PreToolUse hook mode (stdin JSON, exit 2 blocks) |

Exit codes: `0` clean, `1` errors (or warnings with `--strict`), `2` usage error or guard block.

## Run log

Every run appends one JSON line to `~/.cache/claude-lint/logs/<date>.log` (one file
per day). Each record holds the timestamp, version, arguments, repository count, elapsed
time, finding counts by level and by code, how many findings were fixed or applied, and the
exit code — counts and codes only, never file contents or secrets. Logging is best-effort:
a failure to write the log never changes the run's result or exit code. The same directory
also holds `--fix` backups and, under `trash/`, whatever an interactive session removed.

## Duplicates and interactive review

Skills, subagents and commands are compared within what one session loads together (the
user scope alone, then the user scope plus each project), so the same skill living in two
unrelated repositories is not a duplicate; a skill copied into 5 or more repositories is
reported once (`DUP_ACROSS_PROJECTS`). Git worktrees under `.claude/worktrees/` are skipped.

- `DUP_EXACT`: identical content (after the frontmatter) in several places;
- `DUP_NAME`: same name for two items of the same kind (a skill and a command count as
  the same kind: only one runs);
- `DUP_SIMILAR`: name and description sharing at least 60% of their meaningful words.

Items generated from one template (for example one wrapper subagent per model, where only
the name and model id differ) are not reported as duplicates but as a family
(`DUP_FAMILY`), with their token cost: `-i` offers to turn a family into a plugin or park it.

The interactive session (`-i`) starts with a menu of sections (duplicates, families,
restructuring, long descriptions, model and MCP) with counts; pick some or all. Each
question explains what the item is and what happens today, gives advice following Claude
Code precedence: for skills the user copy wins, so a project copy is dead and can go; for
subagents the project copy wins in that project only, so an identical project copy can go
but a different one is treated as an intended override. A user-scope item is never
proposed for removal because of one project, since it also serves every other project. marks what the advice would remove, and accepts batch answers (apply
the advice to every safe group, accept or skip every proposal of one kind). `vN` shows a
file before deciding. A final summary lists what was done and the undo script.

They are reported in every run. With `-i`, each cluster is shown with kind, name, size,
last modification date, path and description, and you choose what to remove. Nothing
is deleted: removed items go to `~/.cache/claude-lint/trash/<timestamp>/`, parked
subagent packs to `<config dir>/parked/` (not loaded), and a `restore.sh` in the trash
folder undoes every move of the session. The same session offers to park subagent packs
(per `agents/<pack>/<group>` directory, with their token cost), shorten skill descriptions
over `tokens.skill_description_chars` (the full text is kept under
`metadata.full_description`), move non-agent Markdown out of `agents/`, switch an Opus
default to Sonnet, and run the suggested `claude mcp add` commands. Agents running under
the guard cannot start it.

## Restructuring proposals

Every run ends with a **RESTRUCTURE** plan: changes of structure that make the setup load
less and work better, ranked by the tokens they remove from every session. With `-i`
each one is offered in turn and applied only if you accept; every change is reversible
(`restore.sh` for moves, backups in `~/.cache/claude-lint/` for edits).

| Proposal | What `-i` does |
|---|---|
| Subagent pack (`agents/<pack>/<group>`, 3+ agents) → on-demand plugin | Moves the agents into `<config dir>/local-marketplace/plugins/<name>/agents/`, writes `plugin.json` and the local `marketplace.json`, registers the marketplace in user settings (`extraKnownMarketplaces`). Nothing is loaded until you install the plugin with the project scope where it is needed. Alternative answer `k` parks the pack instead. |
| Skill family (3+ skills sharing a prefix, such as `django-*`) → on-demand plugin | Same, under `plugins/<prefix>-skills/skills/`; the skills are then invoked as `/<plugin>:<skill>` (or by their bare name when unique). |
| Skill over 500 lines → `SKILL.md` + `references/` | Keeps the introduction and first sections (up to `restructure.skill_keep_lines`), moves the other `##` sections into `references/<section>.md` and links them, fence-aware. |
| Command → skill | Moves `commands/x.md` to `skills/x/SKILL.md` (same `/x`, plus skill features). |
| Unscoped rule clearly about one language or tool → `paths:` | Adds the matching glob (`**/*.py`, `**/*.{ts,tsx}`, `**/*.tf`...). |
| Procedure section in `CLAUDE.md` (numbered steps, 15+ lines) → skill | Moves the section into `skills/<slug>/SKILL.md` and leaves a one-line pointer. `AGENTS.md` is never touched (it stays tool-neutral). |

## Token optimization

Every run ends with a **TOKENS** block: an estimate (bytes / 4) of what is re-sent with
every request, split into instruction files and their imports, unscoped rules, the skill
and subagent listing, the auto-memory index and MCP servers, with the five biggest
contributors. Above `tokens.max_always_loaded` (10,000 by default) it becomes a warning.

What reduces it, following the official cost guidance:

| Lever | Where |
|---|---|
| Instruction files under 200 lines, HTML comments (free) for maintainer notes, imports counted as loaded | lint (`INSTR_*`, `TOKEN_IMPORTS`) |
| Rules scoped with `paths:` so they load only for matching files | lint (`RULE_UNSCOPED`) |
| Short skill descriptions (listed every turn); side-effect skills get `disable-model-invocation`, which also removes them from the listing | lint, `--fix` |
| No MCP server when the CLI is installed (`gh`, `sentry-cli`, `aws`, `gcloud`); servers capped | lint (`MCP_PREFER_CLI`), generation skips them |
| rtk compresses Bash output, only where it rewrites; hook present; no duplicated awareness | lint, `--fix`, generation |
| Generated and vendored directories denied to `Read` (`node_modules`, `.venv`, `dist`, `coverage`, `.next`, source maps, Unity `Library/`...) | generation |
| Mechanical subagents on `model: haiku` (generated `test-runner`); verbose work delegated to subagents | generation, lint (`TOKEN_SUBAGENT_MODEL`) |
| Compaction instructions in `CLAUDE.md` (keep decisions and failures, drop logs) | generation |
| `crossSessionInbound = "hold"`: no idle turns re-sending the whole context | generation (user) |
| Opus as default model, missing code intelligence plugin for typed stacks | lint (`TOKEN_MODEL`, `TOKEN_LSP`) |
| Instruction duplicated between user and project scope | lint (`INSTR_DUPLICATED`) |

Session habits the tool cannot enforce are printed with the block: `/clear` between
tasks, `/context` and `/usage` to check, `/skill-doctor` for unused skills, Sonnet by
default. The estimate is conservative about MCP (tool definitions are deferred: only
names and server instructions load) and does not include the system prompt.

## Generation (`--generate`)

The repository is scanned first (Python / uv, Node package manager and scripts, React-like
UI, Docker / Compose, Kubernetes / Helm, Terraform / OpenTofu, Unity, Makefile targets,
GitHub remote and `gh`, Sentry and Supabase dependencies), then only what is missing is
created or completed. Existing rules, hooks and servers are kept; files are never
overwritten. Everything generated goes through the linter in the same run, so the output
already follows every rule below.

| Generated | Content |
|---|---|
| `.claude/settings.json` | `$schema`, attribution off; allow rules for the stack's read and build commands (git read/add/commit, safe Makefile targets, pytest/ruff/mypy, package scripts, docker compose, kubectl read, helm template/lint, terraform fmt/validate/plan, gh read), routed through rtk only where rtk rewrites them; `ask` for external actions and gated Makefile targets (`deploy`, `release`...); `deny` for secrets and generated directories (plus Unity `Library/`, `Temp/`...) |
| `.claude/hooks/format.py` + PostToolUse hook | formats the edited file with the project's own tools (ruff, local prettier, terraform fmt, gofmt); never blocks |
| `.claude/skills/check` | runs the project's lint and test commands, reports failures only |
| `.claude/skills/review-changes` | reviews the uncommitted diff against `AGENTS.md` |
| `.claude/agents/` | `code-reviewer`, `test-runner`, `security-auditor`, `infra-reviewer` (read-only tools, except the test runner) when relevant |
| `.mcp.json` | `github` (remote repo on GitHub, token from `${GITHUB_PERSONAL_ACCESS_TOKEN}`), `sentry` and `supabase` (when used, OAuth), `playwright` (web UI); capped by `mcp.max_servers` |
| `.gitignore` | `.claude/settings.local.json`, `CLAUDE.local.md`, plus a secrets block (`.env`, `*.pem`, `*.key`, `secrets/`) when missing (`[security] scaffold_gitignore`) |
| `AGENTS.md`, `CLAUDE.md` | skeleton and `@AGENTS.md` import (scaffolding) |
| `pre-compact.sh` | portable `PreCompact` hook (session snapshot) when settings reference one that is missing (`[security] scaffold_missing_hooks`); written inside the repo or the user config dir only |
| `~/.claude/settings.json` (`--user`) | attribution off, deny on `~/.ssh`, `~/.aws`, `~/.kube`, `~/.gnupg`, vault token, gh hosts; `disableBypassPermissionsMode`; native rtk hook and `RTK_TELEMETRY_DISABLED=1` when rtk is installed |
| rtk `config.toml` (`--user`) | `[hooks] exclude_commands`, `[retriever] mode = "sqlite"` |
| user MCP servers (`--user`) | printed as `claude mcp add --scope user ...` commands (Notion by default): `~/.claude.json` is written by the CLI only |

Tune it in `.claude-lint.toml`, table `[generate]`: which skills, agents and MCP servers,
`extra_allow` / `extra_ask` / `extra_deny`, safe and gated Makefile targets,
`rtk_exclude_commands`, and on/off switches per artifact.

## What it checks and repairs

**Settings** (`.claude/settings*.json`, user settings): strict JSON (comments, trailing
commas and BOM repaired), `$schema`, deprecated `includeCoAuthoredBy` migrated,
`attribution` disabled, keys a repository cannot set, `disableAllHooks`,
`enableAllProjectMcpServers`, inline secrets removed, `settings.local.json` gitignored.

**Permissions**: rule syntax and tool-name case, legacy tools (`Task` -> `Agent`),
path rules on `Write`/`Glob`/`Grep`/`NotebookEdit` (never consulted) rewritten to
`Edit`/`Read`, `mcp__` rules with parentheses, parameter rules on primary fields,
mid-rule `:*`, single-slash absolute paths (`/home/...` -> `//home/...`), `WebFetch`
without `domain:`, unanchored allow globs, unrestricted shell, environment runners
(`npx *`, `uv run *`...), wildcard before the subcommand, external actions moved from
`allow` to `ask`, allow rules dead under a deny, shadowed and duplicate rules, required
deny rules for secrets, rtk routing for Bash allow rules and rtk/non-rtk twins for
deny/ask rules (anthropics/claude-code#79400).

**Hooks**: event names, legacy and flattened formats, handler types and required fields,
`if` on non-tool events, matchers on events without matcher support, `mcp__server`
matchers that match nothing, non-canonical tool names, `once` outside skills, relative
script paths converted to exec form on `${CLAUDE_PROJECT_DIR}`, missing or
non-executable scripts, gating scripts that exit 1 instead of 2, async gating hooks,
HTTP header variables missing from `allowedEnvVars`, `mcp_tool` hooks skipped at launch,
hooks re-printing instruction files.

**MCP** (`.mcp.json`, read-only `~/.claude.json`): shape, `type` for URL servers,
command/args split, deprecated SSE, inline secrets replaced by `${VAR}`, server count.

**Instructions**: size (200-line target, 4 MiB hard limit, HTML comments excluded),
`@imports` (missing, deeper than four hops, external), `AGENTS.md` loading rules
(`CLAUDE.md` must import it; `CLAUDE.local.md` silently disables it), `CLAUDE.local.md`
gitignored, generated renders when `doctrine/rules/` exists, lines duplicated from user
scope, auto-memory `MEMORY.md` over 200 lines / 25 KB. Instruction files for other agent
tools are checked the same way — `.github/copilot-instructions.md` (Copilot),
`.cursorrules` (Cursor), `.windsurfrules` (Windsurf) and `GEMINI.md` (Gemini CLI); Codex /
ChatGPT read `AGENTS.md` directly. Adjust the list in `[instructions] rendered_files`.

**Rules** (`.claude/rules`): `paths` only (`globs`/`applyTo` renamed), invalid patterns,
frontmatter not on line 1, symlinks outside the project.

**Skills, subagents, commands**: frontmatter position and typos, custom fields moved under
`metadata:` (kept, and valid for the Agent Skills spec), `trigger`/`triggers` copied
into `when_to_use` so Claude Code actually uses them, subagent fields shared by a whole
pack (such as `emoji`, `vibe`) reported once instead of per file,
Agent Skills spec portability, name vs directory, description (derived when missing,
1536-char listing cap), 500-line body, fork-only fields, `disable-model-invocation` added
to side-effect skills, broad `allowed-tools`, reserved `synced` name, commands shadowed
by skills, subagent `name`/`description`/`tools`.

**Attribution**: assistant signatures in files and recent commits; installs a
`commit-msg` hook that strips them.

**Helpers**: `statusLine`, `subagentStatusLine`, `fileSuggestion`, `apiKeyHelper`,
`awsAuthRefresh`, `awsCredentialExport`, `otelHeadersHelper`: command present, script
exists and is executable (chmod fixed), repository-supplied helpers flagged.

**Plugins and marketplaces** (any `.claude-plugin/` in the repository): manifest
(`name` kebab-case, semver `version`, unknown fields, missing metadata), component paths
(`./` prefix fixed, absolute or escaping paths, missing targets), components wrongly
placed inside `.claude-plugin/`, plugin `hooks/hooks.json`, `.mcp.json`, skills, agents,
commands and output styles; `marketplace.json` (name, plugin entries, local sources,
duplicates); `enabledPlugins` and `extraKnownMarketplaces` in settings. When the `claude`
CLI is installed, `claude plugin validate` is run as the authoritative check.

**Output styles** (`.claude/output-styles`, user and plugin): frontmatter position,
description, unknown fields.

**Misplaced or misnamed files**: `claude.md` / `Claude.md` and `agents.md` (not loaded on
case-sensitive systems: renamed), `mcp.json` or `.claude/.mcp.json` (moved to
`./.mcp.json`), flat `.claude/skills/x.md` (moved to `x/SKILL.md`), `mcpServers` inside
`settings.json` (moved to `.mcp.json`), `.claudeignore` (no such feature),
`.claude/settings.yaml`, `.claude/config.json`, a `.claude.json` inside a repository.

**GitHub Actions** (workflows using `anthropics/claude-code-action`): moving refs
(`@main`), literal credentials, permission bypass, unrestricted Bash, missing
`permissions:` block, `pull_request_target`, `issue_comment` without author filter.

**Credentials**: Anthropic API keys in any repository file (committed ones must be
rotated) and in shell startup files.

**User machine** (`--user`): `keybindings.json`, user output styles, Claude Desktop
`claude_desktop_config.json` (Linux, macOS, Windows paths), managed settings validity
(read-only), `~/.claude.json` (read-only).

**rtk (Rust Token Killer)**, when `permissions.require_rtk` is on:

- installation: rtk missing, wrong package on PATH (Rust Type Kit collision, detected
  with `rtk gain`), versions before the native hook (0.37.2);
- hook: no rtk `PreToolUse` hook (the native `rtk hook claude` hook is added to user
  settings), legacy `rtk-rewrite.sh` shell hook, matcher that misses `Bash`;
- permissions: allow rules are routed through rtk **only for commands rtk actually
  rewrites** (asked to `rtk rewrite` when available, README list otherwise, minus
  `[hooks] exclude_commands`); existing `Bash(rtk make ...)`-style rules that can never
  match are unwrapped back to the plain command, only when rtk itself reports what it
  supports (`rtk rewrite` or `rtk --help`) and never for rtk's own commands (`env`,
  `proxy`, `read`...); `rtk proxy`/`test`/`err`/`summary` rules are flagged as runners; deny/ask rules get rtk/non-rtk twins;
- `config.toml`: TOML validity, `awareness = "full"` alongside the hook (context
  duplicated), retriever disabled (no `rtk recall` after failures), telemetry enabled;
- `--rtk-report` shows measured savings and missed commands, so you can decide with data
  (compression is not free: the hook only sees Bash, never Read/Grep/Glob).

When `require_rtk` is on but `rtk` is not installed, the tool says so and points to both
ways forward: install rtk, or set `permissions.require_rtk = false` to skip rtk routing.
Both `rtk` and `llmtrim` are probed only when the CLIs are allowed (not under `--no-cli`).

**llmtrim** (companion CLI, when present): subagents that carry the llmtrim route marker
delegate to the `llmtrim` binary. If those route subagents exist but `llmtrim` is not on
`PATH`, the tool reports it (`LLMTRIM_MISSING`) — they load into every session but route
nowhere — so you can install llmtrim or remove them (`-i` offers to park them). When
llmtrim is installed, its route agents are left alone.

**Scaffolding** (disable with `--no-scaffold`): baseline `.claude/settings.json`,
`AGENTS.md` skeleton plus `CLAUDE.md` importing it, user settings, commit-msg hook.

## Guarded audit session

For what the linter cannot decide (renaming, rewriting hook scripts, splitting long
instruction files) and to follow documentation changes:

```sh
cp -r skills/config-audit <repo>/.claude/skills/      # or ~/.claude/skills/
./claude-lint.py --session-settings /tmp/audit.json
claude --settings /tmp/audit.json                     # then run /config-audit
```

The session file (read-only) installs `claude-lint.py --guard` on every edit and
shell command, and denies commits, pushes and external actions. The guard blocks any
edit that would:

- add an allow rule, remove a deny/ask rule, enable bypass or auto modes, extend
  `additionalDirectories`, disable the sandbox;
- remove a hook, set `disableAllHooks`, add MCP servers, env variables or code-executing
  helpers (`apiKeyHelper`, `statusLine`, plugins...);
- extend a skill's or subagent's tools, remove `disable-model-invocation`, add
  frontmatter hooks, inline MCP servers or shell injection;
- add assistant attribution anywhere;
- add a plugin component that executes code (hooks, MCP, LSP, monitors), a new
  marketplace plugin, or a Desktop MCP server;
- add a permission bypass, `pull_request_target` or unrestricted Bash to a CI workflow,
  or remove its `permissions:` block;
- touch `~/.claude.json`, managed settings, synced skills, installed plugins, git hooks,
  the linter or the session file;
- change `.claude-lint.toml` outside the `[reference]` table;
- run `--generate --fix`, `--session-settings` or `--policy` (a `--generate` preview is allowed);
- write configuration files through the shell instead of Edit/Write.

The guard fails closed: any internal error blocks. The workflow stops for approval after
the plan and ends with a report in two sections: fixed / not fixed.

### Keeping up with the docs

The agent compares `--dump-reference` with the current documentation and records new
settings keys, hook events, tools and fields in the `[reference]` table of
`.claude-lint.toml`. The linter then recognises them without code changes. Changes that
need new logic are reported, not worked around.

## Policy

Copy `claude-lint.example.toml` to `<repo>/.claude-lint.toml` and keep only what you
change. Main knobs: `permissions.require_rtk`, `permissions.rtk_twin_deny`,
`permissions.rule_style` (`keep` / `space` / `colon`), `permissions.external_action_prefixes`,
`permissions.required_deny` (rtk also reads its own `exclude_commands`), `skills.portable`, `skills.gate_side_effects`,
`instructions.claude_md_import`, `scaffold.*`.

### Model, effort and scopes

Under `[tokens]` you set what the token checks expect, instead of them hard-coding
model names:

```toml
[tokens]
preferred_model = "sonnet"      # recommended session default
heavy_models = ["opus"]         # flagged (TOKEN_MODEL) when set as the default
subagent_model = "haiku"        # suggested for mechanical subagents
max_effort = "high"             # effortLevel above this is flagged; "" disables
effort_levels = ["low", "medium", "high"]
```

`[scopes]` declares where each item type is expected to live
(`project` = a repo's `.claude/`, `user` = `~/.claude*`, `local` =
git-ignored `settings.local.json`). An item found outside its scopes is flagged:

```toml
[scopes]
skill   = ["project", "user"]
agent   = ["project", "user"]
command = ["project", "user"]
mcp     = ["project", "user", "local"]
secret  = ["local"]             # secrets never in committed settings
```

Related checks: `TOKEN_MODEL`, `TOKEN_SUBAGENT_MODEL`, `TOKEN_EFFORT`,
`SCOPE_SECRET`, `SCOPE_MISMATCH`. See the built-in policy with `--print-policy`.

## Catalog (editable checks)

The reference data (known settings keys, hook events, tools, skill/agent fields)
and the metadata of every check (severity, category, `→ fix` action, doc ref) are
exposed as one editable YAML catalog. Export it, edit it, and feed it back:

```sh
claude-lint.py --print-catalog > claude-lint.catalog.yaml   # the built-in catalog
# edit it, then:
claude-lint.py . --catalog claude-lint.catalog.yaml
```

An overlaid catalog:

- **extends the reference sets** — add a new settings key, hook event, tool or
  frontmatter field so the linter accepts it (useful as Claude Code evolves);
- **overrides a check** — set `severity` to `error` / `warn` / `info` / `off`
  (or `enabled: false`) to re-rank or silence it, and set `action_fr` / `action_en`
  to change the `→ fix` line shown in `--details`.

Anything not mentioned in the file keeps its built-in default, so a catalog can be
as small as the changes you want. The catalog needs PyYAML
(`pip install 'PyYAML>=6'`, declared under `[project.optional-dependencies].catalog`
in `pyproject.toml`); without it the linter still runs and
the `--catalog` / `--print-catalog` options degrade gracefully.

## Plugins (add your own checks)

New checks can be added as plugins, without editing the engine. A plugin is a
`.py` file dropped in a plugin directory; it defines `register(api)` and registers
one or more checks:

```python
def register(api):
    @api.check("MY_RULE", scope="project")   # or scope="user"
    def _rule(ctx):
        p = ctx.path("forbidden.txt")
        if p.is_file():
            ctx.add("warn", "MY_RULE", p, "forbidden.txt must not be committed",
                    action_en="delete it or add it to .gitignore")
```

`ctx` gives `root`, `path(*parts)`, `read(path)`, `glob(pattern)` and `add(level,
code, path, message, action_fr=…, action_en=…, fixable=…)`. Plugin findings flow
into the normal report and obey the catalog (a plugin code can be disabled or
re-ranked via `--catalog`, and its `→ fix` action shows in `--details`). A plugin
that raises is reported and skipped — it never crashes a run.

Discovery, in order: `<config dir>/plugins/`, `<repo>/.claude-lint/plugins/`, and
any `--plugin-dir DIR` (repeatable). `--list-plugins` shows what loaded. A ready
example is in [`examples/plugins/example_check.py`](examples/plugins/example_check.py).

## CI

```sh
python3 claude-lint.py . --strict --format json --no-cli --no-scaffold
```

## Limits

- Reference data reflects the documentation at a point in time; unknown keys are
  reported as info, never as errors.
- The guard's shell check is heuristic: a program writing a settings file without
  naming it on the command line is not detected. Enable the sandbox during audits for
  an OS-level boundary.
- Permission rules are not a security boundary on their own (indirect reads, other
  invocation forms); the sandbox is.
