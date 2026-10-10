# Testing

How this repo is tested and what "green" means. Structure: [ARCHITECTURE.md](ARCHITECTURE.md).

## Run

- `make test` — the pytest suite (`tests/`, ~30 files).
- `make check` — lint + typecheck + test; the gate before declaring work done.
- `make cov` — tests with coverage, floor 60% (target 90%).
- `make selfcheck` — runs prism-ai-lint on its own repo (see below).
- `make docker-test` — the suite in `python:3.14-slim`, the CI entry point.

No global install: everything runs through `make`, invoking `python3 -m ruff/pytest/mypy`.

## How the tests work

- The engine is imported directly (`import prism_ai_lint`) via the `linter_module` fixture — most
  unit tests call functions (`check_*`, `scaffold_*`, `guard_check`, `load_policy`) and
  assert on the resulting `Report.findings` / `new_files` / `edits`.
- Integration tests use the `env` fixture: a miniature HOME + `a custom config dir` + sample
  repos, and `env.run(*args)` which invokes the **CLI as a subprocess** with `HOME` /
  `CLAUDE_CONFIG_DIR` overridden, so end-to-end output and exit codes are covered.
- Coverage measures the subprocess too: when `COVERAGE_RUN` is set, `env.run` launches the
  CLI through `coverage run --parallel-mode`, and `make cov` runs `coverage combine`.
- Globally-installed pytest plugins that assume a Django app are disabled in
  `addopts` (`-p no:django` etc.). Some projects need extra `-p no:<plugin>` flags.

## `make selfcheck` semantics

`tests/_selfcheck.py` runs prism-ai-lint on this repo and **fails only on a real in-repo
attribution trace or leaked secret** (`ATTR_TRACE`, `API_KEY_LEAK`, `SECRET_INLINE`).
Advisory findings (a missing hook, unscoped rules, long descriptions) do **not** fail it.
Expected terminal line: `traces in repo: 0`.

## What every change must add

- A bug fix or new check ships with a test that fails before the fix / without the check.
- A new fixer needs a test asserting it does **not** loosen config or write outside the
  scanned repo / user config dir (the invariant in [docs/FIXER_POLICY.md](docs/FIXER_POLICY.md)).
- False-positive fixes get a regression test (a case that must NOT be flagged).

## Conventions

- Tests are unannotated (mypy checks `prism_ai_lint.py` / `prism-ai-lint.py`, not `tests/`).
- Keep fixtures minimal and hermetic; never touch the developer's real `~/.claude*`.
- Do not lower the coverage floor to make a change pass.
