# Architecture

How prism-ai-lint is built, so a change lands in the right place. User-facing behaviour lives in
[README.md](README.md); the rationale behind the choices here is in [DECISIONS.md](DECISIONS.md).

## Shape

- **`prism-ai-lint.py`** — thin CLI wrapper: `from prism_ai_lint import main`. Kept as a hyphenated,
  directly runnable entry point.
- **`prism_ai_lint/_engine.py`** — legacy orchestration module: checks, repairs, generation,
  guard, catalogue, plugins and rendering. It is importable (tests, mypy and coverage
  attach to it); the hyphenated name could not be imported, hence the split.
- **`prism_ai_lint/content_validation.py`** — object-oriented validation gate for critical
  content files in guarded sessions (`CriticalContentValidator`, `CriticalContentPolicy`).
- **`prism_ai_lint/project_profile.py`** — object-oriented stack and project-profile detection
  (`ProjectProfiler`) used by reports, JSON and future generation branching.
- **`prism_ai_lint/self_update.py`** — object-oriented self-update prompt (`SelfUpdater`,
  `SelfUpdateConfig`, `GitRunner`). New isolated domains should follow this pattern:
  one thematic module, empty package `__init__.py`, small objects with explicit methods.
- No runtime dependencies (standard library only). PyYAML is optional and used **only** by
  the editable catalogue (`--catalog` / `--print-catalog`); everything degrades gracefully
  without it.

## Module map

`prism_ai_lint/_engine.py` still carries most historical behaviour. Navigate by the `# ----`
section banners:

