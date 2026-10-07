"""TOKEN_SKILL_DESC carries a shorter proposal and never edits the skill."""

from __future__ import annotations

SENT = "Create an architecture decision record in the project format with a fatal hypothesis and a kill test. "
LONG = (SENT * 6).strip()


def test_short_description_is_returned_unchanged(linter_module):
    assert linter_module.shorten_description("Short text.", 400) == "Short text."


def test_whole_leading_sentences_are_kept(linter_module):
    out = linter_module.shorten_description(LONG, 250)
    assert len(out) <= 250
    assert out.endswith(".")
    assert LONG.startswith(out)


def test_single_long_sentence_is_cut_on_a_word_boundary(linter_module):
    out = linter_module.shorten_description("word " * 200, 50)
    assert len(out) <= 50
    assert out.endswith("…")
    assert not out[:-1].endswith("wor")


def test_whitespace_is_normalised(linter_module):
    assert linter_module.shorten_description("a  b\n\nc", 400) == "a b c"


def test_finding_message_has_the_proposal_and_file_is_untouched(linter_module, tmp_path):
    m = linter_module
    d = tmp_path / ".claude" / "skills" / "adr"
    d.mkdir(parents=True)
    f = d / "SKILL.md"
    f.write_text(f"---\nname: adr\ndescription: {LONG}\n---\nbody\n")
    before = f.read_bytes()
    pol = m.load_policy(None, [tmp_path])
    rep = m.Report()
    m._skill_listing([tmp_path / ".claude"], rep, pol)
    msg = next(x.message for x in rep.findings if x.code == "TOKEN_SKILL_DESC")
    assert "shorter proposal" in msg
    assert "tokens/turn saved" in msg
    assert "(not applied)" in msg
    assert f.read_bytes() == before


def test_report_and_interactive_review_share_one_shortener(linter_module):
    from prism_ai_lint import _markup, tui_app

    assert tui_app.shorten_description is _markup.shorten_description
    assert linter_module.shorten_description is _markup.shorten_description


def test_interactive_proposal_never_cuts_inside_a_word(linter_module):
    from prism_ai_lint import tui_app

    class Probe:
        limit = 50

    out = tui_app.TuiApp._short_description(Probe(), "word " * 200)
    assert len(out) <= 50
    assert out.endswith("…")
    assert not out[:-1].endswith("wor")
