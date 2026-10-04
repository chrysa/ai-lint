# Token savings

Every report ends with a **TOKENS** block: an estimate (bytes / 4) of what is re-sent with every
request, split into instruction files and their imports, unscoped rules, the skill and subagent
listing, the auto-memory index and MCP servers, with the biggest contributors. Above
`tokens.max_always_loaded` (10,000 by default) it becomes a warning. In `--details`, each
finding that weighs on context shows its `~N tokens/session`, and the block ends with the
potential savings of acting on them.

## Levers

| Lever | How ai-lint applies it |
|---|---|
| Instruction files under 200 lines; HTML comments for maintainer notes (not loaded) | lint (`INSTR_*`, `TOKEN_IMPORTS`) |
| Bullet points instead of prose, no filler or hedging wording | lint (`INSTR_PROSE`, `INSTR_FILLER`, `INSTR_VAGUE`) |
| Rules scoped with `paths:` so they load only for matching files | lint (`RULE_UNSCOPED`), `-i` adds the glob |
| Short skill descriptions (listed every turn); side-effect skills get `disable-model-invocation` | lint, `--fix`, `-i` shortens |
| Subagent packs and skill families moved into on-demand plugins | `-i` restructuring |
| Long skills split into `SKILL.md` + `references/`; long `CLAUDE.md` procedures moved into skills | `-i` restructuring |
| No MCP server when the CLI is installed (`gh`, `aws`...); server count capped | lint (`MCP_PREFER_CLI`) |
| Generated and vendored directories denied to `Read` (`node_modules`, `.venv`, `dist`...) | `--generate` |
| Mechanical subagents on a light model; heavy model not the session default | lint (`TOKEN_MODEL`, `TOKEN_SUBAGENT_MODEL`) |
| Instructions duplicated between user and project scope | lint (`INSTR_DUPLICATED`) |
| Output compression with rtk (Bash) and llmtrim when the context is heavy | lint (`LLMTRIM_SUGGESTED`), rtk routing |

## Interactive restructuring (`-i`)

Every run ends with a **RESTRUCTURE** plan ranked by the tokens each change removes from every
session. With `-i`, each proposal is offered in turn and applied only if you accept:

| Proposal | What `-i` does |
|---|---|
| Subagent pack (3+ agents) → on-demand plugin | moves the agents into a local marketplace plugin; nothing loads until installed where needed |
| Skill family (3+ skills sharing a prefix) → plugin | same, under `plugins/<prefix>-skills/` |
| Skill over 500 lines → `SKILL.md` + `references/` | keeps the first sections, moves the rest into linked references |
| Command → skill | moves `commands/x.md` to `skills/x/SKILL.md` |
| Unscoped rule about one language → `paths:` | adds the matching glob |
| Procedure section in `CLAUDE.md` → skill | moves it into a skill, leaves a one-line pointer |

Every move is reversible (`restore.sh` in the trash folder, backups for edits).

## Habits the tool cannot enforce

`/clear` between tasks, `/context` and `/usage` to check, a lighter model by default and a
heavier one only when needed.
