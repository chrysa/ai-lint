---
paths: "**/*.py"
---

# shared-standards compliance for ai-lint

ai-lint validates, repairs and guards agent configurations. These rules prevent regressions:

## Never loosen

- No fix adds an `allow` rule or widens a matcher.
- No change removes a `deny` or disables a control.
- Security gates (secrets, attribution, permissions) block before repair.
- The fixer applies tightening repairs only; loosening findings are reported, not fixed.

See [docs/FIXER_POLICY.md](../../docs/FIXER_POLICY.md).

## Tests ship with behaviour changes

- Every feature, fix or refactor includes a pytest test.
- `make check` must pass (lint + typecheck + test, no skips).
- Coverage floor not lowered. New code has focused test cases.

## Docs and code stay in sync

- User-facing behaviour changes → [README.md](../../README.md)
- Rationale, decisions → [DECISIONS.md](../../DECISIONS.md)
- Architecture, data flow → [ARCHITECTURE.md](../../ARCHITECTURE.md)
- Test strategy → [TESTING.md](../../TESTING.md)
- Changes committed in the same PR/commit as code.

## Critical content requires human validation

- `CLAUDE.md`, `AGENTS.md`, `README.md`, architecture/decision/testing docs, `.claude/rules/*.md`
- Config files: `.ai-lint.toml`, `pyproject.toml`, `.mcp.json`
- Guard blocks unvalidated writes. `--approve-conversion` required for agent-config edits.

## Python packaging single-source

- `pyproject.toml` is the source of truth for:
  - Build config (`[build-system]`)
  - Project metadata (name, version, description, authors, urls)
  - Ruff, mypy, pytest, coverage config
  - Dependencies and optional groups
- No `setup.py`, `setup.cfg`, `ruff.toml`, `mypy.ini` or `pytest.ini` side config.

## CI deterministic and least-privilege

- CI runs Python tools **directly**: `ruff check`, `mypy`, `pytest`, `coverage`.
- No `make` in CI (local developer shortcut only).
- Release on main via git-cliff + Conventional Commits. One commit = one release.
- Permissions: `contents: write` (tags/releases only), no secrets in workflow unless guarded.

## No hardcoded external endpoints or secrets

- Credentials, API keys, host paths come from env vars or config files, never inline.
- Secrets scanning catches `.env`, SSH keys, tokens, PEM files.
- Generated MCP and settings use `env:VAR` refs, never literal secrets.
- Pre-commit hook strips assistant attribution.

## Refactoring targets

- Reduce `ai_lint/_engine.py` gradually; currently ~8500 lines (procedural, by design).
- One class per file when extracting thematic modules (see `content_validation.py`, `project_profile.py`).
- Always backward-compatible public API (`ai-lint.py` entry point, `main()` function).
