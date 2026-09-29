"""SECURITY_GITIGNORE on an existing .gitignore must be applied by --fix
(appended, not dropped) so repeated runs converge instead of warning forever."""

from __future__ import annotations


def test_existing_gitignore_append_is_an_edit(linter_module, tmp_path):
    m = linter_module
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("node_modules/\n.env\n")
    rep = m.Report()
    m.scaffold_security(tmp_path, m.load_policy(None, [tmp_path]), rep)
    gi = tmp_path / ".gitignore"
    # Must be a registered edit (apply() writes edits; it skips new_files that exist).
    assert gi in rep.edits
    old, new = rep.edits[gi]
    assert "*.pem" in new and "node_modules/" in new  # appended, original kept
    assert new.startswith("node_modules/")


def test_fully_covered_gitignore_not_flagged(linter_module, tmp_path):
    m = linter_module
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("\n".join(m.SECRETS_GITIGNORE) + "\n")
    rep = m.Report()
    m.scaffold_security(tmp_path, m.load_policy(None, [tmp_path]), rep)
    assert (tmp_path / ".gitignore") not in rep.edits
    assert not any(f.code == "SECURITY_GITIGNORE" for f in rep.findings)


def test_fix_converges(env):
    repo = env.repos[0]
    (repo / ".gitignore").write_text("node_modules/\n")
    env.run(str(repo), "--fix", "--no-cli")
    out = env.run(str(repo), "--no-cli").stdout
    assert "SECURITY_GITIGNORE" not in out  # cleared, does not recur
