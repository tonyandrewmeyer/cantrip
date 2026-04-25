"""Tests for rockcraft and OCI registry tools."""

import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import httpx
import pytest

from cantrip.agent.tools.rockcraft import (
    LocalRegistryStatusTool,
    RegistryImageExistsTool,
    RegistryMirrorTool,
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
    async def test_experimental_flag_set_for_flask(self, tool):
        """Sets ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS even for flask.

        All rockcraft framework extensions (Flask, Django, FastAPI, Go,
        ExpressJS, Spring Boot) are flagged experimental upstream, so the
        wrapper sets the enable flag unconditionally — matching the shape
        of ``RockcraftPackTool``.
        """
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
        assert call_kwargs["env"]["ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS"] == "true"


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


class TestRegistryImageExistsTool:
    """Tests for RegistryImageExistsTool — short-circuits ImagePullBackOff."""

    @pytest.fixture
    def tool(self):
        return RegistryImageExistsTool()

    @pytest.mark.asyncio
    async def test_skopeo_not_installed(self, tool):
        """Error when skopeo is not on PATH."""
        with mock.patch("cantrip.agent.tools.rockcraft.shutil.which", return_value=None):
            result = await tool.execute(image_ref="docker.io/library/redis:7-alpine")

        assert not result.success
        assert "skopeo not found" in result.error

    @pytest.mark.asyncio
    async def test_image_exists_returns_metadata(self, tool):
        """Successful inspect returns digest, architecture, layer count."""
        manifest = {
            "Digest": "sha256:abcd1234",
            "Architecture": "amd64",
            "Created": "2026-01-01T00:00:00Z",
            "Layers": ["layer1", "layer2", "layer3"],
        }
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"Digest": "sha256:abcd1234", "Architecture": "amd64", "Created": "2026-01-01T00:00:00Z", "Layers": ["layer1", "layer2", "layer3"]}'  # noqa: E501
        mock_result.stderr = ""
        del manifest  # consumed via the JSON string above

        with (
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                return_value="/usr/bin/skopeo",
            ),
            mock.patch(
                "cantrip.agent.tools.rockcraft.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(image_ref="docker.io/library/redis:7-alpine")

        assert result.success
        assert result.data["exists"] is True
        assert result.data["digest"] == "sha256:abcd1234"
        assert result.data["architecture"] == "amd64"
        assert result.data["layers"] == 3

    @pytest.mark.asyncio
    async def test_strips_docker_prefix(self, tool):
        """Accepts ``docker://...`` refs and feeds them as bare to skopeo."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "{}"
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
            await tool.execute(image_ref="docker://docker.io/library/redis:7")

        argv = mock_run.call_args[0][0]
        assert "docker://docker.io/library/redis:7" in argv
        # Make sure we didn't accidentally end up with a double prefix.
        assert "docker://docker://docker.io/library/redis:7" not in argv

    @pytest.mark.asyncio
    async def test_localhost_auto_insecure(self, tool):
        """Localhost references auto-enable ``--tls-verify=false``."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "{}"
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
            await tool.execute(image_ref="localhost:32000/my-app:latest")

        argv = mock_run.call_args[0][0]
        assert "--tls-verify=false" in argv

    @pytest.mark.asyncio
    async def test_image_not_found_reports_clear_error(self, tool):
        """``manifest unknown`` from skopeo surfaces verbatim."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "manifest unknown\n"

        with (
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                return_value="/usr/bin/skopeo",
            ),
            mock.patch(
                "cantrip.agent.tools.rockcraft.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(image_ref="docker.io/library/nonexistent:99")

        assert not result.success
        assert "manifest unknown" in result.error
        assert result.data["exists"] is False


class TestRegistryMirrorTool:
    """Tests for RegistryMirrorTool — copy from public to local registry."""

    @pytest.fixture
    def tool(self):
        return RegistryMirrorTool()

    @pytest.mark.asyncio
    async def test_skopeo_not_installed(self, tool):
        with mock.patch("cantrip.agent.tools.rockcraft.shutil.which", return_value=None):
            result = await tool.execute(source="docker.io/library/redis:7-alpine")

        assert not result.success
        assert "skopeo not found" in result.error

    @pytest.mark.asyncio
    async def test_default_target_derived_from_source(self, tool):
        """No ``target`` → mirror to ``localhost:32000/<basename>``."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
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
            result = await tool.execute(source="docker.io/library/redis:7-alpine")

        assert result.success
        assert result.data["target"] == "localhost:32000/redis:7-alpine"
        argv = mock_run.call_args[0][0]
        assert "docker://docker.io/library/redis:7-alpine" in argv
        assert "docker://localhost:32000/redis:7-alpine" in argv
        # Local target → dest TLS verification off.
        assert "--dest-tls-verify=false" in argv
        # Public source → src TLS verification on (no flag).
        assert "--src-tls-verify=false" not in argv

    @pytest.mark.asyncio
    async def test_default_tag_when_source_has_none(self, tool):
        """``source: nginx`` (no tag) defaults to ``latest`` on target."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                return_value="/usr/bin/skopeo",
            ),
            mock.patch(
                "cantrip.agent.tools.rockcraft.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(source="docker.io/library/nginx")

        assert result.data["target"] == "localhost:32000/nginx:latest"

    @pytest.mark.asyncio
    async def test_explicit_target_used_verbatim(self, tool):
        """``target='ghcr.io/...'`` overrides the default localhost target."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
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
                source="docker.io/library/redis:7",
                target="ghcr.io/me/redis:7",
            )

        assert result.data["target"] == "ghcr.io/me/redis:7"
        argv = mock_run.call_args[0][0]
        # No insecure flags — both ends are real registries with TLS.
        assert "--src-tls-verify=false" not in argv
        assert "--dest-tls-verify=false" not in argv

    @pytest.mark.asyncio
    async def test_failure_surfaces_skopeo_stderr(self, tool):
        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "unauthorized: access denied"

        with (
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                return_value="/usr/bin/skopeo",
            ),
            mock.patch(
                "cantrip.agent.tools.rockcraft.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(source="ghcr.io/private/image:1")

        assert not result.success
        assert "unauthorized" in result.error


class TestLocalRegistryStatusTool:
    """Tests for LocalRegistryStatusTool — substrate-aware probe."""

    @pytest.fixture
    def tool(self):
        return LocalRegistryStatusTool()

    @pytest.mark.asyncio
    async def test_registry_reachable_http(self, tool):
        """200 on ``/v2/`` → registry is alive."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_client = mock.MagicMock()
        mock_client.__enter__ = mock.MagicMock(return_value=mock_client)
        mock_client.__exit__ = mock.MagicMock(return_value=False)
        mock_client.get = mock.MagicMock(return_value=mock_response)

        with (
            mock.patch("cantrip.agent.tools.rockcraft.httpx.Client", return_value=mock_client),
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                side_effect=lambda b: "/snap/bin/microk8s" if b == "microk8s" else None,
            ),
        ):
            result = await tool.execute()

        assert result.success
        assert result.data["available"] is True
        assert result.data["substrate_hint"] == "microk8s"
        assert result.data["scheme"] == "http"

    @pytest.mark.asyncio
    async def test_registry_reachable_via_https_fallback(self, tool):
        """HTTP fails, HTTPS returns 401 → still considered reachable."""
        responses = [httpx.ConnectError("nope"), mock.MagicMock(status_code=401)]
        mock_client = mock.MagicMock()
        mock_client.__enter__ = mock.MagicMock(return_value=mock_client)
        mock_client.__exit__ = mock.MagicMock(return_value=False)

        def _get(_url):
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        mock_client.get = _get

        with (
            mock.patch("cantrip.agent.tools.rockcraft.httpx.Client", return_value=mock_client),
            mock.patch("cantrip.agent.tools.rockcraft.shutil.which", return_value=None),
        ):
            result = await tool.execute()

        assert result.success
        assert result.data["scheme"] == "https"

    @pytest.mark.asyncio
    async def test_no_registry_on_k8s_snap_explains_alternatives(self, tool):
        """k8s snap with no registry → error names the three options."""
        mock_client = mock.MagicMock()
        mock_client.__enter__ = mock.MagicMock(return_value=mock_client)
        mock_client.__exit__ = mock.MagicMock(return_value=False)
        mock_client.get = mock.MagicMock(side_effect=httpx.ConnectError("no host"))

        with (
            mock.patch("cantrip.agent.tools.rockcraft.httpx.Client", return_value=mock_client),
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                side_effect=lambda b: "/snap/bin/k8s" if b == "k8s" else None,
            ),
        ):
            result = await tool.execute()

        assert not result.success
        assert result.data["available"] is False
        assert result.data["substrate_hint"] == "k8s"
        # Surfaces all three escape hatches.
        assert "ghcr.io" in result.error or "public registry" in result.error
        assert "registry-k8s" in result.error or "registry charm" in result.error
        assert "ctr images import" in result.error

    @pytest.mark.asyncio
    async def test_no_registry_on_microk8s_suggests_enabling_addon(self, tool):
        """microk8s with the registry add-on disabled → suggest enabling it."""
        mock_client = mock.MagicMock()
        mock_client.__enter__ = mock.MagicMock(return_value=mock_client)
        mock_client.__exit__ = mock.MagicMock(return_value=False)
        mock_client.get = mock.MagicMock(side_effect=httpx.ConnectError("no host"))

        with (
            mock.patch("cantrip.agent.tools.rockcraft.httpx.Client", return_value=mock_client),
            mock.patch(
                "cantrip.agent.tools.rockcraft.shutil.which",
                side_effect=lambda b: "/snap/bin/microk8s" if b == "microk8s" else None,
            ),
        ):
            result = await tool.execute()

        assert not result.success
        assert "microk8s enable registry" in result.error
