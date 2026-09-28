"""Regressions for false positives seen on real data:
- a grouping skill dir that only holds nested skills is not "missing SKILL.md"
- a line forbidding attribution is not itself an attribution trace."""

from __future__ import annotations


def test_grouping_skill_dir_not_flagged(linter_module, tmp_path):
    m = linter_module
    group = tmp_path / "gitnexus"
    (group / "gitnexus-cli").mkdir(parents=True)
    (group / "gitnexus-cli" / "SKILL.md").write_text(
        "---\nname: gitnexus-cli\ndescription: cli\n---\n\nx\n"
    )
    rep = m.Report()
    m.check_skill(group, m.load_policy(None, [tmp_path]), rep)
    assert not any(f.code == "SKILL_MISSING" for f in rep.findings)


def test_leaf_dir_without_skill_still_flagged(linter_module, tmp_path):
    m = linter_module
    empty = tmp_path / "broken"
    empty.mkdir()
    (empty / "notes.txt").write_text("hi")
    rep = m.Report()
    m.check_skill(empty, m.load_policy(None, [tmp_path]), rep)
    assert any(f.code == "SKILL_MISSING" for f in rep.findings)


def test_attribution_negation_not_flagged(linter_module):
    m = linter_module
    assert (
        m._is_attribution("append Co-Authored" + "-By: Claude <noreply@" + "anthropic.com>") is True
    )
    assert m._is_attribution("NEVER add a Co-Authored" + "-By trailer or Claude line") is False
    assert m._is_attribution("- do not add the noreply@" + "anthropic.com trailer") is False
    assert m._is_attribution("strip any Generated with Claude Code line") is False


def test_attribution_scan_skips_anti_instruction(linter_module, tmp_path):
    m = linter_module
    repo = tmp_path / "r"
    (repo / ".claude").mkdir(parents=True)
    good = repo / ".claude" / "commit.md"
    good.write_text("## Rules\n- NEVER add a Co-Authored" + "-By: Claude trailer.\n")
    policy = m.load_policy(None, [repo])
    rep = m.Report()
    m.check_attribution(repo, policy, rep, history=False)
    assert not any(f.code == "ATTR_TRACE" for f in rep.findings)
