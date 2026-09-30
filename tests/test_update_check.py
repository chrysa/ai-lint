"""Self-update prompts are interactive and opt-in for side effects."""

from __future__ import annotations

from types import SimpleNamespace

from ai_lint.self_update import SelfUpdateConfig, SelfUpdater


def test_update_prompt_mentions_release_branch():
    updater = SelfUpdater(SelfUpdateConfig(remote="origin", release_branch="main"))

    msg = updater.prompt("a" * 40, "b" * 40)

    assert "origin/main" in msg
    assert "aaaaaaaaaaaa" in msg
    assert "bbbbbbbbbbbb" in msg


def test_update_confirmation_accepts_english_and_french():
    updater = SelfUpdater()

    assert updater.wants_update("yes")
    assert updater.wants_update("Y")
    assert updater.wants_update("oui")
    assert updater.wants_update("O")
    assert not updater.wants_update("")
    assert not updater.wants_update("no")


def test_update_check_skips_non_interactive_json(monkeypatch):
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("update check should stay silent for JSON output")

    monkeypatch.setattr("ai_lint.self_update.subprocess.run", fail_if_called)
    args = SimpleNamespace(no_update_check=False, format="json", quiet=False)

    SelfUpdater().check(args)

    assert called is False


def test_update_check_respects_disable_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_LINT_UPDATE_CHECK", "0")
    updater = SelfUpdater(SelfUpdateConfig(cache_path=tmp_path / "update-check.json"))

    assert updater._due(force=False) is False
    assert updater._due(force=True) is True
