#!/usr/bin/env python3
"""CLI entry point. The implementation lives in the `prism_ai_lint` package
(`prism_ai_lint/_engine.py`); this thin wrapper keeps the `./prism-ai-lint.py` invocation
working. The package `__init__` is intentionally empty (shared-standards)."""

import sys

from prism_ai_lint._engine import main

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nprism-ai-lint interrupted.", file=sys.stderr)
        raise SystemExit(130) from None
