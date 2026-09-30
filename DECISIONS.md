# Decisions

Why the project is the way it is — the rationale an agent would otherwise re-derive (or
undo) each session. History of *what* changed is in [CHANGELOG.md](CHANGELOG.md); this file
records *why*. Newest first. Each entry: decision, why, and what would reverse it.

## D-017 · Clone installs get an interactive release-branch update prompt
ai-lint checks for a newer fast-forward commit on the release branch (`origin/main` by
default) during interactive text runs from a clean clone, then asks before running
`git pull --ff-only`. The check is cached daily and is silent in CI, JSON output, quiet
mode, pipes and non-interactive sessions. **Why:** ai-lint is often used as a clone-and-run
tool; users should learn that a released update exists without the tool mutating itself or
breaking offline use. **How to apply:** keep update checks best-effort and opt-out
(`--no-update-check`, `AI_LINT_UPDATE_CHECK=0`); never pull without confirmation; only use
fast-forward pulls from the release branch. **Reverse:** if ai-lint becomes package-manager
first, replace the git prompt with package-manager upgrade instructions.

## D-016 · Reports explain adaptation and next actions
ai-lint's human feedback must show not only findings, but the reasoning needed to act on them:
the detected project profile, evidence, why a rule applies, whether it is auto-fixable,
interactive-only or manual-only, and the next command or decision. Standards that are skipped
or downgraded because of the scanned project's profile are reported as such. **Why:** profile
adaptation without explanation looks like inconsistency; a report that only lists problems keeps
the human in the verification loop. Clear feedback lets ai-lint be trusted in CI, interactive
review and unattended guard workflows. **Reverse:** none foreseen; output may become more compact,
but it must keep the profile/evidence/action split.

## D-015 · Scanned-project profile drives generated config
ai-lint adapts to the project it scans before generating or judging Claude configuration.
The project profile — CLI, library, full-stack app, frontend, infrastructure, standards repo,
game/tooling repo, config-only repo; plus detected stack, runtime, maturity and local policy —
decides which checks are errors, warnings or hints and which artifacts are generated. **Why:**
the same Claude Code best practice or shared-standard rule can be correct for one repository
and noise for another. Blindly applying every known rule would create false positives, bloated
context and unsafe generation. **How to apply:** detect first, generate second; prefer no-op or
info-level guidance when intent is unclear; ask interactively when the choice changes behaviour;
never use adaptation to loosen config automatically.

