"""MCP_BROKEN flags stdio servers whose command cannot run, and nothing else."""

from __future__ import annotations

import json
import os
import stat


def _scan(m, tmp_path, servers):
    cfg = tmp_path / ".mcp.json"
    cfg.write_text(json.dumps({"mcpServers": servers}))
    rep = m.Report()
    m._MCP.check_mcp(cfg, rep, m.load_policy(None, [tmp_path]))
    return [f for f in rep.findings if f.code == "MCP_BROKEN"]


def test_missing_command_is_reported(linter_module, tmp_path):
    found = _scan(linter_module, tmp_path, {"x": {"command": "definitely-not-installed-zzz"}})
    assert len(found) == 1
    assert "definitely-not-installed-zzz" in found[0].message
    assert found[0].level == "info"


def test_command_on_path_is_fine(linter_module, tmp_path):
    assert _scan(linter_module, tmp_path, {"x": {"command": "python3", "args": ["-V"]}}) == []


def test_relative_script_is_resolved_from_the_config_folder(linter_module, tmp_path):
    script = tmp_path / "bin" / "serve"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    assert _scan(linter_module, tmp_path, {"x": {"command": os.path.join(".", "bin", "serve")}}) == []
    assert len(_scan(linter_module, tmp_path, {"x": {"command": "./bin/missing"}})) == 1


def test_command_with_a_variable_is_not_judged(linter_module, tmp_path):
    assert _scan(linter_module, tmp_path, {"x": {"command": "${TOOLS}/serve"}}) == []


def test_http_server_has_no_command_to_check(linter_module, tmp_path):
    assert _scan(linter_module, tmp_path, {"x": {"type": "http", "url": "https://example.test/mcp"}}) == []


def test_finding_never_edits_the_config(linter_module, tmp_path):
    cfg = tmp_path / ".mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"x": {"command": "definitely-not-installed-zzz"}}}))
    before = cfg.read_bytes()
    rep = linter_module.Report()
    linter_module._MCP.check_mcp(cfg, rep, linter_module.load_policy(None, [tmp_path]))
    assert not rep.edits
    assert cfg.read_bytes() == before
