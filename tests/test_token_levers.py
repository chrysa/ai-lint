"""Token levers: MCP output cap suggestion."""

from __future__ import annotations

import json


def _repo(tmp_path, servers, env_settings=None):
    repo = tmp_path / "r"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".mcp.json").write_text(json.dumps({"mcpServers": servers}))
    if env_settings is not None:
        (repo / ".claude" / "settings.json").write_text(json.dumps({"env": env_settings}))
    return repo


def test_mcp_output_cap_suggested(linter_module, tmp_path, monkeypatch):
    m = linter_module
    monkeypatch.delenv("MAX_MCP_OUTPUT_TOKENS", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    repo = _repo(tmp_path, {"playwright": {"type": "stdio", "command": "npx"}})
    rep = m.Report()
    m.check_token_levers(repo, m.load_policy(None, [repo]), rep)
    assert any(f.code == "TOKEN_MCP_OUTPUT" for f in rep.findings)


def test_mcp_output_cap_not_flagged_when_set(linter_module, tmp_path, monkeypatch):
    m = linter_module
    monkeypatch.delenv("MAX_MCP_OUTPUT_TOKENS", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    repo = _repo(tmp_path, {"x": {"type": "stdio", "command": "y"}}, env_settings={"MAX_MCP_OUTPUT_TOKENS": "8000"})
    rep = m.Report()
    m.check_token_levers(repo, m.load_policy(None, [repo]), rep)
    assert not any(f.code == "TOKEN_MCP_OUTPUT" for f in rep.findings)
