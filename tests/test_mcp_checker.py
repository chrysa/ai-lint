"""McpChecker in isolation: real secret scanner, no engine state."""

from __future__ import annotations

import json

from prism_ai_lint.mcp_checker import McpChecker
from prism_ai_lint.report import Report
from prism_ai_lint.secret_scan import InlineSecretScanner

POLICY = {"mcp": {"max_servers": 2}}


def _run(tmp_path, data, policy=POLICY):
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    rep = Report()
    McpChecker(InlineSecretScanner()).check_mcp(path, rep, policy)
    codes = {(f.level, f.code) for f in rep.findings}
    new = json.loads(rep.edits[path][1]) if path in rep.edits else None
    return rep, codes, new


def test_literal_env_secret_is_replaced_by_a_reference(tmp_path):
    data = {"mcpServers": {"api": {"command": "srv", "env": {"API_TOKEN": "literal-value-not-secret"}}}}
    _rep, codes, new = _run(tmp_path, data)
    assert ("error", "SECRET_INLINE") in codes
    assert new["mcpServers"]["api"]["env"]["API_TOKEN"] == "${API_TOKEN}"
    assert (tmp_path / ".mcp.json").read_text(encoding="utf-8") == json.dumps(data)  # recorded, not written


def test_top_level_servers_are_moved_under_mcp_servers(tmp_path):
    _rep, codes, new = _run(tmp_path, {"api": {"command": "srv"}})
    assert ("warn", "MCP_MISPLACED") in codes
    assert new == {"mcpServers": {"api": {"command": "srv"}}}


def test_server_count_above_policy_is_flagged(tmp_path):
    servers = {f"s{i}": {"command": "srv"} for i in range(3)}
    _rep, codes, _new = _run(tmp_path, {"mcpServers": servers})
    assert ("warn", "MCP_TOO_MANY") in codes


def test_server_without_command_or_url_is_an_error(tmp_path):
    _rep, codes, _new = _run(tmp_path, {"mcpServers": {"broken": {"env": {}}}})
    assert ("error", "MCP_SHAPE") in codes
