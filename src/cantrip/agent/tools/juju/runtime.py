"""Juju runtime introspection and execution tools.

Status, SSH, action/dispatch, wait, config (read/write), and unit
inspection — the tools used during the test/run phase of charm work.
"""

import asyncio
import functools
import json
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.juju import _common


class JujuStatusTool(Tool):
    """Tool to get Juju model status."""

    @property
    def name(self) -> str:
        return "juju_status"

    @property
    def description(self) -> str:
        return "Get the current status of a Juju model, including all applications and units."

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        model = arguments.get("model")
        return f"Reading juju status ({model})…" if model else "Reading juju status…"

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
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = _common.jubilant.Juju(model=model)
            status = await _common._run_juju(juju.status)

            # Format output. Status messages are included verbatim so the
            # agent can act on operator hints like
            # ``Run `juju trust <app> --scope=cluster```.
            output_lines = [f"Model: {status.model.name}"]

            for app_name, app in status.apps.items():
                status_str = app.app_status.current or "unknown"
                app_msg = (app.app_status.message or "").strip()
                app_line = f"\nApp: {app_name} ({status_str})"
                if app_msg:
                    app_line += f" — {app_msg}"
                output_lines.append(app_line)

                for unit_name, unit in app.units.items():
                    unit_status = unit.workload_status.current or "unknown"
                    unit_msg = (unit.workload_status.message or "").strip()
                    unit_line = f"  - {unit_name}: {unit_status}"
                    if unit_msg:
                        unit_line += f" — {unit_msg}"
                    output_lines.append(unit_line)

            app_count = len(status.apps)
            blocked = sum(
                1
                for app in status.apps.values()
                if (app.app_status.current or "").lower() == "blocked"
            )
            caption_parts = [f"{app_count} app{'s' if app_count != 1 else ''}"]
            if blocked:
                caption_parts.append(f"{blocked} blocked")
            return ToolResult(
                success=True,
                output="\n".join(output_lines),
                data={"model": status.model.name, "apps": list(status.apps.keys())},
                caption=", ".join(caption_parts),
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju status timed out — the controller may be unavailable.",
            )
        except (
            _common.jubilant.CLIError,
            _common.jubilant.TaskError,
            OSError,
            ValueError,
        ) as e:
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
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = _common.jubilant.Juju(model=model)
            result = await _common._run_juju(juju.ssh, unit, command)

            # Cap output to prevent context overflow.
            output = result if isinstance(result, str) else str(result)
            truncated = False
            if len(output) > 8000:
                output = output[:8000]
                truncated = True

            # Caption: short command + unit, truncated for readability.
            cmd_preview = command.split("\n")[0]
            if len(cmd_preview) > 30:
                cmd_preview = cmd_preview[:29] + "…"
            return ToolResult(
                success=True,
                output=output + ("\n…(output truncated at 8000 chars)" if truncated else ""),
                data={"unit": unit, "command": command, "truncated": truncated},
                caption=f"ssh {unit}: {cmd_preview}",
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju ssh timed out — the unit may be unreachable.",
            )
        except (
            _common.jubilant.CLIError,
            _common.jubilant.TaskError,
            OSError,
            ValueError,
        ) as e:
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
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = _common.jubilant.Juju(model=model)
            result = await _common._run_juju(juju.run, unit, action, **(params or {}))

            return ToolResult(
                success=True,
                output=json.dumps(result, indent=2) if isinstance(result, dict) else str(result),
                data={"unit": unit, "action": action, "result": result},
                caption=f"Ran {action} on {unit}",
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju run timed out — the action is taking too long.",
            )
        except (
            _common.jubilant.CLIError,
            _common.jubilant.TaskError,
            OSError,
            ValueError,
        ) as e:
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
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = _common.jubilant.Juju(model=model)
            result = await _common._run_juju(juju.config, app_name, values=values)

            if values:
                if len(values) == 1:
                    k, v = next(iter(values.items()))
                    caption = f"Set {app_name}: {k}={v}"
                else:
                    caption = f"Set {app_name}: {len(values)} values"
                return ToolResult(
                    success=True,
                    output=f"Config updated for {app_name}: {values}",
                    data={"app_name": app_name, "values": values},
                    caption=caption,
                )

            # Get mode — format the returned config for display.
            return ToolResult(
                success=True,
                output=json.dumps(result, indent=2, default=str),
                data={"app_name": app_name, "config": result},
                caption=f"Read {app_name} config",
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju config timed out — the controller may be unavailable.",
            )
        except _common.jubilant.CLIError as e:
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

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        app = arguments.get("app_name")
        model = arguments.get("model")
        target = f"{app} ({model})" if app and model else (app or model)
        return f"Waiting for {target} to settle…" if target else "Waiting for the model to settle…"

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
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = _common.jubilant.Juju(model=model)
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
                caption=f"{app_name} settled (active/idle)",
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error=f"Timed out waiting for {app_name} to reach active/idle after {timeout}s.",
            )
        except _common.jubilant.CLIError as e:
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
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        # Guard against shell metacharacters in the event name.
        if not _common.re.fullmatch(r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?", event):
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Invalid event name '{event}'. "
                    "Must contain only lowercase letters, digits, hyphens, and underscores."
                ),
            )

        charm_dir = _common._agent_charm_dir(unit)
        dispatch_cmd = f"JUJU_DISPATCH_PATH=hooks/{event} {charm_dir}/dispatch"

        try:
            juju = _common.jubilant.Juju(model=model)
            k8s = await _common._is_k8s_model(juju)

            if k8s:
                output = await _common._run_juju(juju.ssh, unit, dispatch_cmd, container="charm")
            else:
                output = await _common._run_juju(juju.ssh, unit, f"sudo {dispatch_cmd}")

            return ToolResult(
                success=True,
                output=output or f"Event '{event}' dispatched on {unit} (no output).",
                data={"unit": unit, "event": event},
                caption=f"Dispatched {event} on {unit}",
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju dispatch timed out — the unit may be unreachable.",
            )
        except _common.jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
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
    charm_dir = _common.pathlib.Path(charm_path)

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
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )
        parsed = await self._fetch_config_json(model, app)
        if isinstance(parsed, ToolResult):
            return parsed
        settings = parsed.get("settings", {})
        lines, config_list, user_set_count = self._render_config_table(settings, app)
        validation = self._render_validation_block(lines, config_list, charm_path)
        caption = f"{app} config: {user_set_count} user-set, {len(config_list)} total"
        if validation:
            caption += (
                f" ({len(validation)} validation issue{'s' if len(validation) != 1 else ''})"
            )
        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={
                "app": app,
                "config": config_list,
                "user_set_count": user_set_count,
                "validation_issues": validation,
            },
            caption=caption,
        )

    @staticmethod
    async def _fetch_config_json(model: str | None, app: str) -> dict[str, Any] | ToolResult:
        """Run ``juju config <app> --format json`` and parse the envelope."""
        try:
            juju = _common.jubilant.Juju(model=model)
            stdout = await _common._run_juju(juju.cli, "config", app, "--format", "json")
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju config timed out.",
            )
        except (_common.jubilant.CLIError, OSError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=f"juju config failed: {e}",
            )
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            return ToolResult(
                success=False,
                output="",
                error="Failed to parse juju config output.",
            )

    @staticmethod
    def _render_config_table(
        settings: dict[str, Any], app: str
    ) -> tuple[list[str], list[dict[str, Any]], int]:
        """Format the per-key config table; return (lines, structured rows, user-set count)."""
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
        return lines, config_list, user_set_count

    @staticmethod
    def _render_validation_block(
        lines: list[str],
        config_list: list[dict[str, Any]],
        charm_path: str | None,
    ) -> list[dict[str, str]]:
        """Cross-reference deployed config against charmcraft.yaml; append findings to *lines*."""
        if not charm_path:
            return []
        validation = _validate_config_against_charm({c["name"] for c in config_list}, charm_path)
        if validation:
            lines.append("")
            lines.append("## Validation Issues")
            lines.append("")
            for issue in validation:
                lines.append(f"  ! {issue['key']}: {issue['issue']}")
        return validation


class JujuShowUnitTool(Tool):
    """Tool to show detailed information about a unit."""

    @property
    def name(self) -> str:
        return "juju_show_unit"

    @property
    def description(self) -> str:
        return (
            "Show detailed information about a Juju unit, including "
            "relation data, opened ports, and workload status."
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
        model: str | None = None,
    ) -> ToolResult:
        """Run juju show-unit."""
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = _common.jubilant.Juju(model=model)
            stdout = await _common._run_juju(
                juju.cli,
                "show-unit",
                unit,
                "--format",
                "json",
                include_model=bool(model),
            )

            # Parse and re-format for readability.
            try:
                data = json.loads(stdout)
                output = json.dumps(data, indent=2)
            except json.JSONDecodeError:
                output = stdout

            return ToolResult(
                success=True,
                output=output,
                data={"unit": unit},
                caption=f"Show {unit}",
            )
        except (TimeoutError, OSError) as e:
            return ToolResult(success=False, output="", error=str(e))
        except _common.jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output=e.stdout or "",
                error=e.stderr or f"Failed to show unit {unit}",
            )
