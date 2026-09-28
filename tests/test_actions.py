"""Every finding proposes a solution: --details prints a '→ fix/solution' line,
and _action_for resolves an action for headline and long-tail codes."""

from __future__ import annotations


def test_action_for_headline_and_tail(linter_module, monkeypatch):
    m = linter_module
    monkeypatch.setattr(m, "LANG", "en")
    # headline code from the brief table
    assert m._action_for("SKILL_NAME")
    assert "rename" in m._action_for("SKILL_NAME").lower()
    # long-tail code falls back to the HINTS why/how sentence
    assert m._action_for("PERM_RTK")
    # unknown code -> empty, no crash
    assert m._action_for("NOPE_NOT_A_CODE") == ""


def test_every_emitted_code_has_an_action(linter_module):
    import re

    src = open(m_path(linter_module)).read()
    emitted = set(re.findall(r'rep\.add\(\s*"[a-z]+",\s*"([A-Z_]+)"', src))
    missing = sorted(c for c in emitted if not linter_module._action_for(c))
    assert not missing, f"codes without a proposed action: {missing}"


def m_path(mod):
    import inspect

    return inspect.getsourcefile(mod)


def test_details_shows_solution_line(env):
    proc = env.run("--user-only", "--no-cli", "--details", "--lang", "en", expect_ok=True)
    assert "→ fix" in proc.stdout
