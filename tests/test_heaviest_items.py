"""The token budget names the heaviest items so the biggest saving is visible at a glance."""

from __future__ import annotations


def _skill(root, name, desc_chars):
    d = root / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {'x' * desc_chars}\n---\nbody\n")


def _budget(m, repo, monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(exist_ok=True)
    pol = m.load_policy(None, [repo])
    return m.token_budget(repo, False, pol, m.Report())


def test_heaviest_items_are_sorted_and_capped(linter_module, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    for i, size in enumerate((50, 900, 300, 1200, 100, 600, 20)):
        _skill(repo / ".claude", f"s{i}", size)
    b = _budget(linter_module, repo, monkeypatch, tmp_path)
    tokens = [h["tokens"] for h in b["heaviest"]]
    assert len(tokens) == 5
    assert tokens == sorted(tokens, reverse=True)
    assert b["heaviest"][0]["item"].endswith("s3/SKILL.md")


def test_mcp_placeholders_are_not_listed_as_items(linter_module, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".mcp.json").write_text('{"mcpServers": {"a": {"command": "x"}}}')
    b = _budget(linter_module, repo, monkeypatch, tmp_path)
    assert all("mcp:" not in h["item"] for h in b["heaviest"])


def test_render_lists_the_heaviest_items(linter_module, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _skill(repo / ".claude", "big", 1500)
    b = _budget(linter_module, repo, monkeypatch, tmp_path)
    out = linter_module.render_token_budget(b, False)
    assert "heaviest items:" in out
    assert "big/SKILL.md" in out
