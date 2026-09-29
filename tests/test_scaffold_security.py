"""scaffold_security proposes the missing PreCompact hook and a secrets
.gitignore block, and honours the [security] policy toggles."""

from __future__ import annotations

import json


def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".claude").mkdir(parents=True)
    return repo


def test_missing_precompact_hook_proposed(linter_module, tmp_path):
    m = linter_module
    repo = _git_repo(tmp_path)
    (repo / ".claude" / "settings.json").write_text(
        json.dumps(
            {"hooks": {"PreCompact": [{"hooks": [{"type": "command", "command": ".claude/hooks/pre-compact.sh"}]}]}}
        )
    )
    rep = m.Report()
    m.scaffold_security(repo, m.load_policy(None, [repo]), rep)
    target = repo / ".claude" / "hooks" / "pre-compact.sh"
    assert target in rep.new_files
    content, mode = rep.new_files[target]
    assert "PreCompact" in content and mode == 0o755


def test_non_compact_missing_hook_not_scaffolded(linter_module, tmp_path):
    m = linter_module
    repo = _git_repo(tmp_path)
    (repo / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": ".claude/hooks/custom.sh"}]}]}})
    )
    rep = m.Report()
    m.scaffold_security(repo, m.load_policy(None, [repo]), rep)
    # project-specific script: reported elsewhere, not auto-written here
    assert not any(p.name == "custom.sh" for p in rep.new_files)


def test_gitignore_block_proposed_when_absent(linter_module, tmp_path):
    m = linter_module
    repo = _git_repo(tmp_path)
    rep = m.Report()
    m.scaffold_security(repo, m.load_policy(None, [repo]), rep)
    gi = repo / ".gitignore"
    assert gi in rep.new_files
    assert ".env" in rep.new_files[gi][0]


def test_gitignore_untouched_when_covered(linter_module, tmp_path):
    m = linter_module
    repo = _git_repo(tmp_path)
    (repo / ".gitignore").write_text("\n".join(m.SECRETS_GITIGNORE) + "\n")
    rep = m.Report()
    m.scaffold_security(repo, m.load_policy(None, [repo]), rep)
    assert (repo / ".gitignore") not in rep.new_files


def test_security_scaffold_disabled_by_policy(linter_module, tmp_path):
    m = linter_module
    repo = _git_repo(tmp_path)
    pol = m.load_policy(None, [repo])
    pol["security"] = {"scaffold_missing_hooks": False, "scaffold_gitignore": False}
    rep = m.Report()
    m.scaffold_security(repo, pol, rep)
    assert not rep.new_files
