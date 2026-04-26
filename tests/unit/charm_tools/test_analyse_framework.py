"""Tests for AnalyseFrameworkTool."""

import pathlib
import tempfile

import pytest

from cantrip.agent.tools.charm import (
    AnalyseFrameworkTool,
)


class TestAnalyseFrameworkTool:
    """Tests for AnalyseFrameworkTool."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        with tempfile.TemporaryDirectory() as td:
            yield pathlib.Path(td)

    @pytest.fixture
    def tool(self):
        return AnalyseFrameworkTool()

    @pytest.mark.asyncio
    async def test_detect_flask(self, tool, temp_dir):
        """Detects Flask and returns the correct profile."""
        (temp_dir / "requirements.txt").write_text("flask>=3.0\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["framework"] == "flask"
        assert result.data["profile"] == "flask-framework"
        assert result.data["needs_experimental"] is False

    @pytest.mark.asyncio
    async def test_detect_express(self, tool, temp_dir):
        """Detects Express from package.json."""
        (temp_dir / "package.json").write_text('{"dependencies": {"express": "^4.18.0"}}')

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["framework"] == "express"
        assert result.data["profile"] == "express-framework"
        assert result.data["language"] == "javascript"

    @pytest.mark.asyncio
    async def test_detect_spring_boot_maven(self, tool, temp_dir):
        """Detects Spring Boot from pom.xml."""
        (temp_dir / "pom.xml").write_text(
            "<project><parent>"
            "<groupId>org.springframework.boot</groupId>"
            "<artifactId>spring-boot-starter-parent</artifactId>"
            "</parent></project>"
        )

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["framework"] == "spring-boot"
        assert result.data["profile"] == "spring-boot-framework"
        assert result.data["language"] == "java"

    @pytest.mark.asyncio
    async def test_detect_spring_boot_gradle(self, tool, temp_dir):
        """Detects Spring Boot from build.gradle.kts."""
        (temp_dir / "build.gradle.kts").write_text(
            'plugins { id("org.springframework.boot") version "3.2.0" }\n'
        )

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["framework"] == "spring-boot"
        assert result.data["language"] == "java"

    @pytest.mark.asyncio
    async def test_profile_returned_for_django(self, tool, temp_dir):
        """Returns the correct profile for Django."""
        (temp_dir / "requirements.txt").write_text("django>=4.2\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.data["profile"] == "django-framework"

    @pytest.mark.asyncio
    async def test_needs_experimental_for_go(self, tool, temp_dir):
        """Reports needs_experimental for Go."""
        (temp_dir / "go.mod").write_text("module example.com/myapp\n\ngo 1.21\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.data["framework"] == "go"
        assert result.data["needs_experimental"] is True

    @pytest.mark.asyncio
    async def test_needs_experimental_for_fastapi(self, tool, temp_dir):
        """Reports needs_experimental for FastAPI."""
        (temp_dir / "requirements.txt").write_text("fastapi>=0.100\nuvicorn\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.data["framework"] == "fastapi"
        assert result.data["needs_experimental"] is True

    @pytest.mark.asyncio
    async def test_suggestion_includes_skill_hint(self, tool, temp_dir):
        """Suggestion text mentions the twelve-factor skill."""
        (temp_dir / "requirements.txt").write_text("flask\n")

        result = await tool.execute(path=str(temp_dir))

        assert "twelve-factor" in result.output.lower()

    @pytest.mark.asyncio
    async def test_unknown_framework(self, tool, temp_dir):
        """Returns no profile for an unknown codebase."""
        (temp_dir / "main.rs").write_text("fn main() {}")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["framework"] is None
        assert result.data["profile"] is None

    @pytest.mark.asyncio
    async def test_nodejs_without_express(self, tool, temp_dir):
        """Node.js without Express has no framework profile."""
        (temp_dir / "package.json").write_text('{"dependencies": {"next": "^14.0.0"}}')

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["language"] == "javascript"
        assert result.data["framework"] is None
        assert result.data["profile"] is None

    @pytest.mark.asyncio
    async def test_custom_app_detects_dockerfile(self, tool, temp_dir):
        """Dockerfile present with no framework suggests K8s substrate."""
        (temp_dir / "Dockerfile").write_text("FROM ubuntu:22.04\nCMD /app\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        hints = result.data["workload_hints"]
        assert hints["has_dockerfile"] is True
        assert hints["suggested_substrate"] == "k8s"

    @pytest.mark.asyncio
    async def test_custom_app_detects_systemd(self, tool, temp_dir):
        """Systemd service file present suggests machine substrate."""
        (temp_dir / "my-app.service").write_text("[Unit]\nDescription=My App\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        hints = result.data["workload_hints"]
        assert hints["has_systemd"] is True
        assert hints["suggested_substrate"] == "machine"

    @pytest.mark.asyncio
    async def test_custom_app_detects_docker_compose(self, tool, temp_dir):
        """Docker-compose file is detected in workload hints."""
        (temp_dir / "docker-compose.yml").write_text("services:\n  app:\n    build: .\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        hints = result.data["workload_hints"]
        assert hints["has_docker_compose"] is True

    @pytest.mark.asyncio
    async def test_custom_app_suggests_custom_charm_skill(self, tool, temp_dir):
        """No framework detected mentions custom-charm skill."""
        (temp_dir / "main.rs").write_text("fn main() {}")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert "custom-charm" in result.output.lower()

    @pytest.mark.asyncio
    async def test_custom_app_workload_hints_structure(self, tool, temp_dir):
        """Workload hints dict is present with all expected keys."""
        (temp_dir / "main.c").write_text("int main() { return 0; }")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        hints = result.data["workload_hints"]
        assert "has_dockerfile" in hints
        assert "has_docker_compose" in hints
        assert "has_systemd" in hints
        assert "has_config_files" in hints
        assert "suggested_substrate" in hints
