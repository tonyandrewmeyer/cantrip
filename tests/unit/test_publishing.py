"""Tests for Charmhub publishing tools."""

import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from cantrip.agent.tools.publishing import (
    CharmcraftReleaseTool,
    CharmcraftUploadTool,
    GenerateIconTool,
    GenerateReadmeTool,
    generate_placeholder_svg,
)


class TestCharmcraftUploadTool:
    """Tests for CharmcraftUploadTool."""

    @pytest.fixture
    def tool(self):
        return CharmcraftUploadTool()

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.mark.asyncio
    async def test_unconfirmed_returns_error(self, tool, temp_dir):
        """Upload without confirmed=True returns a confirmation prompt."""
        charm_file = temp_dir / "my-charm.charm"
        charm_file.write_bytes(b"fake")

        result = await tool.execute(charm_file=str(charm_file), confirmed=False)

        assert not result.success
        assert "confirmation" in result.error.lower()

    @pytest.mark.asyncio
    async def test_file_not_found(self, tool):
        """Upload with a non-existent file returns an error."""
        result = await tool.execute(charm_file="/nonexistent/path.charm", confirmed=True)

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_charmcraft_not_installed(self, tool, temp_dir):
        """Error when charmcraft is not on PATH."""
        charm_file = temp_dir / "my-charm.charm"
        charm_file.write_bytes(b"fake")

        with mock.patch("cantrip.agent.tools.publishing.shutil.which", return_value=None):
            result = await tool.execute(charm_file=str(charm_file), confirmed=True)

        assert not result.success
        assert "charmcraft not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_upload_success(self, tool, temp_dir):
        """Successful upload parses revision number."""
        charm_file = temp_dir / "my-charm.charm"
        charm_file.write_bytes(b"fake")

        with mock.patch(
            "cantrip.agent.tools.publishing.subprocess.run",
            return_value=mock.Mock(
                returncode=0,
                stdout="Revision 42 of 'my-charm' created",
                stderr="",
            ),
        ):
            result = await tool.execute(charm_file=str(charm_file), confirmed=True)

        assert result.success
        assert result.data["revision"] == 42
        assert "my-charm.charm" in result.data["charm_file"]

    @pytest.mark.asyncio
    async def test_upload_failure(self, tool, temp_dir):
        """Failed upload returns error."""
        charm_file = temp_dir / "my-charm.charm"
        charm_file.write_bytes(b"fake")

        with mock.patch(
            "cantrip.agent.tools.publishing.subprocess.run",
            return_value=mock.Mock(
                returncode=1,
                stdout="",
                stderr="upload failed: not registered",
            ),
        ):
            result = await tool.execute(charm_file=str(charm_file), confirmed=True)

        assert not result.success
        assert "not registered" in result.error

    @pytest.mark.asyncio
    async def test_upload_timeout(self, tool, temp_dir):
        """Timeout returns an error."""
        charm_file = temp_dir / "my-charm.charm"
        charm_file.write_bytes(b"fake")

        with mock.patch(
            "cantrip.agent.tools.publishing.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="charmcraft", timeout=120),
        ):
            result = await tool.execute(charm_file=str(charm_file), confirmed=True)

        assert not result.success
        assert "timed out" in result.error.lower()


