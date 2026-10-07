"""TOKEN_SUBAGENT_MODEL proposes a cheaper model only for read-only mechanical subagents."""

from __future__ import annotations


def _agent(repo, name, tools=None, model=None, desc="Run the test suite and summarize failures"):
    d = repo / ".claude" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    fm = [f"name: {name}", f"description: {desc}"]
    if tools:
        fm.append(f"tools: {tools}")
    if model:
        fm.append(f"model: {model}")
    (d / f"{name}.md").write_text("---\n" + "\n".join(fm) + "\n---\nbody\n")


def _findings(m, repo):
    pol = m.load_policy(None, [repo])
    rep = m.Report()
    m.check_token_levers(repo, pol, rep)
    return [f for f in rep.findings if f.code == "TOKEN_SUBAGENT_MODEL"]


def test_read_only_mechanical_agent_gets_a_proposal(linter_module, tmp_path):
    _agent(tmp_path, "test-runner", tools="Read, Grep, Glob, Bash")
    found = _findings(linter_module, tmp_path)
    assert len(found) == 1
    assert "read-only" in found[0].message
    assert "haiku" in found[0].message


def test_agent_with_write_tools_gets_no_proposal(linter_module, tmp_path):
    _agent(tmp_path, "test-fixer", tools="Read, Edit, Write")
    found = _findings(linter_module, tmp_path)
    assert len(found) == 1
    assert "left on the inherited model" in found[0].message
    assert "test-fixer" in found[0].message


def test_unrestricted_agent_counts_as_able_to_write(linter_module, tmp_path):
    _agent(tmp_path, "log-triage")
    found = _findings(linter_module, tmp_path)
    assert [("left on the inherited model" in f.message) for f in found] == [True]


def test_agent_with_a_model_is_left_alone(linter_module, tmp_path):
    _agent(tmp_path, "test-runner", tools="Read, Grep", model="haiku")
    assert _findings(linter_module, tmp_path) == []


def test_non_mechanical_agent_is_left_alone(linter_module, tmp_path):
    _agent(tmp_path, "architect", tools="Read, Grep", desc="Design the system architecture")
    assert _findings(linter_module, tmp_path) == []


def test_policy_model_is_used(linter_module, tmp_path):
    _agent(tmp_path, "test-runner", tools="Read")
    pol = linter_module.load_policy(None, [tmp_path])
    pol["tokens"]["subagent_model"] = "my-cheap-route"
    rep = linter_module.Report()
    linter_module.check_token_levers(tmp_path, pol, rep)
    assert "my-cheap-route" in [f.message for f in rep.findings if f.code == "TOKEN_SUBAGENT_MODEL"][0]
