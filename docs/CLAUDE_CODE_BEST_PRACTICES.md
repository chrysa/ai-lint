# Claude Code best practices for ai-lint

How ai-lint maps the official Claude Code best-practice guidance into checks,
scaffolding, maintenance rules and agent workflow. Source reference: official Claude Code
best practices, accessed 2026-09-30: <https://code.claude.com/docs/fr/best-practices>.

This document is intentionally not imported by `CLAUDE.md`: it is a reference to load when
changing checks, generation, guard behaviour or documentation around Claude Code usage.
Keep the always-loaded contract in `CLAUDE.md` concise.

## Principles to preserve

1. Give the agent a way to verify its work.
2. Explore first, then plan, then implement, then validate.
3. Put specific, stable project instructions in `CLAUDE.md`; move situational workflows to
   skills, hooks or docs.
4. Manage context aggressively: keep always-loaded instructions short, scoped and
   de-duplicated.
5. Prefer scoped permissions, narrow tools and deterministic checks over broad trust.
6. Use subagents for investigation and review when the main context would otherwise get
   noisy.
7. Add adversarial review for unattended or high-impact changes.
8. Treat prompts, rules and agent config as maintainable code.
9. Adapt to the scanned project instead of applying a universal preset.

## Project adaptation

ai-lint must profile the scanned project before judging or generating agent configuration.
The detected stack, repository role, maturity, runtime constraints and local policy decide
which checks are errors, warnings or advice. A Python CLI, a full-stack web app, a Unity game,
a config-only repository and a shared standards repo should not receive the same generated
skills, MCP servers, permissions, hooks or documentation scaffold.

Adaptation rules:

- Detect stack signals first: Python, Node/React, Docker/Compose, Kubernetes, Terraform,
  Unity, GitHub remote, Makefile targets, test commands and existing `.claude/` assets.
- Generate only artifacts that fit the detected project; do not add MCP, agents, hooks or
  skills just because ai-lint knows how to generate them.
- Treat missing project intent as an interactive question or an info-level hint, not an error.
- Respect repo-local policy files and documented decisions over generic defaults.
- Keep fixes conservative across every profile: adaptation may reduce scope or ask the human,
  but it may never loosen config automatically.

## Feedback quality

ai-lint reports should be decision-ready, not just diagnostic. A useful report tells the
operator what ai-lint inferred, what it changed or refused to change, and what to do next.

Report requirements:

- Show the detected project profile and the main signals behind it.
- Separate errors, warnings, info and restructure proposals.
- For each high-impact finding, include evidence, risk, recommended action and whether it is
  auto-fixable, interactive-only or manual-only.
- Explain skipped or not-applicable standards so the user can tell adaptation from omission.
- Surface uncertainty explicitly and ask a focused question when the next action depends on
  project intent.
- End with a short next-step block: commands to run, files to review, and decisions needed.
- Keep machine-readable JSON stable for CI while keeping human output brief and prioritized.
- In JSON, enrich each finding with `status`, `category`, `fix_mode`, `evidence`,
  `manual_reason` and `next_action` so another agent or dashboard can continue from the
  report without re-parsing prose.

## What ai-lint should check or encourage

| Best practice | ai-lint surface | Expected behaviour |
|---|---|---|
| Verification exists | Generated `check` skill, CI examples, docs | Prefer commands with success/failure signals: tests, lint, typecheck, selfcheck. |
| `CLAUDE.md` stays concise | `INSTR_*`, token checks, restructuring | Flag oversized/prose-heavy instruction files; suggest moving procedures to skills. |
| Stable rules in `CLAUDE.md`, situational workflows in skills | Generation and restructure proposals | Scaffold a short repo contract; move long procedure sections to skills when safe. |
| Permissions are scoped | permission checks, generation | Keep read/build/test rules narrow; external actions go to `ask`; never add broad allows. |
| Hooks are deterministic gates | hook checks, guard | Hooks should have clear exit semantics and should not reprint instruction files. |
| MCP is useful but bounded | MCP checks, generation | Prefer installed CLIs when they cover the workflow; cap servers and avoid inline secrets. |
| Skills are on-demand context | skill checks | Keep descriptions short; avoid loading long bodies unless invoked. |
| Subagents handle noisy work | subagent checks, generated agents | Mechanical agents use lighter models; investigation/review agents are scoped and read-only. |
| Context is managed intentionally | token block, compaction guidance | Encourage `/clear`, compaction instructions and duplicate removal; estimate always-loaded cost. |
| Reviewer is independent | `review-changes` skill, generated reviewer | Review diffs against explicit requirements and report correctness gaps, not taste. |

## Generation guidance

When `--generate` creates or completes Claude Code configuration, generated artifacts should
follow these defaults unless policy overrides them:

- `CLAUDE.md`: import `AGENTS.md`, include only repo-specific non-obvious commands,
  workflow rules, sensitive zones and compact instructions.
- Skills: create `check` and `review-changes` as on-demand workflows instead of bloating
  always-loaded instructions.
- Hooks: format hooks may be non-blocking; guard/security hooks fail closed and document
  their exit codes.
- Permissions: allow only project-local read/build/test operations; put release, deploy,
  network write, messaging, secrets and repository writes behind `ask` or leave them to
  the human.
- MCP: generate only detected, useful servers; prefer environment variable references for
  credentials; prefer local CLIs when they cover the same operation.
- Subagents: generate reviewer/security/test agents only when they map to a real workflow;
  use read-only tools unless the agent's role requires writes.

## Maintenance guidance

When changing ai-lint's Claude Code support:

1. Start from the documented best-practice intent, not only from the current syntax.
2. Add or update a deterministic check where the practice can be detected reliably.
3. Keep advisory guidance at `info` severity when there is no correctness or security risk.
4. Avoid false certainty: if a practice depends on project intent, report a hint or ask the
   user in interactive mode.
5. Add tests for each new rule and for at least one non-violation case.
6. Update `README.md` for user-facing behaviour, `DECISIONS.md` for lasting rationale and
   `CLAUDE.md` only for rules that agents must always remember.

## Anti-patterns to catch early

- `CLAUDE.md` becomes a long tutorial, API reference or file-by-file map.
- A command, hook or MCP server exists only because it is possible, not because the project
  needs it.
- A generated permission allows a family of commands when the project needs one command.
- A hook blocks without a clear fix path or with a generic exit code.
- A subagent loads heavyweight context for mechanical work.
- A review step checks style preferences instead of stated requirements and edge cases.

## Non-goals

- Do not copy the official documentation into this repository.
- Do not make every best practice an error; most workflow guidance is advisory.
- Do not add runtime dependencies to inspect best practices.
- Do not weaken the core invariant in [FIXER_POLICY.md](FIXER_POLICY.md): automatic actions
  only tighten, repair or stay neutral.