class TestCharmcraftReleaseTool:
    """Tests for CharmcraftReleaseTool."""

    @pytest.fixture
    def tool(self):
        return CharmcraftReleaseTool()

    @pytest.mark.asyncio
    async def test_unconfirmed_returns_error(self, tool):
        """Release without confirmed=True returns a confirmation prompt."""
        result = await tool.execute(name="my-charm", revision=1, confirmed=False)

        assert not result.success
        assert "confirmation" in result.error.lower()

    @pytest.mark.asyncio
    async def test_charmcraft_not_installed(self, tool):
        """Error when charmcraft is not on PATH."""
        with mock.patch("cantrip.agent.tools.publishing.shutil.which", return_value=None):
            result = await tool.execute(name="my-charm", revision=1, confirmed=True)

        assert not result.success
        assert "charmcraft not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_release_success(self, tool):
        """Successful release returns data."""
        with mock.patch(
            "cantrip.agent.tools.publishing.subprocess.run",
            return_value=mock.Mock(
                returncode=0,
                stdout="Released.",
                stderr="",
            ),
        ):
            result = await tool.execute(
                name="my-charm", revision=5, channel="latest/edge", confirmed=True
            )

        assert result.success
        assert result.data["name"] == "my-charm"
        assert result.data["revision"] == 5
        assert result.data["channel"] == "latest/edge"

    @pytest.mark.asyncio
    async def test_release_with_resources(self, tool):
        """Release passes resource flags."""
        with mock.patch(
            "cantrip.agent.tools.publishing.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="Released.", stderr=""),
        ) as mock_run:
            result = await tool.execute(
                name="my-charm",
                revision=5,
                resources=["oci-image:3"],
                confirmed=True,
            )

        assert result.success
        cmd = mock_run.call_args[0][0]
        assert "--resource" in cmd
        assert "oci-image:3" in cmd

    @pytest.mark.asyncio
    async def test_release_failure(self, tool):
        """Failed release returns error."""
        with mock.patch(
            "cantrip.agent.tools.publishing.subprocess.run",
            return_value=mock.Mock(
                returncode=1,
                stdout="",
                stderr="revision not found",
            ),
        ):
            result = await tool.execute(name="my-charm", revision=99, confirmed=True)

        assert not result.success
        assert "revision not found" in result.error

    @pytest.mark.asyncio
    async def test_release_timeout(self, tool):
        """Timeout returns an error."""
        with mock.patch(
            "cantrip.agent.tools.publishing.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="charmcraft", timeout=120),
        ):
            result = await tool.execute(name="my-charm", revision=1, confirmed=True)

        assert not result.success
        assert "timed out" in result.error.lower()


