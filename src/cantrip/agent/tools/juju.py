"""Juju operation tools via Jubilant."""

import json
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Jubilant import - will fail gracefully if not available
try:
    import jubilant

    JUBILANT_AVAILABLE = True
except ImportError:
    JUBILANT_AVAILABLE = False


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
        if not JUBILANT_AVAILABLE:
            return ToolResult(
                success=False,
                output="",
                error="Jubilant not available. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            status = juju.status()

            # Format output
            output_lines = [f"Model: {status.model.name}"]

            for app_name, app in status.apps.items():
                status_str = app.status.current if app.status else "unknown"
                output_lines.append(f"\nApp: {app_name} ({status_str})")

                for unit_name, unit in app.units.items():
                    unit_status = (
                        unit.workload_status.current if unit.workload_status else "unknown"
                    )
                    output_lines.append(f"  - {unit_name}: {unit_status}")

            return ToolResult(
                success=True,
                output="\n".join(output_lines),
                data={"model": status.model.name, "apps": list(status.apps.keys())},
            )
        except Exception as e:
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
    ) -> ToolResult:
        """Deploy a charm."""
        if not JUBILANT_AVAILABLE:
            return ToolResult(
                success=False,
                output="",
                error="Jubilant not available. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)

            # Build deploy arguments
            deploy_args: dict[str, Any] = {"charm": charm}
            if app_name:
                deploy_args["app"] = app_name
            if config:
                deploy_args["config"] = config
            if num_units != 1:
                deploy_args["num_units"] = num_units

            juju.deploy(**deploy_args)

            return ToolResult(
                success=True,
                output=f"Deployed {charm}" + (f" as {app_name}" if app_name else ""),
                data={"charm": charm, "app_name": app_name or charm},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


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
            },
            "required": ["app_name"],
        }

    async def execute(
        self,
        app_name: str,
        path: str | None = None,
        model: str | None = None,
    ) -> ToolResult:
        """Refresh a charm."""
        if not JUBILANT_AVAILABLE:
            return ToolResult(
                success=False,
                output="",
                error="Jubilant not available. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            refresh_args: dict[str, Any] = {"app": app_name}
            if path:
                refresh_args["path"] = path

            juju.refresh(**refresh_args)

            return ToolResult(
                success=True,
                output=f"Refreshed {app_name}" + (f" from {path}" if path else ""),
                data={"app_name": app_name, "path": path},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


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
        if not JUBILANT_AVAILABLE:
            return ToolResult(
                success=False,
                output="",
                error="Jubilant not available. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            juju.integrate(app1, app2)

            return ToolResult(
                success=True,
                output=f"Created relation: {app1} <-> {app2}",
                data={"app1": app1, "app2": app2},
            )
        except Exception as e:
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
        if not JUBILANT_AVAILABLE:
            return ToolResult(
                success=False,
                output="",
                error="Jubilant not available. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            result = juju.ssh(unit, command)

            return ToolResult(
                success=True,
                output=result,
                data={"unit": unit, "command": command},
            )
        except Exception as e:
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
        if not JUBILANT_AVAILABLE:
            return ToolResult(
                success=False,
                output="",
                error="Jubilant not available. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            result = juju.run(unit, action, **(params or {}))

            return ToolResult(
                success=True,
                output=json.dumps(result, indent=2) if isinstance(result, dict) else str(result),
                data={"unit": unit, "action": action, "result": result},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
