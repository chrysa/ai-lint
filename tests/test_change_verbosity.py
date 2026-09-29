"""--fix reports what changed: a per-change summary at -v and a full unified
diff under --diff. The change log survives the re-scan a fix pass runs."""

from __future__ import annotations


def _dirty(env):
    repo = env.repos[0]
    (repo / ".claude").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "settings.json").write_text(
        '{\n "includeCoAuthoredBy": true,\n "permissions": {"allow": ["Task"]}\n}\n'
    )
    return repo


def test_verbose_lists_change_detail(env):
    repo = _dirty(env)
    out = env.run(str(repo), "--fix", "-v", "--no-cli").stdout
    assert "settings.json" in out
    assert "lines (+" in out  # the per-change summary line


def test_diff_flag_shows_unified_diff(env):
    repo = _dirty(env)
    out = env.run(str(repo), "--fix", "--diff", "--no-cli").stdout
    assert "--- a/" in out and "+++ b/" in out
    assert "$schema" in out


def test_quiet_has_no_change_detail(env):
    repo = _dirty(env)
    out = env.run(str(repo), "--fix", "-q", "--no-cli").stdout
    assert "lines (+" not in out
