"""Verbose repository discovery: a readable summary of what was searched and
found, quiet for a single plain repo, and a labelled rtk report."""

from __future__ import annotations


def _tree(tmp_path):
    for rel in ("a/.git", "b/.git", "sub/c/.git", "node_modules/x"):
        (tmp_path / rel).mkdir(parents=True)
    return tmp_path


def test_discover_repos_records_and_prunes(linter_module, tmp_path):
    m = linter_module
    _tree(tmp_path)
    m.DISCOVERY.clear()
    repos = m.discover_repos(tmp_path)
    assert len(repos) == 3  # a, b, sub/c ; node_modules pruned
    rec = m.DISCOVERY[-1]
    assert rec["kind"] == "tree" and rec["pruned"] >= 1


def test_single_git_repo_is_quiet(linter_module, tmp_path):
    m = linter_module
    (tmp_path / ".git").mkdir()
    m.DISCOVERY.clear()
    m.discover_repos(tmp_path)
    m.state.verbosity = 0
    assert m.render_discovery(color=False) == ""  # nothing to say for one repo


def test_multi_repo_discovery_rendered(linter_module, tmp_path):
    m = linter_module
    _tree(tmp_path)
    m.DISCOVERY.clear()
    m.discover_repos(tmp_path)
    out = m.render_discovery(color=False)
    assert "Discovered 3 repository(ies)" in out
    assert "pruned" in out


def test_no_git_dir_scanned_as_is(linter_module, tmp_path):
    m = linter_module
    (tmp_path / "plain").mkdir()
    m.DISCOVERY.clear()
    repos = m.discover_repos(tmp_path / "plain")
    assert repos == [tmp_path / "plain"]
    assert m.DISCOVERY[-1]["kind"] == "no-git"
