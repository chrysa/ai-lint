"""A commit-msg hook that strips attribution must be recognised as the guard,
whatever tool wrote it (regression: the rename broke name-based recognition and
flooded ATTR_HOOK_CONFLICT across every repo)."""

from __future__ import annotations

import subprocess


def _repo(tmp_path, hook_body):
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(repo), "init", "-q"],
        check=True,
    )
    hook = repo / ".git" / "hooks" / "commit-msg"
    hook.write_text(hook_body)
    return repo


def test_attribution_stripping_hook_not_flagged(linter_module, tmp_path):
    m = linter_module
    body = "#!/bin/sh\n# strip trailers\nsed -i '/Co-Authored" + '-By/d\' "$1"\n'
    rep = m.Report()
    m.check_attribution(_repo(tmp_path, body), m.load_policy(None, [tmp_path]), rep, history=False)
    assert not any(f.code == "ATTR_HOOK_CONFLICT" for f in rep.findings)


def test_unrelated_hook_still_flagged(linter_module, tmp_path):
    m = linter_module
    body = "#!/bin/sh\n# lint the message\ngrep -q '^JIRA-' \"$1\" || exit 1\n"
    rep = m.Report()
    m.check_attribution(_repo(tmp_path, body), m.load_policy(None, [tmp_path]), rep, history=False)
    assert any(f.code == "ATTR_HOOK_CONFLICT" for f in rep.findings)
