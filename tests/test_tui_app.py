"""Scripted terminal flows, explicit approvals and recoverable actions."""

from __future__ import annotations

import json
import subprocess

import pytest

from prism_ai_lint.tui_app import TuiApp


@pytest.fixture
def review(linter_module, tmp_path, monkeypatch):
    repo = tmp_path / "project"
    repo.mkdir()
    cfg = tmp_path / "home" / ".claude"
    cfg.mkdir(parents=True)
    (cfg / "settings.json").write_text('{"model": "sonnet"}')
    monkeypatch.setenv("HOME", str(cfg.parent))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.setattr(linter_module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(linter_module, "session_duplicates", lambda *args: [])
    monkeypatch.setattr(linter_module, "compute_proposals", lambda *args: [])
    policy = linter_module.load_policy(None, [repo])
    report = linter_module.Report()
    report.project_profiles = [{"path": str(repo), "kind": "python-cli", "confidence": "high", "signals": ["python"]}]
    return linter_module, repo, cfg, policy, report


def answers(monkeypatch, values):
    queue = iter(values)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(queue))


def rule_proposal(repo, name="style"):
    path = repo / ".claude" / "rules" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Rules\nPrefer clear names.\n")
    return {
        "kind": "rule-paths",
        "path": path,
        "glob": "**/*.py",
        "gain": 10,
        "title": "Scope rule",
        "root": repo / ".claude",
    }


def run(review, monkeypatch, values, proposals):
    mod, repo, _cfg, policy, report = review
    monkeypatch.setattr(mod, "compute_proposals", lambda *args: proposals)
    answers(monkeypatch, values)
    app = mod._tui_app()
    assert isinstance(app, TuiApp)
    return app, app.run(report, [repo], policy, False)


def test_overview_and_findings_without_actions(review, capsys):
    mod, repo, _cfg, policy, report = review
    report.add("error", "IMPORT_MISSING", repo / "CLAUDE.md", "Missing target")
    assert mod.interactive(report, [repo], policy, False) == 0
    output = capsys.readouterr().out
    assert "python-cli (high confidence)" in output
    assert "Evidence: python" in output
    assert "AUTONOMY READINESS" in output
    assert "ERROR / instructions / manual: 1" in output
    assert "IMPORT_MISSING" in output


def test_non_tty_does_not_scan_or_prompt(review, monkeypatch, capsys):
    mod, repo, _cfg, policy, report = review
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(mod, "compute_proposals", lambda *args: pytest.fail("non-TTY must not scan review actions"))
    monkeypatch.setattr("builtins.input", lambda *args: pytest.fail("non-TTY must not prompt"))
    assert mod.interactive(report, [repo], policy, False) == 0
    assert "terminal" in capsys.readouterr().out


def test_full_yes_applies_critical_proposal_without_tty(review, monkeypatch):
    mod, repo, _cfg, policy, report = review
    proposal = rule_proposal(repo)
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(mod, "compute_proposals", lambda *args: [proposal])
    monkeypatch.setattr("builtins.input", lambda *args: pytest.fail("full yes must not prompt"))
    app = mod._tui_app()
    app.full_yes = True
    app.run(report, [repo], policy, False)
    assert app.done["restructurations appliquées"] == 1
    assert proposal["path"].read_text() != "# Rules\nPrefer clear names.\n"


@pytest.mark.parametrize("approval", ["", "o", "A", "y", "no", "q"])
def test_critical_proposal_requires_exact_approval(review, monkeypatch, capsys, approval):
    proposal = rule_proposal(review[1])
    old = proposal["path"].read_text()
    app, changed = run(review, monkeypatch, ["", "o", approval], [proposal])
    assert changed == 0
    assert proposal["path"].read_text() == old
    assert app.done["critical proposals refused"] == 1
    assert not app.restore
    output = capsys.readouterr().out
    assert "CRITICAL CONTENT VALIDATION" in output
    assert "+paths:" in output
    assert "Refused" in output


