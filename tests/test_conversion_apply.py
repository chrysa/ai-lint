"""Applying an agent-contract conversion (#25): write the target only with
explicit human approval, back it up for undo, refuse a stale preview, and
converge (idempotent)."""

from __future__ import annotations


def _converter(linter_module):
    return linter_module.AgentConverter(redact=lambda s: s)


def test_apply_requires_approval(linter_module, tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# P\n\n- rule\n")
    conv = _converter(linter_module)
    out = conv.apply(tmp_path, "claude", "codex", approved=False, preview_existing=None)
    assert out["applied"] is False and "validation" in out["reason"].lower()
    assert not (tmp_path / "AGENTS.md").exists()


def test_apply_writes_with_approval_and_backs_up(linter_module, tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# P\n\n- rule one\n")
    conv = _converter(linter_module)
    backups: list[tuple[str, str]] = []
    out = conv.apply(
        tmp_path,
        "claude",
        "codex",
        approved=True,
        preview_existing=None,
        backup=lambda p, old: backups.append((p.name, old)),
    )
    assert out["applied"] is True and out["created"] is True
    assert (tmp_path / "AGENTS.md").read_text() == "# P\n\n- rule one\n"
    assert backups == []  # nothing to back up when the target did not exist


def test_apply_backs_up_existing_target(linter_module, tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# P\n\n- rule one\n")
    (tmp_path / "AGENTS.md").write_text("OLD\n")
    conv = _converter(linter_module)
    saved: list[tuple[str, str]] = []
    out = conv.apply(
        tmp_path,
        "claude",
        "codex",
        approved=True,
        preview_existing="OLD\n",
        backup=lambda p, old: saved.append((p.name, old)),
    )
    assert out["applied"] is True and out["created"] is False
    assert ("AGENTS.md", "OLD\n") in saved  # old content preserved for undo


def test_apply_refuses_stale_preview(linter_module, tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# P\n\n- rule one\n")
    (tmp_path / "AGENTS.md").write_text("CHANGED SINCE PREVIEW\n")
    conv = _converter(linter_module)
    # Reviewer saw an empty/older target; it changed on disk -> refuse.
    out = conv.apply(tmp_path, "claude", "codex", approved=True, preview_existing="OLD PREVIEW\n")
    assert out["applied"] is False and "stale" in out["reason"].lower()
    assert (tmp_path / "AGENTS.md").read_text() == "CHANGED SINCE PREVIEW\n"  # untouched


def test_apply_is_idempotent(linter_module, tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# P\n\n- rule one\n")
    conv = _converter(linter_module)
    conv.apply(tmp_path, "claude", "codex", approved=True, preview_existing=None)
    again = conv.apply(
        tmp_path, "claude", "codex", approved=True, preview_existing=(tmp_path / "AGENTS.md").read_text()
    )
    assert again["applied"] is False and "matches" in again["reason"].lower()