| Region (approx.) | Contents |
|---|---|
| `# Policy` | `DEFAULT_POLICY` (nested dict), `load_policy` (TOML overlay via `deep_merge`), `to_toml`. Every knob defaults here. |
| `prism_ai_lint/_reference.py` (docs snapshot) | Known settings keys, hook events, tools, skill/agent fields, dead keys; also the attribution patterns and the scaffold templates (`COMMIT_MSG_HOOK`, `PRE_COMPACT_HOOK`, `SECRETS_GITIGNORE`, `AGENTS_SKELETON`). Pure data shared by every module. The source of truth the checks compare against; carries the doc date. |
| `# Hints and references` | `HINTS[code] = (why/how, doc_url)`. |
| checks | `check_*` functions (settings, permissions, plugins, workflows, secrets). Each appends `Finding`s to a `Report`. |
| `# Token budget` | `token_budget`, `check_token_levers`, `check_effort_levels`, `render_token_budget` — the always-loaded weight estimate and its levers. |
| `# Scaffolding` | `scaffold_project`, `scaffold_user`, `scaffold_security`, `gen_new_file` — files `--generate` proposes. |
| `# Orchestration` | `run_lint`, `lint_repo`, `lint_user`, `apply`, `main`, and the render functions. |
| `# Guard` | `guard_check`, `run_guard` — the PreToolUse hook. |
| `# Plugin system` | `CheckContext`, `PluginAPI`, `load_plugins`, `run_plugin_checks`. |
| catalogue | `catalog_data`, `dump_catalog`, `load_catalog`. |
| `prism_ai_lint/_runtime.py` | `RunState` (`state`): per-run options set by `main()`, plus base helpers `log`, `read_text`, `_loc`, `dedupe`, `_writable`, `config_dir`, `lenient_json`, `dump_json`, and the git helpers `git`, `is_tracked`, `is_ignored`, `add_gitignore`. Extracted check modules import these from here, never from `_engine` (D-022). |
| `prism_ai_lint/hook_checker.py` | `HookChecker`: hook events, matchers, handlers, script paths and exec form. The engine holds one instance (`_HOOKS`) and injects `check_env_secrets`. |
| `prism_ai_lint/secret_scan.py` | `InlineSecretScanner.check_env_secrets`: literal secrets in env, headers and args; reports, or replaces them by `${VAR}` / removes them. One engine instance (`_SECRETS`), injected into the hook and MCP checkers. |
| `prism_ai_lint/mcp_checker.py` | `McpChecker`: `.mcp.json` servers (shape, type, command/args split, inline secrets, count) and the read-only `~/.claude.json`. Engine instance `_MCP`. |
| `prism_ai_lint/_markup.py` | Markdown helpers: frontmatter (`split_frontmatter`, `set_frontmatter`...), `strip_code`, `strip_html_comments`, `@import` parsing (`IMPORT_RE`, `import_targets`), `slugify`, `derive_description`, `frontmatter_of`, `move_to_metadata`. |
| `prism_ai_lint/instruction_checker.py` | `InstructionChecker`: instruction file size and style, `@imports`, `AGENTS.md` wiring, rendered files, `.claude/rules` frontmatter, auto-memory `MEMORY.md`. Engine instance `_INSTRUCTIONS`. |
| `prism_ai_lint/skill_agent_checker.py` | `SkillAgentChecker`: skill and subagent frontmatter, names, descriptions, tools, Agent Skills spec portability, asset directories. Receives the `InstructionChecker` for rules inside asset dirs. Engine instance `_SKILLS`. |
| `prism_ai_lint/content_validation.py` | `CriticalContentValidator.validation_reason()` blocks critical content edits until human validation. Covers instruction, doc, config and rule files. Generic defaults; repository-specific files come from `[critical] extra_files` (`state.critical_extra`). |
| `prism_ai_lint/project_profile.py` | `ProjectProfiler.detect_stack()` and `.detect_profile()` classify the scanned repo (CLI, library, app, etc.). Standards-repository markers come from `[profile] standards_markers`; none by default. |
| `prism_ai_lint/self_update.py` | `SelfUpdater.check()` handles release-branch update detection, confirmation and `git pull --ff-only`; config is in `SelfUpdateConfig`. |
| `prism_ai_lint/update_followup.py` | `UpdateFollowUp`: after an accepted self-update, offers the changelog (`git log old..new`) and a `--fix` run on a chosen folder or on the whole PC (`all`: home + user scope). Runs in a fresh process on the new code, shows the exact command, asks confirmation, never passes `--full-yes`. |
| `prism_ai_lint/config_flags.py` | `ConfigFlags`: CLI defaults from the `[flags]` table of `.prism-ai-lint.toml` in the current directory, limited to options that never write (`SAFE_FLAGS`); the command line wins, other keys are rejected with a warning, guard mode never reads it. |
| `prism_ai_lint/ape_checker.py` | `APEChecker`: hedging verbs and open-ended scope in instruction files; `InstructionChecker` reports one `INSTR_VAGUE` (info) per file above `instructions.vague_wording_min`. |
| `prism_ai_lint/llmtrim_checker.py` | `LlmtrimChecker`: `token_budget` adds `LLMTRIM_SUGGESTED` (info) when the always-loaded context exceeds `tokens.max_always_loaded` and llmtrim is absent (skipped with `--no-cli`). |
| `prism_ai_lint/agent_converter.py` | `AgentConverter` and per-tool adapters (`ClaudeAdapter`, `CodexAdapter`, `AgentsAdapter`) for lossless agent-config conversion (Claude ↔ Codex ↔ AGENTS). |
| `prism_ai_lint/guard_checker.py` | `GuardChecker` extracts guard logic from engine: PreToolUse checks for loosening config, removed deny rules, attribution, critical content. |
| `prism_ai_lint/tui_app.py` | `TuiApp` (interactive terminal review) and `TuiServices` provide structured feedback, section selection, critical-diff approval, conversion flows and readiness signals. |
| `prism_ai_lint/plugin_registry.py` | `CheckContext`, `PluginAPI`, `PluginRegistry` for user-defined checks via plugins. |
| `prism_ai_lint/finding.py`, `report.py`, `feedback_renderer.py` | Core finding/report model + rendering layer. |
| `prism_ai_lint/pdf_checker.py` | `PdfChecker`: PDFs inside `.claude/` or referenced from instruction files, at or above `tokens.pdf_min_bytes`; the engine reports `PDF_HEAVY` (info). Read-only, never converts. |
| `prism_ai_lint/compression_checker.py` | `CompressionChecker`: rtk, llmtrim and a local gateway found in settings; two or more layers give `COMPRESSION_DOUBLE` (info). |
| `prism_ai_lint/issue_reporter.py` | `Anonymizer` and `IssueReporter`: anonymized Markdown for unfixed findings (`--report-issue`), local preview only. Policy `[reporting]`. |
| `prism_ai_lint/desktop_checker.py` | `DesktopChecker` detects desktop-app frameworks (Electron, Tauri, .NET, Java) and OS-specific config paths. |

