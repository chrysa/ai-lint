"""Self-update prompts are interactive and opt-in for side effects."""

from __future__ import annotations

from types import SimpleNamespace


def test_update_prompt_mentions_release_branch(linter_module):
    msg = linter_module.update_prompt("a" * 40, "b" * 40, "origin", "main")

    assert "origin/main" in msg
    assert "aaaaaaaaaaaa" in msg
    assert "bbbbbbbbbbbb" in msg


def test_update_confirmation_accepts_english_and_french(linter_module):
    assert linter_module.wants_update("yes")
    assert linter_module.wants_update("Y")
    assert linter_module.wants_update("oui")
    assert linter_module.wants_update("O")
    assert not linter_module.wants_update("")
    assert not linter_module.wants_update("no")


def test_update_check_skips_non_interactive_json(monkeypatch, linter_module):
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("update check should stay silent for JSON output")

    monkeypatch.setattr(linter_module.subprocess, "run", fail_if_called)
    args = SimpleNamespace(no_update_check=False, format="json", quiet=False)

    linter_module.maybe_check_for_ai_lint_update(args)

    assert called is False


def test_update_check_respects_disable_env(monkeypatch, linter_module):
    monkeypatch.setenv("AI_LINT_UPDATE_CHECK", "0")

    assert linter_module._update_check_due(force=False) is False
    assert linter_module._update_check_due(force=True) is True
