"""restore_trash: empty, partial, missing and normal sessions."""

from __future__ import annotations


def _trash_base(env):
    return env.home / ".cache" / "ai-lint" / "trash"


def test_missing_target_returns_1(env, linter_module, capsys):
    rc = linter_module.restore_trash(str(env.home / "nope" / "does-not-exist"))
    assert rc == 1
    assert "introuvable" in capsys.readouterr().out


def test_no_sessions_ok(env, linter_module, capsys):
    rc = linter_module.restore_trash(None)
    assert rc == 0
    assert "Aucune session" in capsys.readouterr().out


def test_empty_session_noticed(env, linter_module, capsys):
    sess = _trash_base(env) / "20260101T000000"
    sess.mkdir(parents=True)
    (sess / "restore.sh").write_text("#!/bin/sh\n")
    rc = linter_module.restore_trash(str(sess))
    assert rc == 0
    assert "vide" in capsys.readouterr().out


def test_normal_restore_moves_file_back(env, linter_module, capsys):
    # a trashed file recorded relative to '/'
    original = env.home / "restore-me.txt"
    sess = _trash_base(env) / "20260102T000000"
    stored = sess / str(original.resolve()).lstrip("/")
    stored.parent.mkdir(parents=True)
    stored.write_text("content")
    rc = linter_module.restore_trash(str(sess))
    assert rc == 0
    assert original.exists() and original.read_text() == "content"
    assert "restauré" in capsys.readouterr().out


def test_partial_restore_skips_existing(env, linter_module, capsys):
    original = env.home / "already-there.txt"
    original.write_text("live")
    sess = _trash_base(env) / "20260103T000000"
    stored = sess / str(original.resolve()).lstrip("/")
    stored.parent.mkdir(parents=True)
    stored.write_text("trashed")
    rc = linter_module.restore_trash(str(sess))
    assert rc == 0
    # existing file is untouched, trashed copy stays in the session
    assert original.read_text() == "live"
    assert stored.exists()
    assert "déjà présent" in capsys.readouterr().out
