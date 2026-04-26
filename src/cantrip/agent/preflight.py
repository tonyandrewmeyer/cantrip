"""Background environment preflight checks.

Runs concierge/Juju setup proactively so the environment is ready by the
time the user describes their charm.

Phase 1 (warm_up): installs snaps (Juju, LXD, craft tools) without
bootstrapping a controller.

Phase 2 (bootstrap): bootstraps a controller for the chosen substrate
and ensures a COS model is deployed.
"""

import asyncio
import collections.abc
import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import jubilant

from cantrip.agent.state import AgentState
from cantrip.agent.tools.environment import (
    _concierge_already_running,
    _concierge_available,
    _is_already_provisioned,
    _juju_controller_healthy,
    _run_concierge,
)

log = logging.getLogger(__name__)

# Default preset used when the charm type is not yet known.  k8s is the most
# common substrate, and if the user later picks "machine" a re-bootstrap is
# fast because snaps are already cached.
DEFAULT_PRESET = "k8s"

# Concierge config that installs LXD + craft tools but skips bootstrap.
_WARMUP_CONFIG = """\
providers:
  lxd:
    enable: true
    bootstrap: false
"""


class CheckStatus(StrEnum):
    """Status of a single preflight check."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PreflightEvent:
    """An event emitted during preflight checks."""

    check_name: str
    status: CheckStatus
    message: str
    detail: str = ""


@dataclass
class PreflightResult:
    """Aggregate result of all preflight checks."""

    concierge_available: bool = False
    juju_available: bool = False
    controller_ready: bool = False
    cos_model: str | None = None
    cos_ready: bool = False
    cos_controller: str | None = None  # Controller hosting COS (if cross-controller)
    preset: str | None = None
    controllers: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def fully_ready(self) -> bool:
        """True when Juju, controller, and COS are all ready."""
        return self.juju_available and self.controller_ready and self.cos_ready

    @property
    def is_cross_controller(self) -> bool:
        """True when COS is on a different controller than the dev model."""
        return self.cos_controller is not None


PreflightCallback = collections.abc.Callable[[PreflightEvent], Any]


class PreflightRunner:
    """Runs background environment preflight checks."""

    def __init__(
        self,
        state: AgentState,
        callback: PreflightCallback | None = None,
    ) -> None:
        self._state = state
        self._callback = callback
        self.result = PreflightResult()

    def _emit(self, check_name: str, status: CheckStatus, message: str, detail: str = "") -> None:
        """Emit a preflight event through the callback.

        A callback failure (TUI widget gone, broken pipe in CLI print)
        must not abort preflight — the underlying environment work
        matters more than the UI notification.
        """
        event = PreflightEvent(
            check_name=check_name,
            status=status,
            message=message,
            detail=detail,
        )
        log.info("preflight: %s — %s: %s", check_name, status, message)
        if self._callback:
            try:
                self._callback(event)
            except Exception:  # noqa: BLE001 - UI surface failure can't break the run.
                log.debug("preflight callback raised for %s", check_name, exc_info=True)

    async def warm_up(self) -> PreflightResult:
        """Phase 1: install snaps and LXD without bootstrapping.

        Writes a temporary concierge config with ``bootstrap: false`` and
        runs ``concierge prepare``.  After that, checks whether the
        ``juju`` CLI is on PATH.
        """
        # Check concierge availability.
        self._emit("concierge", CheckStatus.RUNNING, "Checking for Concierge")
        if not _concierge_available():
            self._emit("concierge", CheckStatus.SKIPPED, "Concierge not installed")
            self.result.concierge_available = False
            # Without concierge we can still check for juju directly.
            self._check_juju()
            return self.result

        self.result.concierge_available = True
        self._emit("concierge", CheckStatus.PASSED, "Concierge found")

        # Refuse to launch while another concierge process is running.
        if _concierge_already_running():
            msg = "Another concierge process is already running — skipping warm_up"
            self._emit("snap_install", CheckStatus.SKIPPED, msg)
            self._check_juju()
            return self.result

        # Write temporary config and run concierge prepare.
        self._emit(
            "snap_install", CheckStatus.RUNNING, "Installing snaps (Juju, LXD, craft tools)"
        )
        config_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".yaml",
                prefix="cantrip-warmup-",
                delete=False,
            ) as tmp:
                tmp.write(_WARMUP_CONFIG)
                config_path = Path(tmp.name)

            rc, stdout, stderr = await _run_concierge(
                "prepare", "-c", str(config_path), timeout=600
            )
            if rc != 0:
                msg = f"concierge prepare failed (exit {rc})"
                self._emit("snap_install", CheckStatus.FAILED, msg, detail=stderr.strip())
                self.result.errors.append(f"{msg}: {stderr.strip()}")
            else:
                self._emit("snap_install", CheckStatus.PASSED, "Snaps installed")
        except TimeoutError:
            msg = "concierge prepare timed out"
            self._emit("snap_install", CheckStatus.FAILED, msg)
            self.result.errors.append(msg)
        finally:
            if config_path and config_path.exists():
                config_path.unlink()

        self._check_juju()
        return self.result

    async def prepare(self, preset: str = DEFAULT_PRESET) -> PreflightResult:
        """Run the full environment preparation in one pass.

        Runs ``concierge prepare --preset {preset}`` (which installs snaps
        *and* bootstraps a controller), then verifies the controller and
        deploys COS.  This is the eager path used at startup so the
        environment is ready by the time the user finishes describing their
        charm.
        """
        self.result.preset = preset

        # Check concierge availability.
        self._emit("concierge", CheckStatus.RUNNING, "Checking for Concierge")
        if not _concierge_available():
            self._emit("concierge", CheckStatus.SKIPPED, "Concierge not installed")
            self.result.concierge_available = False
            self._check_juju()
            self._emit("controller", CheckStatus.SKIPPED, "No concierge — skipping bootstrap")
            self._emit("cos", CheckStatus.SKIPPED, "No concierge — skipping COS")
            return self.result

        self.result.concierge_available = True
        self._emit("concierge", CheckStatus.PASSED, "Concierge found")

        # Refuse to launch while another concierge process is running.
        if _concierge_already_running():
            msg = "Another concierge process is already running — skipping prepare"
            self._emit("prepare", CheckStatus.SKIPPED, msg)
            self.result.errors.append(msg)
            self._check_juju()
            return self.result

        # Skip if already provisioned — concierge prepare is not fully
        # idempotent and can break the k8s cluster if run twice.
        provisioned, mismatch_cloud = await _is_already_provisioned(preset)
        if provisioned:
            self._emit("prepare", CheckStatus.PASSED, "Environment already provisioned (skipped)")
            self._check_juju()

            # Still verify the controller is healthy.
            self._emit("controller", CheckStatus.RUNNING, "Checking controller")
            if _juju_controller_healthy():
                self.result.controller_ready = True
                self._emit("controller", CheckStatus.PASSED, "Controller ready")
            else:
                self.result.controller_ready = False
                self._emit("controller", CheckStatus.FAILED, "Controller not ready")
                self.result.errors.append("Controller check failed")
                return self.result

            cos_model_name = self._state.cos_model or "cos"
            self._emit("cos", CheckStatus.RUNNING, f"Checking COS model ({cos_model_name})")
            await self._ensure_cos(cos_model_name)
            return self.result

        # Mismatched existing controller — refuse to clobber it with concierge.
        if mismatch_cloud is not None:
            msg = (
                f"Healthy controller on cloud '{mismatch_cloud}' does not match "
                f"preset '{preset}' — skipping concierge prepare"
            )
            self._emit("prepare", CheckStatus.SKIPPED, msg)
            self.result.errors.append(msg)
            self._check_juju()
            return self.result

        # Run the full concierge prepare with the preset.
        self._emit(
            "prepare",
            CheckStatus.RUNNING,
            f"Preparing environment ({preset})",
        )
        try:
            rc, stdout, stderr = await _run_concierge(
                "prepare",
                "--preset",
                preset,
                timeout=600,
            )
            if rc != 0:
                msg = f"concierge prepare --preset {preset} failed (exit {rc})"
                self._emit("prepare", CheckStatus.FAILED, msg, detail=stderr.strip())
                self.result.errors.append(f"{msg}: {stderr.strip()}")
                self._check_juju()
                return self.result
            self._emit("prepare", CheckStatus.PASSED, "Environment prepared")
        except TimeoutError:
            msg = "concierge prepare timed out"
            self._emit("prepare", CheckStatus.FAILED, msg)
            self.result.errors.append(msg)
            self._check_juju()
            return self.result

        self._check_juju()

        # Check controller.
        self._emit("controller", CheckStatus.RUNNING, "Checking controller")
        if _juju_controller_healthy():
            self.result.controller_ready = True
            self._emit("controller", CheckStatus.PASSED, "Controller ready")
        else:
            self.result.controller_ready = False
            self._emit("controller", CheckStatus.FAILED, "Controller not ready")
            self.result.errors.append("Controller check failed after prepare")
            return self.result

        # Check / deploy COS.
        cos_model_name = self._state.cos_model or "cos"
        self._emit("cos", CheckStatus.RUNNING, f"Checking COS model ({cos_model_name})")
        await self._ensure_cos(cos_model_name)

        return self.result

    def _check_juju(self) -> None:
        """Check whether the juju CLI is available."""
        self._emit("juju", CheckStatus.RUNNING, "Checking for Juju CLI")
        if shutil.which("juju"):
            self.result.juju_available = True
            self._emit("juju", CheckStatus.PASSED, "Juju CLI found")
        else:
            self.result.juju_available = False
            self._emit("juju", CheckStatus.FAILED, "Juju CLI not found")

    async def bootstrap(self, preset: str) -> PreflightResult:
        """Phase 2: bootstrap a controller and deploy COS.

        Runs ``concierge prepare --preset {preset}`` (snaps are already
        cached from phase 1 so this mostly just bootstraps), then checks
        the controller and COS model.
        """
        # Refuse to launch while another concierge process is running.
        if _concierge_already_running():
            msg = "Another concierge process is already running — skipping bootstrap"
            self._emit("bootstrap", CheckStatus.SKIPPED, msg)
            self.result.errors.append(msg)
            return self.result

        # Skip if already provisioned — concierge prepare is not fully
        # idempotent and can break the k8s cluster if run twice.
        provisioned, mismatch_cloud = await _is_already_provisioned(preset)
        if provisioned:
            self._emit(
                "bootstrap",
                CheckStatus.PASSED,
                "Environment already provisioned (skipped)",
            )

            self._emit("controller", CheckStatus.RUNNING, "Checking controller")
            if _juju_controller_healthy():
                self.result.controller_ready = True
                self._emit("controller", CheckStatus.PASSED, "Controller ready")
            else:
                self.result.controller_ready = False
                self._emit("controller", CheckStatus.FAILED, "Controller not ready")
                self.result.errors.append("Controller check failed")
                return self.result

            cos_model_name = self._state.cos_model or "cos"
            self._emit("cos", CheckStatus.RUNNING, f"Checking COS model ({cos_model_name})")
            await self._ensure_cos(cos_model_name)
            return self.result

        # Mismatched existing controller — refuse to clobber it with concierge.
        if mismatch_cloud is not None:
            msg = (
                f"Healthy controller on cloud '{mismatch_cloud}' does not match "
                f"preset '{preset}' — skipping concierge bootstrap"
            )
            self._emit("bootstrap", CheckStatus.SKIPPED, msg)
            self.result.errors.append(msg)
            return self.result

        # Run concierge prepare with the full preset.
        self._emit("bootstrap", CheckStatus.RUNNING, f"Bootstrapping controller ({preset})")
        try:
            rc, stdout, stderr = await _run_concierge("prepare", "--preset", preset, timeout=600)
            if rc != 0:
                msg = f"concierge prepare --preset {preset} failed (exit {rc})"
                self._emit("bootstrap", CheckStatus.FAILED, msg, detail=stderr.strip())
                self.result.errors.append(f"{msg}: {stderr.strip()}")
                return self.result
            self._emit("bootstrap", CheckStatus.PASSED, "Controller bootstrapped")
        except TimeoutError:
            msg = "Controller bootstrap timed out"
            self._emit("bootstrap", CheckStatus.FAILED, msg)
            self.result.errors.append(msg)
            return self.result

        # Check controller.
        self._emit("controller", CheckStatus.RUNNING, "Checking controller")
        if _juju_controller_healthy():
            self.result.controller_ready = True
            self._emit("controller", CheckStatus.PASSED, "Controller ready")
        else:
            self.result.controller_ready = False
            self._emit("controller", CheckStatus.FAILED, "Controller not ready")
            self.result.errors.append("Controller check failed after bootstrap")
            return self.result

        # Check / deploy COS.
        cos_model_name = self._state.cos_model or "cos"
        self._emit("cos", CheckStatus.RUNNING, f"Checking COS model ({cos_model_name})")
        await self._ensure_cos(cos_model_name)

        return self.result

    async def _ensure_cos(self, cos_model_name: str) -> None:
        """Ensure a COS model exists and has cos-lite deployed.

        cos-lite contains only Kubernetes charms, so it can only be deployed
        on a K8s controller.  When the active controller is IAAS (e.g. LXD),
        a separate K8s controller is detected automatically (Phase 22) and
        COS is deployed there with cross-model offers for observability.
        """
        if not self.result.controllers:
            self.result.controllers = await asyncio.to_thread(list_controllers)

        # Decide which controller will host COS — the current one if it's
        # K8s, otherwise a separate K8s controller.  All subsequent checks
        # and creation attempts target this controller explicitly so we
        # don't look for the model on an IAAS controller that can't host it.
        cos_controller: str | None = None
        if not _current_controller_is_k8s():
            cos_controller = await asyncio.to_thread(_find_k8s_controller)
            if not cos_controller:
                self._emit(
                    "cos",
                    CheckStatus.SKIPPED,
                    "No Kubernetes controller found — COS requires K8s",
                )
                return
            self.result.cos_controller = cos_controller

        juju = await self._check_cos_model(cos_model_name, cos_controller)
        if juju is None:
            return

        if not await self._deploy_cos_lite(juju, cos_model_name):
            return

        await self._create_cos_offers(cos_model_name)

    async def _check_cos_model(
        self,
        cos_model_name: str,
        cos_controller: str | None,
    ) -> jubilant.Juju | None:
        """Check the COS model on the target controller, creating it if needed.

        ``cos_controller`` is the controller that should host COS, or
        ``None`` to use the current controller.  Returns a ``Juju`` instance
        targeting the COS model when cos-lite still needs to be deployed,
        or ``None`` when the model is already ready, was skipped, or
        creation failed.
        """
        target = f"{cos_controller}:{cos_model_name}" if cos_controller else cos_model_name
        try:
            juju = jubilant.Juju(model=target)
            status = await asyncio.to_thread(juju.status)
            if status.apps:
                self.result.cos_ready = True
                self.result.cos_model = cos_model_name
                self._state.cos_model = cos_model_name
                self._emit("cos", CheckStatus.PASSED, "COS model ready")
                return None
            if not _model_is_k8s(target):
                self._emit(
                    "cos",
                    CheckStatus.SKIPPED,
                    "COS model is on a non-Kubernetes cloud",
                )
                return None
            self._emit("cos", CheckStatus.RUNNING, "Deploying cos-lite")
            return juju
        except jubilant.CLIError:
            return await self._create_cos_model(cos_model_name, cos_controller)

    async def _create_cos_model(
        self,
        cos_model_name: str,
        cos_controller: str | None,
    ) -> jubilant.Juju | None:
        """Create the COS model on the target controller.

        ``cos_controller`` is the K8s controller that should host COS, or
        ``None`` to use the current (K8s) controller.  Returns a ``Juju``
        instance for the new model, or ``None`` if creation failed.
        """
        if cos_controller is None:
            self._emit("cos", CheckStatus.RUNNING, f"Creating model {cos_model_name}")
            try:
                juju_default = jubilant.Juju()
                await asyncio.to_thread(juju_default.add_model, cos_model_name)
                return jubilant.Juju(model=cos_model_name)
            except jubilant.CLIError as exc:
                self._emit(
                    "cos",
                    CheckStatus.FAILED,
                    "Failed to create COS model",
                    detail=str(exc),
                )
                self.result.errors.append(f"COS model creation failed: {exc}")
                return None

        self._emit(
            "cos",
            CheckStatus.RUNNING,
            f"Creating COS model on K8s controller '{cos_controller}'",
        )
        rc, stderr = await asyncio.to_thread(
            _create_model_on_controller, cos_model_name, cos_controller
        )
        if rc != 0:
            self._emit(
                "cos",
                CheckStatus.FAILED,
                f"Failed to create COS model on controller '{cos_controller}'",
                detail=stderr.strip(),
            )
            self.result.errors.append(
                f"COS model creation on {cos_controller} failed: {stderr.strip()}"
            )
            return None
        return jubilant.Juju(model=f"{cos_controller}:{cos_model_name}")

    async def _deploy_cos_lite(self, juju: jubilant.Juju, cos_model_name: str) -> bool:
        """Deploy cos-lite into the COS model.

        Returns ``True`` on success, ``False`` on failure.
        """
        try:
            await asyncio.to_thread(juju.deploy, "cos-lite", trust=True)
            self.result.cos_ready = True
            self.result.cos_model = cos_model_name
            self._state.cos_model = cos_model_name
            self._emit("cos", CheckStatus.PASSED, "COS deployed")
            return True
        except jubilant.CLIError as exc:
            self._emit("cos", CheckStatus.FAILED, "COS deployment failed", detail=str(exc))
            self.result.errors.append(f"COS deployment failed: {exc}")
            return False

    async def _create_cos_offers(self, cos_model_name: str) -> None:
        """Set up cross-model offers if COS is on a different controller."""
        if _current_controller_is_k8s():
            return
        # Reaching this line means ``_ensure_cos`` decided we need a
        # separate K8s controller, so it has already populated
        # ``cos_controller`` (or returned early).  No fallback needed.
        assert self.result.cos_controller is not None
        self._emit("cos", CheckStatus.RUNNING, "Setting up cross-model COS offers")
        target = f"{self.result.cos_controller}:{cos_model_name}"
        offers = await asyncio.to_thread(_setup_cos_cross_model_offers, target)
        if offers:
            self._emit(
                "cos",
                CheckStatus.PASSED,
                f"COS offers created: {', '.join(offers)}",
            )
        else:
            self._emit(
                "cos",
                CheckStatus.PASSED,
                "COS deployed (offers will be configured during charm integration)",
            )


_K8S_CLOUDS = frozenset({"k8s", "microk8s", "kubernetes"})


def _run_juju_json(args: list[str], *, timeout: int = 15) -> dict[str, Any] | None:
    """Run a juju subcommand expecting JSON output; return the parsed dict.

    Returns ``None`` when juju isn't on PATH, the command failed,
    timed out, or the output isn't parseable.  All discovery callers
    here treat any of those as "no information available", so a
    single shared envelope is enough.
    """
    juju_bin = shutil.which("juju")
    if not juju_bin:
        return None
    try:
        result = subprocess.run(
            [juju_bin, *args, "--format=json"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return None
        parsed = json.loads(result.stdout)
        return parsed if isinstance(parsed, dict) else None
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None


def _model_is_k8s(model_name: str) -> bool:
    """Check whether an existing model is on a Kubernetes cloud.

    Accepts either a plain model name or ``controller:model`` syntax.  The
    JSON returned by ``juju show-model`` is keyed on the bare model name
    regardless of how the model was specified, so we inspect the first
    value rather than looking up by key.
    """
    data = _run_juju_json(["show-model", model_name], timeout=10)
    if not data:
        return False
    model_info = next(iter(data.values()), {})
    return model_info.get("model-type", "") == "caas"


def _current_controller_is_k8s() -> bool:
    """Check whether the current controller is on a Kubernetes cloud."""
    data = _run_juju_json(["show-controller"], timeout=10)
    if not data:
        return False
    for info in data.values():
        details = info.get("details", {})
        if details.get("cloud", "") in _K8S_CLOUDS:
            return True
    return False


def _find_k8s_controller() -> str | None:
    """Find a K8s controller among all registered Juju controllers.

    Returns the controller name, or ``None`` if no K8s controller exists.
    Used when the active controller is IAAS (LXD) and COS needs to be
    deployed on a separate K8s controller (e.g. ``concierge-k8s``).
    """
    data = _run_juju_json(["controllers"])
    if not data:
        return None
    for name, info in data.get("controllers", {}).items():
        if info.get("cloud", "") in _K8S_CLOUDS:
            return name
    return None


def list_controllers() -> list[dict[str, Any]]:
    """Enumerate all registered Juju controllers with their cloud types.

    Returns a list of dicts with ``name``, ``cloud``, ``is_k8s``, and
    ``models`` count.  Used by the preflight multi-controller report.
    """
    data = _run_juju_json(["controllers"])
    if not data:
        return []
    controllers = data.get("controllers", {})
    return [
        {
            "name": name,
            "cloud": info.get("cloud", ""),
            "is_k8s": info.get("cloud", "") in _K8S_CLOUDS,
            "models": info.get("model-count", 0),
        }
        for name, info in sorted(controllers.items())
    ]


def _create_model_on_controller(
    model_name: str,
    controller: str,
) -> tuple[int, str]:
    """Create a Juju model on a specific controller.

    Returns ``(returncode, stderr)``.  A non-zero returncode indicates
    failure; ``stderr`` carries the juju CLI error message for diagnostics.
    """
    juju_bin = shutil.which("juju")
    if not juju_bin:
        return 1, "juju CLI not found on PATH"
    try:
        result = subprocess.run(
            [juju_bin, "add-model", model_name, "-c", controller],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "add-model timed out"
    except OSError as exc:
        return 1, str(exc)


def _setup_cos_cross_model_offers(cos_model: str) -> list[str]:
    """Create cross-model offers for COS endpoints.

    Offers grafana, prometheus, loki, and tempo endpoints so that
    charms on other controllers can consume them.  Returns a list of
    offer URLs (e.g. ``cos.grafana:grafana-dashboard``).
    """
    juju_bin = shutil.which("juju")
    if not juju_bin:
        return []

    # COS-lite app names and their offer-worthy endpoints.
    cos_endpoints = [
        ("grafana", "grafana-dashboard"),
        ("prometheus", "receive-remote-write"),
        ("loki", "logging"),
        ("tempo", "tracing"),
    ]

    offers: list[str] = []
    for app_hint, endpoint in cos_endpoints:
        # Find the actual app name (may be grafana-k8s, prometheus-k8s, etc.).
        try:
            result = subprocess.run(
                [juju_bin, "status", "--model", cos_model, "--format=json"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                continue
            status = json.loads(result.stdout)
            app_name = None
            for name in status.get("applications", {}):
                if app_hint in name:
                    app_name = name
                    break
            if not app_name:
                continue
        except (subprocess.TimeoutExpired, OSError, ValueError):
            continue

        # Create the offer.
        try:
            result = subprocess.run(
                [juju_bin, "offer", "--model", cos_model, f"{app_name}:{endpoint}"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                offers.append(f"{cos_model}.{app_name}:{endpoint}")
        except (subprocess.TimeoutExpired, OSError):
            pass

    return offers
