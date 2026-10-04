# Custom checks

Add a `.py` file to `<repo>/.ai-lint/plugins/`, `<config dir>/plugins/` or any `--plugin-dir`:

```python
def register(api):
    @api.check("MY_RULE", scope="project")   # or scope="user"
    def _rule(ctx):
        p = ctx.path("forbidden.txt")
        if p.is_file():
            ctx.add("warn", "MY_RULE", p, "forbidden.txt must not be committed",
                    action_en="delete it or add it to .gitignore")
```

`ctx` provides `root`, `path(*parts)`, `read(path)`, `glob(pattern)` and
`add(level, code, path, message, action_fr=..., action_en=..., fixable=...)`. Plugin findings
appear in the normal report and obey the catalogue. A plugin that raises is reported and
skipped; it never crashes a run. `ai-lint --list-plugins` shows what loaded.

Plugins are code: only load plugins you trust. They never run in guard mode.
