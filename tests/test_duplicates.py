"""White-box tests for find_duplicates: correct exact/name/similar labeling and
acceptable performance on many items."""

from __future__ import annotations

import time


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


def test_exact_labeled_exact(linter_module):
    m = linter_module
    items = [_item(m, "check", "skill", "H1"), _item(m, "check", "skill", "H1")]
    out = m.find_duplicates(items)
    assert len(out) == 1
    assert out[0][0] == "DUP_EXACT"


def test_name_only_labeled_name(linter_module):
    m = linter_module
    # same name, different body hashes -> DUP_NAME, not DUP_EXACT
    items = [_item(m, "check", "skill", "H1"), _item(m, "check", "skill", "H2")]
    out = m.find_duplicates(items)
    assert len(out) == 1
    assert out[0][0] == "DUP_NAME"


def test_exact_wins_over_name_in_same_cluster(linter_module):
    m = linter_module
    # two identical + one same-name-different-body: cluster should rank as EXACT
    items = [
        _item(m, "check", "skill", "H1"),
        _item(m, "check", "skill", "H1"),
        _item(m, "check", "skill", "H2"),
    ]
    out = m.find_duplicates(items)
    assert len(out) == 1
    assert out[0][0] == "DUP_EXACT"


def test_distinct_items_not_grouped(linter_module):
    m = linter_module
    items = [
        _item(m, "alpha", "skill", "H1", "does alpha things"),
        _item(m, "bravo", "agent", "H2", "does bravo things"),
    ]
    assert m.find_duplicates(items) == []


def test_skill_and_command_same_name_are_name_dups(linter_module):
    m = linter_module
    items = [_item(m, "deploy", "skill", "H1"), _item(m, "deploy", "command", "H2")]
    out = m.find_duplicates(items)
    assert len(out) == 1 and out[0][0] == "DUP_NAME"


def test_performance_realistic_scope(linter_module):
    m = linter_module
    # A large real user scope (~450 skills + subagents, distinct wording) must
    # cluster near-instantly. This is the shape of the actual --user run.
    items = []
    for i in range(500):
        kind = ["skill", "agent"][i % 2]
        items.append(
            _item(
                m,
                f"item-{i}",
                kind,
                f"H{i}",
                f"handles the {i} workflow for team {i % 7} in project scope",
            )
        )
    t0 = time.perf_counter()
    m.find_duplicates(items)
    assert time.perf_counter() - t0 < 3.0
