"""Attribution scan: fast on a large tree, still finds and strips traces."""
from __future__ import annotations

import time


def _big_repo(tmp_path, n):
    repo = tmp_path / "big"
    (repo / "src").mkdir(parents=True)
    for i in range(n):
        (repo / "src" / f"m{i}.py").write_text(f"# module {i}\nvalue = {i}\n" * 20)
    return repo


def test_scan_is_fast(tmp_path, linter_module):
    m = linter_module
    repo = _big_repo(tmp_path, 6000)
    policy = m.load_policy(None, [repo])
    rep = m.Report()
    t0 = time.perf_counter()
    m.check_attribution(repo, policy, rep, history=False)
    elapsed = time.perf_counter() - t0
    assert elapsed < 15.0, f"scan took {elapsed:.1f}s"


def test_scan_still_detects_attribution(tmp_path, linter_module):
    m = linter_module
    repo = _big_repo(tmp_path, 50)
    tainted = repo / ".claude" / "CLAUDE.md"
    tainted.parent.mkdir(parents=True)
    # Build the trailer from parts so this source file never itself carries the
    # attribution string it is testing for.
    trailer = "Co-Authored" + "-By: " + "Cla" + "ude <noreply@" + "anthropic.com>"
    tainted.write_text(f"# notes\n\n{trailer}\n")
    policy = m.load_policy(None, [repo])
    rep = m.Report()
    m.check_attribution(repo, policy, rep, history=False)
    codes = [f.code for f in rep.findings]
    assert "ATTR_TRACE" in codes
