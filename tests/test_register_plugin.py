"""Plugin names written under the local marketplace cannot escape it."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize("name", ["../evil", "a/b", "/abs", "UPPER", "", "x" * 65, "-lead"])
def test_register_plugin_rejects_unsafe_names(linter_module, tmp_path, monkeypatch, name):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    policy = linter_module.load_policy(None, [tmp_path])
    with pytest.raises(ValueError):
        linter_module._register_plugin(name, "desc", policy, [])
    assert not any(tmp_path.rglob("plugin.json"))
