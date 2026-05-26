"""Coverage backfill for ``cantrip.agent.preflight`` helpers and branches.

The existing :mod:`tests.unit.agent.test_preflight` covers the runner's
happy-paths via heavy ``mock.patch`` blocks but leaves the module-level
helpers (``_run_juju_json``, ``list_controllers``,
``_setup_cos_cross_model_offers``, …) and a handful of runner branches
(``is_cross_controller`` property, ``_check_cos_model``'s CLIError →
``_create_cos_model`` flow, ``_create_cos_offers`` happy paths,
provisioned-but-controller-failed paths) untested.  This file fills
those gaps directly rather than complicating the heavy bootstrap
fixtures.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.agent.preflight import (
    CheckStatus,
    PreflightEvent,
    PreflightResult,
    PreflightRunner,
    _create_model_on_controller,
    _current_controller_is_k8s,
    _find_k8s_controller,
    _model_is_k8s,
    _run_juju_json,
    _setup_cos_cross_model_offers,
    list_controllers,
)
from cantrip.agent.state import AgentState

# ---------------------------------------------------------------------------
# PreflightResult.is_cross_controller
# ---------------------------------------------------------------------------


class TestIsCrossController:
    """The Phase 22 ``is_cross_controller`` flag tracks COS placement."""

    def test_false_by_default(self) -> None:
        assert PreflightResult().is_cross_controller is False

    def test_true_when_cos_controller_is_set(self) -> None:
        result = PreflightResult(cos_controller="concierge-k8s")
        assert result.is_cross_controller is True


# ---------------------------------------------------------------------------
# _run_juju_json
# ---------------------------------------------------------------------------


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    """Build a stand-in for :class:`subprocess.CompletedProcess`."""
    cp = MagicMock()
    cp.returncode = returncode
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


class TestRunJujuJson:
    """``_run_juju_json`` is the shared envelope for discovery callers."""

    def test_returns_none_when_juju_missing(self) -> None:
        with patch("cantrip.agent.preflight.shutil.which", return_value=None):
            assert _run_juju_json(["status"]) is None

    def test_returns_none_on_non_zero_rc(self) -> None:
        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/bin/juju"),
            patch(
                "cantrip.agent.preflight.subprocess.run",
                return_value=_completed(returncode=1, stdout=""),
            ),
        ):
            assert _run_juju_json(["status"]) is None

    def test_returns_none_on_timeout(self) -> None:
        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/bin/juju"),
            patch(
                "cantrip.agent.preflight.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="juju", timeout=1),
            ),
        ):
            assert _run_juju_json(["status"]) is None

    def test_returns_none_on_oserror(self) -> None:
        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/bin/juju"),
            patch(
                "cantrip.agent.preflight.subprocess.run",
                side_effect=OSError("boom"),
            ),
        ):
            assert _run_juju_json(["status"]) is None

    def test_returns_none_on_invalid_json(self) -> None:
        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/bin/juju"),
            patch(
                "cantrip.agent.preflight.subprocess.run",
                return_value=_completed(returncode=0, stdout="not json"),
            ),
        ):
            assert _run_juju_json(["status"]) is None

    def test_returns_none_when_top_level_is_not_a_dict(self) -> None:
        # ``juju ... --format=json`` callers all expect dict-shaped output;
        # a list would be a juju-CLI-shape change worth the explicit None.
        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/bin/juju"),
            patch(
                "cantrip.agent.preflight.subprocess.run",
                return_value=_completed(returncode=0, stdout=json.dumps(["a", "b"])),
            ),
        ):
            assert _run_juju_json(["status"]) is None

    def test_returns_dict_on_happy_path(self) -> None:
        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/bin/juju"),
            patch(
                "cantrip.agent.preflight.subprocess.run",
                return_value=_completed(
                    returncode=0,
                    stdout=json.dumps({"controllers": {"x": {}}}),
                ),
            ),
        ):
            assert _run_juju_json(["controllers"]) == {"controllers": {"x": {}}}


# ---------------------------------------------------------------------------
# _model_is_k8s
# ---------------------------------------------------------------------------


class TestModelIsK8s:
    """Detects whether a model lives on a CAAS (Kubernetes) cloud."""

    def test_false_when_juju_returns_nothing(self) -> None:
        with patch("cantrip.agent.preflight._run_juju_json", return_value=None):
            assert _model_is_k8s("cos") is False

    def test_true_when_first_model_is_caas(self) -> None:
        payload = {"cos": {"model-type": "caas"}}
        with patch("cantrip.agent.preflight._run_juju_json", return_value=payload):
            assert _model_is_k8s("cos") is True

    def test_false_when_first_model_is_iaas(self) -> None:
        payload = {"cos": {"model-type": "iaas"}}
        with patch("cantrip.agent.preflight._run_juju_json", return_value=payload):
            assert _model_is_k8s("cos") is False

    def test_handles_controller_qualified_name(self) -> None:
        # ``juju show-model controller:cos`` keys the result on the bare
        # model name regardless of the syntax used.
        payload = {"cos": {"model-type": "caas"}}
        with patch("cantrip.agent.preflight._run_juju_json", return_value=payload):
            assert _model_is_k8s("concierge-k8s:cos") is True


# ---------------------------------------------------------------------------
# _current_controller_is_k8s
# ---------------------------------------------------------------------------


class TestCurrentControllerIsK8s:
    """Inspects the active controller's cloud field."""

    def test_false_when_no_data(self) -> None:
        with patch("cantrip.agent.preflight._run_juju_json", return_value=None):
            assert _current_controller_is_k8s() is False

    def test_true_for_microk8s(self) -> None:
        payload = {"current": {"details": {"cloud": "microk8s"}}}
        with patch("cantrip.agent.preflight._run_juju_json", return_value=payload):
            assert _current_controller_is_k8s() is True

    def test_true_for_k8s(self) -> None:
        payload = {"current": {"details": {"cloud": "k8s"}}}
        with patch("cantrip.agent.preflight._run_juju_json", return_value=payload):
            assert _current_controller_is_k8s() is True

    def test_false_for_lxd(self) -> None:
        payload = {"current": {"details": {"cloud": "localhost"}}}
        with patch("cantrip.agent.preflight._run_juju_json", return_value=payload):
            assert _current_controller_is_k8s() is False


