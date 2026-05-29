"""Tests for Juju agent tools."""

import pathlib
from unittest import mock

import jubilant
import pytest

from cantrip.agent.tools.juju import (
    BundleDeployTool,
    CharmSyncTool,
    JujuAddModelTool,
    JujuConfigTool,
    JujuConsumeTool,
    JujuDeployTool,
    JujuDestroyModelTool,
    JujuDispatchTool,
    JujuOfferTool,
    JujuRefreshTool,
    JujuStatusTool,
    JujuTrustTool,
    JujuWaitTool,
    _agent_charm_dir,
    _is_k8s_model,
    _juju_available,
)


class TestJujuAvailable:
    """Tests for the juju_available helper."""

    def test_available(self):
        """Returns True when juju is on PATH."""
        with mock.patch("shutil.which", return_value="/usr/bin/juju"):
            assert _juju_available() is True

    def test_not_available(self):
        """Returns False when juju is not on PATH."""
        with mock.patch("shutil.which", return_value=None):
            assert _juju_available() is False


class TestJujuStatusTool:
    """Tests for JujuStatusTool."""

    @pytest.fixture
    def tool(self):
        return JujuStatusTool()

    @staticmethod
    def _fake_app(
        current: str,
        message: str = "",
        units: dict[str, mock.MagicMock] | None = None,
    ) -> mock.MagicMock:
        app = mock.MagicMock()
        app.app_status.current = current
        app.app_status.message = message
        app.units = units or {}
        return app

    @staticmethod
    def _fake_unit(current: str, message: str = "") -> mock.MagicMock:
        unit = mock.MagicMock()
        unit.workload_status.current = current
        unit.workload_status.message = message
        return unit

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=False):
            result = await tool.execute()

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_status_message_in_output(self, tool):
        """Blocked status message ('Run `juju trust ...`') is surfaced verbatim.

        Without the message, the agent has no way to know it should call
        ``juju_trust`` to unblock the app.
        """
        fake_status = mock.MagicMock()
        fake_status.model.name = "testing"
        mysql_app = self._fake_app(
            current="blocked",
            message="Run `juju trust mysql --scope=cluster`. Needed for in-place refreshes",
            units={"mysql/0": self._fake_unit("unknown")},
        )
        fake_status.apps = {"mysql": mysql_app}

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant") as fake_jubilant,
        ):
            fake_jubilant.Juju.return_value.status = mock.MagicMock(return_value=fake_status)
            fake_jubilant.CLIError = jubilant.CLIError
            fake_jubilant.TaskError = jubilant.TaskError
            result = await tool.execute()

        assert result.success
        assert "Run `juju trust mysql --scope=cluster`" in result.output
        assert "App: mysql (blocked)" in result.output

    @pytest.mark.asyncio
    async def test_unit_message_in_output(self, tool):
        """Per-unit workload messages also render in the output."""
        fake_status = mock.MagicMock()
        fake_status.model.name = "testing"
        app = self._fake_app(
            current="active",
            units={"booklore/0": self._fake_unit("waiting", "installing agent")},
        )
        fake_status.apps = {"booklore": app}

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant") as fake_jubilant,
        ):
            fake_jubilant.Juju.return_value.status = mock.MagicMock(return_value=fake_status)
            fake_jubilant.CLIError = jubilant.CLIError
            fake_jubilant.TaskError = jubilant.TaskError
            result = await tool.execute()

        assert result.success
        assert "booklore/0: waiting — installing agent" in result.output

    @pytest.mark.asyncio
    async def test_no_message_no_dash(self, tool):
        """When status has no message, the em-dash separator is omitted."""
        fake_status = mock.MagicMock()
        fake_status.model.name = "testing"
        app = self._fake_app(current="active", units={"redis/0": self._fake_unit("active")})
        fake_status.apps = {"redis": app}

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant") as fake_jubilant,
        ):
            fake_jubilant.Juju.return_value.status = mock.MagicMock(return_value=fake_status)
            fake_jubilant.CLIError = jubilant.CLIError
            fake_jubilant.TaskError = jubilant.TaskError
            result = await tool.execute()

        assert result.success
        assert "App: redis (active)\n" in result.output
        assert "—" not in result.output

    @pytest.mark.asyncio
    async def test_crash_shaped_clierror_writes_dump(
        self, tool, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A crash-shaped ``CLIError`` from Jubilant lands in diagnostics.log.

        Lets the user file an upstream juju bug with verbatim repro
        material (cmd, returncode, stdout, stderr) even after the
        agent's chat context has rolled over.
        """
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        monkeypatch.setattr(
            "cantrip.agent.tools.juju._common._juju_version",
            lambda: "juju 3.6.0",
        )

        crash = jubilant.CLIError(
            46,
            ["juju", "status"],
            "",
            "2026/04/26 01:37:44 cmd_run.go:178: oh no\n",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant") as fake_jubilant,
        ):
            fake_jubilant.Juju.return_value.status = mock.MagicMock(side_effect=crash)
            fake_jubilant.CLIError = jubilant.CLIError
            fake_jubilant.TaskError = jubilant.TaskError
            result = await tool.execute()

        assert not result.success
        log_file = tmp_path / "cantrip" / "diagnostics.log"
        assert log_file.exists()
        body = log_file.read_text(encoding="utf-8")
        assert "jubilant:" in body
        assert "exit 46" in body
        assert "cmd_run.go" in body
        assert "juju 3.6.0" in body


class TestJujuAddModelTool:
    """Tests for JujuAddModelTool."""

    @pytest.fixture
    def tool(self):
        return JujuAddModelTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=False):
            result = await tool.execute(model="dev")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_add_model_success(self, tool):
        """Creates a model successfully."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(model="dev")

        assert result.success
        assert result.data["model"] == "dev"
        mock_juju.add_model.assert_called_once_with("dev", cloud=None)

    @pytest.mark.asyncio
    async def test_add_model_error(self, tool):
        """Reports CLI errors."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.add_model.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "add-model"],
            stderr="model already exists",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(model="dev")

        assert not result.success
        assert "already exists" in result.error


class TestJujuDestroyModelTool:
    """Tests for JujuDestroyModelTool."""

    @pytest.fixture(autouse=True)
    def _local_controller(self):
        """Phase 10b: bypass the controller-safety gate for tests that target
        the underlying juju logic, not the gate itself."""
        with mock.patch(
            "cantrip.agent.tools.juju._common.controller_confirm_required",
            return_value=(False, ""),
        ) as patched:
            yield patched

    @pytest.fixture
    def tool(self):
        return JujuDestroyModelTool()

    @pytest.fixture
    def _approve_destructive(self):
        """Phase 80.5: bypass the destructive gate for tests that target the
        underlying juju logic, not the gate itself."""
        with mock.patch(
            "cantrip.agent.policy.policy.destructive_gate",
            return_value=(True, ""),
        ) as patched:
            yield patched

    @pytest.mark.asyncio
    async def test_destructive_gate_blocks_by_default(self, tool, tmp_path, monkeypatch):
        """Phase 80.5: without approve_destructive anywhere, the tool refuses.

        The gate fires *before* the Juju CLI check, so a missing
        juju binary still yields the policy error — that's the
        defence-in-depth shape we want.
        """
        # Point the policy discovery at an empty directory so the test
        # is deterministic regardless of what's in $HOME.
        monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
        result = await tool.execute(model="dev")

        assert not result.success
        assert "approve_destructive" in result.error
        assert "juju_destroy_model" in result.error

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool, _approve_destructive):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=False):
            result = await tool.execute(model="dev")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_destroy_model_success(self, tool, _approve_destructive):
        """Destroys a model successfully."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(model="dev")

        assert result.success
        assert result.data["model"] == "dev"
        mock_juju.destroy_model.assert_called_once_with(
            "dev",
            force=False,
            destroy_storage=True,
            no_wait=False,
        )

    @pytest.mark.asyncio
    async def test_destroy_model_force(self, tool, _approve_destructive):
        """Passes force and no_wait when force=True."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(model="dev", force=True)

        assert result.success
        mock_juju.destroy_model.assert_called_once_with(
            "dev",
            force=True,
            destroy_storage=True,
            no_wait=True,
        )

    @pytest.mark.asyncio
    async def test_destroy_model_error(self, tool, _approve_destructive):
        """Reports CLI errors."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.destroy_model.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "destroy-model"],
            stderr="model not found",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(model="nonexistent")

        assert not result.success
        assert "not found" in result.error


class TestJujuOfferTool:
    """Tests for JujuOfferTool."""

    @pytest.fixture
    def tool(self):
        return JujuOfferTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=False):
            result = await tool.execute(app="grafana", endpoint="grafana-dashboard")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_offer_success(self, tool):
        """Creates an offer successfully."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app="grafana", endpoint="grafana-dashboard", model="cos")

        assert result.success
        assert "grafana:grafana-dashboard" in result.output
        mock_juju.offer.assert_called_once_with("grafana", endpoint="grafana-dashboard")

    @pytest.mark.asyncio
    async def test_offer_error(self, tool):
        """Reports CLI errors."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.offer.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "offer"],
            stderr="endpoint not found",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app="grafana", endpoint="bad-endpoint")

        assert not result.success
        assert "endpoint not found" in result.error


