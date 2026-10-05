"""Shared run state and base helpers (prism_ai_lint._runtime)."""

from __future__ import annotations

import io

from prism_ai_lint import _runtime
from prism_ai_lint._runtime import _loc, dedupe, log, read_text, state


def test_engine_shares_the_runtime_state(linter_module):
    assert linter_module.state is state
    assert linter_module.log is log


def test_loc_follows_state_lang(monkeypatch):
    monkeypatch.setattr(state, "lang", "en")
    assert _loc("bonjour", "hello") == "hello"
    monkeypatch.setattr(state, "lang", "fr")
    assert _loc("bonjour", "hello") == "bonjour"


def test_log_honours_verbosity_and_debug_log(monkeypatch, capsys):
    sink = io.StringIO()
    monkeypatch.setattr(state, "debug_log_fh", sink)
    monkeypatch.setattr(state, "verbosity", 0)
    log(1, "quiet")
    assert capsys.readouterr().err == ""
    assert "[1] quiet" in sink.getvalue()
    monkeypatch.setattr(state, "verbosity", 1)
    log(1, "shown")
    assert "shown" in capsys.readouterr().err


def test_read_text_cache_misses_after_a_write(tmp_path, monkeypatch):
    monkeypatch.setattr(_runtime, "_READ_CACHE", {})
    p = tmp_path / "f.txt"
    p.write_text("one", encoding="utf-8")
    assert read_text(p) == "one"
    p.write_text("two, longer", encoding="utf-8")
    assert read_text(p) == "two, longer"
    assert read_text(tmp_path / "missing") is None


def test_dedupe_keeps_first_occurrence_order():
    assert dedupe(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]