def test_critical_proposal_approval_and_restore(review, monkeypatch):
    proposal = rule_proposal(review[1])
    old = proposal["path"].read_text()
    app, changed = run(review, monkeypatch, ["", "o", "approve"], [proposal])
    assert changed == 1
    assert "paths:" in proposal["path"].read_text()
    subprocess.run(["sh", str(app.restore.script)], check=True)
    assert proposal["path"].read_text() == old


def test_bulk_action_still_validates_each_critical_diff(review, monkeypatch):
    first, second = rule_proposal(review[1], "first"), rule_proposal(review[1], "second")
    original = second["path"].read_text()
    app, changed = run(review, monkeypatch, ["", "A", "approve", ""], [first, second])
    assert changed == 1
    assert "paths:" in first["path"].read_text()
    assert second["path"].read_text() == original
    assert app.done["critical proposals refused"] == 1


def test_changed_file_after_approval_is_not_overwritten(review, monkeypatch, capsys):
    proposal = rule_proposal(review[1])
    mod, repo, _cfg, policy, report = review
    monkeypatch.setattr(mod, "compute_proposals", lambda *args: [proposal])
    queue = iter(["", "o"])

    def reply(prompt):
        if "Type approve" in prompt:
            proposal["path"].write_text("# Concurrent edit\n")
            return "approve"
        return next(queue)

    monkeypatch.setattr("builtins.input", reply)
    assert mod.interactive(report, [repo], policy, False) == 0
    assert proposal["path"].read_text() == "# Concurrent edit\n"
    assert "changed after approval" in capsys.readouterr().out


def test_navigation_rejects_invalid_input_and_numbers_progress(review, monkeypatch, capsys):
    proposal = rule_proposal(review[1])
    app, changed = run(review, monkeypatch, ["bad", "9", "?", "f", "1,1", ""], [proposal])
    assert changed == 0
    assert app.chosen == ["restructure"]
    output = capsys.readouterr().out
    assert "Invalid selection" in output
    assert "out of range" in output
    assert "[1/1] RESTRUCTURATIONS" in output
    assert "1 section(s) revue(s) / 1 selected" in output


def test_keyboard_interrupt_in_navigation_is_safe(review, monkeypatch, capsys):
    mod, repo, _cfg, policy, report = review
    proposal = rule_proposal(repo)
    old = proposal["path"].read_text()
    monkeypatch.setattr(mod, "compute_proposals", lambda *args: [proposal])

    def interrupt(prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)
    assert mod.interactive(report, [repo], policy, False) == 0
    assert proposal["path"].read_text() == old
    assert "Review interrupted" in capsys.readouterr().out


def test_procedure_preview_creation_and_restore(review, monkeypatch):
    mod, repo, _cfg, policy, _report = review
    path = repo / "CLAUDE.md"
    old = "# Project\n\n## Deployment\nRun tests before deploying.\n"
    path.write_text(old)
    proposal = {
        "kind": "procedure-to-skill",
        "path": path,
        "section": "Deployment",
        "gain": 20,
        "title": "Extract procedure",
    }
    planned = mod.proposal_edits(proposal, policy)
    assert path.read_text() == old
    assert len(planned) == 2
    app, changed = run(review, monkeypatch, ["", "o", "approve"], [proposal])
    assert changed == 1
    skill = repo / ".claude" / "skills" / "deployment" / "SKILL.md"
    assert skill.exists()
    subprocess.run(["sh", str(app.restore.script)], check=True)
    assert path.read_text() == old
    assert not skill.exists()


def test_mcp_command_failure_is_not_reported_as_applied(review, monkeypatch, capsys):
    mod, repo, _cfg, policy, report = review
    report.add("info", "GENERATE_USER_MCP", repo, "claude mcp add demo --scope user")
    answers(monkeypatch, ["", "o"])
    monkeypatch.setattr(mod.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 1))
    assert mod.interactive(report, [repo], policy, False) == 0
    assert "MCP command exited with status 1" in capsys.readouterr().out


def test_description_shortening_keeps_first_complete_sentence(review):
    app = review[0]._tui_app()
    app.limit = 15
    assert app._short_description("First sentence. Another sentence.") == "First sentence."


def test_json_interactive_flag_keeps_noninteractive_contract(env):
    result = env.run(str(env.repos[0]), "--format", "json", "--interactive", "--no-update")
    data = json.loads(result.stdout)
    assert "findings" in data
    assert "PROJECT OVERVIEW" not in result.stdout


