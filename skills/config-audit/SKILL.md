---
name: config-audit
description: Audit and repair everything Claude-related (Claude Code settings, permissions, hooks, helpers, MCP, instructions, rules, skills, subagents, output styles, plugins, marketplaces, Desktop config, CI workflows, leaked keys) against the current official docs, inside a guarded session. Use when the user asks to audit, fix, optimize or update the Claude configuration.
disable-model-invocation: true
---

# Guarded configuration audit

The linter (`agent-config-lint.py`) does every deterministic repair. You handle what it
cannot: judgment calls, and keeping its reference data in line with the docs.

## 0. Preconditions (check first, stop if not met)

- The session must run with the guard: `claude --settings <file>` where the file was
  produced by `agent-config-lint.py --session-settings <file>`. Check that a PreToolUse
  hook calling `agent-config-lint.py --guard` is active (`/hooks`). If not, stop and tell
  the user the exact two commands to start a guarded session.
- The guard blocks any change that would loosen the configuration. A block is an answer,
  not an obstacle: never retry through another tool, another path, a script or a shell
  redirection. Record it under "Non corrigé" with the guard's reason.
- Never run `git commit`, `git push` or any command with effects outside this machine.

## 1. Deterministic pass

1. Run `agent-config-lint.py . --user -v` (read-only). Keep the whole output.
2. Show the user the SUMMARY section and ask for approval, then run it again with `--fix`.
3. Everything listed under "NOT FIXED" becomes your worklist.
4. Run `agent-config-lint.py . --user --generate` (preview only) and include in your plan
   what generation would add. Applying it (`--generate --fix`) is the user's action.

## 1b. rtk review (when rtk is used)

1. Run `agent-config-lint.py . --user --rtk-report -v` and read the rtk findings and the
   `rtk gain` / `rtk discover` output.
2. Propose, with the numbers: commands to add to `[hooks] exclude_commands` in the rtk
   `config.toml` when compressed output hid information the task needed (re-runs, raw
   reads), and frequent missed commands worth an explicit rule. Savings claims must come
   from `rtk gain`, never from assumptions.
3. Never run `rtk init`, `rtk hook` or `rtk telemetry enable` (denied in the session);
   give the user the exact command instead.

## 1c. Duplicates

List the DUP_* findings with your recommendation for each cluster (which item to keep and
why: most recent, most complete, the one referenced elsewhere). Removal is done by the
user with `agent-config-lint.py -i` (you cannot run it under the guard).

## 1d. Restructuring

Read the RESTRUCTURE plan. For each proposal, say whether you recommend it and why
(for example: a pack used in one project only belongs in a plugin installed there; a
procedure used weekly belongs in a skill). The user applies them with `-i`.

## 1e. Token budget

Read the TOKENS block. Propose, largest first: instruction content that is a procedure
(move it to a skill) or only relevant to some files (move it to `.claude/rules/` with
`paths:`), content Claude can derive from the code (drop it), long skill descriptions,
MCP servers replaced by an installed CLI, unscoped rules. Never delete the user's
instruction content without approval; moving it is also a `behaviour change`.

## 2. Adapt to the current docs

1. Run `agent-config-lint.py --dump-reference`.
2. Fetch the current pages and compare them with the reference data and with the
   linter's findings:
   https://code.claude.com/docs/en/settings-reference.md, /permissions.md, /hooks.md,
   /memory.md, /skills.md, /sub-agents.md, /tools-reference.md, /mcp.md,
   /costs.md, /output-styles.md, /statusline.md, /github-actions.md, /plugins/manifest-reference.md,
   /plugins/marketplace-reference.md, /claude-directory.md,
   and https://github.com/rtk-ai/rtk (README: hook, supported commands, config.toml),
   and the most recent entries under https://code.claude.com/docs/en/whats-new/index.md
3. New settings keys, hook events, tools, skill or subagent fields: add them to the
   `[reference]` table of `.agent-lint.toml` (the only table you may edit there), and set
   `docs_checked` to today's date. Re-run the linter to confirm the related info findings
   disappear.
4. Anything else that changed (a rule the linter now gets wrong, a renamed tool, a new
   known issue): do not work around it. List it for the user as "linter update needed",
   with the doc link.

## 3. Plan the judgment calls, then STOP

For each worklist item give: file, problem, evidence (doc or issue link), the exact edit
you propose, and a label: `safe` / `behaviour change` / `needs decision`.
Typical items: hook scripts that block with `exit 1` instead of `exit 2`, handlers with an
`if` on a non-tool event, instruction files over 200 lines (move procedures to skills,
scoped content to `.claude/rules/` with `paths:`), broken `@imports`, skill directories to
rename, overly broad `allowed-tools`, broad runner rules such as `Bash(npx *)`,
non-kebab plugin names (renaming changes install references), missing plugin paths,
CI workflows (pin the action to a SHA, add `permissions:`, filter `issue_comment` by
`author_association`), leaked API keys (the user must revoke and rotate them).
Anything that needs a wider permission is always `needs decision` and never applied by you.
Wait for the user's explicit go before editing.

## 4. Apply

- Apply only approved items, with Edit or Write, one file at a time, minimal diffs.
- Conventions: `AGENTS.md` is the neutral source and `CLAUDE.md` only imports it; if
  `doctrine/rules/` exists, instruction files are generated: report instead of editing.
  Everything written to disk is in English and never mentions an AI assistant.
- After all edits, run `agent-config-lint.py . --user` and confirm you introduced no new
  finding. If you did, revert your own change.

## 5. Final report (in French, always last, nothing after it)

**Corrigé**: one line per change: file, what, why (link).
**Non corrigé**: one line per remaining item: file, what, reason (bloqué par le garde,
décision humaine, action externe, fichier généré, mise à jour du linter nécessaire), and
the exact command or edit the user should do.
