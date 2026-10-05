# What it checks

**Settings** (`.claude/settings*.json`, user settings): strict JSON (comments, trailing commas
and BOM repaired), `$schema`, deprecated keys migrated, attribution disabled, keys a repository
cannot set, inline secrets removed, `settings.local.json` git-ignored.

**Permissions**: rule syntax and tool-name case, legacy tools, path rules on tools that never
consult them, unanchored or unrestricted allow rules, environment runners (`npx *`,
`uv run *`), external actions moved from `allow` to `ask`, allow rules dead under a deny,
shadowed and duplicate rules, required deny rules for secrets, rtk routing.

**Hooks**: event names, legacy formats, handler types and required fields, matchers that match
nothing, missing or non-executable scripts, gating scripts that exit 1 instead of 2, async
gating hooks, HTTP header variables missing from `allowedEnvVars`.

**MCP** (`.mcp.json`, read-only `~/.claude.json`): shape, `type` for URL servers, command/args
split, deprecated SSE, inline secrets replaced by `${VAR}`, server count.

**Instructions**: size (200-line target), `@imports` (missing, too deep, external), `AGENTS.md`
loading rules, lines duplicated from user scope, auto-memory `MEMORY.md` size, wording (prose,
filler, vague instructions). Other tools' instruction files are checked the same way.

**Rules** (`.claude/rules`): `paths` only, invalid patterns, frontmatter position.

**Skills, subagents, commands**: frontmatter position and typos, custom fields moved under
`metadata:`, triggers copied into `when_to_use`, description length, 500-line body,
`disable-model-invocation` on side-effect skills, broad `allowed-tools`, duplicates and
families.

**Plugins and marketplaces**: manifest, component paths, `enabledPlugins` and
`extraKnownMarketplaces`.

**Other**: misplaced or misnamed files (`claude.md`, `mcp.json`, flat skills), GitHub Actions
running the Claude action (moving refs, literal credentials, permission bypass), Anthropic API
keys in any file, assistant attribution in files and commits.

**rtk and llmtrim** (when present): installation, hook, permission routing, dead route agents.

Run `prism-ai-lint --dump-reference` to see the documentation snapshot the checks compare against.
Unknown keys are reported as info, never as errors.
