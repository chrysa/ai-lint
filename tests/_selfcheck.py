"""Fail only if the tool finds a real attribution/secret trace in this repo.
Advisory findings (e.g. a missing commit-msg hook) do not fail the check."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLOCKERS = {"ATTR_TRACE", "API_KEY_LEAK", "SECRET_INLINE"}

proc = subprocess.run(
    [
        sys.executable,
        str(ROOT / "ai-lint.py"),
        ".",
        "--no-cli",
        "--no-history",
        "--no-scaffold",
        "--format",
        "json",
    ],
    capture_output=True,
    text=True,
    cwd=str(ROOT),
)
data = json.loads(proc.stdout or "{}")
bad = [f for f in data.get("findings", []) if f["code"] in BLOCKERS and str(ROOT) in str(f["path"])]
print(f"traces in repo: {len(bad)}")
for f in bad:
    print(" ", f["code"], f["path"])
sys.exit(1 if bad else 0)
