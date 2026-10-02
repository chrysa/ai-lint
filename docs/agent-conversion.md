# Agent contract conversion previews

Use the selected project root to preview an instruction mapping:

```sh
python3 ai-lint.py . --convert-from claude --convert-to codex --format json
python3 ai-lint.py . --convert-from codex --convert-to claude --interactive
python3 ai-lint.py . --convert-from claude --convert-to agents
```

The preview is strictly read-only. It exits before linting, scaffolding, plugins,
CLI detection, update checks and history logging. `--fix`, `--generate`, user
scope, guard and restore cannot be combined with conversion. No approval is implied
by viewing the preview.

## Applying a conversion

The target instruction file (`CLAUDE.md` / `AGENTS.md`) is **critical content**, so
writing it requires explicit human approval (see issue #16):

```sh
python3 ai-lint.py . --convert-from claude --convert-to codex \
  --apply-conversion --approve-conversion
```

- Without `--approve-conversion`, `--apply-conversion` refuses and exits non-zero.
- The previous target content is backed up under `~/.cache/ai-lint/trash/<stamp>/`
  with a `restore.sh`, so the write is undoable.
- A **stale preview** is refused: if the target changed on disk since it was read,
  nothing is written — re-run to see the new diff first.
- Application is **idempotent**: when the target already matches the conversion,
  nothing is written.
- Unresolved diagnostics (conflicts, unmapped scope) block application until resolved.

| Ecosystem | Selected root sources | Proposed target |
| --- | --- | --- |
| Claude | `CLAUDE.md`, `.claude/CLAUDE.md`, `.claude/rules/**/*.md` | `CLAUDE.md` |
| Codex | `AGENTS.override.md` when present, otherwise `AGENTS.md` | `AGENTS.md` |
| Neutral AGENTS | `AGENTS.md` | `AGENTS.md` |

Without `--convert-from`, conversion to Claude uses neutral AGENTS; conversion
to Codex/AGENTS uses Claude. Specify the source explicitly when Codex overrides
must be honored. These adapters describe a project document mapping, not a full
simulation of an agent's runtime discovery or precedence.

The neutral representation retains complete source documents and provenance.
A single document is rendered unchanged; multiple documents retain their text
with source comments. No instruction, safety rule or constraint is deduplicated
or rewritten. Exact duplicate lines across documents are reported and retained.
Existing target differences are conflicts, including harmless formatting changes;
no automatic merge attempts to resolve contradictory prose.

JSON uses `conversion_schema_version: 1` and `conversion_plans`. Each plan includes
mapping, canonical documents, diagnostics, preview content/diff, scope,
`requires_human_validation: true` and `applied: false`. Content and diffs use the
existing secret redactor. Exit 0 means no diagnosed limitations; exit 1 means
review is needed; exit 2 is usage error. Even a complete plan requires human
validation before any future write, and completeness is not a semantic proof.

Imports and frontmatter are retained but flagged for manual review. Claude
settings/permissions/hooks are reported as unmapped; their original files remain
intact. User, ancestor and nested directory contracts, local instruction files,
and runtime size limits are outside this first increment. Symlinked instruction
paths are not read. Conversion does not claim equivalent enforcement of policies.

Mapping references: [Claude memory](https://code.claude.com/docs/en/memory) and
[Codex project instructions](https://developers.openai.com/codex/guides/agents-md).
