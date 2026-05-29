"""Tests for background environment preflight checks."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.agent.runtime.preflight import (
    DEFAULT_PRESET,
    CheckStatus,
    PreflightCallback,
    PreflightEvent,
    PreflightResult,
    PreflightRunner,
)
from cantrip.agent.state import AgentState


class TestCheckStatus:
    """Tests for the CheckStatus enum."""

    def test_values(self):
        """All expected statuses exist."""
        assert CheckStatus.PENDING == "pending"
        assert CheckStatus.RUNNING == "running"
        assert CheckStatus.PASSED == "passed"
        assert CheckStatus.FAILED == "failed"
        assert CheckStatus.SKIPPED == "skipped"


class TestPreflightEvent:
    """Tests for the PreflightEvent dataclass."""

    def test_creation(self):
        """Basic event creation."""
        event = PreflightEvent(
            check_name="juju",
            status=CheckStatus.PASSED,
            message="Juju CLI found",
        )
        assert event.check_name == "juju"
        assert event.status == CheckStatus.PASSED
        assert event.message == "Juju CLI found"
        assert event.detail == ""

    def test_detail_field(self):
        """Detail field is stored correctly."""
        event = PreflightEvent(
            check_name="cos",
            status=CheckStatus.FAILED,
            message="COS failed",
            detail="exit code 1",
        )
        assert event.detail == "exit code 1"


class TestPreflightResult:
    """Tests for the PreflightResult dataclass."""

    def test_defaults(self):
        """All fields default to false/empty."""
        result = PreflightResult()
        assert result.concierge_available is False
        assert result.juju_available is False
        assert result.controller_ready is False
        assert result.cos_model is None
        assert result.cos_ready is False
        assert result.preset is None
        assert result.errors == []
        assert result.fully_ready is False

    def test_fully_ready_true(self):
        """fully_ready is True when juju, controller, and COS are all ready."""
        result = PreflightResult(
            juju_available=True,
            controller_ready=True,
            cos_ready=True,
        )
        assert result.fully_ready is True

    def test_fully_ready_false_without_juju(self):
        """fully_ready is False when juju is missing."""
        result = PreflightResult(controller_ready=True, cos_ready=True)
        assert result.fully_ready is False

    def test_fully_ready_false_without_controller(self):
        """fully_ready is False when controller is not ready."""
        result = PreflightResult(juju_available=True, cos_ready=True)
        assert result.fully_ready is False

    def test_fully_ready_false_without_cos(self):
        """fully_ready is False when COS is not ready."""
        result = PreflightResult(juju_available=True, controller_ready=True)
        assert result.fully_ready is False


class TestPreflightCallback:
    """Tests for the callback type alias."""

    def test_callable_annotation(self):
        """PreflightCallback accepts a callable that takes a PreflightEvent."""
        events: list[PreflightEvent] = []

        def cb(event: PreflightEvent) -> None:
            events.append(event)

        callback: PreflightCallback = cb
        callback(PreflightEvent("test", CheckStatus.PASSED, "ok"))
        assert len(events) == 1


class TestWarmUp:
    """Tests for PreflightRunner.warm_up()."""

    @pytest.mark.asyncio
    async def test_concierge_not_installed(self):
        """warm_up skips concierge and checks juju when concierge is missing."""
        events: list[PreflightEvent] = []
        state = AgentState()
        runner = PreflightRunner(state, callback=events.append)

        with (
            patch("cantrip.agent.runtime.preflight._concierge_available", return_value=False),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value=None),
        ):
            result = await runner.warm_up()

        assert result.concierge_available is False
        assert result.juju_available is False
        names = [e.check_name for e in events]
        assert "concierge" in names
        assert "juju" in names
        # Concierge should be skipped, not failed.
        concierge_event = next(
            e for e in events if e.check_name == "concierge" and e.status != CheckStatus.RUNNING
        )
        assert concierge_event.status == CheckStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_concierge_prepare_succeeds(self):
        """warm_up installs snaps and finds juju on success."""
        events: list[PreflightEvent] = []
        state = AgentState()
        runner = PreflightRunner(state, callback=events.append)

        with (
            patch("cantrip.agent.runtime.preflight._concierge_available", return_value=True),
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(0, "ok", ""),
            ),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
        ):
            result = await runner.warm_up()

        assert result.concierge_available is True
        assert result.juju_available is True
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_concierge_prepare_fails(self):
        """warm_up records error when concierge prepare fails."""
        state = AgentState()
        runner = PreflightRunner(state)

        with (
            patch("cantrip.agent.runtime.preflight._concierge_available", return_value=True),
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(1, "", "install error"),
            ),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value=None),
        ):
            result = await runner.warm_up()

        assert len(result.errors) == 1
        assert "failed" in result.errors[0]

    @pytest.mark.asyncio
    async def test_concierge_prepare_timeout(self):
        """warm_up records error when concierge prepare times out."""
        state = AgentState()
        runner = PreflightRunner(state)

        with (
            patch("cantrip.agent.runtime.preflight._concierge_available", return_value=True),
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                side_effect=TimeoutError,
            ),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value=None),
        ):
            result = await runner.warm_up()

        assert len(result.errors) == 1
        assert "timed out" in result.errors[0]

    @pytest.mark.asyncio
    async def test_no_callback_runs_silently(self):
        """warm_up works without a callback."""
        state = AgentState()
        runner = PreflightRunner(state, callback=None)

        with (
            patch("cantrip.agent.runtime.preflight._concierge_available", return_value=False),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
        ):
            result = await runner.warm_up()

        assert result.juju_available is True

    @pytest.mark.asyncio
    async def test_callback_failure_does_not_abort_run(self):
        """A raising callback (e.g. dead Textual widget) must not break preflight."""
        state = AgentState()
        call_count = 0

        def _flaky(_event: PreflightEvent) -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("simulated UI failure")

        runner = PreflightRunner(state, callback=_flaky)

        with (
            patch("cantrip.agent.runtime.preflight._concierge_available", return_value=False),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
        ):
            result = await runner.warm_up()

        assert result.juju_available is True
        # Multiple events fired — every callback raised but none aborted the run.
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_callback_receives_events_in_order(self):
        """Events are emitted in the expected order during a successful warm_up."""
        events: list[PreflightEvent] = []
        state = AgentState()
        runner = PreflightRunner(state, callback=events.append)

        with (
            patch("cantrip.agent.runtime.preflight._concierge_available", return_value=True),
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(0, "ok", ""),
            ),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
        ):
            await runner.warm_up()

        check_names = [e.check_name for e in events]
        # Concierge checked first, then snap install, then juju.
        assert check_names[0] == "concierge"
        assert "snap_install" in check_names
        assert check_names[-1] == "juju"

    @pytest.mark.asyncio
    async def test_temp_config_cleaned_up(self):
        """The temporary config file is removed after warm_up."""
        state = AgentState()
        runner = PreflightRunner(state)
        written_paths: list[str] = []

        original_run = AsyncMock(return_value=(0, "ok", ""))

        async def capture_path(*args: str, timeout: int = 600) -> tuple[int, str, str]:
            for arg in args:
                if "cantrip-warmup" in arg:
                    written_paths.append(arg)
            return await original_run(*args, timeout=timeout)

        with (
            patch("cantrip.agent.runtime.preflight._concierge_available", return_value=True),
            patch("cantrip.agent.runtime.preflight._run_concierge", side_effect=capture_path),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
        ):
            await runner.warm_up()

        # A temp file path should have been passed to concierge.
        assert len(written_paths) == 1
        # The file should be cleaned up.
        import os

        assert not os.path.exists(written_paths[0])


class TestBootstrap:
    """Tests for PreflightRunner.bootstrap()."""

    @pytest.mark.asyncio
    async def test_bootstrap_full_success(self):
        """bootstrap succeeds when controller and COS are ready."""
        events: list[PreflightEvent] = []
        state = AgentState()
        runner = PreflightRunner(state, callback=events.append)

        mock_status = MagicMock()
        mock_status.apps = {"grafana": MagicMock()}

        mock_juju_cls = MagicMock()
        mock_juju_instance = MagicMock()
        mock_juju_instance.status.return_value = mock_status
        mock_juju_cls.return_value = mock_juju_instance

        with (
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(0, "ok", ""),
            ),
            patch("cantrip.agent.runtime.preflight.jubilant.Juju", mock_juju_cls),
            patch("cantrip.agent.runtime.preflight.jubilant.CLIError", Exception),
            patch("cantrip.agent.runtime.preflight.list_controllers", return_value=[]),
            patch("cantrip.agent.runtime.preflight._current_controller_is_k8s", return_value=True),
            patch("cantrip.agent.runtime.preflight._juju_controller_healthy", return_value=True),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
        ):
            result = await runner.bootstrap("machine")

        assert result.controller_ready is True
        assert result.cos_ready is True
        assert result.cos_model == "cos"
        assert state.cos_model == "cos"

    @pytest.mark.asyncio
    async def test_bootstrap_concierge_fails(self):
        """bootstrap returns early when concierge prepare fails."""
        state = AgentState()
        runner = PreflightRunner(state)

        with (
            patch(
                "cantrip.agent.runtime.preflight._is_already_provisioned",
                new_callable=AsyncMock,
                return_value=(False, None),
            ),
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(1, "", "boom"),
            ),
        ):
            result = await runner.bootstrap("k8s")

        assert result.controller_ready is False
        assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_bootstrap_concierge_timeout(self):
        """bootstrap records error when concierge times out."""
        state = AgentState()
        runner = PreflightRunner(state)

        with (
            patch(
                "cantrip.agent.runtime.preflight._is_already_provisioned",
                new_callable=AsyncMock,
                return_value=(False, None),
            ),
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                side_effect=TimeoutError,
            ),
        ):
            result = await runner.bootstrap("machine")

        assert result.controller_ready is False
        assert "timed out" in result.errors[0]

    @pytest.mark.asyncio
    async def test_bootstrap_controller_not_ready(self):
        """bootstrap returns early when the controller check fails."""
        state = AgentState()
        runner = PreflightRunner(state)

        with (
            patch(
                "cantrip.agent.runtime.preflight._is_already_provisioned",
                new_callable=AsyncMock,
                return_value=(False, None),
            ),
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(0, "ok", ""),
            ),
            patch(
                "cantrip.agent.runtime.preflight._juju_controller_healthy",
                return_value=False,
            ),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value=None),
        ):
            result = await runner.bootstrap("machine")

        assert result.controller_ready is False
        assert result.cos_ready is False

    @pytest.mark.asyncio
    async def test_bootstrap_cos_model_missing_creates_and_deploys(self):
        """bootstrap creates the COS model and deploys cos-lite."""
        state = AgentState()
        runner = PreflightRunner(state)

        cli_error = type("CLIError", (Exception,), {})

        # Default Juju (no model) — controller check passes.
        default_juju = MagicMock()
        default_juju.status.return_value = MagicMock()
        default_juju.add_model = MagicMock()

        # COS-specific Juju — first call raises (model missing), second succeeds.
        cos_juju = MagicMock()
        cos_juju.status.side_effect = cli_error("model not found")
        cos_juju.deploy = MagicMock()

        call_count = {"n": 0}

        def juju_factory(model: str | None = None) -> MagicMock:
            if model is None:
                call_count["n"] += 1
                return default_juju
            # After add_model, the second Juju(model=cos) should work.
            if call_count["n"] >= 2:
                fresh = MagicMock()
                fresh.deploy = MagicMock()
                return fresh
            return cos_juju

        with (
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(0, "ok", ""),
            ),
            patch("cantrip.agent.runtime.preflight.jubilant.Juju", side_effect=juju_factory),
            patch("cantrip.agent.runtime.preflight.jubilant.CLIError", cli_error),
            patch(
                "cantrip.agent.runtime.preflight.asyncio.to_thread", new_callable=AsyncMock
            ) as mock_to_thread,
            patch("cantrip.agent.runtime.preflight._current_controller_is_k8s", return_value=True),
            patch("cantrip.agent.runtime.preflight._juju_controller_healthy", return_value=True),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
        ):
            await runner.bootstrap("machine")

        # add_model and deploy should have been called.
        assert mock_to_thread.await_count >= 1
        assert state.cos_model == "cos"

    @pytest.mark.asyncio
    async def test_bootstrap_cos_model_empty_deploys(self):
        """bootstrap deploys cos-lite into an empty existing COS model."""
        state = AgentState()
        runner = PreflightRunner(state)

        # Controller check — passes.
        default_juju = MagicMock()
        default_juju.status.return_value = MagicMock()

        # COS model exists but has no apps.
        cos_juju = MagicMock()
        cos_status = MagicMock()
        cos_status.apps = {}
        cos_juju.status.return_value = cos_status
        cos_juju.deploy = MagicMock()

        def juju_factory(model: str | None = None) -> MagicMock:
            if model is None:
                return default_juju
            return cos_juju

        with (
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(0, "ok", ""),
            ),
            patch("cantrip.agent.runtime.preflight.jubilant.Juju", side_effect=juju_factory),
            patch("cantrip.agent.runtime.preflight.jubilant.CLIError", Exception),
            patch(
                "cantrip.agent.runtime.preflight.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=[[], cos_status, None],
            ) as mock_to_thread,
            patch("cantrip.agent.runtime.preflight._model_is_k8s", return_value=True),
            patch("cantrip.agent.runtime.preflight._current_controller_is_k8s", return_value=True),
            patch("cantrip.agent.runtime.preflight._juju_controller_healthy", return_value=True),
            patch(
                "cantrip.agent.runtime.preflight._is_already_provisioned",
                new_callable=AsyncMock,
                return_value=(False, None),
            ),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
        ):
            result = await runner.bootstrap("machine")

        # to_thread called for list_controllers, juju.status, juju.deploy.
        assert mock_to_thread.await_count == 3
        assert result.cos_ready is True

    @pytest.mark.asyncio
    async def test_bootstrap_cos_deploy_fails(self):
        """bootstrap records error when COS deployment fails."""
        state = AgentState()
        runner = PreflightRunner(state)

        cli_error = type("CLIError", (Exception,), {})

        # Controller check — passes.
        default_juju = MagicMock()
        default_juju.status.return_value = MagicMock()

        # COS model exists but is empty, deploy will fail.
        cos_juju = MagicMock()
        cos_status = MagicMock()
        cos_status.apps = {}
        cos_juju.status.return_value = cos_status

        def juju_factory(model: str | None = None) -> MagicMock:
            if model is None:
                return default_juju
            return cos_juju

        # to_thread calls: list_controllers, juju.status, juju.deploy (fails).
        call_count = 0

        async def selective_to_thread(func, *args, **kwargs):  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return []  # list_controllers
            if call_count == 2:
                return cos_status  # juju.status
            raise cli_error("deploy failed")

        with (
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(0, "ok", ""),
            ),
            patch("cantrip.agent.runtime.preflight.jubilant.Juju", side_effect=juju_factory),
            patch("cantrip.agent.runtime.preflight.jubilant.CLIError", cli_error),
            patch(
                "cantrip.agent.runtime.preflight.asyncio.to_thread",
                side_effect=selective_to_thread,
            ),
            patch("cantrip.agent.runtime.preflight._model_is_k8s", return_value=True),
            patch("cantrip.agent.runtime.preflight._current_controller_is_k8s", return_value=True),
            patch("cantrip.agent.runtime.preflight._juju_controller_healthy", return_value=True),
            patch(
                "cantrip.agent.runtime.preflight._is_already_provisioned",
                new_callable=AsyncMock,
                return_value=(False, None),
            ),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
        ):
            result = await runner.bootstrap("machine")

        assert result.cos_ready is False
        assert any("COS deployment failed" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_bootstrap_cos_skipped_on_non_k8s_controller(self):
        """bootstrap skips COS when no Kubernetes controller is available."""
        state = AgentState()
        runner = PreflightRunner(state)

        cli_error = type("CLIError", (Exception,), {})

        # COS model does not exist (status raises CLIError).
        cos_juju = MagicMock()
        cos_juju.status.side_effect = cli_error("model not found")

        default_juju = MagicMock()
        default_juju.status.return_value = MagicMock()

        def juju_factory(model: str | None = None) -> MagicMock:
            if model is None:
                return default_juju
            return cos_juju

        # to_thread calls: list_controllers, _find_k8s_controller (returns None → skip).
        call_count = 0

        async def selective_to_thread(func, *args, **kwargs):  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return []  # list_controllers
            return None  # _find_k8s_controller — no K8s controller

        with (
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(0, "ok", ""),
            ),
            patch("cantrip.agent.runtime.preflight.jubilant.Juju", side_effect=juju_factory),
            patch("cantrip.agent.runtime.preflight.jubilant.CLIError", cli_error),
            patch(
                "cantrip.agent.runtime.preflight.asyncio.to_thread",
                side_effect=selective_to_thread,
            ),
            patch(
                "cantrip.agent.runtime.preflight._current_controller_is_k8s", return_value=False
            ),
            patch("cantrip.agent.runtime.preflight._juju_controller_healthy", return_value=True),
            patch(
                "cantrip.agent.runtime.preflight._is_already_provisioned",
                new_callable=AsyncMock,
                return_value=(False, None),
            ),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
        ):
            result = await runner.bootstrap("machine")

        assert result.cos_ready is False
        # Should have been skipped, not failed.
        assert not result.errors

    @pytest.mark.asyncio
    async def test_bootstrap_cos_empty_model_skipped_on_non_k8s(self):
        """bootstrap skips COS deploy when an empty model is on a non-K8s cloud."""
        state = AgentState()
        runner = PreflightRunner(state)

        default_juju = MagicMock()
        default_juju.status.return_value = MagicMock()

        cos_juju = MagicMock()
        cos_status = MagicMock()
        cos_status.apps = {}
        cos_juju.status.return_value = cos_status

        def juju_factory(model: str | None = None) -> MagicMock:
            if model is None:
                return default_juju
            return cos_juju

        with (
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(0, "ok", ""),
            ),
            patch("cantrip.agent.runtime.preflight.jubilant.Juju", side_effect=juju_factory),
            patch("cantrip.agent.runtime.preflight.jubilant.CLIError", Exception),
            patch(
                "cantrip.agent.runtime.preflight.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=[[], cos_status],
            ),
            patch("cantrip.agent.runtime.preflight._model_is_k8s", return_value=False),
            patch("cantrip.agent.runtime.preflight._current_controller_is_k8s", return_value=True),
            patch("cantrip.agent.runtime.preflight._juju_controller_healthy", return_value=True),
            patch(
                "cantrip.agent.runtime.preflight._is_already_provisioned",
                new_callable=AsyncMock,
                return_value=(False, None),
            ),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
        ):
            result = await runner.bootstrap("machine")

        assert result.cos_ready is False
        assert not result.errors

    @pytest.mark.asyncio
    async def test_bootstrap_uses_state_cos_model_name(self):
        """bootstrap uses the cos_model name from state if set."""
        state = AgentState(cos_model="my-cos")
        runner = PreflightRunner(state)

        mock_status = MagicMock()
        mock_status.apps = {"grafana": MagicMock()}

        mock_juju_cls = MagicMock()
        mock_juju_cls.return_value.status.return_value = mock_status

        with (
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(0, "ok", ""),
            ),
            patch("cantrip.agent.runtime.preflight.jubilant.Juju", mock_juju_cls),
            patch("cantrip.agent.runtime.preflight.jubilant.CLIError", Exception),
            patch("cantrip.agent.runtime.preflight._current_controller_is_k8s", return_value=True),
            patch("cantrip.agent.runtime.preflight._juju_controller_healthy", return_value=True),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
        ):
            result = await runner.bootstrap("machine")

        assert result.cos_model == "my-cos"
        # Juju was called with the custom model name.
        mock_juju_cls.assert_any_call(model="my-cos")

    @pytest.mark.asyncio
    async def test_idempotent_rerun(self):
        """Running warm_up twice does not fail."""
        state = AgentState()
        runner = PreflightRunner(state)

        with (
            patch("cantrip.agent.runtime.preflight._concierge_available", return_value=True),
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(0, "ok", ""),
            ),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
        ):
            result1 = await runner.warm_up()
            result2 = await runner.warm_up()

        assert result1.juju_available is True
        assert result2.juju_available is True

    @pytest.mark.asyncio
    async def test_bootstrap_existing_cos_on_separate_k8s_controller(self):
        """bootstrap finds an existing COS model on a separate K8s controller.

        Regression: previously, when the current controller was IAAS (LXD)
        and COS already existed on a K8s controller, the code checked the
        model against the current controller (which raised CLIError) and
        then tried to add-model on the K8s controller, which failed because
        the model already existed there.  The fix routes the existence
        check to the K8s controller via ``controller:model`` syntax.
        """
        state = AgentState()
        runner = PreflightRunner(state)

        default_juju = MagicMock()
        default_juju.status.return_value = MagicMock()

        # COS model already exists on concierge-k8s with cos-lite deployed.
        cos_juju = MagicMock()
        cos_status = MagicMock()
        cos_status.apps = {"grafana": MagicMock()}
        cos_juju.status.return_value = cos_status

        seen_models: list[str | None] = []

        def juju_factory(model: str | None = None) -> MagicMock:
            seen_models.append(model)
            if model is None:
                return default_juju
            return cos_juju

        with (
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(0, "ok", ""),
            ),
            patch("cantrip.agent.runtime.preflight.jubilant.Juju", side_effect=juju_factory),
            patch("cantrip.agent.runtime.preflight.jubilant.CLIError", Exception),
            patch(
                "cantrip.agent.runtime.preflight.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=[[], "concierge-k8s", cos_status],
            ),
            patch(
                "cantrip.agent.runtime.preflight._current_controller_is_k8s", return_value=False
            ),
            patch("cantrip.agent.runtime.preflight._juju_controller_healthy", return_value=True),
            patch(
                "cantrip.agent.runtime.preflight._is_already_provisioned",
                new_callable=AsyncMock,
                return_value=(True, None),
            ),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
        ):
            result = await runner.bootstrap("machine")

        assert result.cos_ready is True
        assert result.cos_controller == "concierge-k8s"
        assert not result.errors
        # The model check used controller:model syntax — it did NOT fall
        # through to add-model.
        assert "concierge-k8s:cos" in seen_models


class TestPrepare:
    """Tests for PreflightRunner.prepare()."""

    @pytest.mark.asyncio
    async def test_full_success(self):
        """prepare succeeds when concierge, controller, and COS are all ready."""
        events: list[PreflightEvent] = []
        state = AgentState()
        runner = PreflightRunner(state, callback=events.append)

        mock_status = MagicMock()
        mock_status.apps = {"grafana": MagicMock()}

        mock_juju_cls = MagicMock()
        mock_juju_instance = MagicMock()
        mock_juju_instance.status.return_value = mock_status
        mock_juju_cls.return_value = mock_juju_instance

        with (
            patch("cantrip.agent.runtime.preflight._concierge_available", return_value=True),
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(0, "ok", ""),
            ),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
            patch("cantrip.agent.runtime.preflight.jubilant.Juju", mock_juju_cls),
            patch("cantrip.agent.runtime.preflight.jubilant.CLIError", Exception),
            patch("cantrip.agent.runtime.preflight.list_controllers", return_value=[]),
            patch("cantrip.agent.runtime.preflight._current_controller_is_k8s", return_value=True),
            patch("cantrip.agent.runtime.preflight._juju_controller_healthy", return_value=True),
        ):
            result = await runner.prepare("k8s")

        assert result.concierge_available is True
        assert result.juju_available is True
        assert result.controller_ready is True
        assert result.cos_ready is True
        assert result.preset == "k8s"
        assert result.fully_ready is True

    @pytest.mark.asyncio
    async def test_default_preset(self):
        """prepare uses DEFAULT_PRESET when no preset is specified."""
        state = AgentState()
        runner = PreflightRunner(state)

        with (
            patch("cantrip.agent.runtime.preflight._concierge_available", return_value=False),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value=None),
        ):
            result = await runner.prepare()

        assert result.preset == DEFAULT_PRESET

    @pytest.mark.asyncio
    async def test_concierge_not_installed(self):
        """prepare skips everything gracefully when concierge is missing."""
        events: list[PreflightEvent] = []
        state = AgentState()
        runner = PreflightRunner(state, callback=events.append)

        with (
            patch("cantrip.agent.runtime.preflight._concierge_available", return_value=False),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value=None),
        ):
            result = await runner.prepare("k8s")

        assert result.concierge_available is False
        assert result.fully_ready is False
        names = [e.check_name for e in events]
        assert "concierge" in names
        assert "juju" in names
        assert "controller" in names
        assert "cos" in names

    @pytest.mark.asyncio
    async def test_concierge_prepare_fails(self):
        """prepare records error and returns early when concierge prepare fails."""
        state = AgentState()
        runner = PreflightRunner(state)

        with (
            patch("cantrip.agent.runtime.preflight._concierge_available", return_value=True),
            patch(
                "cantrip.agent.runtime.preflight._is_already_provisioned",
                new_callable=AsyncMock,
                return_value=(False, None),
            ),
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(1, "", "boom"),
            ),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value=None),
        ):
            result = await runner.prepare("k8s")

        assert len(result.errors) == 1
        assert "failed" in result.errors[0]
        assert result.controller_ready is False

    @pytest.mark.asyncio
    async def test_concierge_prepare_timeout(self):
        """prepare records error when concierge prepare times out."""
        state = AgentState()
        runner = PreflightRunner(state)

        with (
            patch("cantrip.agent.runtime.preflight._concierge_available", return_value=True),
            patch(
                "cantrip.agent.runtime.preflight._is_already_provisioned",
                new_callable=AsyncMock,
                return_value=(False, None),
            ),
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                side_effect=TimeoutError,
            ),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value=None),
        ):
            result = await runner.prepare("machine")

        assert len(result.errors) == 1
        assert "timed out" in result.errors[0]

    @pytest.mark.asyncio
    async def test_controller_not_ready(self):
        """prepare returns early when the controller check fails."""
        state = AgentState()
        runner = PreflightRunner(state)

        with (
            patch("cantrip.agent.runtime.preflight._concierge_available", return_value=True),
            patch(
                "cantrip.agent.runtime.preflight._is_already_provisioned",
                new_callable=AsyncMock,
                return_value=(False, None),
            ),
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(0, "ok", ""),
            ),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
            patch(
                "cantrip.agent.runtime.preflight._juju_controller_healthy",
                return_value=False,
            ),
        ):
            result = await runner.prepare("k8s")

        assert result.controller_ready is False
        assert result.cos_ready is False

    @pytest.mark.asyncio
    async def test_mismatched_controller_skips_concierge(self):
        """A wrong-substrate controller aborts prepare without running concierge."""
        state = AgentState()
        runner = PreflightRunner(state)

        run_concierge_mock = AsyncMock(return_value=(0, "", ""))
        with (
            patch("cantrip.agent.runtime.preflight._concierge_available", return_value=True),
            patch(
                "cantrip.agent.runtime.preflight._concierge_already_running", return_value=False
            ),
            patch(
                "cantrip.agent.runtime.preflight._is_already_provisioned",
                new_callable=AsyncMock,
                return_value=(False, "localhost"),
            ),
            patch("cantrip.agent.runtime.preflight._run_concierge", run_concierge_mock),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
        ):
            result = await runner.prepare("k8s")

        # Concierge prepare must NOT have been invoked.
        run_concierge_mock.assert_not_awaited()
        assert any("localhost" in e for e in result.errors)
        assert any("does not match" in e for e in result.errors)
        assert result.controller_ready is False

    @pytest.mark.asyncio
    async def test_running_concierge_skips_prepare(self):
        """If a concierge process is already running, prepare bails out."""
        state = AgentState()
        runner = PreflightRunner(state)

        run_concierge_mock = AsyncMock(return_value=(0, "", ""))
        with (
            patch("cantrip.agent.runtime.preflight._concierge_available", return_value=True),
            patch("cantrip.agent.runtime.preflight._concierge_already_running", return_value=True),
            patch("cantrip.agent.runtime.preflight._run_concierge", run_concierge_mock),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
        ):
            result = await runner.prepare("k8s")

        run_concierge_mock.assert_not_awaited()
        assert any("already running" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_events_emitted_in_order(self):
        """Events are emitted in the expected order during a successful prepare."""
        events: list[PreflightEvent] = []
        state = AgentState()
        runner = PreflightRunner(state, callback=events.append)

        mock_status = MagicMock()
        mock_status.apps = {"grafana": MagicMock()}

        mock_juju_cls = MagicMock()
        mock_juju_cls.return_value.status.return_value = mock_status

        with (
            patch("cantrip.agent.runtime.preflight._concierge_available", return_value=True),
            patch(
                "cantrip.agent.runtime.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(0, "ok", ""),
            ),
            patch("cantrip.agent.runtime.preflight.shutil.which", return_value="/snap/bin/juju"),
            patch("cantrip.agent.runtime.preflight.jubilant.Juju", mock_juju_cls),
            patch("cantrip.agent.runtime.preflight.jubilant.CLIError", Exception),
            patch("cantrip.agent.runtime.preflight._juju_controller_healthy", return_value=True),
        ):
            await runner.prepare("k8s")

        check_names = [e.check_name for e in events]
        assert check_names[0] == "concierge"
        assert "prepare" in check_names
        assert "juju" in check_names
        assert "controller" in check_names
        assert check_names[-1] == "cos"