class TestJujuConsumeTool:
    """Tests for JujuConsumeTool."""

    @pytest.fixture
    def tool(self):
        return JujuConsumeTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=False):
            result = await tool.execute(model_and_app="cos.grafana")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_consume_success(self, tool):
        """Consumes an offer successfully."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(model_and_app="cos.grafana")

        assert result.success
        assert "grafana" in result.output
        mock_juju.consume.assert_called_once_with("cos.grafana", None)

    @pytest.mark.asyncio
    async def test_consume_with_alias(self, tool):
        """Consumes an offer with a local alias."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(
                model_and_app="cos.grafana",
                alias="cos-grafana",
                model="dev",
            )

        assert result.success
        assert "cos-grafana" in result.output
        mock_juju.consume.assert_called_once_with("cos.grafana", "cos-grafana")

    @pytest.mark.asyncio
    async def test_consume_error(self, tool):
        """Reports CLI errors."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.consume.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "consume"],
            stderr="offer not found",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(model_and_app="cos.nonexistent")

        assert not result.success
        assert "offer not found" in result.error


class TestJujuDeployTool:
    """Tests for JujuDeployTool resources and trust parameters."""

    @pytest.fixture(autouse=True)
    def _local_controller(self):
        """Phase 10b: bypass the controller-safety gate so these tests target
        the underlying deploy logic rather than the gate."""
        with mock.patch(
            "cantrip.agent.tools.juju._common.controller_confirm_required",
            return_value=(False, ""),
        ) as patched:
            yield patched

    @pytest.fixture
    def tool(self):
        return JujuDeployTool()

    @pytest.mark.asyncio
    async def test_deploy_with_resources(self, tool):
        """Passes resources to Jubilant deploy."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(
                charm="./my-app.charm",
                resources={"oci-image": "localhost:32000/my-app:latest"},
            )

        assert result.success
        mock_juju.deploy.assert_called_once()
        call_kwargs = mock_juju.deploy.call_args[1]
        assert call_kwargs["resources"] == {"oci-image": "localhost:32000/my-app:latest"}

    @pytest.mark.asyncio
    async def test_deploy_with_trust(self, tool):
        """Passes trust=True to Jubilant deploy."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(charm="traefik-k8s", trust=True)

        assert result.success
        mock_juju.deploy.assert_called_once()
        call_kwargs = mock_juju.deploy.call_args[1]
        assert call_kwargs["trust"] is True

    @pytest.mark.asyncio
    async def test_deploy_without_resources_or_trust(self, tool):
        """Does not pass resources or trust when not specified."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(charm="my-charm")

        assert result.success
        mock_juju.deploy.assert_called_once()
        call_kwargs = mock_juju.deploy.call_args[1]
        assert "resources" not in call_kwargs
        assert "trust" not in call_kwargs


