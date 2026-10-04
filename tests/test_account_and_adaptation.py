"""Tests for account capabilities and project adaptation."""

from __future__ import annotations

from ai_lint.account_capabilities import AccountCapabilities, AccountCapabilitiesChecker
from ai_lint.project_adaptation import ProjectAdaptationRecommender


def test_account_capabilities_is_premium():
    cap = AccountCapabilities(model_available="opus")
    assert cap.is_premium() is True
    cap_haiku = AccountCapabilities(model_available="haiku")
    assert cap_haiku.is_premium() is False


def test_account_capabilities_recommendation():
    cap = AccountCapabilities(model_available="haiku")
    rec = cap.recommendation_for_model()
    assert rec is not None
    assert "Haiku" in rec


def test_account_capabilities_checker_detect():
    checker = AccountCapabilitiesChecker()
    cap = checker.detect()
    assert isinstance(cap, AccountCapabilities)
    assert cap.token_limit > 0
    assert cap.has_vision is True


def test_project_adaptation_python_cli():
    profile = {"kind": "python-cli"}
    recommender = ProjectAdaptationRecommender(profile)
    skills = recommender.recommend_skills()
    assert "/selfcheck" in skills
    assert "/lint-backend" in skills


def test_project_adaptation_fastapi():
    profile = {"kind": "fastapi"}
    recommender = ProjectAdaptationRecommender(profile)
    skills = recommender.recommend_skills()
    assert "/lint-backend" in skills
    assert "/test-backend" in skills


def test_project_adaptation_full_stack():
    profile = {"kind": "full-stack"}
    recommender = ProjectAdaptationRecommender(profile)
    skills = recommender.recommend_skills()
    assert "/integration-test" in skills
    assert "/e2e-test" in skills


def test_project_adaptation_mcp_servers():
    profile = {"kind": "fastapi"}
    recommender = ProjectAdaptationRecommender(profile)
    mcp = recommender.recommend_mcp_servers()
    assert "GitHub" in mcp


def test_project_adaptation_settings_template():
    profile = {"kind": "python-cli"}
    recommender = ProjectAdaptationRecommender(profile)
    template = recommender.generate_settings_template()
    assert "model" in template
    assert "skills" in template
    assert "mcpServers" in template


def test_check_settings_ignores_non_object_json(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("[]")
    assert AccountCapabilitiesChecker().check_settings(p) == {}
