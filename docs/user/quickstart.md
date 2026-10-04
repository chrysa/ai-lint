# Quick start

## Install

```sh
pip install "git+https://github.com/chrysa/ai-lint@vX.Y.Z"   # pin a release tag
ai-lint --help
```

From a clone instead:

```sh
git clone https://github.com/chrysa/ai-lint && cd ai-lint
./ai-lint.py --help
```

## First run (read-only)

```sh
ai-lint .              # this repository
ai-lint . --user       # plus ~/.claude (or $CLAUDE_CONFIG_DIR)
ai-lint ~/dev          # every git repository under ~/dev (3 levels deep)
```

A run never writes unless you ask. The brief report lists, in priority order: security issues,
what is configured but broken, what weighs on every session (tokens), duplicates, then the next
steps. `--details` prints every finding with a `→ fix` line.

## Apply what is safe

```sh
ai-lint . --fix        # automatic repairs, in passes until stable; backups in ~/.cache/ai-lint/
ai-lint . -i           # interactive review: duplicates, packs, long descriptions, model...
ai-lint --restore      # undo the last interactive session
```

`--diff` shows exactly what changed.

## Generate a configuration for your stack

```sh
ai-lint . --generate          # preview
ai-lint . --generate --fix    # write it, then lint and repair the result
```

The stack is detected (Python, Node, Docker, Kubernetes, Terraform, GitHub...) and only what is
missing is created: settings with permissions for your build commands, a format hook, `check`
and `review-changes` skills, read-only reviewer subagents, MCP servers, a secrets `.gitignore`
block. Existing files are never overwritten.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | clean |
| `1` | errors (or warnings with `--strict`) |
| `2` | usage error, or a change blocked by the guard |
