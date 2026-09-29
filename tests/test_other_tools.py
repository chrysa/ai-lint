"""Instruction files for other agent tools (Cursor, Windsurf, Gemini) are linted
as always-loaded instructions, like copilot-instructions.md. Codex/ChatGPT read
AGENTS.md directly, so no separate file is expected for them."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize("fname", [".cursorrules", ".windsurfrules", "GEMINI.md"])
def test_other_tool_instruction_file_is_linted(linter_module, tmp_path, fname):
    m = linter_module
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    policy = m.load_policy(None, [repo])
    assert fname in policy["instructions"]["rendered_files"]
    # An oversized file must trigger INSTR_LONG, proving it flows through the check.
    long = "\n".join(f"line {i} with enough words to matter here" for i in range(400))
    (repo / fname).write_text(long)
    rep = m.Report()
    m.lint_repo(repo, policy, rep, history=False, user_text=None)
    assert any(f.code in ("INSTR_LONG", "INSTR_TOO_LARGE") and str(f.path).endswith(fname) for f in rep.findings)


def test_rendered_files_leading_pair_unchanged(linter_module):
    m = linter_module
    rf = m.DEFAULT_POLICY["instructions"]["rendered_files"]
    assert rf[0] == "CLAUDE.md" and rf[1] == "AGENTS.md"  # scaffold slicing relies on this
