# Guarded agent sessions

For changes the linter cannot decide alone, let an agent work under the guard:

```sh
cp -r skills/config-audit <repo>/.claude/skills/      # or ~/.claude/skills/
prism-ai-lint --session-settings /tmp/audit.json
claude --settings /tmp/audit.json                     # then run /config-audit
```

The session installs `prism-ai-lint --guard` as a `PreToolUse` hook on every edit and shell command.
The guard blocks any change that would:

- add an allow rule, remove a deny or ask rule, enable bypass modes, disable the sandbox;
- remove a hook, add MCP servers or code-executing helpers;
- extend a skill's or subagent's tools, add assistant attribution;
- edit critical files without human validation (`CLAUDE.md`, `AGENTS.md`, `README.md`, policy
  files, `.claude/rules/*.md`, and `[critical] extra_files`);
- modify the linter itself, its plugins or its policy, or run options reserved to the human
  (`--policy`, `-i`, `--full-yes`, `--plugin-dir`, `--generate --fix`).

The guard fails closed: any internal error blocks the action. It never runs code from the
repository (no plugins, no catalogue) before a tool call.

!!! note "Limits"
    The shell check is heuristic. Enable the sandbox for an OS-level boundary: permission
    rules alone are not a security boundary.
