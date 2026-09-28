"""The plugin system: a dropped-in check runs, reports, is listed, is isolated
from failures, and honours the catalog (disable/severity)."""

from __future__ import annotations


def _write_plugin(d, body):
    d.mkdir(parents=True, exist_ok=True)
    (d / "myplugin.py").write_text(body)


GOOD = """
def register(api):
    @api.check("PLUGIN_DEMO", scope="project")
    def _c(ctx):
        if ctx.path("MARKER").is_file():
            ctx.add("warn", "PLUGIN_DEMO", ctx.path("MARKER"), "marker present",
                    action_en="remove it")
"""

BAD = "def register(api):\n    raise RuntimeError('boom')\n"


def _reset(m):
    m._PLUGIN_CHECKS.clear()
    m._PLUGINS_LOADED.clear()


def test_plugin_check_runs_and_reports(linter_module, tmp_path, monkeypatch):
    m = linter_module
    _reset(m)
    _write_plugin(tmp_path / "plg", GOOD)
    m.load_plugins([tmp_path / "plg"])
    assert "myplugin" in m._PLUGINS_LOADED
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "MARKER").write_text("x")
    rep = m.Report()
    m.run_plugin_checks("project", repo, m.load_policy(None, [repo]), rep)
    assert any(f.code == "PLUGIN_DEMO" for f in rep.findings)
    assert m._action_for("PLUGIN_DEMO") == "remove it"


def test_plugin_failure_is_isolated(linter_module, tmp_path):
    m = linter_module
    _reset(m)
    _write_plugin(tmp_path / "bad", BAD)
    m.load_plugins([tmp_path / "bad"])  # must not raise
    assert "myplugin" not in m._PLUGINS_LOADED


def test_plugin_check_error_isolated(linter_module, tmp_path):
    m = linter_module
    _reset(m)
    _write_plugin(
        tmp_path / "plg",
        "def register(api):\n    @api.check('PLUGIN_X')\n    def _c(ctx):\n        raise ValueError('nope')\n",
    )
    m.load_plugins([tmp_path / "plg"])
    rep = m.Report()
    m.run_plugin_checks("project", tmp_path, m.load_policy(None, [tmp_path]), rep)  # no raise
    assert not any(f.code == "PLUGIN_X" for f in rep.findings)


def test_plugin_check_honours_catalog_disable(linter_module, tmp_path, monkeypatch):
    m = linter_module
    _reset(m)
    monkeypatch.setattr(m, "DISABLED_CODES", {"PLUGIN_DEMO"})
    _write_plugin(tmp_path / "plg", GOOD)
    m.load_plugins([tmp_path / "plg"])
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "MARKER").write_text("x")
    rep = m.Report()
    m.run_plugin_checks("project", repo, m.load_policy(None, [repo]), rep)
    assert not any(f.code == "PLUGIN_DEMO" for f in rep.findings)
