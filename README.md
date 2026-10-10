# prism-ai-lint

[![Tests](https://github.com/chrysa/prism-ai-lint/actions/workflows/ci.yml/badge.svg)](https://github.com/chrysa/prism-ai-lint/actions/workflows/ci.yml) [![License](https://img.shields.io/badge/license-MIT-blue)](pyproject.toml) [![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=chrysa_agent-config-lint&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=chrysa_agent-config-lint) [![Coverage](https://sonarcloud.io/api/project_badges/measure?project=chrysa_agent-config-lint&metric=coverage)](https://sonarcloud.io/summary/new_code?id=chrysa_agent-config-lint) [![Docs](https://img.shields.io/badge/docs-user%20guide-blue)](https://chrysa.github.io/prism-ai-lint/)

**Linter, fixer and guard for AI coding-agent configuration.** Validates permissions, instructions, hooks, MCP servers, skills and subagents; flags security, token cost and correctness issues; repairs safely. Works with Claude Code, Cursor, Windsurf and others.

## 30-second pitch

Agent config drifts. prism-ai-lint catches three problems:
- **Security**: permission rules that silently allow too much, committed keys, broken hooks, missing gitignore. Only tightens, never loosens.
- **Tokens**: everything in your instructions, rules, skills and MCP is re-sent per request. prism-ai-lint estimates it, names the biggest killers, suggests concrete cuts.
- **Correctness**: deprecated keys, invalid shapes, duplicates, config in the wrong scope.

For individuals: run it to secure and cheapen your setup. For teams: share one `.prism-ai-lint.toml` policy, run `--guard` as a hook, wire into CI.

## What it covers

Settings, permissions, hooks, helpers, MCP servers, instruction files (`CLAUDE.md`, `AGENTS.md`), rules, skills, subagents, commands, output styles, plugins, keybindings, GitHub Actions workflows, misplaced files, and Anthropic API keys. Also checks `.github/copilot-instructions.md` (Copilot), `.cursorrules` (Cursor), `.windsurfrules` (Windsurf), and `GEMINI.md` (Gemini CLI).

Two layers: `prism-ai-lint.py` for deterministic checks (safe to run in CI), and an optional guarded agent session (`/config-audit`) for judgment calls.

**Pure Python, no runtime dependencies.** Python >= 3.13; PyYAML optional.

## File layout

- `prism-ai-lint.py` — CLI entry point
- `prism_ai_lint/` — engine (`_engine.py` + thematic checkers)
- `prism-ai-lint.example.toml` — default policy; copy to `.prism-ai-lint.toml` to customize
- `skills/config-audit/` — optional guarded agent workflow
- `tests/` — pytest suite (400+ tests)
- `examples/plugins/` — sample custom check

## Documentation

**User guide: <https://chrysa.github.io/prism-ai-lint/>** (install, token savings, checks, configuration, CI, guarded sessions).

For maintainers:

- [ARCHITECTURE.md](ARCHITECTURE.md) — engine map and data flow
- [CLAUDE.md](CLAUDE.md) — working contract (for Claude Code / agents)
- [docs/FIXER_POLICY.md](docs/FIXER_POLICY.md) — safety guarantees
- [DECISIONS.md](DECISIONS.md) — design choices
- [TESTING.md](TESTING.md) — test strategy

## Install

No runtime dependencies (Python >= 3.13). Install from this repository, pinned to a release tag.

> Not published on PyPI yet: install from GitHub as shown below.

### With pip (from GitHub)

```sh
pip install "git+https://github.com/chrysa/prism-ai-lint@vX.Y.Z"   # a release tag
prism-ai-lint --help
```

### From source (git clone)

Clone the repo (the CLI `prism-ai-lint.py` imports the engine from the `prism_ai_lint` package) and run it:

```sh
git clone https://github.com/chrysa/prism-ai-lint && cd prism-ai-lint
./prism-ai-lint.py --help
```

For a shorter invocation from anywhere when running from source, add an alias:

```sh
alias prism-ai-lint='python3 /path/to/prism-ai-lint/prism-ai-lint.py'
```

Running it with no arguments prints the help, including the effective defaults.
Optional companions it uses when present: the `claude` CLI and `llmtrim` (`--no-cli`
to skip both), and `rtk` (`--no-rtk` skips only RTK).

## Quick start

```sh
prism-ai-lint .                    # read-only scan
prism-ai-lint . --fix              # apply repairs (backup in ~/.cache/prism-ai-lint/)
prism-ai-lint . -i                 # interactive review: pick what to fix
prism-ai-lint . --generate         # preview generated config
prism-ai-lint . --generate --fix   # generate + lint + repair
prism-ai-lint . --user --fix       # include user scope (~/.claude)
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

**More**: `--policy FILE`, `--catalog FILE`, `--plugin-dir DIR`, `--guard`, `--dump-reference`, `--print-policy`, `--list-plugins`, `--restore [DIR]`, `--no-cli`, `--no-rtk`, `--no-scaffold`, `--no-update-check`, `--graphify`, `--rtk-report`, `--report-issue`.

`--report-issue` prints an anonymized Markdown body for the findings that have no automatic fix (paths, hosts, e-mails, URLs, names and quoted values replaced by stable tokens; secrets removed). It is a local preview: nothing is ever sent. Forbid it with `PRISM_AI_LINT_REPORTING=off` or `[reporting] mode = "off"`.

Run it on a folder of repositories to see what no single project shows: `PORTFOLIO_COPIED` reports a pack of agents or skills copied identically into many projects, with its cost per session and how far the copies have drifted.

Token-saving signals (info): `PDF_HEAVY` (a large PDF the agent can load; export it to text) and `COMPRESSION_DOUBLE` (rtk, llmtrim or a local gateway stacked on the same traffic). `INSTR_GENERATED_LOADED` (a large generated file such as an agent registry, loaded in every session).

Exit codes: `0` clean, `1` errors/warnings (`--strict`), `2` usage or guard block.

## Pre-commit hook

Add to `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/chrysa/prism-ai-lint
  rev: vX.Y.Z  # a release tag; `pre-commit autoupdate` picks the latest
  hooks:
    - id: prism-ai-lint
```

Runs only when agent config changes (`.claude/`, `CLAUDE.md`, `AGENTS.md`, `.mcp.json`, `.prism-ai-lint.toml`, workflows...). Read-only: it never runs `--fix`, never calls external CLIs, and blocks the commit on errors only, listing each with its `→ fix`. Run it on demand with `pre-commit run prism-ai-lint --hook-stage manual`.

## Features

**Detection**: stacks (Python, Node, React, Docker, Kubernetes, Terraform, etc.) and the project profile (CLI, library, app, infra, config-only...), shown in every report and used by `--generate`. `--generate` does not copy a skill or agent into a project when your user scope already has one with that name (reported as `GENERATE_SKIPPED`); set `[generate] skip_user_duplicates = false` to copy it anyway.

**Generation**: `.claude/settings.json`, hooks, skills (`/check`, `/review-changes`), subagents (`/test-runner`, `/security-auditor`), MCP servers, `.gitignore` secrets block, `CLAUDE.md` / `AGENTS.md` skeletons.

**Optimization**: duplicates, families, long descriptions, token estimate, restructuring proposals (pack → plugin, skill → plugin, procedure → skill).

**Interactive review** (`-i`): remove duplicates, park subagent packs, shorten descriptions, switch Opus → Sonnet, run MCP setup. Everything reversible with `restore.sh`.

**Guarded session**: `/config-audit` workflow for judgment calls; every edit checked with `--guard`; loosening blocked.

**CI-friendly**: JSON output, no human prompts, backups, exit codes, self-check.




## Generation

Scans stacks (Python, Node, React, Docker, Kubernetes, Terraform, GitHub, Sentry, Supabase) then generates only what's missing. Existing rules, hooks and servers left alone.

Generates: `.claude/settings.json` (with allow/ask/deny rules tuned to your stack), hooks (`format.py`), skills (`/check`, `/review-changes`), subagents (`/test-runner`, `/security-auditor`), `.mcp.json`, `.gitignore` secrets block, `CLAUDE.md` / `AGENTS.md` skeletons, `pre-compact.sh` hook.

Tune generation in `.prism-ai-lint.toml` `[generate]` section: which skills/agents/MCP, safe/gated Makefile targets, extra allow/ask/deny, rtk exclusions.

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
prism-ai-lint --session-settings /tmp/audit.json
claude --settings /tmp/audit.json  # then /config-audit
```

Every edit checked by `prism-ai-lint --guard` (PreToolUse hook); loosening blocked. Guard blocks: adding allow rules, removing deny/ask, extending tools, adding attribution, code-executing plugins, permission bypasses, edits to critical files, or edits to the linter itself (the whole `prism_ai_lint` package).

## Customization

Copy `prism-ai-lint.example.toml` to `.prism-ai-lint.toml` and keep only what you change.

**Main knobs**: `permissions.require_rtk`, `permissions.rule_style` (keep/space/colon), `skills.gate_side_effects`, `instructions.claude_md_import`, `scaffold.*`.

**CLI defaults** (`[flags]`, in `.prism-ai-lint.toml` of the current directory): `strict`, `no_cli`, `no_history`, `verbose`, `format`, `details`, `diff`, `lang`, `min_level`... Options that write or approve (`fix`, `generate`, `interactive`, `full_yes`, `user`) are refused: pass them on the command line, which always wins.

**Repository-specific rules**: `[critical] extra_files` adds files that need human validation in guarded sessions (repo-relative paths); `[profile] standards_markers` lists paths that mark a standards repository.

**Token checks** (`[tokens]`): preferred model, heavy models (flagged when default), subagent model, max effort level.

**Scopes** (`[scopes]`): where skills/agents/commands/MCP should live (project, user, local).

Print defaults: `prism-ai-lint --print-policy` or `prism-ai-lint --print-catalog`.

## Extending with a catalog

Export, edit, and feed back the reference data and check metadata:

```sh
prism-ai-lint --print-catalog > prism-ai-lint.catalog.yaml
# edit it (add new keys/events/tools, change severities, override `→ fix` actions)
prism-ai-lint . --catalog prism-ai-lint.catalog.yaml
```

Catalog needs PyYAML (`pip install 'PyYAML>=6'`); without it, `--catalog` degrades gracefully.

## Custom checks (plugins)

Add a `.py` file in `<repo>/.prism-ai-lint/plugins/` or any `--plugin-dir`:

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
make selfcheck      # run prism-ai-lint on its own repo
```

CI runs Python toolchain directly (no `make`): `ruff`, `mypy`, `pytest`, self-check.

## Limits

- Reference data is a snapshot (2026-09); unknown keys flagged as info, never errors.
- Guard's shell check is heuristic; rely on the sandbox for OS-level boundary.
- Permission rules alone are not a security boundary; the sandbox is.

## Fully automated repair

```sh
prism-ai-lint . --full-yes   # runs --fix, accepts all local interactive actions
```
