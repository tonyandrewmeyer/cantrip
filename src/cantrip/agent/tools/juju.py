"""Juju operation tools via Jubilant."""

import asyncio
import functools
import json
import os
import re
import shlex
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import jubilant

from cantrip.agent.tools.base import Tool, ToolResult

# Default timeout for Jubilant operations (seconds).
_JUJU_TIMEOUT = 120


def _juju_available() -> bool:
    """Check whether the juju CLI is installed."""
    return shutil.which("juju") is not None


async def _run_juju(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a blocking Jubilant call in a thread with a timeout.

    Prevents a hung Juju CLI from blocking the entire event loop.
    """
    return await asyncio.wait_for(
        asyncio.to_thread(functools.partial(func, *args, **kwargs)),
        timeout=_JUJU_TIMEOUT,
    )


def _agent_charm_dir(unit: str) -> str:
    """Convert a unit name like ``my-app/0`` to its on-disk charm directory.

    Raises ``ValueError`` if the unit name is not in ``app/number`` format.
    """
    parts = unit.split("/")
    if len(parts) != 2 or not parts[1].isdigit():
        raise ValueError(f"Invalid unit name '{unit}'. Expected format: 'app-name/0'")
    return f"/var/lib/juju/agents/unit-{parts[0]}-{parts[1]}/charm"


async def _is_k8s_model(juju: jubilant.Juju) -> bool:
    """Return True if the current model is a Kubernetes (CAAS) model."""
    info = await _run_juju(juju.show_model)
    return info.model_type == "caas"


class JujuStatusTool(Tool):
    """Tool to get Juju model status."""

    @property
    def name(self) -> str:
        return "juju_status"

    @property
    def description(self) -> str:
        return "Get the current status of a Juju model, including all applications and units."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
            },
        }

    async def execute(self, model: str | None = None) -> ToolResult:
        """Get juju status."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            status = await _run_juju(juju.status)

            # Format output
            output_lines = [f"Model: {status.model.name}"]

            for app_name, app in status.apps.items():
                status_str = app.app_status.current or "unknown"
                output_lines.append(f"\nApp: {app_name} ({status_str})")

                for unit_name, unit in app.units.items():
                    unit_status = unit.workload_status.current or "unknown"
                    output_lines.append(f"  - {unit_name}: {unit_status}")

            return ToolResult(
                success=True,
                output="\n".join(output_lines),
                data={"model": status.model.name, "apps": list(status.apps.keys())},
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju status timed out — the controller may be unavailable.",
            )
        except (jubilant.CLIError, jubilant.TaskError, OSError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class JujuDeployTool(Tool):
    """Tool to deploy a charm."""

    @property
    def name(self) -> str:
        return "juju_deploy"

    @property
    def description(self) -> str:
        return "Deploy a charm to the current Juju model."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "charm": {
                    "type": "string",
                    "description": "Charm name or path to .charm file",
                },
                "app_name": {
                    "type": "string",
                    "description": "Application name (defaults to charm name)",
                },
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
                "config": {
                    "type": "object",
                    "description": "Configuration options as key-value pairs",
                },
                "num_units": {
                    "type": "integer",
                    "description": "Number of units to deploy",
                    "default": 1,
                },
                "resources": {
                    "type": "object",
                    "description": (
                        "Named resources as key-value pairs. "
                        "For 12-factor charms: {'oci-image': 'localhost:32000/my-app:latest'}"
                    ),
                },
                "trust": {
                    "type": "boolean",
                    "description": "Grant the charm access to cloud credentials.",
                    "default": False,
                },
            },
            "required": ["charm"],
        }

    async def execute(
        self,
        charm: str,
        app_name: str | None = None,
        model: str | None = None,
        config: dict[str, Any] | None = None,
        num_units: int = 1,
        resources: dict[str, str] | None = None,
        trust: bool = False,
    ) -> ToolResult:
        """Deploy a charm."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        temp_copy: Path | None = None
        try:
            juju = jubilant.Juju(model=model)

            # Resolve local .charm paths to absolute so juju doesn't
            # misinterpret them as Charmhub names.
            charm_path = Path(charm)
            if charm_path.suffix == ".charm" and charm_path.exists():
                charm = str(charm_path.resolve())
            elif not charm_path.is_absolute() and (Path.cwd() / charm_path).exists():
                charm = str((Path.cwd() / charm_path).resolve())

            # The Juju snap uses strict confinement and cannot read files
            # outside the user's home directory.  If the charm file lives
            # in a non-accessible location (e.g. /tmp), copy it to a
            # snap-accessible path before deploying.
            charm_file = Path(charm)
            if charm_file.suffix == ".charm" and charm_file.exists():
                home = Path.home()
                if not str(charm_file).startswith(str(home)):
                    snap_dir = home / "snap" / "juju" / "common"
                    snap_dir.mkdir(parents=True, exist_ok=True)
                    temp_copy = snap_dir / charm_file.name
                    shutil.copy2(charm_file, temp_copy)
                    charm = str(temp_copy)

            # Build deploy arguments.
            deploy_args: dict[str, Any] = {"charm": charm}
            if app_name:
                deploy_args["app"] = app_name
            if config:
                deploy_args["config"] = config
            if num_units != 1:
                deploy_args["num_units"] = num_units
            if resources:
                deploy_args["resources"] = resources
            if trust:
                deploy_args["trust"] = True

            await asyncio.wait_for(
                asyncio.to_thread(functools.partial(juju.deploy, **deploy_args)),
                timeout=300,
            )

            return ToolResult(
                success=True,
                output=f"Deployed {charm}" + (f" as {app_name}" if app_name else ""),
                data={"charm": charm, "app_name": app_name or charm},
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju deploy timed out — the operation is taking too long.",
            )
        except (jubilant.CLIError, jubilant.TaskError, OSError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
        finally:
            if temp_copy is not None and temp_copy.exists():
                temp_copy.unlink(missing_ok=True)


class JujuRefreshTool(Tool):
    """Tool to refresh (upgrade) a deployed charm."""

    @property
    def name(self) -> str:
        return "juju_refresh"

    @property
    def description(self) -> str:
        return "Refresh a deployed charm with a new version or local .charm file."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "Application name to refresh",
                },
                "path": {
                    "type": "string",
                    "description": "Path to local .charm file",
                },
                "model": {
                    "type": "string",
                    "description": "Model name",
                },
                "resources": {
                    "type": "object",
                    "description": (
                        "Named resources as key-value pairs. "
                        "For 12-factor charms: {'oci-image': 'localhost:32000/my-app:latest'}"
                    ),
                },
            },
            "required": ["app_name"],
        }

    async def execute(
        self,
        app_name: str,
        path: str | None = None,
        model: str | None = None,
        resources: dict[str, str] | None = None,
    ) -> ToolResult:
        """Refresh a charm."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        temp_copy: Path | None = None
        try:
            juju = jubilant.Juju(model=model)
            refresh_args: dict[str, Any] = {"app": app_name}
            if path:
                # Copy to snap-accessible path if needed (same as deploy).
                charm_file = Path(path)
                if charm_file.suffix == ".charm" and charm_file.exists():
                    home = Path.home()
                    if not str(charm_file.resolve()).startswith(str(home)):
                        snap_dir = home / "snap" / "juju" / "common"
                        snap_dir.mkdir(parents=True, exist_ok=True)
                        temp_copy = snap_dir / charm_file.name
                        shutil.copy2(charm_file, temp_copy)
                        path = str(temp_copy)
                refresh_args["path"] = path
            if resources:
                refresh_args["resources"] = resources

            await _run_juju(juju.refresh, **refresh_args)

            return ToolResult(
                success=True,
                output=f"Refreshed {app_name}" + (f" from {path}" if path else ""),
                data={"app_name": app_name, "path": path},
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju refresh timed out — the controller may be unavailable.",
            )
        except jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
        finally:
            if temp_copy is not None and temp_copy.exists():
                temp_copy.unlink(missing_ok=True)