# ---------------------------------------------------------------------------
# _find_k8s_controller
# ---------------------------------------------------------------------------


class TestFindK8sController:
    """Returns the first registered K8s controller (or None)."""

    def test_returns_none_when_no_data(self) -> None:
        with patch("cantrip.agent.preflight._run_juju_json", return_value=None):
            assert _find_k8s_controller() is None

    def test_finds_microk8s_controller(self) -> None:
        payload = {
            "controllers": {
                "lxd": {"cloud": "localhost"},
                "k8s": {"cloud": "microk8s"},
            }
        }
        with patch("cantrip.agent.preflight._run_juju_json", return_value=payload):
            assert _find_k8s_controller() == "k8s"

    def test_returns_none_when_only_iaas_controllers(self) -> None:
        payload = {"controllers": {"lxd": {"cloud": "localhost"}}}
        with patch("cantrip.agent.preflight._run_juju_json", return_value=payload):
            assert _find_k8s_controller() is None


# ---------------------------------------------------------------------------
# list_controllers
# ---------------------------------------------------------------------------


class TestListControllers:
    """Surface used by the multi-controller preflight summary."""

    def test_empty_when_no_data(self) -> None:
        with patch("cantrip.agent.preflight._run_juju_json", return_value=None):
            assert list_controllers() == []

    def test_normalises_controller_records(self) -> None:
        payload = {
            "controllers": {
                "k8s": {"cloud": "microk8s", "model-count": 3},
                "lxd": {"cloud": "localhost", "model-count": 1},
            }
        }
        with patch("cantrip.agent.preflight._run_juju_json", return_value=payload):
            entries = list_controllers()
        assert entries == [
            {"name": "k8s", "cloud": "microk8s", "is_k8s": True, "models": 3},
            {"name": "lxd", "cloud": "localhost", "is_k8s": False, "models": 1},
        ]


# ---------------------------------------------------------------------------
# _create_model_on_controller
# ---------------------------------------------------------------------------


