# Decisions

Why the project is the way it is — the rationale an agent would otherwise re-derive (or
undo) each session. History of *what* changed is in [CHANGELOG.md](CHANGELOG.md); this file
records *why*. Newest first. Each entry: decision, why, and what would reverse it.

## D-027 · SonarCloud analysis from CI, with coverage
SonarCloud project `chrysa_agent-config-lint` (organisation `chrysa`). `sonar-project.properties`
configures a CI analysis that also imports `.reports/coverage.xml`; the CI step runs only when
the `SONAR_TOKEN` secret exists, on the Python 3.13 job. Third-party actions are pinned to a
commit SHA. **Why:** automatic analysis cannot import coverage, so the quality gate had no
coverage signal. **How to apply:** turn off automatic analysis in SonarCloud, then add the
`SONAR_TOKEN` secret; until then the step is skipped and automatic analysis keeps running.
`pythonsecurity:S6549` on the guard's path handling stays open pending an explicit decision.
**Reverse:** only if SonarCloud is dropped.

## D-026 · No project-specific names in the core defaults
The core ships generic defaults only. Repository-specific critical documents go in
`[critical] extra_files` of that repository's `.ai-lint.toml`; standards-repository markers go in
`[profile] standards_markers`. This repository lists its own `docs/FIXER_POLICY.md`,
`docs/SHARED_STANDARDS_MAPPING.md` and `docs/CLAUDE_CODE_BEST_PRACTICES.md`, so its guard
protection is unchanged (a test runs the guard against it). **Why:** ai-lint is a standalone,
public tool; hard-coding one ecosystem's file names in every scan was wrong for other users.
**How to apply:** `extra_files` only adds protection; a guarded agent cannot remove entries
(only `[reference]` of `.ai-lint.toml` is editable). Absolute or `..` paths are ignored with a
warning. **Reverse:** never put project names back into the defaults.

## D-025 · [flags] only sets options that never write; two unreliable checkers removed
The `[flags]` table of `.ai-lint.toml` can set reporting and probing options only (`strict`,
`no_cli`, `verbose`, `format`, `details`...). `fix`, `generate`, `interactive`, `full_yes`,
`user`, `approve_conversion`, `plugin_dir` and `policy` are rejected with a warning.
**Why:** that file lives in the scanned repository; honouring `fix = true` or
`approve_conversion = true` would let a repository turn a read-only run into one that writes
files or approves critical content. `account_capabilities` (looked for a model name in
`claude --version`, which prints none; invented token limits) and `project_adaptation`
(project kinds unknown to `ProjectProfiler`, recommended skills that exist nowhere) were
removed instead of wired: they could only produce wrong findings, and `--generate` already
adapts configuration to the detected stack. **Reverse:** reintroduce either only on a
reliable data source, with tests against real output.

## D-024 · The guard must survive how Claude Code launches it
The session hook runs `python …/ai_lint/_engine.py --guard` from the agent's working
directory. The engine puts its package root on `sys.path` when run as a script, and in guard
mode `main()` loads the policy inside a fail-closed `try` and dispatches before any catalogue
or plugin loading. **Why:** a script run could not import `ai_lint` (exit 1, which Claude Code
treats as non-blocking, so every edit went through), a malformed legacy policy file had the
same effect, and loading `.ai-lint/plugins/*.py` there ran repository code before each tool
call. **How to apply:** keep guard mode free of repository-provided code; any new early
failure must return 2. A test launches the guard as the hook does. **Reverse:** never.

## D-023 · The guard protects the whole linter package
`GuardChecker.protected_path` treats every file under the `ai_lint/` package, plus the
`ai-lint.py` wrapper next to it, as "the linter itself". **Why:** it used to protect only
`_engine.py` and `guard_checker.py`, so a guarded agent could edit `content_validation.py`
(disabling human validation), the wrapper, or `_reference.py` (attribution and secret
patterns, known tools). Every extraction out of the engine widened that gap. **How to
apply:** new modules are covered automatically; do not add per-file exceptions. **Reverse:**
never loosen this; if a file must become agent-editable, move it out of the package.

