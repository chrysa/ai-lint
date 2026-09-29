"""strip_code must remove fenced code blocks even when indented (nested in a
list), so a code-example import like `from '@/services'` is not mistaken for a
CLAUDE.md @import (IMPORT_MISSING false positive)."""

from __future__ import annotations

MD = """# Guide

1. **Create the page** (`page.tsx`):
   ```typescript
   import { vehicleService } from '@/services'
   ```
2. done
"""


def test_indented_fence_is_stripped(linter_module):
    m = linter_module
    out = m.strip_code(MD)
    assert "@/services" not in out
    assert "vehicleService" not in out


def test_indented_code_import_not_flagged(linter_module, tmp_path):
    m = linter_module
    p = tmp_path / "copilot-instructions.md"
    p.write_text(MD)
    rep = m.Report()
    m.check_imports(p, MD, rep, m.load_policy(None, [tmp_path]), tmp_path)
    assert not any(f.code == "IMPORT_MISSING" for f in rep.findings)


def test_real_import_outside_fence_still_flagged(linter_module, tmp_path):
    m = linter_module
    p = tmp_path / "CLAUDE.md"
    text = "See @./missing-file.md for details.\n"
    p.write_text(text)
    rep = m.Report()
    m.check_imports(p, text, rep, m.load_policy(None, [tmp_path]), tmp_path)
    assert any(f.code == "IMPORT_MISSING" for f in rep.findings)
