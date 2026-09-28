#!/usr/bin/env python3
"""CLI entry point. The implementation lives in the importable module
`claude_lint` (so tooling can type-check and measure it); this thin wrapper keeps
the `./claude-lint.py` invocation working."""

from claude_lint import main

if __name__ == "__main__":
    raise SystemExit(main())