class TestBundleDeployTool:
    """Tests for BundleDeployTool — legacy bundle consumption path."""

    @pytest.fixture
    def tool(self):
        return BundleDeployTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool, tmp_path):
        bundle = tmp_path / "bundle.yaml"
        bundle.write_text("bundle: kubernetes\napplications: {}\n")
        with mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=False):
            result = await tool.execute(path=str(bundle))
        assert not result.success
        assert "Juju CLI not found" in result.error

    @pytest.mark.asyncio
    async def test_missing_bundle_fails_fast(self, tool, tmp_path):
        """The tool refuses to dispatch if the bundle path does not exist."""
        missing = tmp_path / "does-not-exist.yaml"
        with mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True):
            result = await tool.execute(path=str(missing))
        assert not result.success
        assert "Bundle file not found" in result.error

    @pytest.mark.asyncio
    async def test_missing_overlay_fails_fast(self, tool, tmp_path):
        """A missing overlay path is reported before dispatching deploy."""
        bundle = tmp_path / "bundle.yaml"
        bundle.write_text("bundle: kubernetes\napplications: {}\n")
        missing_overlay = tmp_path / "overlays" / "missing.yaml"
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(path=str(bundle), overlays=[str(missing_overlay)])
        assert not result.success
        assert "Overlay file not found" in result.error
        mock_juju.deploy.assert_not_called()

    @pytest.mark.asyncio
    async def test_bundle_deploy_success(self, tool, tmp_path):
        """A valid bundle is passed through to ``jubilant.Juju.deploy``."""
        bundle = tmp_path / "bundle.yaml"
        bundle.write_text("bundle: kubernetes\napplications: {}\n")
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(path=str(bundle))
        assert result.success
        mock_juju.deploy.assert_called_once()
        call_kwargs = mock_juju.deploy.call_args[1]
        assert call_kwargs["charm"] == str(bundle.resolve())
        assert "overlays" not in call_kwargs
        assert "trust" not in call_kwargs

    @pytest.mark.asyncio
    async def test_bundle_deploy_with_overlays_and_trust(self, tool, tmp_path):
        """Overlay paths and trust flow through to ``Juju.deploy``."""
        bundle = tmp_path / "bundle.yaml"
        bundle.write_text("bundle: kubernetes\napplications: {}\n")
        overlay_a = tmp_path / "overlay-a.yaml"
        overlay_a.write_text("applications: {}\n")
        overlay_b = tmp_path / "overlay-b.yaml"
        overlay_b.write_text("applications: {}\n")
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(
                path=str(bundle),
                overlays=[str(overlay_a), str(overlay_b)],
                trust=True,
            )
        assert result.success
        call_kwargs = mock_juju.deploy.call_args[1]
        assert call_kwargs["trust"] is True
        assert call_kwargs["overlays"] == [
            str(overlay_a.resolve()),
            str(overlay_b.resolve()),
        ]
        # Output should mention the overlay count so the user sees both applied.
        assert "2 overlay" in result.output

    @pytest.mark.asyncio
    async def test_bundle_deploy_cli_error_surfaces(self, tool, tmp_path):
        """Jubilant CLI errors surface as an unsuccessful ToolResult."""
        bundle = tmp_path / "bundle.yaml"
        bundle.write_text("bundle: kubernetes\napplications: {}\n")
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.deploy.side_effect = jubilant.CLIError(
            returncode=1, cmd=["juju", "deploy"], stderr="bundle syntax error"
        )
        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(path=str(bundle))
        assert not result.success
        assert "bundle syntax error" in result.error


