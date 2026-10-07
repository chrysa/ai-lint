"""SETTINGS_UNKNOWN_KEY suggests the closest known key and never rewrites it."""

from __future__ import annotations

import json


def _run(linter_module, tmp_path, key):
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    f = repo / ".claude" / "settings.json"
    f.write_text(json.dumps({key: "x"}))
    pol = linter_module.load_policy(None, [repo])
    rep = linter_module.Report()
    linter_module.check_settings(f, repo, "project", pol, rep)
    return f, [x for x in rep.findings if x.code == "SETTINGS_UNKNOWN_KEY"]


def test_misspelled_key_gets_a_suggestion(linter_module, tmp_path):
    known = sorted(linter_module.KNOWN_SETTINGS_KEYS)[0]
    _, found = _run(linter_module, tmp_path, known + "s")
    assert len(found) == 1
    assert f"did you mean '{known}'" in found[0].message


def test_new_key_gets_no_suggestion(linter_module, tmp_path):
    _, found = _run(linter_module, tmp_path, "zzzqqqwww")
    assert len(found) == 1
    assert "did you mean" not in found[0].message
    assert "schema may be newer" in found[0].message


def test_key_is_never_rewritten(linter_module, tmp_path):
    known = sorted(linter_module.KNOWN_SETTINGS_KEYS)[0]
    f, _ = _run(linter_module, tmp_path, known + "s")
    assert list(json.loads(f.read_text())) == [known + "s"]
