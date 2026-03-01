"""Tests for Charmhub publishing tools."""

import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from cantrip.agent.tools.publishing import (
    CharmcraftReleaseTool,
    CharmcraftUploadTool,
    GenerateReadmeTool,
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