class TestCreateModelOnController:
    """``add-model -c controller`` wrapper for cross-controller flows."""

    def test_returns_failure_when_juju_missing(self) -> None:
        with patch("cantrip.agent.preflight.shutil.which", return_value=None):
            rc, stderr = _create_model_on_controller("cos", "k8s-ctrl")
        assert rc == 1
        assert "juju CLI not found" in stderr

    def test_success_returns_zero(self) -> None:
        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/bin/juju"),
            patch(
                "cantrip.agent.preflight.subprocess.run",
                return_value=_completed(returncode=0, stderr=""),
            ),
        ):
            rc, stderr = _create_model_on_controller("cos", "k8s-ctrl")
        assert rc == 0
        assert stderr == ""

    def test_failure_returns_juju_stderr(self) -> None:
        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/bin/juju"),
            patch(
                "cantrip.agent.preflight.subprocess.run",
                return_value=_completed(returncode=2, stderr="permission denied"),
            ),
        ):
            rc, stderr = _create_model_on_controller("cos", "k8s-ctrl")
        assert rc == 2
        assert stderr == "permission denied"

    def test_timeout_is_translated_to_failure(self) -> None:
        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/bin/juju"),
            patch(
                "cantrip.agent.preflight.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="juju", timeout=1),
            ),
        ):
            rc, stderr = _create_model_on_controller("cos", "k8s-ctrl")
        assert rc == 1
        assert "timed out" in stderr

    def test_oserror_is_translated_to_failure(self) -> None:
        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/bin/juju"),
            patch(
                "cantrip.agent.preflight.subprocess.run",
                side_effect=OSError("permission denied"),
            ),
        ):
            rc, stderr = _create_model_on_controller("cos", "k8s-ctrl")
        assert rc == 1
        assert "permission denied" in stderr


# ---------------------------------------------------------------------------
# _setup_cos_cross_model_offers
# ---------------------------------------------------------------------------


def _status_payload(*apps: str) -> str:
    return json.dumps({"applications": {a: {} for a in apps}})


class TestSetupCosCrossModelOffers:
    """Best-effort offer creation for cross-model COS integrations."""

    def test_returns_empty_when_juju_missing(self) -> None:
        with patch("cantrip.agent.preflight.shutil.which", return_value=None):
            assert _setup_cos_cross_model_offers("cos") == []

    def test_creates_offers_for_present_apps(self) -> None:
        # Two ``subprocess.run`` calls per endpoint: status, then offer.
        # For each of the four COS apps we return both apps in status so
        # the offer call fires; the offer succeeds for the first three
        # and fails for tempo so we exercise both branches.
        status = _completed(
            returncode=0,
            stdout=_status_payload("grafana-k8s", "prometheus-k8s", "loki-k8s", "tempo-k8s"),
        )
        offer_ok = _completed(returncode=0)
        offer_fail = _completed(returncode=1)

        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/bin/juju"),
            patch(
                "cantrip.agent.preflight.subprocess.run",
                side_effect=[
                    status,
                    offer_ok,
                    status,
                    offer_ok,
                    status,
                    offer_ok,
                    status,
                    offer_fail,
                ],
            ),
        ):
            offers = _setup_cos_cross_model_offers("cos")

        assert offers == [
            "cos.grafana-k8s:grafana-dashboard",
            "cos.prometheus-k8s:receive-remote-write",
            "cos.loki-k8s:logging",
        ]

    def test_skips_app_when_status_fails(self) -> None:
        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/bin/juju"),
            patch(
                "cantrip.agent.preflight.subprocess.run",
                return_value=_completed(returncode=1, stdout=""),
            ),
        ):
            assert _setup_cos_cross_model_offers("cos") == []

    def test_skips_app_when_status_raises_subprocess_error(self) -> None:
        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/bin/juju"),
            patch(
                "cantrip.agent.preflight.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="juju", timeout=1),
            ),
        ):
            assert _setup_cos_cross_model_offers("cos") == []

    def test_skips_app_when_status_returns_invalid_json(self) -> None:
        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/bin/juju"),
            patch(
                "cantrip.agent.preflight.subprocess.run",
                return_value=_completed(returncode=0, stdout="not json"),
            ),
        ):
            assert _setup_cos_cross_model_offers("cos") == []

    def test_skips_when_no_app_matches_hint(self) -> None:
        # Status reports an unrelated app; no hint matches → the per-hint
        # ``app_name is None`` branch runs and the loop continues without
        # firing an offer.
        status = _completed(returncode=0, stdout=_status_payload("unrelated-app"))
        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/bin/juju"),
            patch(
                "cantrip.agent.preflight.subprocess.run",
                return_value=status,
            ),
        ):
            assert _setup_cos_cross_model_offers("cos") == []

    def test_offer_subprocess_error_is_swallowed(self) -> None:
        status = _completed(returncode=0, stdout=_status_payload("grafana-k8s"))

        # Status returns OK for every hint; the offer call always raises.
        # The offer-side ``except`` block keeps the loop alive and the
        # per-app result is simply dropped.
        def fake_run(*args: object, **_kwargs: object) -> MagicMock:
            cmd = args[0]
            if "status" in cmd:
                return status
            raise OSError("offer failed")

        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/bin/juju"),
            patch("cantrip.agent.preflight.subprocess.run", side_effect=fake_run),
        ):
            assert _setup_cos_cross_model_offers("cos") == []


