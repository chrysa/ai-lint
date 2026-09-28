"""Example claude-lint plugin.

Copy this file into a plugin directory to add a check:
  - <config dir>/plugins/        (user scope, e.g. ~/.claude/plugins/)
  - <repo>/.claude-lint/plugins/ (per project)
  - any dir passed with --plugin-dir

A plugin defines register(api) and registers one or more checks. Each check is a
function fn(ctx); it inspects the tree via ctx and reports with ctx.add(...).
Findings flow into the normal report and obey the catalog (severity / enable /
the "-> fix" action). Errors in a plugin are isolated: they never crash a run.
"""


def register(api):
    # scope="project" runs once per repository; scope="user" runs once for the
    # user configuration (with --user).
    @api.check("EXAMPLE_TODO_AT_ROOT", scope="project")
    def _no_todo_at_root(ctx):
        todo = ctx.path("TODO.md")
        if todo.is_file():
            ctx.add(
                "info",
                "EXAMPLE_TODO_AT_ROOT",
                todo,
                "a stray TODO.md sits at the repository root",
                action_fr="le convertir en tickets suivis",
                action_en="fold it into your issue tracker",
            )

    @api.check("EXAMPLE_USER_TOO_MANY_AGENTS", scope="user")
    def _too_many_agents(ctx):
        agents = ctx.glob("agents/**/*.md")
        if len(agents) > 200:
            ctx.add(
                "info",
                "EXAMPLE_USER_TOO_MANY_AGENTS",
                ctx.path("agents"),
                f"{len(agents)} user subagents — consider on-demand plugins",
                action_en="move rarely-used agents into per-project plugins",
            )
