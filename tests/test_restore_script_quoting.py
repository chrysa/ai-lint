"""Restore scripts are shell: a file name from a scanned project must never become a command."""

from __future__ import annotations

import subprocess

import pytest

HOSTILE = [
    "a'b.md",
    "a'; touch PWNED; '.md",
    "x$(touch PWNED).md",
    "y`touch PWNED`.md",
    "z;touch PWNED;.md",
    "line\ntouch PWNED\n.md",
]


def _run_restore(lines, cwd):
    script = "\n".join(lines) + "\n"
    subprocess.run(["sh", "-c", script], cwd=cwd, check=True)


@pytest.mark.parametrize("name", HOSTILE)
def test_family_to_plugin_restore_line_is_inert_and_works(linter_module, tmp_path, monkeypatch, name):
    m = linter_module
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    src = tmp_path / "proj" / "agents"
    src.mkdir(parents=True)
    f = src / name
    f.write_text("---\nname: demo\n---\nbody\n")
    members = [{"kind": "agent", "path": f, "name": "demo", "desc": ""}]
    restore: list[str] = []
    pol = m.load_policy(None, [tmp_path])
    m._family_to_plugin(members, "demo", pol, restore)
    assert not f.exists()
    work = tmp_path / "work"
    work.mkdir()
    _run_restore(restore, work)
    assert f.read_text().startswith("---")
    assert not (work / "PWNED").exists()
    assert not (tmp_path / "PWNED").exists()


@pytest.mark.parametrize("bad", ["../../evil", "Has Space", "UPPER", "", "x" * 80, "a/b"])
def test_marketplace_name_from_policy_is_validated(linter_module, tmp_path, monkeypatch, bad):
    m = linter_module
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    pol = m.load_policy(None, [tmp_path])
    pol["restructure"]["marketplace_name"] = bad
    assert m._local_marketplace(pol)[1] == "personal"


def test_valid_marketplace_name_is_kept(linter_module, tmp_path, monkeypatch):
    m = linter_module
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    pol = m.load_policy(None, [tmp_path])
    pol["restructure"]["marketplace_name"] = "team-tools"
    assert m._local_marketplace(pol)[1] == "team-tools"