# ---------------------------------------------------------------------------
# Runner branches the existing suite skips
# ---------------------------------------------------------------------------


class _CLIError(Exception):
    """Stand-in for :class:`jubilant.CLIError` that's safe to ``raise``."""


class TestRunnerSkipBranches:
    """Branches the existing test_preflight.py leaves uncovered."""

    @pytest.mark.asyncio
    async def test_warm_up_skips_when_concierge_already_running(self) -> None:
        events: list[PreflightEvent] = []
        runner = PreflightRunner(AgentState(), callback=events.append)

        with (
            patch("cantrip.agent.preflight._concierge_available", return_value=True),
            patch("cantrip.agent.preflight._concierge_already_running", return_value=True),
            patch("cantrip.agent.preflight.shutil.which", return_value=None),
        ):
            result = await runner.warm_up()

        assert result.concierge_available is True
        statuses = [(e.check_name, e.status) for e in events]
        # ``snap_install`` is skipped because another concierge is running.
        assert ("snap_install", CheckStatus.SKIPPED) in statuses

    @pytest.mark.asyncio
    async def test_bootstrap_skips_when_concierge_already_running(self) -> None:
        runner = PreflightRunner(AgentState())
        with patch("cantrip.agent.preflight._concierge_already_running", return_value=True):
            result = await runner.bootstrap("k8s")
        assert any("already running" in e for e in result.errors)
        assert result.controller_ready is False

    @pytest.mark.asyncio
    async def test_bootstrap_mismatched_cloud_aborts(self) -> None:
        runner = PreflightRunner(AgentState())
        with (
            patch("cantrip.agent.preflight._concierge_already_running", return_value=False),
            patch(
                "cantrip.agent.preflight._is_already_provisioned",
                new_callable=AsyncMock,
                return_value=(False, "localhost"),
            ),
        ):
            result = await runner.bootstrap("k8s")
        assert any("does not match" in e for e in result.errors)
        assert result.controller_ready is False

    @pytest.mark.asyncio
    async def test_bootstrap_provisioned_but_controller_unhealthy(self) -> None:
        runner = PreflightRunner(AgentState())
        with (
            patch("cantrip.agent.preflight._concierge_already_running", return_value=False),
            patch(
                "cantrip.agent.preflight._is_already_provisioned",
                new_callable=AsyncMock,
                return_value=(True, None),
            ),
            patch("cantrip.agent.preflight._juju_controller_healthy", return_value=False),
        ):
            result = await runner.bootstrap("k8s")
        assert result.controller_ready is False
        assert any("Controller check failed" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_prepare_full_success_after_concierge_run(self) -> None:
        # The existing happy-path prepare() test does not mock
        # ``_is_already_provisioned``, so it returns early through the
        # provisioned-skip branch and never exercises the post-prepare
        # controller / COS path.  This case forces concierge to run, then
        # asserts the controller-ready emit and the cos model handoff.
        state = AgentState()
        runner = PreflightRunner(state)
        cos_juju = MagicMock()
        cos_status = MagicMock()
        cos_status.apps = {"grafana": MagicMock()}
        cos_juju.status.return_value = cos_status

        with (
            patch("cantrip.agent.preflight._concierge_available", return_value=True),
            patch("cantrip.agent.preflight._concierge_already_running", return_value=False),
            patch(
                "cantrip.agent.preflight._is_already_provisioned",
                new_callable=AsyncMock,
                return_value=(False, None),
            ),
            patch(
                "cantrip.agent.preflight._run_concierge",
                new_callable=AsyncMock,
                return_value=(0, "ok", ""),
            ),
            patch("cantrip.agent.preflight._juju_controller_healthy", return_value=True),
            patch("cantrip.agent.preflight._current_controller_is_k8s", return_value=True),
            patch("cantrip.agent.preflight.list_controllers", return_value=[]),
            patch("cantrip.agent.preflight.shutil.which", return_value="/bin/juju"),
            patch("cantrip.agent.preflight.jubilant.Juju", return_value=cos_juju),
            patch("cantrip.agent.preflight.jubilant.CLIError", _CLIError),
        ):
            result = await runner.prepare("k8s")

        assert result.controller_ready is True
        assert result.cos_ready is True
        assert result.cos_model == "cos"

    @pytest.mark.asyncio
    async def test_prepare_provisioned_but_controller_unhealthy(self) -> None:
        runner = PreflightRunner(AgentState())
        with (
            patch("cantrip.agent.preflight._concierge_available", return_value=True),
            patch("cantrip.agent.preflight._concierge_already_running", return_value=False),
            patch(
                "cantrip.agent.preflight._is_already_provisioned",
                new_callable=AsyncMock,
                return_value=(True, None),
            ),
            patch("cantrip.agent.preflight._juju_controller_healthy", return_value=False),
            patch("cantrip.agent.preflight.shutil.which", return_value="/bin/juju"),
        ):
            result = await runner.prepare("k8s")
        assert result.controller_ready is False
        assert any("Controller check failed" in e for e in result.errors)


class TestEnsureCosCreatePaths:
    """Drive ``_create_cos_model`` and ``_create_cos_offers`` directly."""

    @pytest.mark.asyncio
    async def test_create_cos_model_local_controller_success(self) -> None:
        runner = PreflightRunner(AgentState())
        runner.result.controllers = []
        runner.result.controller_ready = True

        default_juju = MagicMock()
        default_juju.add_model = MagicMock()

        with (
            patch("cantrip.agent.preflight.jubilant.Juju", return_value=default_juju),
            patch("cantrip.agent.preflight.jubilant.CLIError", _CLIError),
        ):
            juju = await runner._create_cos_model("cos", cos_controller=None)

        assert juju is not None
        # The local-controller branch calls ``add_model`` on a default Juju.
        default_juju.add_model.assert_called_once_with("cos")

    @pytest.mark.asyncio
    async def test_create_cos_model_local_controller_failure(self) -> None:
        runner = PreflightRunner(AgentState())

        default_juju = MagicMock()
        default_juju.add_model = MagicMock(side_effect=_CLIError("boom"))

        with (
            patch("cantrip.agent.preflight.jubilant.Juju", return_value=default_juju),
            patch("cantrip.agent.preflight.jubilant.CLIError", _CLIError),
        ):
            juju = await runner._create_cos_model("cos", cos_controller=None)

        assert juju is None
        assert any("COS model creation failed" in e for e in runner.result.errors)

    @pytest.mark.asyncio
    async def test_create_cos_model_remote_controller_success(self) -> None:
        runner = PreflightRunner(AgentState())

        with (
            patch(
                "cantrip.agent.preflight._create_model_on_controller",
                return_value=(0, ""),
            ),
            patch("cantrip.agent.preflight.jubilant.Juju") as juju_cls,
            patch("cantrip.agent.preflight.jubilant.CLIError", _CLIError),
        ):
            juju = await runner._create_cos_model("cos", cos_controller="k8s")

        assert juju is not None
        juju_cls.assert_called_with(model="k8s:cos")

    @pytest.mark.asyncio
    async def test_create_cos_model_remote_controller_failure(self) -> None:
        runner = PreflightRunner(AgentState())

        with patch(
            "cantrip.agent.preflight._create_model_on_controller",
            return_value=(1, "denied"),
        ):
            juju = await runner._create_cos_model("cos", cos_controller="k8s")

        assert juju is None
        assert any("denied" in e for e in runner.result.errors)

    @pytest.mark.asyncio
    async def test_check_cos_model_falls_through_to_create_on_clierror(self) -> None:
        # ``_check_cos_model`` raises ``jubilant.CLIError`` when the model
        # is missing; this should route into ``_create_cos_model``.
        runner = PreflightRunner(AgentState())
        runner.result.controller_ready = True

        cos_juju = MagicMock()
        cos_juju.status.side_effect = _CLIError("model not found")

        # The post-create Juju instance is the second one constructed.
        post_create = MagicMock()

        # Drive ``_create_cos_model`` down the local-controller branch
        # by passing ``cos_controller=None``.
        with (
            patch(
                "cantrip.agent.preflight.jubilant.Juju",
                side_effect=[cos_juju, post_create],
            ),
            patch("cantrip.agent.preflight.jubilant.CLIError", _CLIError),
            patch.object(
                runner,
                "_create_cos_model",
                new_callable=AsyncMock,
                return_value=post_create,
            ) as create,
        ):
            juju = await runner._check_cos_model("cos", cos_controller=None)

        assert juju is post_create
        create.assert_awaited_once_with("cos", None)

    @pytest.mark.asyncio
    async def test_create_cos_offers_records_offers(self) -> None:
        runner = PreflightRunner(AgentState())
        runner.result.cos_controller = "k8s"

        with (
            patch("cantrip.agent.preflight._current_controller_is_k8s", return_value=False),
            patch(
                "cantrip.agent.preflight._setup_cos_cross_model_offers",
                return_value=["k8s:cos.grafana:dash", "k8s:cos.prometheus:rrw"],
            ),
        ):
            events: list[PreflightEvent] = []
            runner._callback = events.append
            await runner._create_cos_offers("cos")

        msgs = [e.message for e in events]
        assert any("COS offers created" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_create_cos_offers_falls_back_when_no_offers(self) -> None:
        runner = PreflightRunner(AgentState())
        runner.result.cos_controller = "k8s"

        with (
            patch("cantrip.agent.preflight._current_controller_is_k8s", return_value=False),
            patch(
                "cantrip.agent.preflight._setup_cos_cross_model_offers",
                return_value=[],
            ),
        ):
            events: list[PreflightEvent] = []
            runner._callback = events.append
            await runner._create_cos_offers("cos")

        msgs = [e.message for e in events]
        assert any("offers will be configured" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_create_cos_offers_skipped_when_current_controller_is_k8s(self) -> None:
        runner = PreflightRunner(AgentState())
        # cos_controller stays None — the early-return guard fires first.
        with patch("cantrip.agent.preflight._current_controller_is_k8s", return_value=True):
            events: list[PreflightEvent] = []
            runner._callback = events.append
            await runner._create_cos_offers("cos")

        # The early return means no offer-related event is emitted.
        assert events == []


# ---------------------------------------------------------------------------
# Phase 97.3 — substrate refinements (MicroCloud / OpenStack)
# ---------------------------------------------------------------------------


class TestDetectMicroCloud:
    """``detect_microcloud`` checks for the locally-installed snap."""

    def test_returns_false_when_snap_missing(self) -> None:
        from cantrip.agent.preflight import detect_microcloud

        with patch("cantrip.agent.preflight.shutil.which", return_value=None):
            assert detect_microcloud() is False

    def test_returns_true_when_snap_list_succeeds(self) -> None:
        from cantrip.agent.preflight import detect_microcloud

        fake_proc = MagicMock(returncode=0, stdout="microcloud  1/stable  …\n", stderr="")
        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/usr/bin/snap"),
            patch("cantrip.agent.preflight.subprocess.run", return_value=fake_proc),
        ):
            assert detect_microcloud() is True

    def test_returns_false_when_snap_list_fails(self) -> None:
        from cantrip.agent.preflight import detect_microcloud

        fake_proc = MagicMock(
            returncode=1, stdout="", stderr="error: snap 'microcloud' not installed"
        )
        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/usr/bin/snap"),
            patch("cantrip.agent.preflight.subprocess.run", return_value=fake_proc),
        ):
            assert detect_microcloud() is False

    def test_swallows_timeout(self) -> None:
        from cantrip.agent.preflight import detect_microcloud

        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/usr/bin/snap"),
            patch(
                "cantrip.agent.preflight.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="snap", timeout=5),
            ),
        ):
            assert detect_microcloud() is False

    def test_swallows_oserror(self) -> None:
        from cantrip.agent.preflight import detect_microcloud

        with (
            patch("cantrip.agent.preflight.shutil.which", return_value="/usr/bin/snap"),
            patch("cantrip.agent.preflight.subprocess.run", side_effect=OSError("boom")),
        ):
            assert detect_microcloud() is False


