"""Juju secret inspection tools (metadata only; contents never revealed)."""

from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.juju import _common


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
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = _common.jubilant.Juju(model=model)
            kwargs: dict[str, Any] = {}
            if owner:
                kwargs["owner"] = owner
            secrets = await _common._run_juju(juju.secrets, **kwargs)

            if not secrets:
                return ToolResult(
                    success=True,
                    output="No secrets found in the model.",
                    data={"secrets": [], "count": 0},
                    caption="no secrets",
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
                caption=f"{len(secrets)} secret{'s' if len(secrets) != 1 else ''}",
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju secrets timed out — the controller may be unavailable.",
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


class JujuShowSecretTool(Tool):
    """Tool to inspect a specific Juju secret."""

    @property
    def name(self) -> str:
        return "juju_show_secret"

    @property
    def description(self) -> str:
        return (
            "Show metadata of a specific Juju secret by name or URI. "
            "Secret contents are never revealed to protect sensitive data."
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
            },
            "required": ["identifier"],
        }

    async def execute(
        self,
        identifier: str,
        model: str | None = None,
    ) -> ToolResult:
        """Show metadata of a specific secret (contents are never revealed)."""
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = _common.jubilant.Juju(model=model)
            secret = await _common._run_juju(juju.show_secret, identifier, reveal=False)

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

            return ToolResult(
                success=True,
                output="\n".join(lines),
                data=data,
                caption=f"Secret {secret.name or identifier} (rev {secret.revision})",
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju show-secret timed out.",
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
