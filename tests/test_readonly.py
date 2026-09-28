"""Read-only / symlinked skills (synced stores) must never crash -i or --fix:
they are detected and skipped, not written."""

from __future__ import annotations

import builtins
import os
import stat


def _make_long_desc_skill(cfg, name, writable):
    long = "Very long skill description. " * 60  # well over the listing cap
    body = f"---\nname: {name}\ndescription: {long}\n---\n\nContent here.\n"
    if writable:
        p = cfg / "skills" / name / "SKILL.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        return p
    # read-only: real file in a store dir, symlinked into skills/, store made read-only
    store = cfg / ".agents" / "skills" / name
    store.mkdir(parents=True, exist_ok=True)
    (store / "SKILL.md").write_text(body)
    link = cfg / "skills" / name
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(os.path.relpath(store, link.parent))
    os.chmod(store, stat.S_IREAD | stat.S_IEXEC)  # dir not writable
    return link / "SKILL.md"


def test_writable_detects_symlinked_readonly(env, linter_module):
    m = linter_module
    ro = _make_long_desc_skill(env.cfg, "frozen-skill", writable=False)
    rw = _make_long_desc_skill(env.cfg, "editable-skill", writable=True)
    assert m._writable(rw) is True
    assert m._writable(ro) is False


def test_interactive_skips_readonly_descriptions(env, linter_module, monkeypatch):
    m = linter_module
    _make_long_desc_skill(env.cfg, "frozen-skill", writable=False)
    _make_long_desc_skill(env.cfg, "editable-skill", writable=True)
    # choose the descriptions section, apply every prompt, then quit.
    answers = iter(["4", "o", "o", "o", "q"] + [""] * 20)
    monkeypatch.setattr(builtins, "input", lambda p="": next(answers, "q"))
    monkeypatch.setattr(m.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: None)
    policy = m.load_policy(None, [])
    rc = m.interactive(m.Report(), [], policy, user_scope=True)
    assert isinstance(rc, int)
    # the read-only skill's file was never rewritten (still a symlink to the store)
    assert (env.cfg / "skills" / "frozen-skill").is_symlink()


def test_proposals_skip_readonly(env, linter_module):
    m = linter_module
    # a 600-line read-only skill would otherwise yield a split-skill proposal
    store = env.cfg / ".agents" / "skills" / "bigfrozen"
    store.mkdir(parents=True, exist_ok=True)
    body = "---\nname: bigfrozen\ndescription: big\n---\n\n" + "\n".join(f"## S{i}\n\nx" for i in range(300))
    (store / "SKILL.md").write_text(body)
    link = env.cfg / "skills" / "bigfrozen"
    link.symlink_to(os.path.relpath(store, link.parent))
    os.chmod(store, stat.S_IREAD | stat.S_IEXEC)
    props = m.compute_proposals([env.cfg], [], m.load_policy(None, []))
    assert not any(p.get("path") == link / "SKILL.md" for p in props)
