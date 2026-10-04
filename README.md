# ai-lint

[![Tests](https://github.com/chrysa/ai-lint/actions/workflows/ci.yml/badge.svg)](https://github.com/chrysa/ai-lint/actions/workflows/ci.yml) [![License](https://img.shields.io/badge/license-MIT-blue)](pyproject.toml)

**Linter, fixer and guard for AI coding-agent configuration.** Validates permissions, instructions, hooks, MCP servers, skills and subagents; flags security, token cost and correctness issues; repairs safely. Works with Claude Code, Cursor, Windsurf and others.

## 30-second pitch

Agent config drifts. ai-lint catches three problems:
- **Security**: permission rules that silently allow too much, committed keys, broken hooks, missing gitignore. Only tightens, never loosens.
- **Tokens**: everything in your instructions, rules, skills and MCP is re-sent per request. ai-lint estimates it, names the biggest killers, suggests concrete cuts.
- **Correctness**: deprecated keys, invalid shapes, duplicates, config in the wrong scope.

For individuals: run it to secure and cheapen your setup. For teams: share one `.ai-lint.toml` policy, run `--guard` as a hook, wire into CI.

## What it covers

Settings, permissions, hooks, helpers, MCP servers, instruction files (`CLAUDE.md`, `AGENTS.md`), rules, skills, subagents, commands, output styles, plugins, keybindings, GitHub Actions workflows, misplaced files, and Anthropic API keys. Also checks `.github/copilot-instructions.md` (Copilot), `.cursorrules` (Cursor), `.windsurfrules` (Windsurf), and `GEMINI.md` (Gemini CLI).

Two layers: `ai-lint.py` for deterministic checks (safe to run in CI), and an optional guarded agent session (`/config-audit`) for judgment calls.

**Pure Python, no runtime dependencies.** Python >= 3.13; PyYAML optional.

## File layout

- `ai-lint.py` — CLI entry point
- `ai_lint/` — engine (`_engine.py` + thematic checkers)
- `ai-lint.example.toml` — default policy; copy to `.ai-lint.toml` to customize
- `skills/config-audit/` — optional guarded agent workflow
- `tests/` — pytest suite (400+ tests)
- `examples/plugins/` — sample custom check

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — engine map and data flow
- [CLAUDE.md](CLAUDE.md) — working contract (for Claude Code / agents)
- [docs/FIXER_POLICY.md](docs/FIXER_POLICY.md) — safety guarantees
- [DECISIONS.md](DECISIONS.md) — design choices
- [TESTING.md](TESTING.md) — test strategy

## Install

No runtime dependencies (Python >= 3.13). Install from this repository, pinned to a release tag.

> The `ai-lint` name on PyPI belongs to an unrelated project. Do not `pip install ai-lint`;
> install from GitHub as shown below.

### With pip (from GitHub)

```sh
pip install "git+https://github.com/chrysa/ai-lint@vX.Y.Z"   # a release tag
ai-lint --help
```

### From source (git clone)

Clone the repo (the CLI `ai-lint.py` imports the engine from the `ai_lint` package) and run it:

```sh
git clone https://github.com/chrysa/ai-lint && cd ai-lint
./ai-lint.py --help
```

For a shorter invocation from anywhere when running from source, add an alias:

```sh
alias ai-lint='python3 /path/to/ai-lint/ai-lint.py'
```

Running it with no arguments prints the help, including the effective defaults.
Optional companions it uses when present: the `claude` CLI and `llmtrim` (`--no-cli`
to skip both), and `rtk` (`--no-rtk` skips only RTK).

## Quick start

```sh
ai-lint .                    # read-only scan
ai-lint . --fix              # apply repairs (backup in ~/.cache/ai-lint/)
ai-lint . -i                 # interactive review: pick what to fix
ai-lint . --generate         # preview generated config
ai-lint . --generate --fix   # generate + lint + repair
ai-lint . --user --fix       # include user scope (~/.claude)
```

**Output**: brief report (findings, detected stack, token estimate, next steps). Add `--details` for full per-file findings with `→ fix` actions. Add `-v` for logs, `-q` for errors only, `--format json` for machines.

## Common options

| Option | Effect |
|---|---|
| `-i` | Interactive: pick what to fix (reversible; `restore.sh` undoes) |
| `--fix` | Apply repairs and re-scan until stable |
| `--generate` | Generate missing config for the detected stack |
| `--user` | Include user scope (`~/.claude`) |
| `--details` | Full per-file report with `→ fix` actions |
| `--diff` | Show diff of changes |
| `-v` | Logs; `-vv` includes doc refs; `-vvv` is debug |
| `-q` | Errors only |
| `--strict` | Exit 1 on warnings (for CI) |
| `--format json` | Machine-readable output |

**More**: `--policy FILE`, `--catalog FILE`, `--plugin-dir DIR`, `--guard`, `--dump-reference`, `--print-policy`, `--list-plugins`, `--restore [DIR]`, `--no-cli`, `--no-rtk`, `--no-scaffold`, `--no-update-check`, `--graphify`, `--rtk-report`.

Exit codes: `0` clean, `1` errors/warnings (`--strict`), `2` usage or guard block.

## Pre-commit hook

Add to `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/chrysa/ai-lint
  rev: vX.Y.Z  # a release tag; `pre-commit autoupdate` picks the latest
  hooks:
    - id: ai-lint
```

Runs only when agent config changes (`.claude/`, `CLAUDE.md`, `AGENTS.md`, `.mcp.json`, `.ai-lint.toml`, workflows...). Read-only: it never runs `--fix`, never calls external CLIs, and blocks the commit on errors only, listing each with its `→ fix`. Run it on demand with `pre-commit run ai-lint --hook-stage manual`.

## Features

**Detection**: stacks (Python, Node, React, Docker, Kubernetes, Terraform, etc.) and the project profile (CLI, library, app, infra, config-only...), shown in every report and used by `--generate`.

**Generation**: `.claude/settings.json`, hooks, skills (`/check`, `/review-changes`), subagents (`/test-runner`, `/security-auditor`), MCP servers, `.gitignore` secrets block, `CLAUDE.md` / `AGENTS.md` skeletons.

**Optimization**: duplicates, families, long descriptions, token estimate, restructuring proposals (pack → plugin, skill → plugin, procedure → skill).

**Interactive review** (`-i`): remove duplicates, park subagent packs, shorten descriptions, switch Opus → Sonnet, run MCP setup. Everything reversible with `restore.sh`.

**Guarded session**: `/config-audit` workflow for judgment calls; every edit checked with `--guard`; loosening blocked.

**CI-friendly**: JSON output, no human prompts, backups, exit codes, self-check.




## Generation

Scans stacks (Python, Node, React, Docker, Kubernetes, Terraform, GitHub, Sentry, Supabase) then generates only what's missing. Existing rules, hooks and servers left alone.

Generates: `.claude/settings.json` (with allow/ask/deny rules tuned to your stack), hooks (`format.py`), skills (`/check`, `/review-changes`), subagents (`/test-runner`, `/security-auditor`), `.mcp.json`, `.gitignore` secrets block, `CLAUDE.md` / `AGENTS.md` skeletons, `pre-compact.sh` hook.

Tune generation in `.ai-lint.toml` `[generate]` section: which skills/agents/MCP, safe/gated Makefile targets, extra allow/ask/deny, rtk exclusions.

## What it checks

**Settings**: JSON format, `$schema`, deprecated keys migrated, secrets removed, `.local.json` gitignored.

**Permissions**: rule syntax, legacy tools, allow rules that are dead or too loose, deny rules for secrets, rtk routing, rtk/non-rtk twins.

**Hooks**: event names, handler types, missing scripts, script permissions, gating scripts (must exit 2), `mcp__server` matchers that match nothing.

**Instructions**: size (200-line target), `@imports` (missing, circular, external), `AGENTS.md` import rules, auto-memory `MEMORY.md` size.

**MCP**: shape, command/args, secrets replaced by `${VAR}`, server count.

**Skills/subagents/commands**: frontmatter, `trigger` copied to `when_to_use`, descriptions (1536-char cap when listed), 500-line body, side-effect skills without `disable-model-invocation`, duplicates, families.

**Rules**: invalid `paths` patterns, frontmatter on line 1.

**Plugins**: manifest (name, version, metadata), component paths, `enabledPlugins` and `extraKnownMarketplaces` in settings.

**Other files**: misplaced files (`.claude.md`, `mcp.json`, flat skills), GitHub Actions workflows (permissions, credentials, unrestricted Bash), Anthropic API keys anywhere, attribution (assistant signatures).

**rtk**: installation, hook present, permission routing.

**llmtrim**: route agents present and binary available.

## Guarded audit workflow

For judgment calls and doc drift, use the `/config-audit` skill:

```sh
cp -r skills/config-audit <repo>/.claude/skills/  # or ~/.claude/skills/
ai-lint --session-settings /tmp/audit.json
claude --settings /tmp/audit.json  # then /config-audit
```

Every edit checked by `ai-lint --guard` (PreToolUse hook); loosening blocked. Guard blocks: adding allow rules, removing deny/ask, extending tools, adding attribution, code-executing plugins, permission bypasses, edits to critical files, or edits to the linter itself (the whole `ai_lint` package).

## Customization

Copy `ai-lint.example.toml` to `.ai-lint.toml` and keep only what you change.

**Main knobs**: `permissions.require_rtk`, `permissions.rule_style` (keep/space/colon), `skills.gate_side_effects`, `instructions.claude_md_import`, `scaffold.*`.

**CLI defaults** (`[flags]`, in `.ai-lint.toml` of the current directory): `strict`, `no_cli`, `no_history`, `verbose`, `format`, `details`, `diff`, `lang`, `min_level`... Options that write or approve (`fix`, `generate`, `interactive`, `full_yes`, `user`) are refused: pass them on the command line, which always wins.

**Repository-specific rules**: `[critical] extra_files` adds files that need human validation in guarded sessions (repo-relative paths); `[profile] standards_markers` lists paths that mark a standards repository.

**Token checks** (`[tokens]`): preferred model, heavy models (flagged when default), subagent model, max effort level.

**Scopes** (`[scopes]`): where skills/agents/commands/MCP should live (project, user, local).

Print defaults: `ai-lint --print-policy` or `ai-lint --print-catalog`.

## Extending with a catalog

Export, edit, and feed back the reference data and check metadata:

```sh
ai-lint --print-catalog > ai-lint.catalog.yaml
# edit it (add new keys/events/tools, change severities, override `→ fix` actions)
ai-lint . --catalog ai-lint.catalog.yaml
```

Catalog needs PyYAML (`pip install 'PyYAML>=6'`); without it, `--catalog` degrades gracefully.

## Custom checks (plugins)

Add a `.py` file in `<repo>/.ai-lint/plugins/` or any `--plugin-dir`:

```python
def register(api):
    @api.check("MY_RULE", scope="project")
    def _rule(ctx):
        if ctx.path("forbidden.txt").is_file():
            ctx.add("warn", "MY_RULE", ctx.path("forbidden.txt"),
                    "forbidden.txt must not be committed",
                    action_en="delete it or add it to .gitignore")
```

`ctx` has: `root`, `path(*parts)`, `read(path)`, `glob(pattern)`, `add(level, code, path, message, action_en=…, action_fr=…)`. Findings flow into the report and obey `--catalog`. See [`examples/plugins/example_check.py`](examples/plugins/example_check.py).

## Development

```sh
make check          # lint + typecheck + test
make test
make lint
make format
make selfcheck      # run ai-lint on its own repo
```

CI runs Python toolchain directly (no `make`): `ruff`, `mypy`, `pytest`, self-check.

## Limits

- Reference data is a snapshot (2026-09); unknown keys flagged as info, never errors.
- Guard's shell check is heuristic; rely on the sandbox for OS-level boundary.
- Permission rules alone are not a security boundary; the sandbox is.

## Fully automated repair

```sh
ai-lint . --full-yes   # runs --fix, accepts all local interactive actions
```
