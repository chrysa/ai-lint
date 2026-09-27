"""Guard the s/S key distinction and French pluralization."""
from __future__ import annotations

import builtins


def test_ask_preserves_case(linter_module, monkeypatch):
    m = linter_module
    for token in ("A", "S", "a", "s", "o", "q", "v2", "2,3"):
        monkeypatch.setattr(builtins, "input", lambda p="", t=token: t)
        assert m._ask("? ", "") == token


def test_ask_empty_uses_default(linter_module, monkeypatch):
    m = linter_module
    monkeypatch.setattr(builtins, "input", lambda p="": "")
    assert m._ask("? ", "yN") == "n"
    monkeypatch.setattr(builtins, "input", lambda p="": "")
    assert m._ask("? ", "") == ""


def test_ask_eof_is_quit(linter_module, monkeypatch):
    m = linter_module

    def boom(p=""):
        raise EOFError

    monkeypatch.setattr(builtins, "input", boom)
    assert m._ask("? ") == "q"


def test_fr_plural(linter_module):
    m = linter_module
    assert m._fr_plural(0, "groupe") == "0 groupe"
    assert m._fr_plural(1, "groupe") == "1 groupe"
    assert m._fr_plural(2, "groupe") == "2 groupes"
    assert m._fr_plural(1, "skill") == "1 skill"
    assert m._fr_plural(3, "skill") == "3 skills"
    assert m._fr_plural(2, "cheval", "chevaux") == "2 chevaux"