class TestGenerateReadmeTool:
    """Tests for GenerateReadmeTool."""

    @pytest.fixture
    def tool(self):
        return GenerateReadmeTool()

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.mark.asyncio
    async def test_no_charmcraft_yaml(self, tool, temp_dir):
        """Error when charmcraft.yaml is missing."""
        result = await tool.execute(path=str(temp_dir))

        assert not result.success
        assert "charmcraft.yaml not found" in result.error

    @pytest.mark.asyncio
    async def test_generates_basic_readme(self, tool, temp_dir):
        """Generates README from minimal charmcraft.yaml."""
        (temp_dir / "charmcraft.yaml").write_text(
            "name: my-charm\ndescription: A test charm for testing.\n"
        )

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["charm_name"] == "my-charm"

        readme = (temp_dir / "README.md").read_text()
        assert "# my-charm" in readme
        assert "A test charm for testing." in readme
        assert "juju deploy my-charm" in readme
        assert "## Contributing" in readme

    @pytest.mark.asyncio
    async def test_generates_config_section(self, tool, temp_dir):
        """Config options are included in README."""
        (temp_dir / "charmcraft.yaml").write_text(
            "name: my-charm\n"
            "config:\n"
            "  options:\n"
            "    port:\n"
            "      type: int\n"
            "      description: Listening port\n"
            "      default: 8080\n"
        )

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        readme = (temp_dir / "README.md").read_text()
        assert "## Configuration" in readme
        assert "`port`" in readme
        assert "Listening port" in readme
        assert "8080" in readme

    @pytest.mark.asyncio
    async def test_generates_actions_section(self, tool, temp_dir):
        """Actions are included in README."""
        (temp_dir / "charmcraft.yaml").write_text(
            "name: my-charm\nactions:\n  backup:\n    description: Create a database backup\n"
        )

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        readme = (temp_dir / "README.md").read_text()
        assert "## Actions" in readme
        assert "`backup`" in readme
        assert "Create a database backup" in readme

    @pytest.mark.asyncio
    async def test_generates_integrations_section(self, tool, temp_dir):
        """Relations are included in README."""
        (temp_dir / "charmcraft.yaml").write_text(
            "name: my-charm\n"
            "requires:\n"
            "  database:\n"
            "    interface: postgresql\n"
            "provides:\n"
            "  metrics:\n"
            "    interface: prometheus-scrape\n"
        )

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        readme = (temp_dir / "README.md").read_text()
        assert "## Integrations" in readme
        assert "`database`" in readme
        assert "`postgresql`" in readme
        assert "`metrics`" in readme
        assert "`prometheus-scrape`" in readme

    @pytest.mark.asyncio
    async def test_handles_optional_files(self, tool, temp_dir):
        """Works when WORKLOAD.md and DESIGN.md are present."""
        (temp_dir / "charmcraft.yaml").write_text("name: my-charm\n")
        (temp_dir / "WORKLOAD.md").write_text("## Purpose\nA widget server.\n")
        (temp_dir / "DESIGN.md").write_text("## Substrate\nK8s.\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        readme = (temp_dir / "README.md").read_text()
        assert "WORKLOAD.md" in readme
        assert "DESIGN.md" in readme

    @pytest.mark.asyncio
    async def test_handles_invalid_yaml(self, tool, temp_dir):
        """Reports error on invalid YAML."""
        (temp_dir / "charmcraft.yaml").write_text("key: [\ninvalid:\n")

        result = await tool.execute(path=str(temp_dir))

        assert not result.success
        assert "parse" in result.error.lower()


# ===================================================================
# TestGeneratePlaceholderSvg
# ===================================================================


class TestGeneratePlaceholderSvg:
    """Tests for the generate_placeholder_svg function."""

    def test_produces_valid_svg(self) -> None:
        svg = generate_placeholder_svg("redis")
        assert svg.startswith("<?xml")
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_contains_initial(self) -> None:
        svg = generate_placeholder_svg("redis")
        assert ">R</text>" in svg

    def test_uses_uppercase_initial(self) -> None:
        svg = generate_placeholder_svg("my-charm")
        assert ">M</text>" in svg

    def test_empty_name_uses_question_mark(self) -> None:
        svg = generate_placeholder_svg("")
        assert ">?</text>" in svg

    def test_deterministic_colour(self) -> None:
        """Same charm name always produces the same colour."""
        svg1 = generate_placeholder_svg("redis")
        svg2 = generate_placeholder_svg("redis")
        assert svg1 == svg2

    def test_different_names_can_differ(self) -> None:
        """Different charm names may produce different colours."""
        svg_redis = generate_placeholder_svg("redis")
        svg_postgres = generate_placeholder_svg("postgres")
        # They could theoretically collide, but with 10 colours it's unlikely.
        assert svg_redis != svg_postgres

    def test_contains_circle(self) -> None:
        svg = generate_placeholder_svg("test")
        assert "<circle" in svg
        assert 'fill="' in svg


# ===================================================================
# TestGenerateIconTool
# ===================================================================


class TestGenerateIconTool:
    """Tests for GenerateIconTool."""

    @pytest.fixture
    def tool(self):
        return GenerateIconTool()

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.mark.asyncio
    async def test_generates_icon(self, tool, temp_dir) -> None:
        """Generates icon.svg in the charm directory."""
        result = await tool.execute(path=str(temp_dir), charm_name="my-charm")

        assert result.success
        assert (temp_dir / "icon.svg").exists()
        svg = (temp_dir / "icon.svg").read_text()
        assert ">M</text>" in svg

    @pytest.mark.asyncio
    async def test_reads_name_from_charmcraft_yaml(self, tool, temp_dir) -> None:
        """Falls back to charmcraft.yaml for the charm name."""
        (temp_dir / "charmcraft.yaml").write_text("name: redis-k8s\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        svg = (temp_dir / "icon.svg").read_text()
        assert ">R</text>" in svg
        assert result.data["charm_name"] == "redis-k8s"

    @pytest.mark.asyncio
    async def test_falls_back_to_directory_name(self, tool, temp_dir) -> None:
        """Falls back to directory name when no charmcraft.yaml exists."""
        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["charm_name"] == temp_dir.name

    @pytest.mark.asyncio
    async def test_nonexistent_directory(self, tool) -> None:
        """Returns error for a nonexistent directory."""
        result = await tool.execute(path="/nonexistent/path")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_explicit_name_overrides_yaml(self, tool, temp_dir) -> None:
        """Explicit charm_name parameter takes precedence."""
        (temp_dir / "charmcraft.yaml").write_text("name: redis-k8s\n")

        result = await tool.execute(path=str(temp_dir), charm_name="custom")

        assert result.success
        svg = (temp_dir / "icon.svg").read_text()
        assert ">C</text>" in svg
