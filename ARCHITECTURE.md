# Architecture

How ai-lint is built, so a change lands in the right place. User-facing behaviour lives in
[README.md](README.md); the rationale behind the choices here is in [DECISIONS.md](DECISIONS.md).

## Shape

- **`ai-lint.py`** — thin CLI wrapper: `from ai_lint import main`. Kept as a hyphenated,
  directly runnable entry point.
- **`ai_lint/_engine.py`** — legacy orchestration module: checks, repairs, generation,
  guard, catalogue, plugins and rendering. It is importable (tests, mypy and coverage
  attach to it); the hyphenated name could not be imported, hence the split.
- **`ai_lint/content_validation.py`** — object-oriented validation gate for critical
  content files in guarded sessions (`CriticalContentValidator`, `CriticalContentPolicy`).
- **`ai_lint/project_profile.py`** — object-oriented stack and project-profile detection
  (`ProjectProfiler`) used by reports, JSON and future generation branching.
- **`ai_lint/self_update.py`** — object-oriented self-update prompt (`SelfUpdater`,
  `SelfUpdateConfig`, `GitRunner`). New isolated domains should follow this pattern:
  one thematic module, empty package `__init__.py`, small objects with explicit methods.
- No runtime dependencies (standard library only). PyYAML is optional and used **only** by
  the editable catalogue (`--catalog` / `--print-catalog`); everything degrades gracefully
  without it.

## Module map

`ai_lint/_engine.py` still carries most historical behaviour. Navigate by the `# ----`
section banners:

| Region (approx.) | Contents |
|---|---|
| `# Policy` | `DEFAULT_POLICY` (nested dict), `load_policy` (TOML overlay via `deep_merge`), `to_toml`. Every knob defaults here. |
| `# Reference data (docs snapshot)` | Known settings keys, hook events, tools, skill/agent fields, dead keys. The source of truth the checks compare against; carries the doc date. |
| `# Hints and references` | `HINTS[code] = (why/how, doc_url)`; the attribution patterns and the scaffold templates (`COMMIT_MSG_HOOK`, `PRE_COMPACT_HOOK`, `SECRETS_GITIGNORE`). |
| checks | `check_*` functions (settings, permissions, hooks, MCP, skills, subagents, rules, instructions, plugins, workflows, secrets). Each appends `Finding`s to a `Report`. |
| `# Token budget` | `token_budget`, `check_token_levers`, `check_effort_levels`, `render_token_budget` — the always-loaded weight estimate and its levers. |
| `# Scaffolding` | `scaffold_project`, `scaffold_user`, `scaffold_security`, `gen_new_file` — files `--generate` proposes. |
| `# Orchestration` | `run_lint`, `lint_repo`, `lint_user`, `apply`, `main`, and the render functions. |
| `# Guard` | `guard_check`, `run_guard` — the PreToolUse hook. |
| `# Plugin system` | `CheckContext`, `PluginAPI`, `load_plugins`, `run_plugin_checks`. |
| catalogue | `catalog_data`, `dump_catalog`, `load_catalog`. |
| `ai_lint/content_validation.py` | `CriticalContentValidator.validation_reason()` blocks critical content edits until human validation. |
| `ai_lint/project_profile.py` | `ProjectProfiler.detect_stack()` and `.detect_profile()` classify the scanned repo. |
| `ai_lint/self_update.py` | `SelfUpdater.check()` handles release-branch update detection, confirmation and `git pull --ff-only`; config is in `SelfUpdateConfig`. |

## Core types

- **`Finding(level, code, path, message, fixable)`** — one result. `level` ∈
  error/warn/info; `code` is a stable slug (e.g. `HOOK_MISSING_SCRIPT`).
- **`Report`** — collects findings and pending mutations: `edits` (path → (old, new)),
  `new_files` (path → (content, mode)), `chmods`, `moves`, plus `budget`/`stats`.
  `Report.add()` honours the catalogue's `DISABLED_CODES` and `SEVERITY_OVERRIDES`.
  `Report.edit()` chains successive edits to the same file.

## Data flow

1. `main` parses args, sets globals (`VERBOSITY`, `SHOW_DIFF`, `SCAFFOLD`, `LANG`,
   `MIN_LEVEL`...), loads the policy and optional catalogue/plugins.
2. `run_lint` builds a fresh `Report`, runs `lint_user` (user scope) and `lint_repo` per
   repo. Checks only **record** findings and proposed mutations — they never write.
3. Read-only run → render (`render_brief` by default, `render_text` for `--details`).
4. `--fix`: loop up to 5 passes — `apply(rep)` writes `edits`/`new_files`/`chmods`/`moves`
   (after a timestamped backup in `~/.cache/ai-lint/`), then **re-scan** with a new
   `Report`. Fixes can unlock further fixes; the loop stops when nothing is pending.
   Because each pass re-scans, the module-level `CHANGE_LOG` accumulates
   `(path, before, after)` so `-v` / `--diff` can report what changed.
5. `-i` interactive: judgment-call proposals (duplicates, packs, long descriptions, model)
   applied one at a time, reversible via a trash dir (`--restore`).

## The two safety mechanisms

- **Checks/fixes only tighten.** No fix adds an allow rule; a change that would loosen is
  reported, not applied. See [docs/FIXER_POLICY.md](docs/FIXER_POLICY.md).
- **Guard (`--guard`)** is a PreToolUse hook: it reads the tool call on stdin, and returns
  exit 2 + a reason to **block** any edit that would loosen config or add attribution. It
  fails closed (any internal error blocks). It recognises the tool's own actions by
  behaviour, not by name.

## Configuration surfaces

- **Policy** (`.ai-lint.toml`, TOML) — thresholds, expected model/effort/scopes, generation
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