class JujuRelateTool(Tool):
    """Tool to create a relation between applications."""

    @property
    def name(self) -> str:
        return "juju_relate"

    @property
    def description(self) -> str:
        return "Create a relation (integration) between two applications."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app1": {
                    "type": "string",
                    "description": "First application (optionally with :endpoint)",
                },
                "app2": {
                    "type": "string",
                    "description": "Second application (optionally with :endpoint)",
                },
                "model": {
                    "type": "string",
                    "description": "Model name",
                },
            },
            "required": ["app1", "app2"],
        }

    async def execute(
        self,
        app1: str,
        app2: str,
        model: str | None = None,
    ) -> ToolResult:
        """Create a relation."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            await _run_juju(juju.integrate, app1, app2)

            return ToolResult(
                success=True,
                output=f"Created relation: {app1} <-> {app2}",
                data={"app1": app1, "app2": app2},
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju integrate timed out — the controller may be unavailable.",
            )
        except (jubilant.CLIError, jubilant.TaskError, OSError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class JujuSSHTool(Tool):
    """Tool to run commands on a unit via SSH."""

    @property
    def name(self) -> str:
        return "juju_ssh"

    @property
    def description(self) -> str:
        return (
            "Run a command on a Juju unit via SSH. "
            "Useful for quick code updates during development."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "unit": {
                    "type": "string",
                    "description": "Unit name (e.g., 'my-app/0')",
                },
                "command": {
                    "type": "string",
                    "description": "Command to execute",
                },
                "model": {
                    "type": "string",
                    "description": "Model name",
                },
            },
            "required": ["unit", "command"],
        }

    async def execute(
        self,
        unit: str,
        command: str,
        model: str | None = None,
    ) -> ToolResult:
        """Run SSH command on a unit."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            result = await _run_juju(juju.ssh, unit, command)

            return ToolResult(
                success=True,
                output=result,
                data={"unit": unit, "command": command},
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju ssh timed out — the unit may be unreachable.",
            )
        except (jubilant.CLIError, jubilant.TaskError, OSError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class JujuRunActionTool(Tool):
    """Tool to run an action on a unit."""

    @property
    def name(self) -> str:
        return "juju_run_action"

    @property
    def description(self) -> str:
        return "Run a charm action on a unit and return the result."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "unit": {
                    "type": "string",
                    "description": "Unit name (e.g., 'my-app/0')",
                },
                "action": {
                    "type": "string",
                    "description": "Action name",
                },
                "params": {
                    "type": "object",
                    "description": "Action parameters",
                },
                "model": {
                    "type": "string",
                    "description": "Model name",
                },
            },
            "required": ["unit", "action"],
        }

    async def execute(
        self,
        unit: str,
        action: str,
        params: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> ToolResult:
        """Run an action."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            result = await _run_juju(juju.run, unit, action, **(params or {}))

            return ToolResult(
                success=True,
                output=json.dumps(result, indent=2) if isinstance(result, dict) else str(result),
                data={"unit": unit, "action": action, "result": result},
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju run timed out — the action is taking too long.",
            )
        except (jubilant.CLIError, jubilant.TaskError, OSError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class JujuAddModelTool(Tool):
    """Tool to create a new Juju model."""

    @property
    def name(self) -> str:
        return "juju_add_model"

    @property
    def description(self) -> str:
        return (
            "Create a new Juju model. Use this for dev models or a dedicated COS model. "
            "For 12-factor / PaaS charms (flask-framework, django-framework, etc.), "
            "specify cloud='k8s' to create the model on a Kubernetes cloud."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Name for the new model",
                },
                "cloud": {
                    "type": "string",
                    "description": (
                        "Cloud (or cloud/region) to create the model on. "
                        "Use 'k8s' for Kubernetes charms, 'localhost' for machine charms. "
                        "Defaults to the controller's default cloud."
                    ),
                },
            },
            "required": ["model"],
        }

    async def execute(self, model: str, cloud: str | None = None) -> ToolResult:
        """Create a Juju model."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju()
            await _run_juju(juju.add_model, model, cloud=cloud)

            suffix = f" on cloud '{cloud}'" if cloud else ""
            return ToolResult(
                success=True,
                output=f"Model '{model}' created{suffix}.",
                data={"model": model, "cloud": cloud},
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju add-model timed out — the controller may be unavailable.",
            )
        except jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class JujuDestroyModelTool(Tool):
    """Tool to destroy a Juju model."""

    @property
    def name(self) -> str:
        return "juju_destroy_model"

    @property
    def description(self) -> str:
        return "Destroy a Juju model and all its applications. Use with caution."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Name of the model to destroy",
                },
                "force": {
                    "type": "boolean",
                    "description": "Force destruction, ignoring errors",
                    "default": False,
                },
            },
            "required": ["model"],
        }

    async def execute(self, model: str, force: bool = False) -> ToolResult:
        """Destroy a Juju model."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju()
            await _run_juju(
                juju.destroy_model,
                model,
                force=force,
                destroy_storage=True,
                no_wait=force,
            )

            return ToolResult(
                success=True,
                output=f"Model '{model}' destruction initiated.",
                data={"model": model, "force": force},
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju destroy-model timed out — the controller may be unavailable.",
            )
        except jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class JujuOfferTool(Tool):
    """Tool to create a cross-model offer."""

    @property
    def name(self) -> str:
        return "juju_offer"

    @property
    def description(self) -> str:
        return (
            "Create a cross-model offer for an application endpoint. "
            "This makes the endpoint available for consumption from other models."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "Application name to create the offer for",
                },
                "endpoint": {
                    "type": "string",
                    "description": "Endpoint name to offer (e.g. 'grafana-dashboard')",
                },
                "model": {
                    "type": "string",
                    "description": "Model where the application lives (uses current if not set)",
                },
            },
            "required": ["app", "endpoint"],
        }

    async def execute(
        self,
        app: str,
        endpoint: str,
        model: str | None = None,
    ) -> ToolResult:
        """Create a cross-model offer."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            await _run_juju(juju.offer, app, endpoint=endpoint)

            return ToolResult(
                success=True,
                output=f"Offer created: {app}:{endpoint}",
                data={"app": app, "endpoint": endpoint, "model": model},
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju offer timed out — the controller may be unavailable.",
            )
        except jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class JujuConsumeTool(Tool):
    """Tool to consume a cross-model offer."""

    @property
    def name(self) -> str:
        return "juju_consume"

    @property
    def description(self) -> str:
        return (
            "Consume a cross-model offer in the current model. "
            "After consuming, use juju_relate to integrate with local applications."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model_and_app": {
                    "type": "string",
                    "description": "Remote offer in 'model.app' format (e.g. 'cos.grafana')",
                },
                "alias": {
                    "type": "string",
                    "description": "Local alias for the consumed offer",
                },
                "model": {
                    "type": "string",
                    "description": "Model to consume the offer into (uses current if not set)",
                },
            },
            "required": ["model_and_app"],
        }

    async def execute(
        self,
        model_and_app: str,
        alias: str | None = None,
        model: str | None = None,
    ) -> ToolResult:
        """Consume a cross-model offer."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            await _run_juju(juju.consume, model_and_app, alias)

            label = alias or model_and_app.split(".")[-1]
            return ToolResult(
                success=True,
                output=f"Consumed offer '{model_and_app}' as '{label}'.",
                data={
                    "model_and_app": model_and_app,
                    "alias": alias,
                    "model": model,
                },
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju consume timed out — the controller may be unavailable.",
            )
        except jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class JujuConfigTool(Tool):
    """Tool to get or set application configuration."""

    @property
    def name(self) -> str:
        return "juju_config"

    @property
    def description(self) -> str:
        return (
            "Get or set configuration values for a deployed application. "
            "Call without values to read the current config, or with values to set them."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "Application name",
                },
                "values": {
                    "type": "object",
                    "description": (
                        "Config values to set as key-value pairs. "
                        "Omit to read the current configuration."
                    ),
                },
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
            },
            "required": ["app_name"],
        }

    async def execute(
        self,
        app_name: str,
        values: dict[str, str] | None = None,
        model: str | None = None,
    ) -> ToolResult:
        """Get or set application config."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            result = await _run_juju(juju.config, app_name, values=values)

            if values:
                return ToolResult(
                    success=True,
                    output=f"Config updated for {app_name}: {values}",
                    data={"app_name": app_name, "values": values},
                )

            # Get mode — format the returned config for display.
            return ToolResult(
                success=True,
                output=json.dumps(result, indent=2, default=str),
                data={"app_name": app_name, "config": result},
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju config timed out — the controller may be unavailable.",
            )
        except jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class JujuWaitTool(Tool):
    """Tool to wait for an application to reach active/idle."""

    @property
    def name(self) -> str:
        return "juju_wait"

    @property
    def description(self) -> str:
        return (
            "Wait for an application to reach active/idle status. "
            "Use after deploy or refresh instead of polling juju_status."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "Application name to wait for",
                },
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 300)",
                    "default": 300,
                },
            },
            "required": ["app_name"],
        }

    async def execute(
        self,
        app_name: str,
        model: str | None = None,
        timeout: int = 300,
    ) -> ToolResult:
        """Wait for an application to settle."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            status = await asyncio.wait_for(
                asyncio.to_thread(
                    functools.partial(
                        juju.wait,
                        lambda s: (
                            app_name in s.apps
                            and s.apps[app_name].app_status.current == "active"
                            and all(
                                u.workload_status.current == "active"
                                and u.juju_status.current == "idle"
                                for u in s.apps[app_name].units.values()
                            )
                        ),
                        timeout=timeout,
                    )
                ),
                timeout=900,
            )

            app = status.apps[app_name]
            units_info = ", ".join(
                f"{name}: {u.workload_status.current}" for name, u in app.units.items()
            )
            return ToolResult(
                success=True,
                output=f"{app_name} is active/idle. Units: {units_info}",
                data={"app_name": app_name, "status": app.app_status.current},
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error=f"Timed out waiting for {app_name} to reach active/idle after {timeout}s.",
            )
        except jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class CharmSyncTool(Tool):
    """Tool to push local Python source files directly to a running unit.

    This bypasses the pack/refresh cycle for rapid iteration on Python-only
    changes. Each hook invocation starts a fresh Python process, so
    overwriting ``.py`` files on disk is sufficient.
    """

    @property
    def name(self) -> str:
        return "charm_sync"

    @property
    def description(self) -> str:
        return (
            "Push local Python source files (src/, lib/) directly to a running unit, "
            "bypassing charmcraft pack. Use for rapid iteration on Python-only changes. "
            "Always validate with a full pack/refresh before declaring the charm done."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "unit": {
                    "type": "string",
                    "description": "Unit name (e.g., 'my-app/0')",
                },
                "charm_dir": {
                    "type": "string",
                    "description": (
                        "Local charm directory containing src/ and lib/. "
                        "Defaults to the current working directory."
                    ),
                },
                "directories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Directories to sync (default: ['src', 'lib'])",
                },
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
            },
            "required": ["unit"],
        }

    async def execute(
        self,
        unit: str,
        charm_dir: str | None = None,
        directories: list[str] | None = None,
        model: str | None = None,
    ) -> ToolResult:
        """Sync local Python source to a running unit."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        local_root = Path(charm_dir) if charm_dir else Path.cwd()
        dirs_to_sync = directories or ["src", "lib"]
        remote_root = _agent_charm_dir(unit)

        try:
            juju = jubilant.Juju(model=model)
            k8s = await _is_k8s_model(juju)

            # Collect all .py files from the requested directories.
            files: list[tuple[Path, str]] = []
            for dir_name in dirs_to_sync:
                local_dir = local_root / dir_name
                if not local_dir.is_dir():
                    continue
                for root, _dirs, filenames in os.walk(local_dir):
                    for fname in filenames:
                        if not fname.endswith(".py"):
                            continue
                        local_path = Path(root) / fname
                        relative = local_path.relative_to(local_root)
                        remote_path = f"{remote_root}/{relative}"
                        files.append((local_path, remote_path))

            if not files:
                return ToolResult(
                    success=True,
                    output=f"No .py files found in {dirs_to_sync}. Nothing to sync.",
                    data={"files_synced": 0},
                )

            # Push each file to the unit.
            for local_path, remote_path in files:
                remote_parent = str(Path(remote_path).parent)
                safe_parent = shlex.quote(remote_parent)
                safe_path = shlex.quote(remote_path)

                if k8s:
                    await _run_juju(
                        juju.ssh,
                        unit,
                        f"mkdir -p {safe_parent}",
                        container="charm",
                    )
                    await _run_juju(
                        juju.scp,
                        str(local_path),
                        f"{unit}:{remote_path}",
                        container="charm",
                    )
                else:
                    await _run_juju(juju.ssh, unit, f"sudo mkdir -p {safe_parent}")
                    content = local_path.read_text()
                    await _run_juju(
                        juju.cli,
                        "ssh",
                        unit,
                        f"sudo tee {safe_path}",
                        stdin=content,
                    )

            synced_names = [str(f[0].relative_to(local_root)) for f in files]
            return ToolResult(
                success=True,
                output=(
                    f"Synced {len(files)} file(s) to {unit}:\n"
                    + "\n".join(f"  {n}" for n in synced_names)
                ),
                data={"files_synced": len(files), "files": synced_names},
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="charm sync timed out — the unit may be unreachable.",
            )
        except jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class JujuDispatchTool(Tool):
    """Tool to fire a charm event on a unit via dispatch.

    Best suited for simple events like ``update-status`` or
    ``config-changed``. Relation events lack the full context that Juju
    normally provides, so prefer a real ``juju config`` or ``juju relate``
    for those.
    """

    @property
    def name(self) -> str:
        return "juju_dispatch"

    @property
    def description(self) -> str:
        return (
            "Fire a charm event on a unit by invoking the dispatch script directly. "
            "Use after charm_sync to trigger the new code. Best for simple events "
            "like update-status or config-changed; relation events lack full context."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "unit": {
                    "type": "string",
                    "description": "Unit name (e.g., 'my-app/0')",
                },
                "event": {
                    "type": "string",
                    "description": ("Event to dispatch (e.g., 'update-status', 'config-changed')"),
                },
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
            },
            "required": ["unit", "event"],
        }

    async def execute(
        self,
        unit: str,
        event: str,
        model: str | None = None,
    ) -> ToolResult:
        """Fire a charm event on a unit."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        # Guard against shell metacharacters in the event name.
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?", event):
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Invalid event name '{event}'. "
                    "Must contain only lowercase letters, digits, hyphens, and underscores."
                ),
            )

        charm_dir = _agent_charm_dir(unit)
        dispatch_cmd = f"JUJU_DISPATCH_PATH=hooks/{event} {charm_dir}/dispatch"

        try:
            juju = jubilant.Juju(model=model)
            k8s = await _is_k8s_model(juju)

            if k8s:
                output = await _run_juju(juju.ssh, unit, dispatch_cmd, container="charm")
            else:
                output = await _run_juju(juju.ssh, unit, f"sudo {dispatch_cmd}")

            return ToolResult(
                success=True,
                output=output or f"Event '{event}' dispatched on {unit} (no output).",
                data={"unit": unit, "event": event},
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju dispatch timed out — the unit may be unreachable.",
            )
        except jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class JujuListSecretsTool(Tool):
    """Tool to list Juju secrets in the current model."""

    @property
    def name(self) -> str:
        return "juju_list_secrets"

    @property
    def description(self) -> str:
        return (
            "List all Juju secrets in the model with owner, granted applications, "
            "and rotation policy. Useful for verifying secrets are correctly "
            "created and granted during charm development."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
                "owner": {
                    "type": "string",
                    "description": "Filter by owner application name",
                },
            },
        }

    async def execute(
        self,
        model: str | None = None,
        owner: str | None = None,
    ) -> ToolResult:
        """List all secrets in the model."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            kwargs: dict[str, Any] = {}
            if owner:
                kwargs["owner"] = owner
            secrets = await _run_juju(juju.secrets, **kwargs)

            if not secrets:
                return ToolResult(
                    success=True,
                    output="No secrets found in the model.",
                    data={"secrets": [], "count": 0},
                )

            lines = [f"Found {len(secrets)} secret(s):", ""]
            secret_data: list[dict[str, Any]] = []

            for secret in secrets:
                name = secret.name or "(unnamed)"
                lines.append(f"- **{name}** ({secret.uri})")
                lines.append(f"  Owner: {secret.owner}")
                lines.append(f"  Revision: {secret.revision}")
                if secret.rotation:
                    lines.append(f"  Rotation: {secret.rotation}")
                if secret.description:
                    lines.append(f"  Description: {secret.description}")
                if secret.access:
                    granted = ", ".join(f"{a.scope}:{a.role}" for a in secret.access)
                    lines.append(f"  Access: {granted}")
                lines.append("")

                secret_data.append(
                    {
                        "uri": str(secret.uri),
                        "name": secret.name,
                        "owner": secret.owner,
                        "revision": secret.revision,
                        "rotation": secret.rotation,
                        "description": secret.description,
                        "created": str(secret.created),
                    }
                )

            return ToolResult(
                success=True,
                output="\n".join(lines),
                data={"secrets": secret_data, "count": len(secrets)},
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju secrets timed out — the controller may be unavailable.",
            )
        except (jubilant.CLIError, jubilant.TaskError, OSError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class JujuShowSecretTool(Tool):
    """Tool to inspect a specific Juju secret."""

    @property
    def name(self) -> str:
        return "juju_show_secret"

    @property
    def description(self) -> str:
        return (
            "Show details of a specific Juju secret by name or URI. "
            "Optionally reveals the secret content (use with caution — "
            "secrets may contain sensitive data like passwords and tokens)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "identifier": {
                    "type": "string",
                    "description": (
                        "Secret name or URI (e.g. 'db-credentials' or 'secret:abc123')"
                    ),
                },
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
                "reveal": {
                    "type": "boolean",
                    "description": "Reveal secret content (default false)",
                    "default": False,
                },
            },
            "required": ["identifier"],
        }

    async def execute(
        self,
        identifier: str,
        model: str | None = None,
        reveal: bool = False,
    ) -> ToolResult:
        """Show details of a specific secret."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            secret = await _run_juju(juju.show_secret, identifier, reveal=reveal)

            lines = [f"Secret: {secret.name or identifier}", ""]
            lines.append(f"URI: {secret.uri}")
            lines.append(f"Owner: {secret.owner}")
            lines.append(f"Revision: {secret.revision}")
            lines.append(f"Created: {secret.created}")
            lines.append(f"Updated: {secret.updated}")
            if secret.rotation:
                lines.append(f"Rotation: {secret.rotation}")
            if secret.expires:
                lines.append(f"Expires: {secret.expires}")
            if secret.description:
                lines.append(f"Description: {secret.description}")
            if secret.access:
                lines.append("Access:")
                for access in secret.access:
                    lines.append(f"  - {access.scope}: {access.role}")

            data: dict[str, Any] = {
                "uri": str(secret.uri),
                "name": secret.name,
                "owner": secret.owner,
                "revision": secret.revision,
                "created": str(secret.created),
                "updated": str(secret.updated),
                "rotation": secret.rotation,
            }

            # If revealed, include the content.
            if reveal and hasattr(secret, "content"):
                content = secret.content
                lines.append("")
                lines.append("Content:")
                if isinstance(content, dict):
                    for key, value in content.items():
                        lines.append(f"  {key}: {value}")
                    data["content"] = content
                else:
                    lines.append(f"  {content}")
                    data["content"] = str(content)

            return ToolResult(
                success=True,
                output="\n".join(lines),
                data=data,
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju show-secret timed out.",
            )
        except (jubilant.CLIError, jubilant.TaskError, OSError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class JujuReadRelationDataTool(Tool):
    """Tool to read relation databag contents."""

    @property
    def name(self) -> str:
        return "juju_read_relation_data"

    @property
    def description(self) -> str:
        return (
            "Read app-level and unit-level relation databags for a deployed "
            "application. Shows both sides of a relation to diagnose integration "
            "failures. Returns structured data including provider and requirer "
            "databags."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "unit": {
                    "type": "string",
                    "description": "Unit name (e.g. 'my-app/0')",
                },
                "endpoint": {
                    "type": "string",
                    "description": "Relation endpoint to filter (optional — shows all if omitted)",
                },
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
            },
            "required": ["unit"],
        }

    async def execute(
        self,
        unit: str,
        endpoint: str | None = None,
        model: str | None = None,
    ) -> ToolResult:
        """Read relation data via juju show-unit."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            stdout = await _run_juju(juju.cli, "show-unit", unit, "--format", "json")
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju show-unit timed out.",
            )
        except (jubilant.CLIError, OSError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=f"juju show-unit failed: {e}",
            )

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return ToolResult(
                success=False,
                output="",
                error="Failed to parse juju show-unit output.",
            )

        unit_data = data.get(unit, {})
        relations = unit_data.get("relation-info", [])

        if endpoint:
            relations = [r for r in relations if r.get("endpoint") == endpoint]

        if not relations:
            msg = f"No relation data found for {unit}"
            if endpoint:
                msg += f" on endpoint '{endpoint}'"
            return ToolResult(
                success=True,
                output=msg,
                data={"unit": unit, "relations": []},
            )

        lines = [f"Relation data for {unit}:", ""]
        relation_list: list[dict[str, Any]] = []

        for rel in relations:
            ep = rel.get("endpoint", "unknown")
            rel_id = rel.get("relation-id", "?")
            lines.append(f"## {ep} (relation {rel_id})")
            lines.append("")

            related_units = rel.get("related-units", {})
            app_data = rel.get("application-data", {})

            if app_data:
                lines.append("**Application data:**")
                for key, value in app_data.items():
                    lines.append(f"  {key}: {value}")
                lines.append("")

            local_unit_data = rel.get("local-unit", {}).get("data", {})
            if local_unit_data:
                lines.append(f"**Local unit data ({unit}):**")
                for key, value in local_unit_data.items():
                    lines.append(f"  {key}: {value}")
                lines.append("")

            if related_units:
                for runit, rdata in related_units.items():
                    lines.append(f"**Related unit: {runit}**")
                    unit_rel_data = rdata.get("data", {})
                    for key, value in unit_rel_data.items():
                        lines.append(f"  {key}: {value}")
                    lines.append("")

            # Highlight asymmetries.
            expected_keys = set()
            for rdata in related_units.values():
                expected_keys.update(rdata.get("data", {}).keys())
            missing_in_local = (
                expected_keys
                - set(local_unit_data.keys())
                - {"ingress-address", "private-address", "egress-subnets"}
            )
            if missing_in_local:
                lines.append(
                    f"**Asymmetry:** remote has keys not in local: {', '.join(sorted(missing_in_local))}"
                )
                lines.append("")

            relation_list.append(
                {
                    "endpoint": ep,
                    "relation_id": rel_id,
                    "application_data": app_data,
                    "local_unit_data": local_unit_data,
                    "related_units": {
                        runit: rdata.get("data", {}) for runit, rdata in related_units.items()
                    },
                }
            )

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"unit": unit, "relations": relation_list},
        )