class TestCurrentControllerCloud:
    """``_current_controller_cloud`` extracts the cloud-name of the active controller."""

    def test_returns_empty_when_juju_returns_nothing(self) -> None:
        from cantrip.agent.preflight import _current_controller_cloud

        with patch("cantrip.agent.preflight._run_juju_json", return_value=None):
            assert _current_controller_cloud() == ""

    def test_returns_cloud_when_present(self) -> None:
        from cantrip.agent.preflight import _current_controller_cloud

        payload = {"my-controller": {"details": {"cloud": "openstack"}}}
        with patch("cantrip.agent.preflight._run_juju_json", return_value=payload):
            assert _current_controller_cloud() == "openstack"

    def test_returns_empty_when_details_missing(self) -> None:
        from cantrip.agent.preflight import _current_controller_cloud

        # No ``details`` key — old controller versions used a different shape;
        # be tolerant rather than crashing on it.
        payload = {"my-controller": {"foo": "bar"}}
        with patch("cantrip.agent.preflight._run_juju_json", return_value=payload):
            assert _current_controller_cloud() == ""


class TestSubstrateSummary:
    """``substrate_summary`` composes the three substrate probes."""

    def test_openstack_target_flag_set_by_active_cloud(self) -> None:
        from cantrip.agent.preflight import substrate_summary

        with (
            patch(
                "cantrip.agent.preflight.list_controllers",
                return_value=[
                    {"name": "openstack", "cloud": "openstack", "is_k8s": False, "models": 1}
                ],
            ),
            patch("cantrip.agent.preflight._current_controller_cloud", return_value="openstack"),
            patch("cantrip.agent.preflight.detect_microcloud", return_value=False),
        ):
            summary = substrate_summary()
        assert summary.active_cloud == "openstack"
        assert summary.openstack_target is True
        assert summary.microcloud_detected is False
        assert summary.controllers[0]["cloud"] == "openstack"

    def test_sunbeam_cloud_also_flags_openstack_target(self) -> None:
        """Sunbeam exposes the same OpenStack tenant API — treat as one."""
        from cantrip.agent.preflight import substrate_summary

        with (
            patch("cantrip.agent.preflight.list_controllers", return_value=[]),
            patch("cantrip.agent.preflight._current_controller_cloud", return_value="sunbeam"),
            patch("cantrip.agent.preflight.detect_microcloud", return_value=False),
        ):
            summary = substrate_summary()
        assert summary.openstack_target is True

    def test_lxd_controller_with_microcloud_snap(self) -> None:
        from cantrip.agent.preflight import substrate_summary

        with (
            patch(
                "cantrip.agent.preflight.list_controllers",
                return_value=[{"name": "lxd", "cloud": "localhost", "is_k8s": False, "models": 0}],
            ),
            patch("cantrip.agent.preflight._current_controller_cloud", return_value="localhost"),
            patch("cantrip.agent.preflight.detect_microcloud", return_value=True),
        ):
            summary = substrate_summary()
        assert summary.openstack_target is False
        assert summary.microcloud_detected is True
        assert summary.active_cloud == "localhost"

    def test_no_controllers_returns_empty_summary(self) -> None:
        from cantrip.agent.preflight import substrate_summary

        with (
            patch("cantrip.agent.preflight.list_controllers", return_value=[]),
            patch("cantrip.agent.preflight._current_controller_cloud", return_value=""),
            patch("cantrip.agent.preflight.detect_microcloud", return_value=False),
        ):
            summary = substrate_summary()
        assert summary.controllers == []
        assert summary.active_cloud == ""
        assert summary.openstack_target is False
        assert summary.microcloud_detected is False
