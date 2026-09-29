# ai-lint

<!-- Neutral agent instructions. Tool-specific files (e.g. CLAUDE.md) only import this one.
     HTML comments are stripped before loading: they cost no context. -->

## Overview

ai-lint is a linter, fixer and guard for AI coding-agent configuration (Claude Code and
other tools). It validates and repairs settings, permissions, hooks, MCP, skills,
subagents, rules and instruction files; flags security, token-cost and correctness
issues; and only ever tightens config (never adds an allow rule). Engine: `ai_lint.py`;
CLI wrapper: `ai-lint.py`. Standard library only (PyYAML optional for the catalogue).

## Commands

- `make test` — pytest suite
- `make lint` — ruff check + format --check
- `make format` — ruff format
- `make typecheck` — mypy
- `make check` — lint + typecheck + test
- `make selfcheck` — run ai-lint on its own repo

## Conventions

- Everything written to disk is in English (identifiers, commits, docs).
- Configuration comes from environment variables; no committed secrets.
<!-- Only what differs from tool defaults; skip what the code already shows. -->

## Boundaries

- Ask before any action with external effects (push, release, deploy, DNS, secrets, messages).
- Never add assistant attribution to commits, PRs, files or docs.
