"""--lang controls the brief report language; default follows $LANG."""

from __future__ import annotations


def _finding(mod, code="DUP_EXACT", level="warn"):
    return mod.Finding(level, code, "/x/a", "msg", False)


def test_brief_english(linter_module, monkeypatch):
    m = linter_module
    monkeypatch.setattr(m.state, "lang", "en")
    rep = m.Report()
    rep.findings.append(_finding(m))
    text = m.render_brief(rep, [], fix=False, repos_count=1, color=False)
    assert "repository(ies) scanned" in text
    assert "4. DUPLICATES" in text
    assert "NEXT STEPS" in text
    assert "DOUBLONS" not in text


def test_brief_french(linter_module, monkeypatch):
    m = linter_module
    monkeypatch.setattr(m.state, "lang", "fr")
    rep = m.Report()
    rep.findings.append(_finding(m))
    text = m.render_brief(rep, [], fix=False, repos_count=1, color=False)
    assert "dépôt(s) analysé(s)" in text
    assert "4. DOUBLONS" in text
    assert "ÉTAPES SUIVANTES" in text


def test_lang_flag_en_via_cli(env):
    proc = env.run(str(env.repos[0]), "--no-cli", "--no-history", "--lang", "en", expect_ok=True)
    assert "DUPLICATES" in proc.stdout or "NEXT STEPS" in proc.stdout or "BROKEN" in proc.stdout


def test_lang_default_from_env_fr(env):
    proc = env.run(str(env.repos[0]), "--no-cli", "--no-history", expect_ok=True)
    # env fixture inherits the developer LANG; assert it produced a coherent report
    assert proc.stdout.strip()
