"""Style levers for always-loaded instructions: flag prose blocks that should be
bullets and polite/filler wording, both info-level and toggleable via policy."""

from __future__ import annotations

from ai_lint.instruction_checker import InstructionChecker

PROSE = (
    "# Rules\n\n"
    "The service reads its configuration from environment variables at startup time here.\n"
    "Every file that gets written to disk must use English identifiers and short names.\n"
    "Secrets must never be committed to the repository, not even inside test fixtures ever.\n"
    "External actions such as pushing or deploying always require explicit human approval.\n"
)


def _check(m, repo, text):
    (repo / "CLAUDE.md").write_text(text)
    rep = m.Report()
    InstructionChecker().check_instruction_file(repo / "CLAUDE.md", "project", m.load_policy(None, [repo]), rep, repo)
    return {f.code for f in rep.findings}


def test_prose_block_flagged(linter_module, tmp_path):
    m = linter_module
    codes = _check(m, tmp_path, PROSE)
    assert "INSTR_PROSE" in codes


def test_bullets_not_flagged(linter_module, tmp_path):
    m = linter_module
    bullets = "# Rules\n\n" + "\n".join(f"- rule number {i} stated concisely as an imperative here" for i in range(8))
    assert "INSTR_PROSE" not in _check(m, tmp_path, bullets)


def test_filler_flagged(linter_module, tmp_path):
    m = linter_module
    codes = _check(m, tmp_path, "# R\n\n- Please make sure to run the tests.\n- Note that lint must pass.\n")
    assert "INSTR_FILLER" in codes


def test_prose_in_code_fence_ignored(linter_module, tmp_path):
    m = linter_module
    fenced = "# R\n\n```\n" + PROSE + "\n```\n"
    assert "INSTR_PROSE" not in _check(m, tmp_path, fenced)


def test_style_checks_disabled_by_policy(linter_module, tmp_path):
    m = linter_module
    (tmp_path / "CLAUDE.md").write_text(PROSE)
    pol = m.load_policy(None, [tmp_path])
    pol["instructions"]["style_checks"] = False
    rep = m.Report()
    InstructionChecker().check_instruction_file(tmp_path / "CLAUDE.md", "project", pol, rep, tmp_path)
    assert not any(f.code in ("INSTR_PROSE", "INSTR_FILLER") for f in rep.findings)


def test_vague_wording_flagged_once_above_threshold(linter_module, tmp_path):
    m = linter_module
    text = "# Rules\n- Maybe run tests.\n- You could lint, etc.\n- Try to format.\n"
    (tmp_path / "CLAUDE.md").write_text(text)
    pol = m.load_policy(None, [tmp_path])
    rep = m.Report()
    InstructionChecker().check_instruction_file(tmp_path / "CLAUDE.md", "project", pol, rep, tmp_path)
    vague = [f for f in rep.findings if f.code == "INSTR_VAGUE"]
    assert len(vague) == 1 and vague[0].level == "info"


def test_vague_wording_below_threshold_is_silent(linter_module, tmp_path):
    m = linter_module
    (tmp_path / "CLAUDE.md").write_text("# Rules\n- A change could loosen config: report it.\n")
    pol = m.load_policy(None, [tmp_path])
    rep = m.Report()
    InstructionChecker().check_instruction_file(tmp_path / "CLAUDE.md", "project", pol, rep, tmp_path)
    assert not [f for f in rep.findings if f.code == "INSTR_VAGUE"]
