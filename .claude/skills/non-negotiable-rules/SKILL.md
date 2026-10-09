---
name: non-negotiable-rules
description: "Procedure: Non-negotiable rules. Use when this procedure is needed."
---

- **Never loosen.** No code path may add an `allow` rule, widen a matcher, remove a
  `deny`, or enable a disabled control. `--fix` only tightens, repairs syntax, or scaffolds
  guard files. See [docs/FIXER_POLICY.md](docs/FIXER_POLICY.md).
- **Fail closed.** The guard (`--guard`) blocks on any error or ambiguity. New guard logic
  defaults to blocking, not allowing.
- **No secrets, ever** — not in code, tests, fixtures, logs or commits. `API_KEY_LEAK`
  must keep ignoring obvious placeholders and `claude-secret-ok` lines only.
- **No assistant/AI attribution** in commits, PRs, files or docs.
- **English on disk.** French only in user-facing strings via the `_loc(fr, en)` table.
- **Conventional Commits.** Ask before any external action (push, release, repo rename).
- **Respect shared-standards.** Apply [docs/SHARED_STANDARDS_MAPPING.md](docs/SHARED_STANDARDS_MAPPING.md)
  and `.claude/rules/shared-standards.md` where they fit this repo.
- **Project adaptation.** Detect the scanned project's profile before generating or judging
  config; adapt rules to the stack, maturity, runtime, repo role and local policy.
- **Feedback quality.** Reports must explain the detected profile, why each important
  finding applies, what can be fixed automatically, what needs human approval, and the next
  command or decision.
