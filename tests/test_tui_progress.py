"""The -i review shows section progress ([k/total] on each section header) and a
'N section(s) reviewed' line in the summary, so the reviewer knows how far along
the session is."""

from __future__ import annotations


def _run(mod, answers, repos, monkeypatch):
    queue = list(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": queue.pop(0) if queue else "q")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: None)
    rep = mod.Report()
    mod.interactive(rep, repos, mod.load_policy(None, repos), user_scope=True)


def test_section_progress_and_summary(linter_module, env, monkeypatch, capsys):
    m = linter_module
    # Answer "" (review every section), then skip through with keep/skip/quit.
    _run(m, ["", "g", "S", "s", "s", "s", "q"], env.repos, monkeypatch)
    out = capsys.readouterr().out
    # Section headers are numbered [k/total] and the summary counts them.
    assert "[1/" in out
    assert "section(s) revue(s)" in out