class TestJujuDeploySnapConfinement:
    """Tests for snap confinement workaround in JujuDeployTool."""

    @pytest.fixture(autouse=True)
    def _local_controller(self):
        """Phase 10b: bypass the controller-safety gate so these tests target
        the snap-confinement logic rather than the gate."""
        with mock.patch(
            "cantrip.agent.tools.juju._common.controller_confirm_required",
            return_value=(False, ""),
        ) as patched:
            yield patched

    @pytest.fixture
    def tool(self):
        return JujuDeployTool()

    @pytest.mark.asyncio
    async def test_copies_charm_from_tmp_to_snap_dir(self, tool, tmp_path):
        """A .charm file outside $HOME is copied to ~/snap/juju/common/."""
        # Create a fake .charm file in /tmp.
        charm_file = tmp_path / "test.charm"
        charm_file.write_text("fake")

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        home = tmp_path / "fake_home"
        home.mkdir()

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
            mock.patch("cantrip.agent.tools.juju._common.pathlib.Path.home", return_value=home),
        ):
            result = await tool.execute(charm=str(charm_file))

        assert result.success
        # The deploy should have used the snap-accessible copy.
        call_kwargs = mock_juju.deploy.call_args[1]
        deployed_path = call_kwargs["charm"]
        assert "snap/juju/common" in deployed_path

    @pytest.mark.asyncio
    async def test_no_copy_when_inside_home(self, tool, tmp_path):
        """A .charm file inside $HOME is NOT copied."""
        charm_file = tmp_path / "test.charm"
        charm_file.write_text("fake")

        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
            mock.patch(
                "cantrip.agent.tools.juju._common.pathlib.Path.home", return_value=tmp_path
            ),
        ):
            result = await tool.execute(charm=str(charm_file))

        assert result.success
        call_kwargs = mock_juju.deploy.call_args[1]
        deployed_path = call_kwargs["charm"]
        assert "snap/juju/common" not in deployed_path

    @pytest.mark.asyncio
    async def test_temp_copy_cleaned_up_on_success(self, tool, tmp_path):
        """The temporary copy is removed after successful deploy."""
        charm_file = tmp_path / "test.charm"
        charm_file.write_text("fake")

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        home = tmp_path / "fake_home"
        home.mkdir()

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
            mock.patch("cantrip.agent.tools.juju._common.pathlib.Path.home", return_value=home),
        ):
            await tool.execute(charm=str(charm_file))

        snap_copy = home / "snap" / "juju" / "common" / "test.charm"
        assert not snap_copy.exists()

    @pytest.mark.asyncio
    async def test_temp_copy_cleaned_up_on_error(self, tool, tmp_path):
        """The temporary copy is removed even when deploy fails."""
        charm_file = tmp_path / "test.charm"
        charm_file.write_text("fake")

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.deploy.side_effect = jubilant.CLIError(1, "deploy failed")
        home = tmp_path / "fake_home"
        home.mkdir()

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
            mock.patch("cantrip.agent.tools.juju._common.pathlib.Path.home", return_value=home),
        ):
            result = await tool.execute(charm=str(charm_file))

        assert not result.success
        snap_copy = home / "snap" / "juju" / "common" / "test.charm"
        assert not snap_copy.exists()


