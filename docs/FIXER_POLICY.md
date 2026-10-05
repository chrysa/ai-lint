# Fixer & security policy

The contract every repair, generation and guard decision must honour. This is the
project's core invariant; treat it as binding, not aspirational. Architecture context:
[../ARCHITECTURE.md](../ARCHITECTURE.md).

## The invariant: only ever tighten

An automatic action may **tighten, repair, or stay neutral**. It may **never loosen**.
Concretely, no code path (`--fix`, `--generate`, `-i`, scaffolding) may:

- add or widen an `allow` permission rule, or broaden a matcher;
- remove or weaken a `deny` / `ask` rule;
- enable a control that was disabled (hooks, bypass-permissions, project MCP servers…);
- add assistant/AI attribution;
- write a secret anywhere.

If a change *could* loosen, it is **reported as a finding and left for the human** under
"not fixed" — never applied.

## What `--fix` is allowed to do

- Repair syntax: JSON comments / trailing commas / BOM, strict-JSON re-emit, `$schema`.
- Migrate deprecated keys to their current form (e.g. `includeCoAuthoredBy` → attribution off).
- Rename legacy tool names to canonical ones (`Task` → `Agent`).
- Rewrite path rules attached to tools that never consult them onto the right tool.
- Add **deny** entries required by policy (`required_deny`), and rtk twin **deny** rules.
- Convert hooks to exec form / anchor relative paths, add `type: command`.
- Add attribution-off, disable-bypass and other **tightening** defaults on scaffold.

## What `--generate` / scaffolding may create

- Baseline `settings.json` with attribution off, secrets denied, external actions on `ask`.
- Format hook, `check` / `review-changes` skills, read-only reviewer subagents.
- `.mcp.json` for detected services (never with an inline secret — env refs only).
- Security files ([../README.md](../README.md) → Generation): a portable `PreCompact`
  hook when settings reference a missing one, and a secrets `.gitignore` block. Writes are
  confined to the scanned repo or the user config dir — never an arbitrary absolute path.

Generation is proposal-only until `--fix` / `-i` applies it; existing files are never
overwritten (`gen_new_file` skips if the target exists).

## The guard (`--guard`)

A PreToolUse hook that **blocks** (exit 2 + reason) any Edit/Write/Bash that would:

- loosen settings / `.mcp.json` / plugin / marketplace / hooks / workflow files
  (`settings_violations`, `mcp_violations`, workflow risk patterns);
- add attribution;
- edit a protected path;
- turn valid strict-JSON config into something looser or invalid.

It **fails closed**: any internal error blocks by default. It recognises prism-ai-lint's own
edits by *behaviour*, not filename, so renaming the tool cannot bypass it. Running the
linter itself is allowed (it only tightens); running it with permission-adding flags
(`--session-settings`, `--policy`, `-i`, `--generate --fix`) is left to the human.

## Secret handling

`API_KEY_LEAK` reports an Anthropic key only when it looks random. It ignores obvious
placeholders (`XXXX`, sequential `ABCDEFGHIJ`/`1234567890`, `example`/`fake`/`test-key`/
`your-key`) and any line carrying a `claude-secret-ok` allow marker. A real committed key
is never auto-removed — it is reported so the human rotates it.

## Severity model

- `error` — broken or insecure config that will not work as intended.
- `warn` — works, but risky or wasteful.
- `info` — advisory (token levers, style, habits). Info is not meant to reach zero.

Severity is re-rankable per code via the catalogue, and codes can be disabled, but that
never changes the tighten-only invariant — only what is surfaced.

## When adding a fixer

1. Prove it can only tighten/repair/neutral. If not, make it report-only.
2. Confine any file write to the scanned repo or user config dir.
3. Add a test that fails if the fixer loosens or writes outside scope.