def _validate_config_against_charm(
    deployed_keys: set[str],
    charm_path: str,
) -> list[dict[str, str]]:
    """Cross-reference deployed config keys against charmcraft.yaml declarations.

    Returns a list of validation issues (undeclared keys in deployed config,
    declared keys absent from deployed config).
    """
    import yaml

    issues: list[dict[str, str]] = []
    charm_dir = Path(charm_path)

    # Load declared config options from charmcraft.yaml or config.yaml.
    declared_keys: set[str] = set()
    for config_file in ("charmcraft.yaml", "config.yaml"):
        config_path = charm_dir / config_file
        if not config_path.exists():
            continue
        try:
            with config_path.open() as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                continue
            # charmcraft.yaml has config.options; config.yaml has options at top level.
            config_section = data.get("config", {})
            if isinstance(config_section, dict) and "options" in config_section:
                declared_keys = set(config_section["options"].keys())
                break
            # config.yaml may have options at top level.
            if config_file == "config.yaml" and "options" in data:
                options = data["options"]
                if isinstance(options, dict):
                    declared_keys = set(options.keys())
                    break
        except (yaml.YAMLError, OSError):
            continue

    if not declared_keys:
        return []

    # Keys in deployed config but not declared (may be deprecated or undeclared).
    for key in sorted(deployed_keys - declared_keys):
        issues.append(
            {
                "key": key,
                "issue": "Deployed but not declared in charm config — may be deprecated",
            }
        )

    # Keys declared but not in deployed config (unusual — Juju usually shows all).
    for key in sorted(declared_keys - deployed_keys):
        issues.append(
            {
                "key": key,
                "issue": "Declared in charm but not present in deployed config",
            }
        )

    return issues


