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
import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import jubilant

from cantrip.agent.state import AgentState
from cantrip.agent.tools.environment import (
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
    preset: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def fully_ready(self) -> bool:
        """True when Juju, controller, and COS are all ready."""
        return self.juju_available and self.controller_ready and self.cos_ready


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
        """Emit a preflight event through the callback."""
        event = PreflightEvent(
            check_name=check_name,
            status=status,
            message=message,
            detail=detail,
        )
        log.info("preflight: %s — %s: %s", check_name, status, message)
        if self._callback:
            self._callback(event)

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

        # Skip if already provisioned — concierge prepare is not fully
        # idempotent and can break the k8s cluster if run twice.
        if await _is_already_provisioned():
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
        # Skip if already provisioned — concierge prepare is not fully
        # idempotent and can break the k8s cluster if run twice.
        if await _is_already_provisioned():
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
        """Ensure a COS model exists and has cos-lite deployed."""
        try:
            juju = jubilant.Juju(model=cos_model_name)
            status = juju.status()
            if status.apps:
                # COS model exists and has apps — assume ready.
                self.result.cos_ready = True
                self.result.cos_model = cos_model_name
                self._state.cos_model = cos_model_name
                self._emit("cos", CheckStatus.PASSED, "COS model ready")
                return
            # Model exists but is empty — deploy cos-lite.
            self._emit("cos", CheckStatus.RUNNING, "Deploying cos-lite")
        except jubilant.CLIError:
            # Model does not exist — create it first.
            self._emit("cos", CheckStatus.RUNNING, f"Creating model {cos_model_name}")
            try:
                juju_default = jubilant.Juju()
                await asyncio.to_thread(juju_default.add_model, cos_model_name)
                juju = jubilant.Juju(model=cos_model_name)
            except jubilant.CLIError as exc:
                self._emit(
                    "cos", CheckStatus.FAILED, "Failed to create COS model", detail=str(exc)
                )
                self.result.errors.append(f"COS model creation failed: {exc}")
                return

        # Deploy cos-lite into the model.
        try:
            await asyncio.to_thread(juju.deploy, "cos-lite", trust=True)
            self.result.cos_ready = True
            self.result.cos_model = cos_model_name
            self._state.cos_model = cos_model_name
            self._emit("cos", CheckStatus.PASSED, "COS deployed")
        except jubilant.CLIError as exc:
            self._emit("cos", CheckStatus.FAILED, "COS deployment failed", detail=str(exc))
            self.result.errors.append(f"COS deployment failed: {exc}")
