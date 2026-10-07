"""--fix --full-yes must finish the repairs that the interactive step unlocks in the same run."""

from __future__ import annotations

import subprocess


def test_command_migrated_to_skill_gets_its_name_in_one_run(env):
    repo = env.home / "migrate-me"
    cmd = repo / ".claude" / "commands"
    cmd.mkdir(parents=True)
    (cmd / "adr-new.md").write_text("---\ndescription: Scaffold an ADR\n---\n# Command\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    env.run(str(repo), "--fix", "--full-yes", "--no-cli", "--no-update-check")
    skill = repo / ".claude" / "skills" / "adr-new" / "SKILL.md"
    assert skill.is_file()
    assert "name: adr-new" in skill.read_text()
