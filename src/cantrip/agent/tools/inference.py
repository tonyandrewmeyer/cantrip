"""Inference snap discovery tool."""

from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult


class ListInferenceSnapsTool(Tool):
    """List locally installed Ubuntu inference snaps."""

    @property
    def name(self) -> str:
        return "list_inference_snaps"

    @property
    def description(self) -> str:
        return (
            "List Ubuntu inference snaps installed on this machine. "
            "Each snap serves a local AI model via an OpenAI-compatible API. "
            "Returns snap names, default ports, and whether each is reachable."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self) -> ToolResult:
        """Discover installed inference snaps and their status."""
        import httpx

        from cantrip.llm.inference_snap import (
            _SNAP_DEFAULTS,
            discover_snap_endpoint,
            list_available_snaps,
        )

        installed = list_available_snaps()
        if not installed:
            return ToolResult(
                success=True,
                output=(
                    "No inference snaps found. Known snaps: "
                    + ", ".join(sorted(_SNAP_DEFAULTS))
                    + ". Install with: sudo snap install <name>"
                ),
            )

        lines = []
        for snap in sorted(installed):
            endpoint = discover_snap_endpoint(snap)
            # Quick health check.
            status = "unreachable"
            model_name = "unknown"
            try:
                with httpx.Client(timeout=5.0) as client:
                    resp = client.get(f"{endpoint}/models")
                    if resp.status_code == 200:
                        data = resp.json()
                        models = data.get("data", [])
                        if models:
                            model_name = models[0].get("id", "unknown")
                        status = "running"
            except httpx.HTTPError:
                pass

            lines.append(f"  {snap}: {status} (endpoint: {endpoint}, model: {model_name})")

        return ToolResult(
            success=True,
            output="Installed inference snaps:\n" + "\n".join(lines),
            data={"snaps": installed},
        )