class TestJujuRefreshTool:
    """Tests for JujuRefreshTool."""

    @pytest.fixture(autouse=True)
    def _local_controller(self):
        """Phase 10b: bypass the controller-safety gate so these tests target
        the underlying refresh logic rather than the gate."""
        with mock.patch(
            "cantrip.agent.tools.juju._common.controller_confirm_required",
            return_value=(False, ""),
        ) as patched:
            yield patched

    @pytest.fixture
    def tool(self):
        return JujuRefreshTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=False):
            result = await tool.execute(app_name="my-app")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_refresh_success(self, tool):
        """Refreshes a charm successfully."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="my-app", path="./my-app.charm")

        assert result.success
        assert "my-app" in result.output
        mock_juju.refresh.assert_called_once_with(app="my-app", path="./my-app.charm")

    @pytest.mark.asyncio
    async def test_refresh_with_resources(self, tool):
        """Passes resources to Jubilant refresh."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(
                app_name="my-app",
                path="./my-app.charm",
                resources={"oci-image": "localhost:32000/my-app:latest"},
            )

        assert result.success
        mock_juju.refresh.assert_called_once_with(
            app="my-app",
            path="./my-app.charm",
            resources={"oci-image": "localhost:32000/my-app:latest"},
        )

    @pytest.mark.asyncio
    async def test_refresh_without_resources(self, tool):
        """Does not pass resources when not specified."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="my-app")

        assert result.success
        mock_juju.refresh.assert_called_once_with(app="my-app")

    @pytest.mark.asyncio
    async def test_refresh_error(self, tool):
        """Reports CLI errors."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.refresh.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "refresh"],
            stderr="app not found",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="my-app")

        assert not result.success
        assert "app not found" in result.error

    @pytest.mark.asyncio
    async def test_refresh_resolves_relative_path(
        self, tool, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A relative ``./foo.charm`` is resolved to absolute before refresh.

        Mirrors deploy's snap-confinement handling: a juju snap running
        in strict confinement cannot follow ``./foo.charm`` because its
        cwd differs from the user's.  Pre-fix refresh passed the raw
        relative string straight through, so ``cantrip refresh
        ./mycharm.charm`` reliably failed with "file not found" inside
        the snap, even when the charm sat in the user's working dir.
        """
        # Real file under tmp_path; the test cd's into tmp_path so the
        # ``./mycharm.charm`` shape exists relative to cwd.
        charm_file = tmp_path / "mycharm.charm"
        charm_file.write_bytes(b"PK\x03\x04")  # zip magic — real refresh just opens.
        monkeypatch.chdir(tmp_path)
        # Pretend ``$HOME`` is somewhere else so the snap-copy branch
        # would trigger if the path stayed relative.
        monkeypatch.setenv("HOME", str(tmp_path))

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="my-app", path="./mycharm.charm")

        assert result.success
        # The path passed to jubilant.refresh must be the absolute path,
        # not the original ``./mycharm.charm``.
        kwargs = mock_juju.refresh.call_args.kwargs
        assert kwargs["app"] == "my-app"
        assert kwargs["path"] == str(charm_file.resolve())


class TestControllerSafetyGate:
    """Phase 10b: the controller-safety CONFIRM gate fires for non-local
    controllers across the mutating juju tools."""

    @pytest.mark.asyncio
    async def test_deploy_blocks_on_non_local_controller(self):
        """juju_deploy refuses without confirmed=true when the gate fires."""
        with mock.patch(
            "cantrip.agent.tools.juju._common.controller_confirm_required",
            return_value=(True, "REFUSE: non-local controller 'prod' (cloud='aws')."),
        ):
            result = await JujuDeployTool().execute(charm="my-charm")
        assert not result.success
        assert "non-local controller" in result.error
        assert "prod" in result.error

    @pytest.mark.asyncio
    async def test_deploy_passes_through_when_confirmed(self):
        """confirmed=true silences the gate and the tool proceeds."""
        gate_called = mock.MagicMock(return_value=(False, ""))
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        with (
            mock.patch(
                "cantrip.agent.tools.juju._common.controller_confirm_required",
                gate_called,
            ),
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await JujuDeployTool().execute(charm="my-charm", confirmed=True)
        assert result.success
        # The gate was called with confirmed=True so it short-circuited
        # without inspecting the controller.
        gate_called.assert_called_once_with("juju_deploy", model=None, confirmed=True)

    @pytest.mark.asyncio
    async def test_refresh_blocks_on_non_local_controller(self):
        from cantrip.agent.tools.juju import JujuRefreshTool

        with mock.patch(
            "cantrip.agent.tools.juju._common.controller_confirm_required",
            return_value=(True, "REFUSE: production controller 'prod'"),
        ):
            result = await JujuRefreshTool().execute(app_name="my-app")
        assert not result.success
        assert "production controller" in result.error

    @pytest.mark.asyncio
    async def test_relate_blocks_on_non_local_controller(self):
        from cantrip.agent.tools.juju import JujuRelateTool

        with mock.patch(
            "cantrip.agent.tools.juju._common.controller_confirm_required",
            return_value=(True, "REFUSE: non-local"),
        ):
            result = await JujuRelateTool().execute(app1="redis", app2="traefik")
        assert not result.success
        assert "non-local" in result.error

    @pytest.mark.asyncio
    async def test_destroy_model_blocks_on_non_local_controller(self):
        """The controller gate fires *before* the destructive policy gate so
        the operator sees the controller name in the refusal."""
        with mock.patch(
            "cantrip.agent.tools.juju._common.controller_confirm_required",
            return_value=(True, "REFUSE: production controller 'prod-aws'"),
        ):
            result = await JujuDestroyModelTool().execute(model="dev")
        assert not result.success
        assert "prod-aws" in result.error
        # The destructive gate's keyword shouldn't appear — the
        # controller gate fired first.
        assert "approve_destructive" not in result.error

    @pytest.mark.asyncio
    async def test_remove_application_blocks_on_non_local_controller(self):
        from cantrip.agent.tools.juju import JujuRemoveApplicationTool

        with mock.patch(
            "cantrip.agent.tools.juju._common.controller_confirm_required",
            return_value=(True, "REFUSE: non-local controller 'remote'"),
        ):
            result = await JujuRemoveApplicationTool().execute(app_name="redis")
        assert not result.success
        assert "remote" in result.error
        assert "approve_destructive" not in result.error


class TestJujuTrustTool:
    """Tests for JujuTrustTool."""

    @pytest.fixture
    def tool(self):
        return JujuTrustTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=False):
            result = await tool.execute(app_name="mongodb")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_trust_cluster_scope(self, tool):
        """Grants trust with a cluster scope for a Kubernetes charm."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="mongodb", scope="cluster")

        assert result.success
        assert "mongodb" in result.output
        assert "cluster" in result.output
        mock_juju.trust.assert_called_once_with(app="mongodb", remove=False, scope="cluster")

    @pytest.mark.asyncio
    async def test_trust_no_scope(self, tool):
        """Omits scope for machine-model charms."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="my-app")

        assert result.success
        mock_juju.trust.assert_called_once_with(app="my-app", remove=False)

    @pytest.mark.asyncio
    async def test_trust_remove(self, tool):
        """Revokes trust when remove=True."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="my-app", remove=True)

        assert result.success
        assert "Revoked" in result.output
        mock_juju.trust.assert_called_once_with(app="my-app", remove=True)

    @pytest.mark.asyncio
    async def test_trust_error(self, tool):
        """Reports CLI errors."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.trust.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "trust"],
            stderr="app not found",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="my-app", scope="cluster")

        assert not result.success
        assert "app not found" in result.error


class TestJujuConfigTool:
    """Tests for JujuConfigTool."""

    @pytest.fixture
    def tool(self):
        return JujuConfigTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=False):
            result = await tool.execute(app_name="my-app")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_get_config(self, tool):
        """Returns current config when values is omitted."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.config.return_value = {"port": "8080", "debug": "false"}

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="my-app")

        assert result.success
        assert "8080" in result.output
        mock_juju.config.assert_called_once_with("my-app", values=None)

    @pytest.mark.asyncio
    async def test_set_config(self, tool):
        """Sets config values when values is provided."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.config.return_value = None

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(
                app_name="my-app",
                values={"port": "9090"},
            )

        assert result.success
        assert "Config updated" in result.output
        mock_juju.config.assert_called_once_with("my-app", values={"port": "9090"})

    @pytest.mark.asyncio
    async def test_config_error(self, tool):
        """Reports CLI errors."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.config.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "config"],
            stderr="app not found",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="nonexistent")

        assert not result.success
        assert "app not found" in result.error


