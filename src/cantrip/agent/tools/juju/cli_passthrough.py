"""Juju passthrough tools: arbitrary CLI escape hatch and trust management."""

from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.juju import _common


class JujuTrustTool(Tool):
    """Tool to grant or revoke trust for a deployed application.

    Used when a charm's status message directs the operator to run
    ``juju trust <app> --scope=cluster`` (common for Kubernetes charms
    that need cluster-wide privileges, e.g. MongoDB in-place refreshes).
    """

    @property
    def name(self) -> str:
        return "juju_trust"

    @property
    def description(self) -> str:
        return (
            "Grant or revoke trust for a deployed application. "
            "On Kubernetes models, pass scope='cluster' (required when the "
            "app's blocked message asks for `juju trust <app> --scope=cluster`). "
            "Set remove=true to revoke previously granted trust."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "Application name to set trust status for.",
                },
                "scope": {
                    "type": "string",
                    "description": (
                        "On Kubernetes models, must be 'cluster'. Omit on machine models."
                    ),
                    "enum": ["cluster"],
                },
                "remove": {
                    "type": "boolean",
                    "description": "Revoke trust instead of granting it.",
                    "default": False,
                },
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified).",
                },
            },
            "required": ["app_name"],
        }

    async def execute(
        self,
        app_name: str,
        scope: str | None = None,
        remove: bool = False,
        model: str | None = None,
    ) -> ToolResult:
        """Set trust status for a deployed application."""
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = _common.jubilant.Juju(model=model)
            trust_kwargs: dict[str, Any] = {"app": app_name, "remove": remove}
            if scope is not None:
                trust_kwargs["scope"] = scope
            await _common._run_juju(juju.trust, **trust_kwargs)

            action = "Revoked trust for" if remove else "Granted trust to"
            scope_note = f" (scope={scope})" if scope else ""
            verb = "Revoked trust" if remove else "Trusted"
            return ToolResult(
                success=True,
                output=f"{action} {app_name}{scope_note}",
                data={"app_name": app_name, "scope": scope, "remove": remove},
                caption=f"{verb} {app_name}",
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju trust timed out — the controller may be unavailable.",
            )
        except _common.jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class JujuCliTool(Tool):
    """Escape hatch for juju subcommands without a typed wrapper.

    The ``juju`` binary is deliberately *not* on the ``run_command``
    allowlist (snap + sandbox PID-namespace incompatibility), so this
    tool is the only way to run juju commands that don't have a
    dedicated ``juju_*`` tool — e.g. ``juju controllers``,
    ``juju add-credential``, ``juju spaces``.  Calls land via
    :meth:`jubilant.Juju.cli`, which uses plain subprocess and bypasses
    the sandbox.  Prefer the typed tools when one fits — those expose
    structured results, while this tool only returns juju's stdout.
    """

    @property
    def name(self) -> str:
        return "juju_cli"

    @property
    def description(self) -> str:
        return (
            "Run an arbitrary juju subcommand (e.g. controllers, "
            "add-credential, spaces) and return its stdout. Use only "
            "when no typed juju_* tool fits — the typed tools expose "
            "structured data, this one just returns raw text."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Arguments to pass to juju, excluding the leading "
                        "'juju' (e.g. ['controllers', '--refresh'])."
                    ),
                },
                "model": {
                    "type": "string",
                    "description": (
                        "Optional model name; injected as --model. "
                        "Omit for commands that don't take a model."
                    ),
                },
            },
            "required": ["args"],
        }

    async def execute(
        self,
        args: list[str] | None = None,
        model: str | None = None,
    ) -> ToolResult:
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )
        if not args:
            return ToolResult(
                success=False,
                output="",
                error="args is required and must be non-empty.",
            )

        try:
            juju = _common.jubilant.Juju(model=model) if model else _common.jubilant.Juju()
            stdout = await _common._run_juju(juju.cli, *args, include_model=bool(model))
            return ToolResult(
                success=True,
                output=stdout,
                data={"args": args, "model": model},
                caption=f"juju {args[0]}",
            )
        except (TimeoutError, OSError) as e:
            return ToolResult(success=False, output="", error=str(e))
        except _common.jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output=e.stdout or "",
                error=e.stderr or f"juju {args[0]} failed",
            )