def test_existing_skill_destination_is_not_overwritten(review, monkeypatch, capsys):
    mod, repo, _cfg, _policy, _report = review
    path = repo / "CLAUDE.md"
    old = "# Project\n\n## Deployment\nRun tests before deploying.\n"
    path.write_text(old)
    destination = repo / ".claude" / "skills" / "deployment" / "SKILL.md"
    destination.parent.mkdir(parents=True)
    destination.write_text("Existing skill\n")
    proposal = {
        "kind": "procedure-to-skill",
        "path": path,
        "section": "Deployment",
        "gain": 20,
        "title": "Extract procedure",
    }
    _app, changed = run(review, monkeypatch, ["", "o"], [proposal])
    assert changed == 0
    assert path.read_text() == old
    assert destination.read_text() == "Existing skill\n"
    assert "already exists" in capsys.readouterr().out


def test_model_change_has_working_undo_script(review, monkeypatch):
    mod, repo, cfg, policy, report = review
    path = cfg / "settings.json"
    old = '{"model": "opus"}'
    path.write_text(old)
    answers(monkeypatch, ["", "o"])
    app = mod._tui_app()
    assert app.run(report, [repo], policy, True) == 1
    assert json.loads(path.read_text())["model"] == "sonnet"
    subprocess.run(["sh", str(app.restore.script)], check=True)
    assert path.read_text() == old


def test_description_change_has_working_undo_script(review, monkeypatch):
    mod, repo, cfg, policy, report = review
    path = cfg / "skills" / "demo" / "SKILL.md"
    path.parent.mkdir(parents=True)
    description = "First complete sentence. " + "Another sentence. " * 40
    old = f"---\nname: demo\ndescription: {description}\n---\nReview the project.\n"
    path.write_text(old)
    answers(monkeypatch, ["", "o"])
    app = mod._tui_app()
    assert app.run(report, [repo], policy, True) == 1
    assert path.read_text() != old
    assert "full_description" in path.read_text()
    subprocess.run(["sh", str(app.restore.script)], check=True)
    assert path.read_text() == old


def test_critical_diff_redacts_secrets(review, monkeypatch, capsys):
    proposal = rule_proposal(review[1])
    secret = "sk-" + "ant-api03-" + "A" * 80
    proposal["path"].write_text(f"# Rules\nToken: {secret}\n")
    _app, changed = run(review, monkeypatch, ["", "o", ""], [proposal])
    assert changed == 0
    assert secret not in capsys.readouterr().out


def test_split_skill_restores_original_and_reference_file(review, monkeypatch):
    mod, repo, _cfg, _policy, _report = review
    skill = repo / ".claude" / "skills" / "demo" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    old = (
        "---\nname: demo\ndescription: Run project checks.\n---\n\n# Overview\n\n## Reference\n"
        + "Detailed guidance.\n" * 200
    )
    skill.write_text(old)
    reference = skill.parent / "references" / "reference.md"
    reference.parent.mkdir()
    reference.write_text("Existing reference\n")
    proposal = {"kind": "split-skill", "path": skill, "gain": 40, "title": "Split skill", "lines": 210}
    app, changed = run(review, monkeypatch, ["", "o"], [proposal])
    assert changed == 1
    assert "Additional resources" in skill.read_text()
    assert reference.read_text() != "Existing reference\n"
    subprocess.run(["sh", str(app.restore.script)], check=True)
    assert skill.read_text() == old
    assert reference.read_text() == "Existing reference\n"


def test_setup_flow_counts_generated_paths(review, capsys):
    linter, repo, _cfg, _policy, report = review
    report.new_files = {
        repo / "CLAUDE.md": ("", 0),
        repo / ".claude" / "settings.json": ("", 0),
        repo / ".claude" / "hooks" / "format.py": ("", 0),
    }
    linter._tui_app().setup_flow(report, scaffold_mode=True)
    out = capsys.readouterr().out
    assert "Instructions: 1" in out
    assert "Settings: 1" in out
    assert "Hooks: 1" in out
