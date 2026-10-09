"""The model lineup snapshot: current vs legacy ids, and Fable counted as a heavy default."""

from __future__ import annotations

import json

import pytest

from prism_ai_lint._reference import CURRENT_MODELS, LEGACY_MODELS, model_status


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("claude-sonnet-5-5", "current"),
        ("claude-fable-5-1", "current"),
        ("claude-haiku-5-5", "current"),
        ("claude-opus-4-5-20251101", "legacy"),
        ("claude-sonnet-4-6", "legacy"),
        ("claude-opus-5-5[1m]", "current"),
        ("sonnet", ""),
        ("opus", ""),
        ("", ""),
        ("some-gateway-route", ""),
    ],
)
def test_model_status(name, expected):
    assert model_status(name) == expected


def test_current_and_legacy_do_not_overlap():
    assert not CURRENT_MODELS & LEGACY_MODELS


def _check(m, tmp_path, monkeypatch, user_model=None, project_model=None):
    home = tmp_path / "home"
    home.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    if user_model:
        (home / "settings.json").write_text(json.dumps({"model": user_model}))
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    if project_model:
        (repo / ".claude" / "settings.json").write_text(json.dumps({"model": project_model}))
    rep = m.Report()
    m.check_token_levers(repo, m.load_policy(None, [repo]), rep)
    return rep.findings


def test_legacy_pinned_model_is_reported(linter_module, tmp_path, monkeypatch):
    found = [
        f
        for f in _check(linter_module, tmp_path, monkeypatch, project_model="claude-opus-4-5")
        if f.code == "MODEL_LEGACY"
    ]
    assert len(found) == 1
    assert "previous generation" in found[0].message
    assert found[0].level == "info"


def test_alias_and_current_ids_are_not_reported(linter_module, tmp_path, monkeypatch):
    for model in ("sonnet", "claude-sonnet-5-5", "claude-fable-5-1"):
        codes = [f.code for f in _check(linter_module, tmp_path / model, monkeypatch, user_model=model)]
        assert "MODEL_LEGACY" not in codes


def test_fable_is_flagged_as_a_heavy_default(linter_module, tmp_path, monkeypatch):
    codes = [f.code for f in _check(linter_module, tmp_path, monkeypatch, user_model="claude-fable-5-1")]
    assert "TOKEN_MODEL" in codes


def test_sonnet_default_is_not_heavy(linter_module, tmp_path, monkeypatch):
    codes = [f.code for f in _check(linter_module, tmp_path, monkeypatch, user_model="claude-sonnet-5-5")]
    assert "TOKEN_MODEL" not in codes