## D-022 · Run state lives in one object, not module globals
Options set by `main()` (verbosity, language, debug log, scaffold, min level...) live in
`ai_lint._runtime.state` (`RunState`), next to the base helpers `log`, `read_text`,
`_loc` and `dedupe`. **Why:** `main()` used to rebind `_engine` module globals, so any
function moved out of `_engine.py` would read stale values; the only way out was
duplicating code, which splits security checks into two diverging copies. One shared
state object lets checks move into thematic modules with a plain import and no cycle.
**How to apply:** read and set options through `state.<name>`; tests patch
`monkeypatch.setattr(m.state, "<name>", value)`. Extracted modules import from
`ai_lint._runtime`, never from `ai_lint._engine`. **Reverse:** only if the engine becomes a
single object that carries its own options.

## D-021 · Configuration files are critical content
Project configuration files (`.ai-lint.toml`, `pyproject.toml`, `.mcp.json`) are
critical content like instruction files and docs. Guarded sessions block unvalidated
edits. **Why:** configuration defines how the project runs; a change without human
review could silently introduce errors (malformed TOML), security gaps (exposed
MCP credentials), or inconsistency. Critical validation gates prevent unattended
rewrites. **How to apply:** `CriticalContentValidator` treats config files the same
as `CLAUDE.md`, `AGENTS.md`, and `.claude/rules/*.md`; guard blocks writes and
prompts for approval. **Reverse:** only if configuration becomes auto-generated
from a trusted schema with validation, making human review redundant.

## D-020 · PyPI publication for wider adoption
ai-lint is published to PyPI (`pip install ai-lint`) alongside git-clone installs.
The wheel includes the full engine package and CLI entry point, built from
`pyproject.toml` as the single source of truth. **Why:** clone-and-run works for
development, but users want package-manager install for CI/CD, reproducible
environments and version pinning. PyPI publication removes friction for adoption.
**How to apply:** `pyproject.toml` declares project metadata, setuptools config and
the console script entry point; CI release workflow builds and publishes the wheel
(requires `PYPI_API_TOKEN` secret). **Reverse:** only if distribution constraints
or licensing change; until then, both install paths (git clone and pip) coexist.

## D-019 · Critical content changes require human validation
Guarded sessions block edits to critical content files: repo contracts (`CLAUDE.md`,
`AGENTS.md`), public/project docs (`README.md`, `ARCHITECTURE.md`, `DECISIONS.md`,
`TESTING.md`), policy/config files and `.claude/rules/*.md`, plus the repository-specific
files listed in `[critical] extra_files` (D-026).
**Why:** these files change project meaning, operating rules or standards; an agent may draft
the change, but a human must validate the content before it lands. **How to apply:** the
`--guard` PreToolUse check returns a block reason for changed critical content. Config
hardening checks still run separately. **Reverse:** only if a future approval channel can pass
an explicit validated decision into the guard.

## D-018 · New domains move into object-oriented modules
ai-lint is being decomposed gradually: new isolated domains should live outside
`ai_lint/_engine.py` as thematic modules with small objects and explicit methods. Package
`__init__.py` files stay empty. Current extracted domains are `ai_lint/self_update.py`,
`ai_lint/project_profile.py` and `ai_lint/content_validation.py`. **Why:** a full one-shot
rewrite of the dense engine would be high-risk, but adding new behaviour to the monolith keeps
increasing coupling. Object modules let tests target one domain without importing unrelated
engine state. **How to apply:** extract one domain at a time, keep public CLI behaviour
stable, and update tests/docs in the same change. **Reverse:** only if packaging constraints
force a single-file distribution again.

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
in `pyproject.toml` `[tool.*]`, Conventional Commits, invariant local `make` shortcuts,
CI wired directly to the tools, Ruff line-length 120, caches git-ignored.

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
**Why:** the tool must run anywhere with a bare Python ≥ 3.13 (never lower), including CI, with no install
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