class JujuGetAppConfigTool(Tool):
    """Tool to read application config with source tracking."""

    @property
    def name(self) -> str:
        return "juju_get_app_config"

    @property
    def description(self) -> str:
        return (
            "Read all configuration values for a deployed application with "
            "source tracking (default, user-set, or model-default). Optionally "
            "cross-references against charmcraft.yaml to detect undeclared or "
            "deprecated config keys."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "Application name",
                },
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
                "charm_path": {
                    "type": "string",
                    "description": (
                        "Path to the charm directory for config validation "
                        "(cross-references deployed config against charmcraft.yaml)"
                    ),
                },
            },
            "required": ["app"],
        }

    async def execute(
        self,
        app: str,
        model: str | None = None,
        charm_path: str | None = None,
    ) -> ToolResult:
        """Read app config with source information."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            stdout = await _run_juju(juju.cli, "config", app, "--format", "json")
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju config timed out.",
            )
        except (jubilant.CLIError, OSError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=f"juju config failed: {e}",
            )

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return ToolResult(
                success=False,
                output="",
                error="Failed to parse juju config output.",
            )

        settings = data.get("settings", {})
        lines = [f"Configuration for {app}:", ""]
        config_list: list[dict[str, Any]] = []
        user_set_count = 0

        for opt_name, opt_data in sorted(settings.items()):
            if not isinstance(opt_data, dict):
                continue
            source = opt_data.get("source", "default")
            value = opt_data.get("value", "")
            opt_type = opt_data.get("type", "")
            description = opt_data.get("description", "")

            marker = "*" if source != "default" else " "
            lines.append(f"  {marker} {opt_name}: {value} ({opt_type}, {source})")

            if source != "default":
                user_set_count += 1

            config_list.append(
                {
                    "name": opt_name,
                    "value": value,
                    "type": opt_type,
                    "source": source,
                    "description": description,
                }
            )

        if user_set_count:
            lines.append("")
            lines.append(f"* = user-set ({user_set_count} non-default value(s))")

        # Config validation: cross-reference against charmcraft.yaml if provided.
        validation: list[dict[str, str]] = []
        if charm_path:
            validation = _validate_config_against_charm(
                {c["name"] for c in config_list}, charm_path
            )
            if validation:
                lines.append("")
                lines.append("## Validation Issues")
                lines.append("")
                for issue in validation:
                    lines.append(f"  ! {issue['key']}: {issue['issue']}")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={
                "app": app,
                "config": config_list,
                "user_set_count": user_set_count,
                "validation_issues": validation,
            },
        )


class JujuListOffersTool(Tool):
    """Tool to list cross-model offers."""

    @property
    def name(self) -> str:
        return "juju_list_offers"

    @property
    def description(self) -> str:
        return (
            "List cross-model offers in the current model or controller, with "
            "endpoint details and consumer tracking. Useful for diagnosing "
            "cross-model relation issues."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
            },
        }

    async def execute(
        self,
        model: str | None = None,
    ) -> ToolResult:
        """List cross-model offers via juju status (offers section)."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            status = await _run_juju(juju.status)

            offers = status.offers
            if not offers:
                return ToolResult(
                    success=True,
                    output="No cross-model offers found in the model.",
                    data={"offers": [], "count": 0},
                )

            lines = [f"Found {len(offers)} offer(s):", ""]
            offer_list: list[dict[str, Any]] = []

            for offer_name, offer in offers.items():
                lines.append(f"- **{offer_name}** (app: {offer.app}, charm: {offer.charm})")
                lines.append(
                    f"  Connected: {offer.active_connected_count}/{offer.total_connected_count}"
                )
                if offer.endpoints:
                    for ep_name, ep in offer.endpoints.items():
                        lines.append(f"  Endpoint: {ep_name} ({ep.interface})")
                lines.append("")

                offer_list.append(
                    {
                        "name": offer_name,
                        "app": offer.app,
                        "charm": offer.charm,
                        "active_connected": offer.active_connected_count,
                        "total_connected": offer.total_connected_count,
                        "endpoints": {
                            name: {"interface": ep.interface}
                            for name, ep in (offer.endpoints or {}).items()
                        },
                    }
                )

            return ToolResult(
                success=True,
                output="\n".join(lines),
                data={"offers": offer_list, "count": len(offers)},
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju status timed out — the controller may be unavailable.",
            )
        except (jubilant.CLIError, jubilant.TaskError, OSError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
