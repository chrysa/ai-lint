"""PORTFOLIO_COPIED: the same agents or skills copied into many scanned projects."""

from __future__ import annotations

from prism_ai_lint.portfolio_checker import PortfolioChecker


def _agent(repo, name, body="body", desc="Does a thing for the project"):
    d = repo / ".claude" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\n{body}\n")


def _repos(tmp_path, n, names=("alpha", "beta", "gamma")):
    out = []
    for i in range(n):
        r = tmp_path / f"p{i}"
        r.mkdir()
        for name in names:
            _agent(r, name)
        out.append(r)
    return out


def test_one_pack_for_items_present_in_the_same_projects(tmp_path):
    packs = PortfolioChecker(5).packs(_repos(tmp_path, 6))
    assert len(packs) == 1
    assert len(packs[0]["projects"]) == 6
    assert packs[0]["names"] == ["agent:alpha", "agent:beta", "agent:gamma"]
    assert packs[0]["versions"] == 1
    assert packs[0]["tokens_per_project"] > 0


def test_below_the_threshold_nothing_is_reported(tmp_path):
    assert PortfolioChecker(5).packs(_repos(tmp_path, 4)) == []


def test_drift_is_counted_by_distinct_content(tmp_path):
    repos = _repos(tmp_path, 6)
    _agent(repos[0], "alpha", body="changed")
    _agent(repos[1], "alpha", body="changed again")
    assert PortfolioChecker(5).packs(repos)[0]["versions"] == 3


def test_items_present_in_different_project_sets_form_separate_packs(tmp_path):
    repos = _repos(tmp_path, 6)
    for r in repos[:5]:
        _agent(r, "extra")
    packs = PortfolioChecker(5).packs(repos)
    assert sorted(len(p["projects"]) for p in packs) == [5, 6]


def test_symlinked_items_are_ignored(tmp_path):
    repos = _repos(tmp_path, 6, names=())
    src = tmp_path / "shared.md"
    src.write_text("---\nname: linked\ndescription: x\n---\n")
    for r in repos:
        (r / ".claude" / "agents").mkdir(parents=True)
        (r / ".claude" / "agents" / "linked.md").symlink_to(src)
    assert PortfolioChecker(5).packs(repos) == []


def test_skills_are_collected_too(tmp_path):
    repos = []
    for i in range(5):
        r = tmp_path / f"s{i}"
        d = r / ".claude" / "skills" / "review"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: review\ndescription: Review the change\n---\nbody\n")
        repos.append(r)
    assert PortfolioChecker(5).packs(repos)[0]["names"] == ["skill:review"]


def test_lint_reports_one_info_finding_per_pack(linter_module, tmp_path, monkeypatch):
    m = linter_module
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    repos = _repos(tmp_path, 6)
    rep = m.Report()
    m.check_portfolio(repos, m.load_policy(None, repos), rep)
    found = [f for f in rep.findings if f.code == "PORTFOLIO_COPIED"]
    assert len(found) == 1
    assert found[0].level == "info"
    assert "6 scanned projects" in found[0].message
    assert "agent:alpha" in found[0].message


def test_a_single_project_run_reports_nothing(linter_module, tmp_path):
    m = linter_module
    repos = _repos(tmp_path, 1)
    rep = m.Report()
    m.check_portfolio(repos, m.load_policy(None, repos), rep)
    assert rep.findings == []
