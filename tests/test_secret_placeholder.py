"""API_KEY_LEAK must ignore doc/CI placeholders and lines marked claude-secret-ok,
but still catch a real-looking Anthropic key."""

from __future__ import annotations

REAL = "sk-ant-api03-" + "Ab3Xz9Kq7Lm2Np5Rt8Wv1Yc4"  # random-looking, 24+ chars


def test_placeholder_key_not_flagged(linter_module):
    m = linter_module
    for text in (
        'KEY = "sk-ant-api03-ABCDEFGHIJ1234567890-XXXXXXXXXXX"',
        "sk-ant-api03-example-key-do-not-use-here",
        'token = "sk-ant-api03-your-key-goes-right-here-xx"  # claude-secret-ok',
    ):
        assert m.find_real_key(text) is None, text


def test_real_key_flagged(linter_module):
    m = linter_module
    assert m.find_real_key(f'KEY = "{REAL}"') == REAL


def test_repo_scan_skips_placeholder(linter_module, tmp_path):
    m = linter_module
    (tmp_path / "HOOKS_README.md").write_text("echo 'K = \"sk-ant-api03-ABCDEFGHIJ1234567890-XXXX\"'\n")
    rep = m.Report()
    m.check_repo_secrets(tmp_path, rep)
    assert not any(f.code == "API_KEY_LEAK" for f in rep.findings)


def test_repo_scan_catches_real(linter_module, tmp_path):
    m = linter_module
    (tmp_path / "leak.md").write_text(f"KEY={REAL}\n")
    rep = m.Report()
    m.check_repo_secrets(tmp_path, rep)
    assert any(f.code == "API_KEY_LEAK" for f in rep.findings)
