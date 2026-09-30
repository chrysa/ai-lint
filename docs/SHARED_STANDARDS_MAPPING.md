# Shared standards mapping for ai-lint

ai-lint must respect the standards maintained in [chrysa/shared-standards](https://github.com/chrysa/shared-standards). This file records how those standards apply to this repository without copying the full standards corpus into always-loaded agent context.

Canonical source: `shared-standards/standards/STANDARDS.chrysa.md` and the generated agent views in `shared-standards/standards/rules/*.md`.

## Profile-aware adaptation

shared-standards is normative, but ai-lint applies it through the profile of the scanned
project. The scanner must infer whether a repository is a CLI, library, full-stack app,
frontend, infrastructure repo, standards repo, game/tooling repo or config-only repo, then
adapt the generated Claude rules, hooks, skills, MCP and findings accordingly. A standard that
does not fit the detected profile is documented as not applicable or surfaced as an optional
recommendation, never forced blindly.

## Application model

| Source standard | ai-lint adaptation | Claude rule / enforcement |
|---|---|---|
| Agent-legible repository | Keep `CLAUDE.md`, `AGENTS.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `TESTING.md` current. | `.claude/rules/shared-standards.md` and `CLAUDE.md` point to this mapping. |
| Python packaging | `pyproject.toml` is the single source for Ruff, mypy, pytest and coverage. No `setup.py` / Python `setup.cfg`. | Review any tooling change against `pyproject.toml`; do not add side config files. |
| Project architecture | ai-lint is a repo-local CLI with a root `ai_lint/` package for now. | D-011 is the local exception to the distributed-library `src/` rule. |
| Tests | Python tests use pytest. `unittest.TestCase` and `unittest.mock` imports are not introduced. | Every behaviour change ships with a pytest test. |
| Code quality | Prefer small, named, testable units; no broad duplication; typed errors where practical. | Refactors should reduce `ai_lint/_engine.py` gradually without changing public CLI behaviour. |
| No hardcoded external endpoints | External services, credentials and host-specific paths come from env/config, never literals. | Generated MCP and settings use env refs, not inline secrets or machine paths. |
| Container/runtime policy | ai-lint has no runtime container requirement; it must run with bare Python >= 3.9. | Do not add runtime dependencies or container-only assumptions for the CLI. |
| CI/CD and pre-commit | CI and hooks should be deterministic, least-privilege and conventional. | `make check`, `make selfcheck`, pre-commit config and Conventional Commits are the gate. |
| Docs and project state | Behaviour changes update docs in the same change. | User-facing behaviour -> README; rationale -> DECISIONS; architecture -> ARCHITECTURE. |
| Security gates | Secret scanning, PII awareness and permission hardening are gates, not afterthoughts. | The fixer policy remains stricter than the generic standard: automatic actions never loosen. |

## Local exceptions

- `src/` layout is deferred because ai-lint is currently a clone-and-run CLI, not a distributed public library. See D-011.
- Object-oriented one-class-per-file is a target for future decomposition, not a requirement to rewrite the dense engine in this documentation-only change.
- Container-first application runtime does not apply to the ai-lint CLI itself; its portability requirement is stronger: standard library runtime, no install step.
- Notion synchronization is not automated by this repo today. Keep repository docs truthful; log project-state changes externally when that workflow is available.

## When to translate a shared standard into a Claude rule

Translate a standard into `.claude/rules/` when it is:

1. stable across sessions;
2. actionable during editing;
3. narrow enough to avoid drowning task-specific context;
4. not already enforced deterministically by Ruff, mypy, pytest, pre-commit or ai-lint itself.

Keep long explanations in docs, not in Claude rules. Rules should tell an agent what to do while editing; docs should explain why.
