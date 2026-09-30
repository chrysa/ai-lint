"""Fuzz the interactive (-i) review over the fixture environment with every
answer combination, asserting it never raises. This guards the crashes that hit
real data twice."""

from __future__ import annotations

import itertools
import subprocess

import pytest


def _run_interactive(mod, answers, repos, monkeypatch):
    """Drive interactive() with a scripted answer queue. isatty is forced True;
    input pops the queue and returns 'q' when exhausted so the run terminates."""
    queue = list(answers)

    def fake_input(prompt=""):
        return queue.pop(0) if queue else "q"

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: True)
    # Never launch a real subprocess (the MCP branch would call `claude mcp add`).
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 0))

    policy = mod.load_policy(None, repos)
    rep = mod.Report()
    return mod.interactive(rep, repos, policy, user_scope=True)


# Individual tokens the dispatcher understands across every section.
ANSWER_TOKENS = [
    "",
    "A",
    "S",
    "a",
    "s",
    "g",
    "p",
    "k",
    "o",
    "q",
    "y",
    "1",
    "2",
    "2,3",
    "v1",
    "v2",
    "?",
    "n",
    "zz",
    "9",
    "1,9,x",
]


@pytest.mark.parametrize("first", ANSWER_TOKENS)
def test_interactive_single_answer_never_crashes(env, linter_module, monkeypatch, first):
    # answer the section picker with 'first', then Enter for everything after.
    rc = _run_interactive(linter_module, [first] + [""] * 60, env.repos, monkeypatch)
    assert isinstance(rc, int)


@pytest.mark.parametrize(
    "seq",
    [list(c) for c in itertools.product(["", "1", "1,2,3"], ["", "A", "s", "g", "2"], ["", "S", "a", "o", "p"])],
)
def test_interactive_answer_sequences_never_crash(env, linter_module, monkeypatch, seq):
    rc = _run_interactive(linter_module, seq + [""] * 40, env.repos, monkeypatch)
    assert isinstance(rc, int)


def test_interactive_all_sections_apply_advice(env, linter_module, monkeypatch):
    # pick all sections (Enter), then apply-advice-to-all in dups (A), and
    # skip/keep elsewhere. Must complete without raising.
    rc = _run_interactive(linter_module, ["", "A"] + [""] * 50, env.repos, monkeypatch)
    assert isinstance(rc, int)


def test_interactive_quit_immediately(env, linter_module, monkeypatch):
    rc = _run_interactive(linter_module, ["q"], env.repos, monkeypatch)
    assert rc == 0
