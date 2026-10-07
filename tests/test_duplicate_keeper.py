"""Near-duplicate findings name a suggested keeper and never move anything."""

from __future__ import annotations


def _item(mod, name, kind, hash_, desc=""):
    return {
        "name": name,
        "kind": kind,
        "hash": hash_,
        "desc": desc,
        "words": mod._words(name.replace("-", " ") + " " + desc),
        "path": f"/x/{name}",
        "file": None,
        "lines": 1,
    }


def test_keeper_is_the_richest_description(linter_module):
    m = linter_module
    short = _item(m, "review", "skill", "H1", "short")
    rich = _item(m, "review-code", "skill", "H2", "a much longer and more useful description")
    assert m.suggest_keeper([short, rich])["name"] == "review-code"


def test_keeper_tie_breaks_on_shortest_path_then_path(linter_module):
    m = linter_module
    a = _item(m, "aaa", "skill", "H1", "same")
    b = _item(m, "bbbbbb", "skill", "H2", "same")
    assert m.suggest_keeper([b, a])["name"] == "aaa"
    assert m.suggest_keeper([a, b])["name"] == "aaa"


def test_finding_message_names_the_keeper_and_states_nothing_moves(linter_module, tmp_path):
    m = linter_module
    rich = "Lint the code with the project tools and report every problem found"
    for root, desc in (("user", "Lint"), ("proj", rich)):
        d = tmp_path / root / "skills" / "lint-code"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: lint-code\ndescription: {desc}\n---\nbody {root}\n")
    rep = m.Report()
    m.check_duplicates([tmp_path / "user"], [tmp_path / "proj"], rep)
    msgs = [f.message for f in rep.findings if f.code.startswith("DUP_")]
    assert msgs
    assert "suggested keeper: skill:lint-code;" in msgs[0]
    assert "nothing is moved until you run -i" in msgs[0]
    assert (tmp_path / "user" / "skills" / "lint-code").is_dir()
    assert (tmp_path / "proj" / "skills" / "lint-code").is_dir()
