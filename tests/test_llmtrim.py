"""llmtrim companion CLI: propose install when its route subagents exist but the
binary is missing; skip silently when installed or when --no-cli."""

from __future__ import annotations


def _reset(m):
    m.LLMTRIM.update({"path": None, "version": None, "checked_cli": False})


def test_missing_llmtrim_is_proposed(linter_module, env, monkeypatch):
    m = linter_module
    _reset(m)
    monkeypatch.setattr(m.shutil, "which", lambda x: None)  # llmtrim absent
    m.detect_llmtrim(use_cli=True)
    rep = m.Report()
    m.check_llmtrim(rep, [], user_scope=True)
    codes = [f.code for f in rep.findings]
    assert "LLMTRIM_MISSING" in codes
    msg = next(f.message for f in rep.findings if f.code == "LLMTRIM_MISSING")
    assert "3" in msg  # three route agents in the fixture


def test_installed_llmtrim_is_skipped(linter_module, env, monkeypatch):
    m = linter_module
    _reset(m)
    monkeypatch.setattr(m.shutil, "which", lambda x: "/usr/bin/llmtrim")
    monkeypatch.setattr(
        m,
        "_run",
        lambda *a, **k: type("R", (), {"stdout": "llmtrim 1.0.0", "stderr": "", "returncode": 0})(),
    )
    m.detect_llmtrim(use_cli=True)
    rep = m.Report()
    m.check_llmtrim(rep, [], user_scope=True)
    assert not any(f.code == "LLMTRIM_MISSING" for f in rep.findings)


def test_no_cli_skips_llmtrim(linter_module, env):
    m = linter_module
    _reset(m)
    m.detect_llmtrim(use_cli=False)
    rep = m.Report()
    m.check_llmtrim(rep, [], user_scope=True)
    assert not any(f.code == "LLMTRIM_MISSING" for f in rep.findings)


def test_no_route_agents_no_finding(linter_module, tmp_path, monkeypatch):
    m = linter_module
    _reset(m)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty"))
    (tmp_path / "empty").mkdir()
    monkeypatch.setattr(m.shutil, "which", lambda x: None)
    m.detect_llmtrim(use_cli=True)
    rep = m.Report()
    m.check_llmtrim(rep, [], user_scope=True)
    assert not any(f.code == "LLMTRIM_MISSING" for f in rep.findings)
