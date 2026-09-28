"""The editable catalog: export round-trips, and an overlay disables a code,
re-ranks a severity, and extends the known settings keys."""

from __future__ import annotations

import pytest

yaml = pytest.importorskip("yaml")


def test_catalog_dump_is_valid_yaml(linter_module):
    m = linter_module
    data = yaml.safe_load(m.dump_catalog())
    assert "reference" in data and "checks" in data
    assert "SKILL_NAME" in data["checks"]
    assert data["checks"]["SKILL_NAME"]["severity"] in ("error", "warn", "info")


def test_catalog_overlay_disables_and_reranks(linter_module, tmp_path, monkeypatch):
    m = linter_module
    monkeypatch.setattr(m, "DISABLED_CODES", set())
    monkeypatch.setattr(m, "SEVERITY_OVERRIDES", {})
    cat = tmp_path / "c.yaml"
    cat.write_text(
        "reference:\n  settings_keys: [myKey]\n"
        "checks:\n  SKILL_NAME:\n    enabled: false\n  RULE_UNSCOPED:\n    severity: error\n"
    )
    m.load_catalog(cat)
    assert "SKILL_NAME" in m.DISABLED_CODES
    assert m.SEVERITY_OVERRIDES.get("RULE_UNSCOPED") == "error"
    assert "myKey" in m.KNOWN_SETTINGS_KEYS
    # Report.add honours both
    rep = m.Report()
    rep.add("warn", "SKILL_NAME", "/x", "msg")
    rep.add("warn", "RULE_UNSCOPED", "/x", "msg")
    assert not any(f.code == "SKILL_NAME" for f in rep.findings)
    assert any(f.code == "RULE_UNSCOPED" and f.level == "error" for f in rep.findings)


def test_catalog_missing_file_is_safe(linter_module, tmp_path, monkeypatch):
    m = linter_module
    monkeypatch.setattr(m, "DISABLED_CODES", set())
    m.load_catalog(tmp_path / "nope.yaml")  # must not raise
    assert m.DISABLED_CODES == set()
