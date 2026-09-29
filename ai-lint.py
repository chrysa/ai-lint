#!/usr/bin/env python3
"""CLI entry point. The implementation lives in the importable module
`ai_lint` (so tooling can type-check and measure it); this thin wrapper keeps
the `./ai-lint.py` invocation working."""

from ai_lint import main

if __name__ == "__main__":
    raise SystemExit(main())