class TestJujuWaitTool:
    """Tests for JujuWaitTool."""

    @pytest.fixture
    def tool(self):
        return JujuWaitTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=False):
            result = await tool.execute(app_name="my-app")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_wait_success(self, tool):
        """Returns status when app reaches active/idle."""
        mock_unit = mock.MagicMock()
        mock_unit.workload_status.current = "active"
        mock_unit.agent_status.current = "idle"

        mock_app = mock.MagicMock()
        mock_app.app_status.current = "active"
        mock_app.units = {"my-app/0": mock_unit}

        mock_status = mock.MagicMock()
        mock_status.apps = {"my-app": mock_app}

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.wait.return_value = mock_status

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="my-app")

        assert result.success
        assert "active/idle" in result.output
        assert "my-app/0" in result.output
        mock_juju.wait.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_timeout(self, tool):
        """Reports timeout when app does not settle."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.wait.side_effect = TimeoutError()

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="my-app", timeout=60)

        assert not result.success
        assert "Timed out" in result.error
        assert "60" in result.error

    @pytest.mark.asyncio
    async def test_wait_error(self, tool):
        """Reports CLI errors."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.wait.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "status"],
            stderr="model not found",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="my-app")

        assert not result.success
        assert "model not found" in result.error


class TestAgentCharmDir:
    """Tests for the _agent_charm_dir helper."""

    def test_simple_unit(self):
        """Converts a standard unit name to the on-disk path."""
        assert _agent_charm_dir("my-app/0") == "/var/lib/juju/agents/unit-my-app-0/charm"

    def test_unit_with_higher_number(self):
        """Works with multi-digit unit numbers."""
        assert _agent_charm_dir("postgresql/12") == "/var/lib/juju/agents/unit-postgresql-12/charm"