## Core types

- **`Finding(level, code, path, message, fixable)`** — one result. `level` ∈
  error/warn/info; `code` is a stable slug (e.g. `HOOK_MISSING_SCRIPT`).
- **`Report`** — collects findings and pending mutations: `edits` (path → (old, new)),
  `new_files` (path → (content, mode)), `chmods`, `moves`, plus `budget`/`stats`.
  `Report.add()` honours the catalogue's `DISABLED_CODES` and `SEVERITY_OVERRIDES`.
  `Report.edit()` chains successive edits to the same file.

## Data flow

1. `main` reads safe `[flags]` defaults (`ConfigFlags`, skipped in guard mode), parses args via argparse. Sets run options on `prism_ai_lint._runtime.state` (`verbosity`,
   `show_diff`, `scaffold`, `lang`, `min_level`...), loads policy, catalogue, plugins.
2. `--convert-to` / `--convert-from`: `AgentConverter` plans lossless conversion between
   Claude/Codex/AGENTS formats. `--approve-conversion` + `apply_conversion()` write the target.
   Guard checks conversion writes via `GuardChecker.mcp_violations()` before critical
   validation blocks (content-violations-first order).
3. `run_lint` builds fresh `Report`, runs `lint_user` (user scope) and `lint_repo` per repo.
   Checks only **record** findings and mutations — never write. `ProjectProfiler` detects stack.
4. `--guard` PreToolUse: `GuardChecker` runs first, checks content violations (MCP, perms, etc),
   then `CriticalContentValidator` blocks unvalidated edits to config/instruction/doc/rule files.
   Guard fails closed on any error.
5. Read-only run → render (`render_brief` default, `render_text` for `--details`).
6. `--fix`: loop ≤5 passes — `apply(rep)` writes `edits`/`new_files`/`chmods`/`moves` (backup
   to `~/.cache/prism-ai-lint/<stamp>/`), then re-scan. Fixes unlock further fixes; stops when nothing
   pending. `CHANGE_LOG` accumulates `(path, before, after)` for `-v`/`--diff`.
7. `-i` interactive / `--full-yes`: `TuiApp` guides judgment calls (duplicates, families,
   restructure, descriptions, model). `preview_conversion()` shows plans; `apply_conversion_interactive()`
   prompts approval before writing. `_overview()` and expanded readiness signals show project
   autonomy status (tests, CI, docs, tooling).

## The two safety mechanisms

- **Checks/fixes only tighten.** No fix adds an allow rule; a change that would loosen is
  reported, not applied. See [docs/FIXER_POLICY.md](docs/FIXER_POLICY.md).
- **Guard (`--guard`)** is a PreToolUse hook: it reads the tool call on stdin, and returns
  exit 2 + a reason to **block** any edit that would loosen config or add attribution. It
  fails closed (any internal error blocks). It recognises the tool's own actions by
  behaviour, not by name.

## Configuration surfaces

- **Policy** (`.prism-ai-lint.toml`, TOML) — thresholds, expected model/effort/scopes, generation
  switches, security scaffolding. Deep-merged over `DEFAULT_POLICY`. Legacy filenames
  `.claude-lint.toml` / `.agent-lint.toml` still accepted.
- **Catalogue** (YAML, optional) — per-code severity/enabled/action overrides and extra
  reference sets, without touching code.
- **Plugins** — a `.py` file dropping `register(api)` adds checks via `@api.check(code, scope)`.

## Extending

- **New check** → add a `check_*` (or a plugin), a `HINTS` entry, `BRIEF_FR`/`BRIEF_EN`
  entries, and a test. Emit `info` unless it is a real error/loosening.
- **New fixable** → only if the fix tightens or repairs; register via `Report.edit` /
  `gen_new_file` and mark the finding `fixable=True`.
- **New policy knob** → add to `DEFAULT_POLICY`, read it in the check, regenerate the
  example TOML.
