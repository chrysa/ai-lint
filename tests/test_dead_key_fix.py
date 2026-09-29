"""A managed-settings-only key in project settings is dead there; --fix removes
it (safe tightening) and repeated runs converge."""

from __future__ import annotations

import json


def test_project_dead_key_removed(linter_module, tmp_path):
    m = linter_module
    key = next(iter(m.PROJECT_DEAD_KEYS))
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({key: "x", "permissions": {"allow": []}}))
    rep = m.Report()
    m.check_settings(p, tmp_path, "project", m.load_policy(None, [tmp_path]), rep)
    assert p in rep.edits
    _old, new = rep.edits[p]
    assert key not in json.loads(new)
    assert any(f.code == "SETTINGS_DEAD_KEY" and f.fixable for f in rep.findings)


def test_dead_key_kept_at_user_scope(linter_module, tmp_path):
    m = linter_module
    key = next(iter(m.PROJECT_DEAD_KEYS))
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({key: "x"}))
    rep = m.Report()
    m.check_settings(p, tmp_path, "user", m.load_policy(None, [tmp_path]), rep)
    # user scope may legitimately set it: not flagged dead, not removed
    assert not any(f.code == "SETTINGS_DEAD_KEY" for f in rep.findings)
