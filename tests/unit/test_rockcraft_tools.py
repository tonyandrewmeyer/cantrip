"""Tests for rockcraft and OCI registry tools."""

import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from cantrip.agent.tools.rockcraft import (
    RockcraftInitTool,
    RockcraftPackTool,
    SkopeoRegistryPushTool,
)


class TestRockcraftInitTool:
    """Tests for RockcraftInitTool."""

    @pytest.fixture
    def tool(self):
        return RockcraftInitTool()

    @pytest.mark.asyncio
    async def test_rockcraft_not_installed(self, tool):
        """Error when rockcraft is not on PATH."""
        with mock.patch("cantrip.agent.tools.rockcraft.shutil.which", return_value=None):
            result = await tool.execute(profile="flask-framework")

        assert not result.success
        assert "rockcraft not found" in result.error

    @pytest.mark.asyncio
    async def test_init_success(self, tool):
        """Runs rockcraft init successfully."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Created rockcraft.yaml.\n"
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                return_value="/usr/bin/rockcraft",
            ),
            mock.patch(
                "cantrip.agent.tools.rockcraft.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(profile="flask-framework", path="/tmp/test")

        assert result.success
        assert result.data["profile"] == "flask-framework"
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == ["rockcraft", "init", "--profile=flask-framework"]

    @pytest.mark.asyncio
    async def test_init_failure(self, tool):
        """Reports error when rockcraft init fails."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "unknown profile"

        with (
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                return_value="/usr/bin/rockcraft",
            ),
            mock.patch(
                "cantrip.agent.tools.rockcraft.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(profile="flask-framework")

        assert not result.success
        assert "unknown profile" in result.error

    @pytest.mark.asyncio
    async def test_init_timeout(self, tool):
        """Reports error on timeout."""
        with (
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                return_value="/usr/bin/rockcraft",
            ),
            mock.patch(
                "cantrip.agent.tools.rockcraft.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="rockcraft", timeout=60),
            ),
        ):
            result = await tool.execute(profile="flask-framework")

        assert not result.success
        assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_experimental_flag_for_go(self, tool):
        """Sets ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS for go-framework."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Created rockcraft.yaml.\n"
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                return_value="/usr/bin/rockcraft",
            ),
            mock.patch(
                "cantrip.agent.tools.rockcraft.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(profile="go-framework")

        assert result.success
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["env"]["ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS"] == "true"

    @pytest.mark.asyncio
    async def test_experimental_flag_for_express(self, tool):
        """Sets ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS for express-framework."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                return_value="/usr/bin/rockcraft",
            ),
            mock.patch(
                "cantrip.agent.tools.rockcraft.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(profile="express-framework")

        assert result.success
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["env"]["ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS"] == "true"

    @pytest.mark.asyncio
    async def test_no_experimental_flag_for_flask(self, tool):
        """Does not set ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS for flask-framework."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                return_value="/usr/bin/rockcraft",
            ),
            mock.patch(
                "cantrip.agent.tools.rockcraft.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(profile="flask-framework")

        assert result.success
        call_kwargs = mock_run.call_args[1]
        assert "ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS" not in call_kwargs["env"]


class TestRockcraftPackTool:
    """Tests for RockcraftPackTool."""

    @pytest.fixture
    def tool(self):
        return RockcraftPackTool()

    @pytest.mark.asyncio
    async def test_rockcraft_not_installed(self, tool):
        """Error when rockcraft is not on PATH."""
        with mock.patch("cantrip.agent.tools.rockcraft.shutil.which", return_value=None):
            result = await tool.execute()

        assert not result.success
        assert "rockcraft not found" in result.error

    @pytest.mark.asyncio
    async def test_pack_success_with_rock_file(self, tool):
        """Packs and discovers the resulting .rock file."""
        with tempfile.TemporaryDirectory() as td:
            rock_file = Path(td) / "my-app_0.1_amd64.rock"
            rock_file.touch()

            mock_result = mock.MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "Packed my-app_0.1_amd64.rock\n"
            mock_result.stderr = ""

            with (
                mock.patch(
                    "cantrip.agent.tools.rockcraft.shutil.which",
                    return_value="/usr/bin/rockcraft",
                ),
                mock.patch(
                    "cantrip.agent.tools.rockcraft.subprocess.run",
                    return_value=mock_result,
                ),
            ):
                result = await tool.execute(path=td)

        assert result.success
        assert result.data["rock_file"] is not None
        assert "my-app_0.1_amd64.rock" in result.data["rock_file"]

    @pytest.mark.asyncio
    async def test_pack_success_no_rock_file(self, tool):
        """Succeeds but reports no rock file when none is found."""
        with tempfile.TemporaryDirectory() as td:
            mock_result = mock.MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "Done\n"
            mock_result.stderr = ""

            with (
                mock.patch(
                    "cantrip.agent.tools.rockcraft.shutil.which",
                    return_value="/usr/bin/rockcraft",
                ),
                mock.patch(
                    "cantrip.agent.tools.rockcraft.subprocess.run",
                    return_value=mock_result,
                ),
            ):
                result = await tool.execute(path=td)

        assert result.success
        assert result.data["rock_file"] is None

    @pytest.mark.asyncio
    async def test_pack_failure(self, tool):
        """Reports error when rockcraft pack fails."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "build failed"

        with (
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                return_value="/usr/bin/rockcraft",
            ),
            mock.patch(
                "cantrip.agent.tools.rockcraft.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute()

        assert not result.success
        assert "build failed" in result.error

    @pytest.mark.asyncio
    async def test_pack_timeout(self, tool):
        """Reports error on timeout."""
        with (
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                return_value="/usr/bin/rockcraft",
            ),
            mock.patch(
                "cantrip.agent.tools.rockcraft.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="rockcraft", timeout=600),
            ),
        ):
            result = await tool.execute()

        assert not result.success
        assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_pack_always_sets_experimental(self, tool):
        """Always sets ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                return_value="/usr/bin/rockcraft",
            ),
            mock.patch(
                "cantrip.agent.tools.rockcraft.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            await tool.execute()

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["env"]["ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS"] == "true"


class TestSkopeoRegistryPushTool:
    """Tests for SkopeoRegistryPushTool."""

    @pytest.fixture
    def tool(self):
        return SkopeoRegistryPushTool()

    @pytest.mark.asyncio
    async def test_skopeo_not_installed(self, tool):
        """Error when skopeo is not on PATH."""
        with mock.patch("cantrip.agent.tools.rockcraft.shutil.which", return_value=None):
            result = await tool.execute(rock_file="app.rock", image_name="my-app")

        assert not result.success
        assert "skopeo not found" in result.error

    @pytest.mark.asyncio
    async def test_rock_file_not_found(self, tool):
        """Error when the .rock file does not exist."""
        with mock.patch(
            "cantrip.agent.tools.rockcraft.shutil.which",
            return_value="/usr/bin/skopeo",
        ):
            result = await tool.execute(rock_file="/nonexistent/app.rock", image_name="my-app")

        assert not result.success
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_push_success(self, tool):
        """Pushes a rock to the registry."""
        with tempfile.NamedTemporaryFile(suffix=".rock") as tf:
            mock_result = mock.MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "Copying blob sha256:abc123\n"
            mock_result.stderr = ""

            with (
                mock.patch(
                    "cantrip.agent.tools.rockcraft.shutil.which",
                    return_value="/usr/bin/skopeo",
                ),
                mock.patch(
                    "cantrip.agent.tools.rockcraft.subprocess.run",
                    return_value=mock_result,
                ) as mock_run,
            ):
                result = await tool.execute(
                    rock_file=tf.name,
                    image_name="my-app",
                    registry="localhost:32000",
                    tag="0.1",
                )

            assert result.success
            assert result.data["image_url"] == "localhost:32000/my-app:0.1"

            call_args = mock_run.call_args[0][0]
            assert "skopeo" in call_args[0]
            assert "--dest-tls-verify=false" in call_args
            assert "docker://localhost:32000/my-app:0.1" in call_args[-1]

    @pytest.mark.asyncio
    async def test_push_failure(self, tool):
        """Reports error when skopeo push fails."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "connection refused"

        with (
            tempfile.NamedTemporaryFile(suffix=".rock") as tf,
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                return_value="/usr/bin/skopeo",
            ),
            mock.patch(
                "cantrip.agent.tools.rockcraft.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(rock_file=tf.name, image_name="my-app")

        assert not result.success
        assert "connection refused" in result.error

    @pytest.mark.asyncio
    async def test_push_timeout(self, tool):
        """Reports error on timeout."""
        with (
            tempfile.NamedTemporaryFile(suffix=".rock") as tf,
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                return_value="/usr/bin/skopeo",
            ),
            mock.patch(
                "cantrip.agent.tools.rockcraft.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="skopeo", timeout=120),
            ),
        ):
            result = await tool.execute(rock_file=tf.name, image_name="my-app")

        assert not result.success
        assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_push_default_registry_and_tag(self, tool):
        """Uses default registry and tag when not specified."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            tempfile.NamedTemporaryFile(suffix=".rock") as tf,
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                return_value="/usr/bin/skopeo",
            ),
            mock.patch(
                "cantrip.agent.tools.rockcraft.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(rock_file=tf.name, image_name="my-app")

        assert result.success
        assert result.data["image_url"] == "localhost:32000/my-app:latest"
