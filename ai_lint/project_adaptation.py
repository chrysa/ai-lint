"""Adapt config recommendations based on project profile."""

from __future__ import annotations


class ProjectAdaptationRecommender:
    """Generate config recommendations based on detected project profile."""

    def __init__(self, profile: dict) -> None:
        """Initialize with project profile from ProjectProfiler."""
        self.profile = profile

    def recommend_skills(self) -> list[str]:
        """Recommend skills based on project type."""
        recommendations = []
        kind = self.profile.get("kind", "unknown")

        if kind == "python-cli":
            recommendations.extend(["/selfcheck", "/lint-backend", "/test-backend"])
        elif kind == "fastapi":
            recommendations.extend(["/lint-backend", "/test-backend", "/type-check"])
        elif kind == "react":
            recommendations.extend(["/lint-frontend", "/type-check-frontend"])
        elif kind == "full-stack":
            recommendations.extend(
                [
                    "/lint-backend",
                    "/lint-frontend",
                    "/integration-test",
                    "/e2e-test",
                ]
            )
        return recommendations

    def recommend_mcp_servers(self) -> list[str]:
        """Recommend MCP servers based on project type."""
        recommendations = []
        kind = self.profile.get("kind", "unknown")

        # GitHub for all code projects
        if kind != "unknown":
            recommendations.append("GitHub")

        # Add optional monitoring for backends
        if kind in ("fastapi", "full-stack", "django"):
            recommendations.append("Sentry (optional)")

        return recommendations

    def recommend_hooks(self) -> dict[str, str]:
        """Recommend hook patterns based on project."""
        hooks = {}
        kind = self.profile.get("kind", "unknown")

        if kind in ("python-cli", "fastapi", "django"):
            hooks["PreToolUse"] = "ruff format on file edits"

        if kind in ("react", "full-stack"):
            hooks["PostToolUse"] = "eslint + prettier on JS/TS edits"

        return hooks

    def generate_settings_template(self) -> dict:
        """Generate recommended settings.json structure."""
        return {
            "model": "sonnet",  # matches the tokens.preferred_model default
            "hooks": self.recommend_hooks(),
            "skills": self.recommend_skills(),
            "mcpServers": {srv: {} for srv in self.recommend_mcp_servers()},
        }
