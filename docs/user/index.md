# ai-lint

**Cut the tokens your AI coding agents burn on every request, without weakening their safety.**

Everything in your instruction files, rules, skill and subagent listings and MCP servers is
re-sent to the model on **every** request. ai-lint measures that always-loaded weight, names the
biggest contributors, and removes or restructures what does not earn its place. It also repairs
broken configuration and refuses any change that would loosen permissions.

It reads the configuration of Claude Code and of other agent tools: `CLAUDE.md`, `AGENTS.md`,
`.github/copilot-instructions.md` (Copilot), `.cursorrules` (Cursor), `.windsurfrules`
(Windsurf) and `GEMINI.md` (Gemini CLI).

## What you get

- **Token savings**: an estimate of what each session reloads, the top contributors, and
  concrete cuts: scoped rules, shorter skill descriptions, subagent packs moved into on-demand
  plugins, lighter default model, fewer MCP servers. See [Token savings](tokens.md).
- **Safe repairs**: `--fix` only tightens or repairs; it never adds an allow rule or removes a
  deny rule. Every write is backed up, every interactive change can be undone.
- **Correctness**: deprecated keys, invalid hook or rule shapes, duplicates, files in the wrong
  place, leaked API keys.

## Start here

```sh
pip install "git+https://github.com/chrysa/ai-lint@vX.Y.Z"   # a release tag
ai-lint .            # read-only report for the current repository
ai-lint . --user     # include your user configuration (~/.claude)
```

Then follow [Quick start](quickstart.md).

!!! warning "Not the PyPI package"
    The `ai-lint` name on PyPI belongs to an unrelated project. Install from GitHub as shown.

## Requirements

Python 3.13 or newer. No runtime dependency. PyYAML is optional (editable catalogue only).
`rtk` and `llmtrim` are used when present, never required.
