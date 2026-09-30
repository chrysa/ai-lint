# Terminal review

Run `python3 ai-lint.py . --interactive` (or `-i`) directly in a terminal. The
structured review shows the scanned project profiles, confidence and evidence,
filesystem readiness signals, and findings grouped by severity, category and
fix mode. Readiness signals indicate detected files or directories; they do not
claim that a project's tests or CI have passed.

| Mode | Use it for | Changes |
| --- | --- | --- |
| Default scan | Inspect findings and proposed changes | Read-only |
| `--fix` | Apply the supported safe automatic fixes | Critical content remains blocked |
| `--interactive` | Inspect and choose individual review actions | Explicit choices; critical proposals also require diff approval |
| `--format json` | Integrations, scripts and CI | Existing JSON contract; no terminal prompts |

The section selector accepts comma-separated numbers. Enter selects every
available section, `f` shows the findings board, `?` shows help and `q` exits.
Invalid selections are rejected instead of applying a default choice. Headers
show `[current/total]` across the selected sections.

The review actions cover duplicate cleanup, generated families, restructuring,
long skill descriptions, model selection and proposed MCP setup. Lowercase and
uppercase keys remain distinct: for example, `s` skips an item while `S` skips
all proposals of its kind. Inspect a duplicate's content with `v1`, `v2`, etc.

For restructuring rules or extracting procedures from instruction files, the
review shows the complete proposed diff before writing. Type exactly `approve`
to authorize that proposal. Enter, `o`, `y`, `A`, `q` and other answers at the
approval prompt refuse it. Bulk action choices never replace per-proposal
critical approval. A file changed since the approved preview is not overwritten;
review its new diff in another session. An existing destination skill is also
left for manual review.

The final receipt lists performed actions, skips, refusals, failures and findings
that still need manual work. Changes trigger the existing CLI rescan. If a
session is interrupted, the receipt still reports completed actions. A pipe or
non-TTY input receives guidance to rerun in a terminal and cannot apply review
actions.

Removed files remain in the session trash. Text edits keep backup snapshots.
The displayed `restore.sh` script contains undo commands for edits and moves;
run that script to undo both. The existing `--restore` command restores moved
files from the session trash. MCP additions still use the existing explicit
command confirmation and are not undone by the local restore script.

Conversion previews are available through the dedicated `--convert-to` /
`--convert-from` route, including `--interactive`; they do not start a writable
review session. See [agent conversion](agent-conversion.md). Normal review also
shows [desktop OS observations](desktop-compatibility.md) when a supported desktop
shape is detected, with runtime compatibility explicitly unverified.

Issue #7 remains open for a fuller conversion/application wizard, project setup
proposals and expanded readiness. Existing action prompts mix French with the
English overview and structured feedback.
