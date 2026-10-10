"""procedure-to-skill never moves a managed block, another document's H1, or content git would ignore."""

from __future__ import annotations

import subprocess

STEPS = "\n".join(f"{i}. step number {i} of the procedure" for i in range(1, 20))


def _proposals(m, repo):
    pol = m.DEFAULT_POLICY
    return [p for p in m.compute_proposals([], [repo], pol) if p["kind"] == "procedure-to-skill"]


def _repo(tmp_path, claude):
    (tmp_path / "CLAUDE.md").write_text(claude, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_plain_procedure_is_proposed(linter_module, tmp_path):
    repo = _repo(tmp_path, f"# Project\n\n## Release\n\n{STEPS}\n")
    assert [p["section"] for p in _proposals(linter_module, repo)] == ["Release"]


def test_managed_block_section_is_never_moved(linter_module, tmp_path):
    body = (
        f"## Release\n\n{STEPS}\n\n<!-- team:standards:start · managed by sync.sh · DO NOT EDIT -->\n# Standards\n- a\n"
    )
    repo = _repo(tmp_path, "# Project\n\n" + body)
    assert _proposals(linter_module, repo) == []


def test_section_containing_another_h1_is_not_moved(linter_module, tmp_path):
    repo = _repo(tmp_path, f"# Project\n\n## Release\n\n{STEPS}\n\n# Another document\n")
    assert _proposals(linter_module, repo) == []


def test_ignored_skill_target_is_not_proposed(linter_module, tmp_path):
    repo = _repo(tmp_path, f"# Project\n\n## Release\n\n{STEPS}\n")
    (repo / ".gitignore").write_text("release\n", encoding="utf-8")
    assert _proposals(linter_module, repo) == []
