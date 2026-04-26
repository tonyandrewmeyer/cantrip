"""Inference snap discovery tool."""

from typing import Any

import httpx

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.llm.inference_snap import (
    _SNAP_DEFAULTS,
    discover_snap_endpoint,
    list_available_snaps,
)


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
        installed = list_available_snaps()
        if not installed:
            return ToolResult(
                success=True,
                output=(
                    "No inference snaps found. Known snaps: "
                    + ", ".join(sorted(_SNAP_DEFAULTS))
                    + ". Install with: sudo snap install <name>"
                ),
                caption="no snaps installed",
            )

        lines = []
        running_count = 0
        for snap in sorted(installed):
            endpoint = discover_snap_endpoint(snap)
            # Quick health check.  Catches ``ValueError`` alongside
            # ``httpx.HTTPError`` because a broken snap returning an HTML
            # error page makes ``resp.json()`` raise ``json.JSONDecodeError``
            # (a ``ValueError`` subclass), which would otherwise crash the
            # whole listing tool.  Non-dict payloads (``models = data.get``
            # on a list) are handled by the ``isinstance`` guard.
            status = "unreachable"
            model_name = "unknown"
            try:
                with httpx.Client(timeout=5.0) as client:
                    resp = client.get(f"{endpoint}/models")
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, dict):
                            models = data.get("data", [])
                            if isinstance(models, list) and models:
                                first = models[0]
                                if isinstance(first, dict):
                                    model_name = first.get("id", "unknown")
                        status = "running"
                        running_count += 1
            except (httpx.HTTPError, ValueError):
                pass

            lines.append(f"  {snap}: {status} (endpoint: {endpoint}, model: {model_name})")

        return ToolResult(
            success=True,
            output="Installed inference snaps:\n" + "\n".join(lines),
            data={"snaps": installed},
            caption=f"{len(installed)} snap{'s' if len(installed) != 1 else ''}, {running_count} running",
        )
