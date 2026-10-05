# Pre-commit and CI

## Pre-commit hook

```yaml
# .pre-commit-config.yaml
- repo: https://github.com/chrysa/prism-ai-lint
  rev: vX.Y.Z   # a release tag; `pre-commit autoupdate` picks the latest
  hooks:
    - id: prism-ai-lint
```

It runs only when agent configuration changes (`.claude/`, `CLAUDE.md`, `AGENTS.md`,
`.mcp.json`, `.prism-ai-lint.toml`, workflows...). It is read-only: no `--fix`, no external CLI, and it
blocks the commit on errors only, each listed with its `→ fix`. Run it on demand:

```sh
pre-commit run prism-ai-lint --hook-stage manual
```

## CI

```sh
prism-ai-lint . --strict --format json --no-cli --no-scaffold
```

`--strict` fails on warnings too. `--format json` returns `findings`, `fixed`, `not_fixed`,
`would_fix` and `project_profiles`; every finding carries `fix_mode` (`auto`, `interactive` or
`manual`), `evidence` and `next_action`.

## Run log

Every run appends one JSON line to `~/.cache/prism-ai-lint/logs/<date>.log`: counts and codes only,
never file contents or secrets.