## D-014 · shared-standards is the normative base, mapped locally
[chrysa/shared-standards](https://github.com/chrysa/shared-standards) is the external
normative source for repo quality, Python tooling, CI/CD, documentation, security and agent
legibility. ai-lint records the local adaptation in
[docs/SHARED_STANDARDS_MAPPING.md](docs/SHARED_STANDARDS_MAPPING.md) and translates the
actionable subset into [.claude/rules/shared-standards.md](.claude/rules/shared-standards.md).
**Why:** copying the whole standards corpus would bloat context and drift from the canon; a
short mapping keeps the source of truth external while making the local exceptions explicit.
The local exceptions are deliberate: root `ai_lint/` package while ai-lint is repo-local
(D-011), zero runtime dependencies over container-first runtime, and gradual engine
decomposition rather than a documentation-only rewrite. **Reverse:** only if ai-lint becomes
fully scaffolded by project-init with generated standards views; then replace the hand-written
mapping with generated views from shared-standards.

## D-013 · Claude Code best practices are mapped, not copied
The official Claude Code best-practice guidance is captured as a compact ai-lint mapping in
[docs/CLAUDE_CODE_BEST_PRACTICES.md](docs/CLAUDE_CODE_BEST_PRACTICES.md), while
[CLAUDE.md](CLAUDE.md) keeps only the always-needed operational rules. **Why:** the source
document is a workflow guide, not a repo-local instruction file; copying it into
always-loaded context would fight ai-lint's own token-cost goals. The project should
translate those practices into checks, generation defaults, restructuring suggestions and
maintenance rules: executable verification, concise `CLAUDE.md`, scoped permissions,
bounded MCP, on-demand skills, focused subagents, aggressive context management and
independent review. **Reverse:** only if the official guidance becomes directly consumable
as a short machine-readable policy; until then, keep the mapping curated and dated.

## D-012 · Computed version + release-on-main (git-cliff)
The version is **computed, never typed** (shared-standards CI-045): `VERSION` is
derived at runtime from package metadata, else `git describe`, else a dev
placeholder. A push to `main` runs the Release workflow: git-cliff computes the
next semver from the Conventional Commits since the last tag (`--bumped-version`),
builds the notes, and the commit is tagged `vX.Y.Z` with a matching GitHub release
(one commit on main = one release, CI-048). It no-ops when nothing new landed.
**Why:** hand-typed version strings drift and conflict on merge; the commit graph
is the single source of truth. git-cliff alone (no GitVersion/.NET) keeps the
release job simple and works from zero tags. **How to apply:** never edit a
version by hand; land Conventional Commits and let main cut the release.
`cliff.toml` is copied from shared-standards.

## D-011 · Engine as a package with an empty `__init__` (not `src/`)
The engine is a package `ai_lint/` (`_engine.py` for now), with an **empty
`__init__.py`**; callers import `ai_lint._engine`. **Why:** the package layout
satisfies "code split into modules" and lets `_engine` be broken into finer
modules later (issue #3) without changing the import surface. `src/` layout is a
shared-standards rule for **distributed libraries** with a public API; ai-lint is
a repo-local CLI (D-003) run from a clone, so a **root package** keeps
`import ai_lint._engine` working with no install and no `sys.path` hacks. The
empty `__init__` follows the request/standard to keep package inits free of
logic. **Reverse:** if published as an installable library, move to `src/` and add
a public API in `__init__`. Other shared-standards points are met: all tool config
in `pyproject.toml` `[tool.*]`, Conventional Commits, invariant `make` targets,
Ruff line-length 120, caches git-ignored.

## D-010 · Renamed `claude-lint` → `ai-lint`
The tool checks configs for several agent tools, not just Claude Code. **Why:** the name
implied Claude-only and misled. **Reverse:** would only make sense if multi-tool support
were dropped. Legacy policy filenames (`.claude-lint.toml`) stay accepted for back-compat.

## D-009 · Multi-tool, not Claude-only
Recognise `.github/copilot-instructions.md`, `.cursorrules`, `.windsurfrules`, `GEMINI.md`
as always-loaded instruction files; Codex/ChatGPT read `AGENTS.md` directly. **Why:** the
same token/attribution/size problems apply to every agent's instruction file. Claude Code
remains the deepest-supported target (settings, hooks, MCP, skills…).

## D-008 · Security files are scaffolded, secrets/hooks are not auto-fixed
`--generate`/`-i` can create a missing `PreCompact` hook and a secrets `.gitignore` block.
But a committed API key is never auto-removed and a project-specific missing hook is not
invented. **Why:** offering a safe, generic file helps; editing secrets or guessing
project logic is unsafe. Writes stay inside the scanned repo or the user config dir.

## D-007 · Model / effort / scopes are policy-configurable
`TOKEN_MODEL`/`TOKEN_SUBAGENT_MODEL`/`TOKEN_EFFORT` read `[tokens]` (preferred_model,
heavy_models, subagent_model, max_effort) instead of hard-coding names; `[scopes]` sets the
expected scope per item type. **Why:** teams differ; hard-coded "Opus is heavy" ages badly.

## D-006 · Verbose change reporting via a module-level `CHANGE_LOG`
`-v` summarises each changed file; `--diff` prints the unified diff. **Why:** "fixed 6
items" hides what actually changed. A `--fix` pass re-scans with a fresh `Report`, so the
change record must outlive the report — hence a module-level accumulator, reset per run.

## D-005 · `--fix` runs re-scan passes (max 5), only tightening
Apply → re-scan → repeat until stable. **Why:** one fix can unlock another (e.g. moving
`mcpServers` out of settings). Bounded at 5 to avoid loops. The invariant holds every pass:
see [docs/FIXER_POLICY.md](docs/FIXER_POLICY.md).

## D-004 · Engine + CLI split (`ai_lint.py` + `ai-lint.py`)
The logic lives in an importable module; the hyphenated CLI is a thin wrapper. **Why:** a
hyphenated filename is not importable, so mypy/coverage/tests could not attach to it.
**Reverse:** none foreseen; the split is invisible to users.

## D-003 · Standard library only; PyYAML optional
No runtime dependency. PyYAML gates only the editable catalogue and degrades gracefully.
**Why:** the tool must run anywhere with a bare Python ≥ 3.9, including CI, with no install
step. A new dependency needs a strong, documented justification.

## D-002 · Faithful to a dated docs snapshot; unknown ≠ error
Reference data (keys, events, tools, fields) mirrors the official docs at a noted date;
unknown keys are reported as info, never errors, and the catalogue can extend the sets.
**Why:** the docs move; the tool must not hard-fail on config newer than its snapshot.

## D-001 · Never loosen; guard fails closed
The founding invariant: automatic actions only tighten/repair; the guard blocks on any
loosening or ambiguity. **Why:** a config linter that can widen permissions is a liability.
This is non-negotiable — see [docs/FIXER_POLICY.md](docs/FIXER_POLICY.md) and
[CLAUDE.md](CLAUDE.md).

## Open questions
- Publication (PyPI package / GitHub Action / Docker image) vs repo-local: currently
  repo-local (clone + run; `make docker-test` only for CI). Revisit if external adoption grows.
- Cursor `.cursor/rules/*.mdc` directory form (only the legacy `.cursorrules` file is
  checked today).