class TestIsK8sModel:
    """Tests for the _is_k8s_model helper."""

    @pytest.mark.asyncio
    async def test_caas_model(self):
        """Returns True for a Kubernetes (CAAS) model."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "caas"

        with mock.patch("cantrip.agent.tools.juju._common._run_juju", return_value=mock_info):
            assert await _is_k8s_model(mock_juju) is True

    @pytest.mark.asyncio
    async def test_iaas_model(self):
        """Returns False for a machine (IAAS) model."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "iaas"

        with mock.patch("cantrip.agent.tools.juju._common._run_juju", return_value=mock_info):
            assert await _is_k8s_model(mock_juju) is False


class TestCharmSyncTool:
    """Tests for CharmSyncTool."""

    @pytest.fixture
    def tool(self):
        return CharmSyncTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=False):
            result = await tool.execute(unit="my-app/0")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_sync_k8s_charm(self, tool, tmp_path):
        """Syncs files to a K8s unit using scp with container='charm'."""
        # Create a local charm directory with a source file.
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        charm_py = src_dir / "charm.py"
        charm_py.write_text("# charm code")

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "caas"
        mock_juju.show_model.return_value = mock_info

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(unit="my-app/0", charm_dir=str(tmp_path))

        assert result.success
        assert result.data["files_synced"] == 1

        # Verify ssh called with container="charm" for mkdir.
        mock_juju.ssh.assert_called_once()
        ssh_call = mock_juju.ssh.call_args
        assert ssh_call.kwargs.get("container") == "charm"

        # Verify scp called with container="charm".
        mock_juju.scp.assert_called_once()
        scp_call = mock_juju.scp.call_args
        assert scp_call.kwargs.get("container") == "charm"
        assert "my-app/0:" in scp_call.args[1]

    @pytest.mark.asyncio
    async def test_sync_machine_charm(self, tool, tmp_path):
        """Syncs files to a machine unit using cli('ssh', ..., stdin=...)."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        charm_py = src_dir / "charm.py"
        charm_py.write_text("# charm code")

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "iaas"
        mock_juju.show_model.return_value = mock_info

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(unit="my-app/0", charm_dir=str(tmp_path))

        assert result.success
        assert result.data["files_synced"] == 1

        # Verify ssh called with sudo mkdir (no container kwarg).
        mock_juju.ssh.assert_called_once()
        ssh_call = mock_juju.ssh.call_args
        assert "sudo mkdir" in ssh_call.args[1]
        assert "container" not in ssh_call.kwargs

        # Verify cli called with stdin containing the file content.
        mock_juju.cli.assert_called_once()
        cli_call = mock_juju.cli.call_args
        assert cli_call.args[0] == "ssh"
        assert cli_call.kwargs.get("stdin") == "# charm code"

    @pytest.mark.asyncio
    async def test_sync_no_matching_files(self, tool, tmp_path):
        """Returns success with 0 files when directories are empty."""
        # Create empty src directory (no .py files).
        (tmp_path / "src").mkdir()

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "caas"
        mock_juju.show_model.return_value = mock_info

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(unit="my-app/0", charm_dir=str(tmp_path))

        assert result.success
        assert result.data["files_synced"] == 0

    @pytest.mark.asyncio
    async def test_sync_correct_remote_path(self, tool, tmp_path):
        """Verifies the remote path is correctly constructed."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "charm.py").write_text("# code")

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "caas"
        mock_juju.show_model.return_value = mock_info

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(unit="my-app/0", charm_dir=str(tmp_path))

        assert result.success
        scp_call = mock_juju.scp.call_args
        expected_remote = "my-app/0:/var/lib/juju/agents/unit-my-app-0/charm/src/charm.py"
        assert scp_call.args[1] == expected_remote

    @pytest.mark.asyncio
    async def test_sync_cli_error(self, tool, tmp_path):
        """CLIError produces a failed ToolResult."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "charm.py").write_text("# code")

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "caas"
        mock_juju.show_model.return_value = mock_info
        mock_juju.ssh.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "ssh"],
            stderr="connection refused",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(unit="my-app/0", charm_dir=str(tmp_path))

        assert not result.success
        assert "connection refused" in result.error

    @pytest.mark.asyncio
    async def test_sync_custom_directories(self, tool, tmp_path):
        """Respects a custom directories list."""
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        (custom_dir / "module.py").write_text("# custom")

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "caas"
        mock_juju.show_model.return_value = mock_info

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(
                unit="my-app/0",
                charm_dir=str(tmp_path),
                directories=["custom"],
            )

        assert result.success
        assert result.data["files_synced"] == 1
        assert "custom/module.py" in result.data["files"][0]


class TestJujuDispatchTool:
    """Tests for JujuDispatchTool."""

    @pytest.fixture
    def tool(self):
        return JujuDispatchTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=False):
            result = await tool.execute(unit="my-app/0", event="update-status")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_dispatch_k8s(self, tool):
        """Dispatches on K8s with container='charm'."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "caas"
        mock_juju.show_model.return_value = mock_info
        mock_juju.ssh.return_value = "hook output"

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(unit="my-app/0", event="update-status")

        assert result.success
        assert "hook output" in result.output
        assert result.data["event"] == "update-status"

        ssh_call = mock_juju.ssh.call_args
        assert ssh_call.kwargs.get("container") == "charm"
        cmd = ssh_call.args[1]
        assert "JUJU_DISPATCH_PATH=hooks/update-status" in cmd
        assert "/var/lib/juju/agents/unit-my-app-0/charm/dispatch" in cmd

    @pytest.mark.asyncio
    async def test_dispatch_machine(self, tool):
        """Dispatches on a machine model with sudo."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "iaas"
        mock_juju.show_model.return_value = mock_info
        mock_juju.ssh.return_value = "machine output"

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(unit="my-app/0", event="config-changed")

        assert result.success
        assert "machine output" in result.output

        ssh_call = mock_juju.ssh.call_args
        assert "container" not in ssh_call.kwargs
        cmd = ssh_call.args[1]
        assert cmd.startswith("sudo ")
        assert "JUJU_DISPATCH_PATH=hooks/config-changed" in cmd

    @pytest.mark.asyncio
    async def test_dispatch_cli_error(self, tool):
        """CLIError produces a failed ToolResult."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "caas"
        mock_juju.show_model.return_value = mock_info
        mock_juju.ssh.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "ssh"],
            stderr="unit not found",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(unit="my-app/0", event="update-status")

        assert not result.success
        assert "unit not found" in result.error
