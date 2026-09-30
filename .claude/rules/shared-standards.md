---
paths:
  - "**/*.py"
  - "pyproject.toml"
  - "Makefile"
  - ".pre-commit-config.yaml"
  - ".github/workflows/**"
  - "CLAUDE.md"
  - "AGENTS.md"
  - "README.md"
  - "ARCHITECTURE.md"
  - "DECISIONS.md"
  - "TESTING.md"
  - "docs/**"
  - ".claude/**"
---

# Shared standards for ai-lint

Apply [chrysa/shared-standards](https://github.com/chrysa/shared-standards) where it fits this repo. The local mapping is in [docs/SHARED_STANDARDS_MAPPING.md](../../docs/SHARED_STANDARDS_MAPPING.md).

- Keep `pyproject.toml` as the single source for Python tooling; do not add `setup.py`, Python `setup.cfg`, `ruff.toml`, `mypy.ini` or `pytest.ini`.
- Use pytest tests only; do not add `unittest.TestCase` or `unittest.mock` imports.
- Keep runtime dependencies at zero unless a decision documents why the standard-library contract changed.
- Keep generated, external-service and secret values out of code. Use env references and documented config examples.
- Preserve the local architecture decision: root `ai_lint/` package is acceptable while this is a repo-local CLI; revisit `src/` only if it becomes a distributed library.
- Behaviour changes update docs in the same change: README for users, DECISIONS for rationale, ARCHITECTURE for structure, TESTING for gates.
- CI runs Ruff, mypy, pytest, self-check and coverage directly from `pyproject.toml` tooling; local maintainer shortcuts may keep `make check` / `make selfcheck`.
- Release work follows Conventional Commits, least-privilege workflow permissions and no plaintext secrets.
- Do not copy the full shared standards corpus into this repo; link to the canonical source and keep only actionable local rules here.