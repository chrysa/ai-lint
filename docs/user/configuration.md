# Configuration

prism-ai-lint reads `.prism-ai-lint.toml` at the root of each scanned repository. Start from the defaults
and keep only what you change:

```sh
prism-ai-lint --print-policy > .prism-ai-lint.toml
```

## Main tables

| Table | What it controls |
|---|---|
| `[tokens]` | always-loaded budget, preferred / heavy / subagent models, maximum effort level |
| `[instructions]` | size targets, style checks, filler phrases, `vague_wording_min` |
| `[permissions]` | rtk routing, rule style, external-action prefixes (always `ask`), required deny rules |
| `[skills]` | portability, gating of side-effect skills |
| `[scopes]` | where skills, agents, commands, MCP servers and secrets may live |
| `[generate]` | what `--generate` creates: skills, agents, MCP servers, extra allow/ask/deny |
| `[critical]` | `extra_files`: repository files that need human validation in guarded sessions |
| `[profile]` | `standards_markers`: paths that mark a standards repository |

## CLI defaults: `[flags]`

`[flags]` in the `.prism-ai-lint.toml` of the current directory sets command-line defaults. Only
options that never write are accepted:

```toml
[flags]
strict = true
no_cli = true
details = true
format = "json"
```

Accepted: `strict`, `no_history`, `no_cli`, `no_rtk`, `no_update_check`, `no_scaffold`,
`details`, `all`, `diff`, `quiet`, `verbose`, `format`, `lang`, `min_level`. Options that write
or approve (`fix`, `generate`, `interactive`, `full_yes`, `user`, `approve_conversion`,
`plugin_dir`, `policy`) are refused with a warning: pass them on the command line. The command
line always wins.

## Editable catalogue

```sh
prism-ai-lint --print-catalog > prism-ai-lint.catalog.yaml   # needs PyYAML
prism-ai-lint . --catalog prism-ai-lint.catalog.yaml
```

The catalogue extends the reference sets (new settings keys, hook events, tools, fields) and
overrides any check's severity (`error` / `warn` / `info` / `off`) or `→ fix` text.
