"""Observability tools for querying debug logs, Tempo traces, and Loki logs."""

import asyncio
import base64
import datetime
import functools
import io
import json
import logging
import pathlib
import re
import urllib.parse
from typing import Any

import jubilant
from jubilant import statustypes
from PIL import Image as PILImage
from PIL import ImageDraw, ImageFont

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.juju_subprocess import juju_available as _juju_available
from cantrip.llm.base import Image

log = logging.getLogger(__name__)

# Cap tool output to avoid overwhelming LLM context.
_MAX_OUTPUT_CHARS = 10000

# Timeout for urllib requests executed inside SSH sessions.
_HTTP_TIMEOUT_SECONDS = 10

# Grafana ``/render`` calls can take tens of seconds on busy dashboards.
_RENDER_TIMEOUT_SECONDS = 60

# Cache directory for rendered artefacts (Grafana screenshots today;
# Tempo waterfalls and Juju status renders once 48.3 / 48.4 land).
_SCREENSHOT_CACHE_DIR = pathlib.Path.home() / ".cache" / "cantrip" / "screenshots"

# PNG magic bytes used to tell a rendered image apart from an HTML
# error page Grafana returns when the dashboard is missing or the
# renderer plugin isn't installed.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _find_cos_unit(cos_model: str, app_hint: str) -> tuple[jubilant.Juju, str]:
    """Find a COS unit whose app name contains *app_hint*.

    Returns a ``(juju, unit_name)`` tuple.  Raises ``ValueError`` with
    the list of available app names if no match is found.
    """
    juju = jubilant.Juju(model=cos_model)
    status = juju.status()

    for app_name, app in status.apps.items():
        if app_hint in app_name:
            # Pick the first unit available.
            for unit_name in app.units:
                return juju, unit_name

    available = ", ".join(sorted(status.apps.keys())) or "(none)"
    raise ValueError(
        f"No app containing '{app_hint}' found in model '{cos_model}'. Available apps: {available}"
    )


def _truncate(text: str, limit: int = _MAX_OUTPUT_CHARS) -> str:
    """Truncate *text* to *limit* characters, appending a notice if trimmed."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n... (truncated — {len(text)} chars total)"


def _ssh_fetch_url(juju: jubilant.Juju, unit_name: str, url: str, timeout: int) -> str:
    """Fetch a URL from inside a Juju unit via SSH, safely.

    The Python script is base64-encoded before being passed through the
    shell, preventing injection regardless of what characters appear in
    the URL.
    """
    # Percent-encode single quotes so the URL is safe inside a Python string literal.
    safe_url = url.replace("'", "%27")
    script = (
        "import urllib.request, sys; "
        f"resp = urllib.request.urlopen('{safe_url}', timeout={timeout}); "
        "sys.stdout.write(resp.read().decode())"
    )
    encoded = base64.b64encode(script.encode()).decode()
    return juju.ssh(
        unit_name,
        f"python3 -c \"import base64,sys;exec(base64.b64decode('{encoded}'))\"",
    )


def _ssh_fetch_binary(
    juju: jubilant.Juju,
    unit_name: str,
    url: str,
    timeout: int,
    auth_header: str | None = None,
) -> bytes:
    """Fetch a URL from inside a Juju unit and return the raw bytes.

    Mirrors :func:`_ssh_fetch_url` but base64-encodes the response
    inside the unit before printing to stdout, so we can reliably
    transport binary payloads (PNGs in particular) across the SSH
    channel — ``juju ssh`` returns a ``str`` and would otherwise
    mangle non-UTF-8 bytes.
    """
    safe_url = url.replace("'", "%27")
    header_line = ""
    if auth_header is not None:
        safe_header = auth_header.replace("'", "%27")
        header_line = f"req.add_header('Authorization', '{safe_header}'); "
    script = (
        "import urllib.request, sys, base64; "
        f"req = urllib.request.Request('{safe_url}'); "
        f"{header_line}"
        f"resp = urllib.request.urlopen(req, timeout={timeout}); "
        "sys.stdout.write(base64.b64encode(resp.read()).decode('ascii'))"
    )
    encoded = base64.b64encode(script.encode()).decode()
    raw = juju.ssh(
        unit_name,
        f"python3 -c \"import base64,sys;exec(base64.b64decode('{encoded}'))\"",
    )
    # ``juju ssh`` occasionally appends trailing whitespace; strip it
    # before b64-decoding.
    return base64.b64decode(raw.strip())


class JujuDebugLogTool(Tool):
    """Tool to retrieve Juju debug log output."""

    @property
    def name(self) -> str:
        return "juju_debug_log"

    @property
    def description(self) -> str:
        return (
            "Retrieve recent Juju debug log output. "
            "Useful for diagnosing hook failures, relation errors, and agent issues. "
            "Does not require COS — works with any Juju model."
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
                "lines": {
                    "type": "integer",
                    "description": "Number of log lines to retrieve (default 50)",
                    "default": 50,
                },
                "unit": {
                    "type": "string",
                    "description": "Filter logs to a specific unit (e.g. 'my-app/0')",
                },
                "level": {
                    "type": "string",
                    "enum": ["ERROR", "WARNING", "INFO", "DEBUG"],
                    "description": "Minimum log level to include",
                },
            },
        }

    async def execute(
        self,
        model: str | None = None,
        lines: int = 50,
        unit: str | None = None,
        level: str | None = None,
    ) -> ToolResult:
        """Retrieve Juju debug log output."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        cmd = ["juju", "debug-log", f"--limit={lines}"]
        if model:
            cmd.extend(["-m", model])
        if unit:
            cmd.extend(["--include", unit])
        if level:
            cmd.extend(["--level", level])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult(
                success=False,
                output="",
                error="juju debug-log timed out after 30 seconds.",
            )

        if proc.returncode != 0:
            return ToolResult(
                success=False,
                output="",
                error=f"juju debug-log failed (exit {proc.returncode}): {stderr.decode().strip()}",
            )

        output = stdout.decode()
        if not output.strip():
            return ToolResult(
                success=True,
                output="(no log output matching the given filters)",
                caption="no log lines",
            )

        line_count = sum(1 for line in output.splitlines() if line.strip())
        return ToolResult(
            success=True,
            output=_truncate(output),
            caption=f"{line_count} log line{'s' if line_count != 1 else ''}",
        )


class JujuStreamLogsTool(Tool):
    """Tool to stream real-time logs from a Juju model.

    Uses ``juju debug-log --tail`` for live log streaming.  Returns a
    batch of recent log lines, useful for monitoring ongoing operations
    or watching for errors as they happen.
    """

    @property
    def name(self) -> str:
        return "juju_stream_logs"

    @property
    def description(self) -> str:
        return (
            "Stream real-time logs from a Juju model using juju debug-log --tail. "
            "Returns a batch of recent log lines. Useful for monitoring live operations."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Model name (required)",
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of initial lines to fetch (default 50)",
                    "default": 50,
                },
                "unit": {
                    "type": "string",
                    "description": "Filter logs to a specific unit (e.g. 'my-app/0')",
                },
                "level": {
                    "type": "string",
                    "enum": ["ERROR", "WARNING", "INFO", "DEBUG"],
                    "description": "Minimum log level to include (default WARNING)",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum total lines to return (default 100)",
                    "default": 100,
                },
            },
            "required": ["model"],
        }

    async def execute(
        self,
        model: str,
        lines: int = 50,
        unit: str | None = None,
        level: str = "WARNING",
        max_lines: int = 100,
    ) -> ToolResult:
        """Stream real-time logs from the model."""
        from cantrip.juju.log_stream import juju_available, stream_lines

        if not juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        collected: list[str] = []
        try:
            async for line in stream_lines(
                model,
                level=level,
                unit=unit,
                lines=lines,
                max_lines=max_lines,
            ):
                collected.append(line)
        except (OSError, TimeoutError) as exc:
            if collected:
                # Return what we got so far.
                output = "\n".join(collected)
                return ToolResult(
                    success=True,
                    output=_truncate(f"{output}\n\n(streaming interrupted: {exc})"),
                )
            return ToolResult(
                success=False,
                output="",
                error=f"Log streaming failed: {exc}",
            )

        if not collected:
            return ToolResult(
                success=True,
                output="(no log output matching the given filters)",
                caption="no log lines",
            )

        return ToolResult(
            success=True,
            output=_truncate("\n".join(collected)),
            caption=f"streamed {len(collected)} log line{'s' if len(collected) != 1 else ''}",
        )


class TempoQueryTool(Tool):
    """Tool to query Tempo for distributed traces via the COS model."""

    @property
    def name(self) -> str:
        return "tempo_query"

    @property
    def description(self) -> str:
        return (
            "Query Tempo for distributed traces. "
            "Searches by service name, TraceQL query, or fetches a specific trace by ID. "
            "Requires a COS model with Tempo deployed."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": (
                        "Filter traces by service name (typically the charm application name)"
                    ),
                },
                "query": {
                    "type": "string",
                    "description": "TraceQL query string (e.g. '{ status = error }')",
                },
                "trace_id": {
                    "type": "string",
                    "description": "Fetch a specific trace by its trace ID",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of traces to return (default 10)",
                    "default": 10,
                },
                "cos_model": {
                    "type": "string",
                    "description": "Name of the COS model (default 'cos')",
                    "default": "cos",
                },
            },
        }

    async def execute(
        self,
        service_name: str | None = None,
        query: str | None = None,
        trace_id: str | None = None,
        limit: int = 10,
        cos_model: str = "cos",
    ) -> ToolResult:
        """Query Tempo for traces."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju, unit_name = _find_cos_unit(cos_model, "tempo")
        except ValueError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        # Build the Tempo HTTP API URL.
        if trace_id:
            # Trace IDs are hex strings — reject anything else to prevent injection.
            if not re.fullmatch(r"[0-9a-fA-F]+", trace_id):
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Invalid trace ID (must be hex): {trace_id[:50]}",
                )
            url = f"http://localhost:3200/api/traces/{trace_id}"
        else:
            params: dict[str, str] = {"limit": str(limit)}
            if query:
                params["q"] = query
            elif service_name:
                # Escape quotes to prevent TraceQL injection.
                safe_name = service_name.replace("\\", "\\\\").replace('"', '\\"')
                params["q"] = f'{{ resource.service.name = "{safe_name}" }}'
            else:
                params["q"] = "{}"
            url = f"http://localhost:3200/api/search?{urllib.parse.urlencode(params)}"

        try:
            result = _ssh_fetch_url(juju, unit_name, url, _HTTP_TIMEOUT_SECONDS)
        except jubilant.CLIError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"SSH to {unit_name} failed: {exc}",
            )

        # Parse and format the response.
        try:
            data = json.loads(result)
        except (json.JSONDecodeError, ValueError):
            return ToolResult(
                success=False,
                output="",
                error=f"Malformed JSON response from Tempo: {_truncate(result, 500)}",
            )

        formatted = json.dumps(data, indent=2)

        if trace_id:
            if not data:
                return ToolResult(
                    success=True,
                    output=f"No trace found with ID {trace_id}.",
                    caption=f"trace {trace_id[:8]}: not found",
                )
            return ToolResult(
                success=True,
                output=_truncate(formatted),
                data={"trace_id": trace_id},
                caption=f"trace {trace_id[:8]}",
            )

        traces = data.get("traces", [])
        if not traces:
            return ToolResult(
                success=True,
                output="No traces found matching the query.",
                caption="no traces",
            )

        return ToolResult(
            success=True,
            output=_truncate(formatted),
            data={"count": len(traces)},
            caption=f"{len(traces)} trace{'s' if len(traces) != 1 else ''}",
        )


class LokiQueryTool(Tool):
    """Tool to query Loki for logs via the COS model."""

    @property
    def name(self) -> str:
        return "loki_query"

    @property
    def description(self) -> str:
        return (
            "Query Loki for logs using LogQL. "
            "Useful for finding workload errors, tracebacks, and application log output. "
            "Requires a COS model with Loki deployed."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        'LogQL query string (e.g. \'{juju_application="my-charm"} |= "error"\')'
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of log entries to return (default 100)",
                    "default": 100,
                },
                "hours": {
                    "type": "number",
                    "description": "How many hours back to search (default 1)",
                    "default": 1,
                },
                "cos_model": {
                    "type": "string",
                    "description": "Name of the COS model (default 'cos')",
                    "default": "cos",
                },
            },
            "required": ["query"],
        }

    async def execute(
        self,
        query: str,
        limit: int = 100,
        hours: float = 1,
        cos_model: str = "cos",
    ) -> ToolResult:
        """Query Loki for logs."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju, unit_name = _find_cos_unit(cos_model, "loki")
        except ValueError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        # Pre-compute the full URL on the agent side to avoid shell-escaping
        # issues with LogQL's {}, |=, and quotes.
        end_ns = "now"
        # Loki expects nanosecond timestamps for 'start'; we compute a
        # relative offset as a duration string instead.
        start = f"now-{hours}h" if hours != 1 else "now-1h"
        params = {
            "query": query,
            "limit": str(limit),
            "start": start,
            "end": end_ns,
        }
        url = f"http://localhost:3100/loki/api/v1/query_range?{urllib.parse.urlencode(params)}"

        try:
            result = _ssh_fetch_url(juju, unit_name, url, _HTTP_TIMEOUT_SECONDS)
        except jubilant.CLIError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"SSH to {unit_name} failed: {exc}",
            )

        try:
            data = json.loads(result)
        except (json.JSONDecodeError, ValueError):
            return ToolResult(
                success=False,
                output="",
                error=f"Malformed JSON response from Loki: {_truncate(result, 500)}",
            )

        # Extract log lines for a more readable output.
        streams = data.get("data", {}).get("result", [])
        if not streams:
            return ToolResult(
                success=True,
                output="No log entries found matching the query.",
                caption="no log entries",
            )

        # Flatten log entries from all streams.
        lines: list[str] = []
        for stream in streams:
            labels = stream.get("stream", {})
            label_str = ", ".join(f"{k}={v}" for k, v in labels.items())
            for entry in stream.get("values", []):
                # Each entry is [timestamp_ns, log_line].
                if len(entry) >= 2:
                    lines.append(f"[{label_str}] {entry[1]}")

        if not lines:
            return ToolResult(
                success=True,
                output="No log entries found matching the query.",
                caption="no log entries",
            )

        output = "\n".join(lines)
        return ToolResult(
            success=True,
            output=_truncate(output),
            data={"count": len(lines)},
            caption=f"{len(lines)} log entr{'ies' if len(lines) != 1 else 'y'}",
        )


def _grafana_admin_password(juju: jubilant.Juju) -> str | None:
    """Fetch the Grafana admin password via the ``get-admin-password`` action.

    Returns ``None`` when the action isn't available or produces no
    usable ``admin-password`` key — the caller falls back to an
    unauthenticated request so the tool still returns a targeted error
    instead of silently failing.
    """
    try:
        task = juju.run("grafana/leader", "get-admin-password")
    except (jubilant.TaskError, ValueError, jubilant.CLIError) as exc:
        log.debug("Grafana get-admin-password action failed: %s", exc)
        return None
    results = getattr(task, "results", {}) or {}
    for key in ("admin-password", "password"):
        value = results.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _screenshot_path(dashboard_uid: str, panel_id: int | None) -> pathlib.Path:
    """Build the target cache path for a freshly rendered screenshot."""
    _SCREENSHOT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    # Dashboard UIDs are alphanumeric-ish; sanitise defensively for a
    # filename without depending on the Grafana server's conventions.
    safe_uid = re.sub(r"[^A-Za-z0-9_.-]+", "_", dashboard_uid)[:32] or "dashboard"
    panel_suffix = f"-p{panel_id}" if panel_id is not None else ""
    return _SCREENSHOT_CACHE_DIR / f"grafana-{safe_uid}{panel_suffix}-{ts}.png"


class GrafanaScreenshotTool(Tool):
    """Render a Grafana panel or dashboard as a PNG via the ``/render`` endpoint.

    Uses the same in-unit SSH-fetch pattern as :class:`TempoQueryTool`
    and :class:`LokiQueryTool` so the request hits Grafana at
    ``http://localhost:3000`` from inside the Grafana unit itself —
    which sidesteps ingress and TLS complexity and gives the remote
    renderer the host it expects.  Requires the Grafana image-renderer
    plugin, which ships with the grafana-k8s charm by default.

    The PNG is saved to ``~/.cache/cantrip/screenshots/`` and its bytes
    are also attached to the :class:`ToolResult` as an ``Image`` so
    vision-capable providers (Anthropic today) can reason about the
    panel visually alongside the text caption.  Providers whose
    tool-role messages are text-only (Gemini ``FunctionResponse``,
    OpenAI-compatible ``role: tool``) drop the attachment and fall
    back to the caption, which always carries panel id, time range,
    dimensions, and the local file path.
    """

    @property
    def name(self) -> str:
        return "grafana_screenshot"

    @property
    def description(self) -> str:
        return (
            "Render a Grafana panel or dashboard as a PNG using Grafana's "
            "/render endpoint. Requires a COS model with Grafana deployed "
            "and its image-renderer plugin (bundled with grafana-k8s by "
            "default). Saves the PNG to ~/.cache/cantrip/screenshots/ and "
            "returns the file path plus a caption (dashboard UID, panel id, "
            "time range, dimensions). Useful for visual diagnostics — "
            "latency spikes, failing-rate graphs, dashboards worth sharing "
            "with the user."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "dashboard_uid": {
                    "type": "string",
                    "description": (
                        "Grafana dashboard UID (the short alphanumeric "
                        "identifier shown in the URL, not the numeric id)."
                    ),
                },
                "panel_id": {
                    "type": "integer",
                    "description": (
                        "Specific panel ID to render (default: full "
                        "dashboard). Find this in a panel's share URL."
                    ),
                },
                "time_range": {
                    "type": "string",
                    "description": (
                        "Grafana duration for the ``from=now-<range>`` "
                        "query (default ``1h``; accepts ``30m``, ``6h``, "
                        "``24h``, ``7d``, etc.)."
                    ),
                    "default": "1h",
                },
                "width": {
                    "type": "integer",
                    "description": "Output width in pixels (default 1000).",
                    "default": 1000,
                },
                "height": {
                    "type": "integer",
                    "description": "Output height in pixels (default 500).",
                    "default": 500,
                },
                "cos_model": {
                    "type": "string",
                    "description": "Name of the COS model (default 'cos').",
                    "default": "cos",
                },
            },
            "required": ["dashboard_uid"],
        }

    async def execute(
        self,
        dashboard_uid: str,
        panel_id: int | None = None,
        time_range: str = "1h",
        width: int = 1000,
        height: int = 500,
        cos_model: str = "cos",
    ) -> ToolResult:
        """Render a Grafana panel or dashboard and return the file path."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        # Reject unreasonable inputs before making a long-running
        # render call: very large canvases tax the image renderer and
        # often hit its per-request memory cap.
        if not 1 <= width <= 4000 or not 1 <= height <= 4000:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"width/height must be between 1 and 4000 pixels; "
                    f"got width={width}, height={height}"
                ),
            )
        if not re.fullmatch(r"\d+[smhdwMy]", time_range):
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"time_range must be a Grafana duration like '1h', "
                    f"'30m', '7d'; got {time_range!r}"
                ),
            )
        # Dashboard UIDs are alphanumeric + a few punctuation chars —
        # reject anything else before it reaches the URL to block
        # even theoretical path-traversal attempts.
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", dashboard_uid):
            return ToolResult(
                success=False,
                output="",
                error=(f"dashboard_uid must match [A-Za-z0-9_.-]+; got {dashboard_uid!r}"),
            )

        try:
            juju, unit_name = _find_cos_unit(cos_model, "grafana")
        except ValueError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        password = _grafana_admin_password(juju)
        auth_header: str | None = None
        if password is not None:
            creds = base64.b64encode(f"admin:{password}".encode()).decode("ascii")
            auth_header = f"Basic {creds}"

        endpoint = "d-solo" if panel_id is not None else "d"
        params = {
            "from": f"now-{time_range}",
            "to": "now",
            "width": str(width),
            "height": str(height),
        }
        if panel_id is not None:
            params["panelId"] = str(panel_id)
        url = (
            f"http://localhost:3000/render/{endpoint}/{dashboard_uid}"
            f"?{urllib.parse.urlencode(params)}"
        )

        try:
            payload = _ssh_fetch_binary(
                juju,
                unit_name,
                url,
                _RENDER_TIMEOUT_SECONDS,
                auth_header=auth_header,
            )
        except jubilant.CLIError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"SSH to {unit_name} failed: {exc}",
            )
        except (ValueError, OSError) as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Could not decode Grafana /render response: {exc}",
            )

        if not payload.startswith(_PNG_MAGIC):
            # Surface the first 500 chars of whatever Grafana returned —
            # typically an HTML error page from the renderer plugin.
            try:
                snippet = payload.decode("utf-8", errors="replace")[:500]
            except UnicodeDecodeError:
                snippet = repr(payload[:200])
            hint = ""
            if password is None:
                hint = (
                    " Tip: run `juju run grafana/leader get-admin-password` "
                    "manually to confirm the Grafana charm exposes the action."
                )
            return ToolResult(
                success=False,
                output="",
                error=(f"Grafana did not return a PNG. Response begins:\n{snippet}{hint}"),
            )

        path = _screenshot_path(dashboard_uid, panel_id)
        path.write_bytes(payload)

        panel_desc = f"panel {panel_id}" if panel_id is not None else "full dashboard"
        caption_lines = [
            f"Rendered Grafana {panel_desc} from dashboard ``{dashboard_uid}``.",
            f"Time range: now-{time_range} to now.",
            f"Dimensions: {width}x{height}.",
            f"Saved to: {path}",
            f"Size: {len(payload):,} bytes.",
        ]
        return ToolResult(
            success=True,
            output="\n".join(caption_lines),
            data={
                "path": str(path),
                "dashboard_uid": dashboard_uid,
                "panel_id": panel_id,
                "time_range": time_range,
                "width": width,
                "height": height,
                "bytes": len(payload),
            },
            images=[Image(data=payload, mime="image/png")],
        )


# ---------------------------------------------------------------------------
# Tempo trace waterfall rendering (Phase 48.3)
# ---------------------------------------------------------------------------


# Common monospace font paths on Linux, macOS, and a bundled-Pillow
# fallback.  We try each in turn; the first one that loads wins.
_MONO_FONT_CANDIDATES: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    "/Library/Fonts/Courier New.ttf",
    "/System/Library/Fonts/Menlo.ttc",
)

_WATERFALL_WIDTH = 1400
_WATERFALL_LABEL_WIDTH = 420
_WATERFALL_ROW_HEIGHT = 18
_WATERFALL_HEADER_HEIGHT = 40
_WATERFALL_PADDING = 10
_WATERFALL_MAX_SPANS = 80

# Bar colour for most spans; the N slowest are redrawn in the "slow"
# colour to draw the eye.
_COLOUR_BG = (255, 255, 255)
_COLOUR_TEXT = (32, 32, 32)
_COLOUR_MUTED = (120, 120, 120)
_COLOUR_GRID = (220, 220, 220)
_COLOUR_BAR = (74, 144, 226)
_COLOUR_BAR_SLOW = (226, 92, 74)

_SLOW_HIGHLIGHT_COUNT = 3


def _load_mono_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """Return a monospace Pillow font at *size*, or Pillow's bitmap default.

    The bitmap default has no size parameter and renders small — the
    rest of the layout checks the font's ``size`` attribute (when
    present) to decide cell height, so a fallback is ugly but
    functional rather than broken.
    """
    for path in _MONO_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    log.debug("No TTF monospace font found; using Pillow default")
    return ImageFont.load_default()


def _collect_spans_from_trace(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a Tempo trace response into a list of span dicts.

    Tempo serves traces in OpenTelemetry ``batches[].resource`` /
    ``batches[].scopeSpans[].spans[]`` shape (older versions use
    ``instrumentationLibrarySpans`` — we accept either).  Service name
    is lifted out of each batch's resource attributes so the waterfall
    can label rows by service.

    Returns spans with the fields the waterfall renderer needs:
    ``span_id``, ``name``, ``service``, ``start_ns``, ``end_ns``,
    ``duration_ns``.  Spans missing a timestamp are skipped — they
    can't be placed on the axis.
    """
    spans: list[dict[str, Any]] = []
    batches = trace.get("batches") if isinstance(trace, dict) else None
    if not isinstance(batches, list):
        return spans

    for batch in batches:
        if not isinstance(batch, dict):
            continue
        service = _extract_service_name(batch)
        scope_lists = batch.get("scopeSpans") or batch.get("instrumentationLibrarySpans") or []
        if not isinstance(scope_lists, list):
            continue
        for scope in scope_lists:
            if not isinstance(scope, dict):
                continue
            for span in scope.get("spans", []) or []:
                if not isinstance(span, dict):
                    continue
                start = _parse_unix_nano(span.get("startTimeUnixNano"))
                end = _parse_unix_nano(span.get("endTimeUnixNano"))
                if start is None or end is None or end < start:
                    continue
                spans.append(
                    {
                        "span_id": str(span.get("spanId", "")),
                        "name": str(span.get("name", "(unnamed)")),
                        "service": service,
                        "start_ns": start,
                        "end_ns": end,
                        "duration_ns": end - start,
                    }
                )
    return spans


def _extract_service_name(batch: dict[str, Any]) -> str:
    """Return ``service.name`` from a batch's resource attributes, or ``?``."""
    resource = batch.get("resource")
    if not isinstance(resource, dict):
        return "?"
    for attr in resource.get("attributes", []) or []:
        if not isinstance(attr, dict):
            continue
        if attr.get("key") != "service.name":
            continue
        value = attr.get("value")
        if isinstance(value, dict):
            inner = value.get("stringValue")
            if isinstance(inner, str) and inner:
                return inner
    return "?"


def _parse_unix_nano(value: Any) -> int | None:
    """Parse a Tempo timestamp (stringified nanoseconds) into an int."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _format_duration(nanos: int) -> str:
    """Format a duration in nanoseconds using the most readable unit."""
    if nanos < 1_000:
        return f"{nanos}ns"
    if nanos < 1_000_000:
        return f"{nanos / 1_000:.1f}µs"
    if nanos < 1_000_000_000:
        return f"{nanos / 1_000_000:.1f}ms"
    return f"{nanos / 1_000_000_000:.2f}s"


def _render_waterfall_png(spans: list[dict[str, Any]], trace_id: str) -> bytes:
    """Render a waterfall PNG from span dicts produced by ``_collect_spans_from_trace``.

    Spans are drawn in start-time order, one per row.  The ``duration``
    bar starts at ``(start - trace_start) / trace_span * timeline_width``
    and is sized by its own duration.  The top-``_SLOW_HIGHLIGHT_COUNT``
    longest spans are recoloured so the reader's eye lands on them
    without needing to read every number.
    """
    ordered = sorted(spans, key=lambda s: s["start_ns"])
    if len(ordered) > _WATERFALL_MAX_SPANS:
        ordered = ordered[:_WATERFALL_MAX_SPANS]

    trace_start = min(s["start_ns"] for s in ordered)
    trace_end = max(s["end_ns"] for s in ordered)
    trace_span = max(trace_end - trace_start, 1)

    # Identify the slowest spans so the renderer can paint them red.
    # Ranked by duration across the *full* span list (not the truncated
    # view), so even in a truncated waterfall the highlighted bars are
    # the most interesting ones the viewer actually sees.
    slow_ids = {
        s["span_id"]
        for s in sorted(spans, key=lambda s: s["duration_ns"], reverse=True)[
            :_SLOW_HIGHLIGHT_COUNT
        ]
    }

    row_height = _WATERFALL_ROW_HEIGHT
    height = _WATERFALL_HEADER_HEIGHT + row_height * len(ordered) + _WATERFALL_PADDING * 2
    img = PILImage.new("RGB", (_WATERFALL_WIDTH, height), _COLOUR_BG)
    draw = ImageDraw.Draw(img)

    font = _load_mono_font(11)
    font_header = _load_mono_font(13)

    header_text = (
        f"Trace {trace_id[:16]}… — {len(ordered)} spans shown "
        f"(of {len(spans)}), total {_format_duration(trace_span)}"
    )
    draw.text(
        (_WATERFALL_PADDING, _WATERFALL_PADDING),
        header_text,
        font=font_header,
        fill=_COLOUR_TEXT,
    )

    timeline_left = _WATERFALL_LABEL_WIDTH
    timeline_right = _WATERFALL_WIDTH - _WATERFALL_PADDING
    timeline_width = max(timeline_right - timeline_left, 1)

    # Faint vertical grid lines at 0 / 25 / 50 / 75 / 100%.
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        x = timeline_left + int(timeline_width * frac)
        draw.line(
            [(x, _WATERFALL_HEADER_HEIGHT), (x, height - _WATERFALL_PADDING)],
            fill=_COLOUR_GRID,
        )

    for index, span in enumerate(ordered):
        y = _WATERFALL_HEADER_HEIGHT + index * row_height
        label = f"{span['service']} · {span['name']}"
        # Keep the label from spilling into the timeline.
        max_chars = (_WATERFALL_LABEL_WIDTH - _WATERFALL_PADDING * 2) // 7
        if len(label) > max_chars:
            label = label[: max_chars - 1] + "…"
        draw.text(
            (_WATERFALL_PADDING, y + 2),
            label,
            font=font,
            fill=_COLOUR_TEXT,
        )

        rel_start = (span["start_ns"] - trace_start) / trace_span
        rel_width = span["duration_ns"] / trace_span
        x0 = timeline_left + int(timeline_width * rel_start)
        x1 = timeline_left + max(int(timeline_width * (rel_start + rel_width)), x0 + 2)
        colour = _COLOUR_BAR_SLOW if span["span_id"] in slow_ids else _COLOUR_BAR
        draw.rectangle([(x0, y + 3), (x1, y + row_height - 4)], fill=colour)

        duration_label = _format_duration(span["duration_ns"])
        # Duration label sits just after the bar when there's room; if
        # the bar reaches the right edge, tuck the label inside the bar.
        label_x = x1 + 4
        text_colour = _COLOUR_MUTED
        if label_x + len(duration_label) * 7 > timeline_right:
            label_x = max(x0 + 4, timeline_left)
            text_colour = _COLOUR_BG
        draw.text((label_x, y + 2), duration_label, font=font, fill=text_colour)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _waterfall_cache_path(trace_id: str) -> pathlib.Path:
    """Build the cache path for a waterfall PNG (same dir as Grafana screenshots)."""
    _SCREENSHOT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_id = re.sub(r"[^A-Za-z0-9]+", "", trace_id)[:32] or "trace"
    return _SCREENSHOT_CACHE_DIR / f"tempo-waterfall-{safe_id}-{ts}.png"


class TempoWaterfallTool(Tool):
    """Render a Tempo trace as a waterfall PNG.

    Useful when a trace has enough spans that the JSON-text view from
    :class:`TempoQueryTool` stops being legible.  The waterfall lays
    spans out along a time axis so the reader can see which spans
    dominate the trace, which overlap, and which cascade serially —
    structure that's hard to extract from a flat list of
    ``startTimeUnixNano`` numbers.

    Fetches the trace with the same in-unit SSH pattern as the other
    observability tools, parses the OpenTelemetry batches, and draws
    the waterfall with Pillow.  The PNG is saved to
    ``~/.cache/cantrip/screenshots/`` and the bytes are attached to
    the :class:`ToolResult.images` so vision-capable providers
    (48.1 / 48.2b) can reason about the layout alongside the text
    caption.
    """

    @property
    def name(self) -> str:
        return "tempo_waterfall"

    @property
    def description(self) -> str:
        return (
            "Render a Tempo distributed trace as a waterfall PNG. Fetches "
            "the trace by ID from Tempo in the COS model, flattens the "
            "OpenTelemetry batches into spans, and draws them on a time "
            "axis with the slowest spans highlighted. Saves the PNG to "
            "~/.cache/cantrip/screenshots/ and returns a caption (total "
            "duration, span count, top-3 slowest spans) plus the image "
            "bytes. Useful when a trace is too dense for the JSON view "
            "to reveal structure."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "trace_id": {
                    "type": "string",
                    "description": "Trace ID (hex string) to fetch from Tempo.",
                },
                "cos_model": {
                    "type": "string",
                    "description": "COS model name (default 'cos').",
                    "default": "cos",
                },
            },
            "required": ["trace_id"],
        }

    async def execute(self, trace_id: str, cos_model: str = "cos") -> ToolResult:
        """Render the waterfall for *trace_id* and save it to the cache dir."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        if not re.fullmatch(r"[0-9a-fA-F]+", trace_id):
            return ToolResult(
                success=False,
                output="",
                error=f"Invalid trace ID (must be hex): {trace_id[:50]}",
            )

        try:
            juju, unit_name = _find_cos_unit(cos_model, "tempo")
        except ValueError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        url = f"http://localhost:3200/api/traces/{trace_id}"
        try:
            raw = _ssh_fetch_url(juju, unit_name, url, _HTTP_TIMEOUT_SECONDS)
        except jubilant.CLIError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"SSH to {unit_name} failed: {exc}",
            )

        try:
            trace = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return ToolResult(
                success=False,
                output="",
                error=(f"Malformed JSON response from Tempo: {_truncate(raw, 500)}"),
            )

        spans = _collect_spans_from_trace(trace)
        if not spans:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"No spans found for trace {trace_id}. The trace may "
                    f"not exist, may have been sampled out, or may use a "
                    f"Tempo response shape this tool doesn't recognise."
                ),
            )

        try:
            png_bytes = _render_waterfall_png(spans, trace_id)
        except (OSError, ValueError) as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Could not render waterfall PNG: {exc}",
            )

        path = _waterfall_cache_path(trace_id)
        path.write_bytes(png_bytes)

        trace_start = min(s["start_ns"] for s in spans)
        trace_end = max(s["end_ns"] for s in spans)
        trace_span = trace_end - trace_start
        slowest = sorted(spans, key=lambda s: s["duration_ns"], reverse=True)[
            :_SLOW_HIGHLIGHT_COUNT
        ]
        slowest_lines = [
            f"  {s['service']} · {s['name']} — {_format_duration(s['duration_ns'])}"
            for s in slowest
        ]

        caption = "\n".join(
            [
                f"Rendered waterfall for trace ``{trace_id}``.",
                f"Total duration: {_format_duration(trace_span)}.",
                f"Spans: {len(spans)} total"
                + (
                    f" ({_WATERFALL_MAX_SPANS} shown; the full list "
                    f"is in the JSON response via tempo_query)."
                    if len(spans) > _WATERFALL_MAX_SPANS
                    else "."
                ),
                f"Saved to: {path}",
                f"Size: {len(png_bytes):,} bytes.",
                "Slowest spans:",
                *slowest_lines,
            ]
        )

        return ToolResult(
            success=True,
            output=caption,
            data={
                "path": str(path),
                "trace_id": trace_id,
                "span_count": len(spans),
                "duration_ns": trace_span,
                "bytes": len(png_bytes),
            },
            images=[Image(data=png_bytes, mime="image/png")],
        )


# ---------------------------------------------------------------------------
# Juju status tree rendering (Phase 48.4)
# ---------------------------------------------------------------------------

# Status → (indicator, fill colour, label colour).  The fill is used for
# the coloured block beside each node; the label colour matches the
# headline text when we want to colour an individual word.
_STATUS_GLYPH: dict[str, str] = {
    "active": "●",
    "waiting": "○",
    "blocked": "◌",
    "maintenance": "◐",
    "unknown": "○",
    "error": "✗",
    "terminated": "✗",
}

_STATUS_COLOUR: dict[str, tuple[int, int, int]] = {
    "active": (46, 160, 67),
    "waiting": (210, 153, 34),
    "blocked": (215, 58, 73),
    "maintenance": (31, 111, 235),
    "unknown": (130, 130, 130),
    "error": (215, 58, 73),
    "terminated": (120, 45, 56),
}

# The render canvas has a title bar and then a list of text lines.
_STATUS_WIDTH = 1200
_STATUS_LINE_HEIGHT = 18
_STATUS_HEADER_HEIGHT = 36
_STATUS_PADDING = 12
_STATUS_INDICATOR_WIDTH = 18

# Cap rendered rows so a 200-app model doesn't blow up into a 4000-pixel
# image.  The caption still reports the full counts; the underlying
# :class:`JujuStatusTool` produces the full text list when that matters.
_STATUS_MAX_LINES = 140

# Bullet characters for the tree structure.  Using the same glyphs as
# the TUI graph so screenshots are instantly recognisable.
_TREE_BRANCH = "├─"
_TREE_LAST = "└─"
_TREE_VERTICAL = "│ "
_TREE_SPACE = "  "


def _status_glyph(status: str) -> str:
    return _STATUS_GLYPH.get(status, "○")


def _status_colour(status: str) -> tuple[int, int, int]:
    return _STATUS_COLOUR.get(status, _COLOUR_TEXT)


def _truncate_label(label: str, max_chars: int) -> str:
    """Trim *label* to *max_chars*, appending an ellipsis when cut."""
    if len(label) <= max_chars:
        return label
    if max_chars <= 1:
        return label[:max_chars]
    return label[: max_chars - 1] + "…"


def _juju_status_tree_lines(
    status: statustypes.Status,
) -> list[dict[str, Any]]:
    """Convert a :class:`jubilant.statustypes.Status` into tree line specs.

    Each line is a dict with ``text`` (what to draw), ``indicator`` (a
    status glyph rendered in colour at the start of the line), ``status``
    (used to pick the indicator colour), and ``kind`` (``app``, ``unit``,
    ``message``, ``relation``, ``heading``).  The renderer treats every
    line the same, just with different text and colours — so the logic
    that decides what to show stays testable without Pillow.
    """
    lines: list[dict[str, Any]] = []

    if not status.apps:
        lines.append(
            {
                "text": "(no applications deployed)",
                "indicator": "",
                "status": "unknown",
                "kind": "message",
            }
        )
        return lines

    app_names = sorted(status.apps.keys())
    for app_index, app_name in enumerate(app_names):
        app = status.apps[app_name]
        is_last_app = app_index == len(app_names) - 1
        app_branch = _TREE_LAST if is_last_app else _TREE_BRANCH
        app_status_name = app.app_status.current or "unknown"
        unit_count = len(app.units)
        unit_word = "unit" if unit_count == 1 else "units"
        headline = f"{app_branch} {app_name} ({app_status_name}) — {unit_count} {unit_word}"
        lines.append(
            {
                "text": headline,
                "indicator": _status_glyph(app_status_name),
                "status": app_status_name,
                "kind": "app",
            }
        )

        app_message = (app.app_status.message or "").strip()
        child_prefix = (_TREE_SPACE if is_last_app else _TREE_VERTICAL) + " "
        if app_message:
            lines.append(
                {
                    "text": f"{child_prefix}{_TREE_BRANCH} {app_message}",
                    "indicator": "",
                    "status": app_status_name,
                    "kind": "message",
                }
            )

        unit_names = sorted(app.units.keys())
        for unit_index, unit_name in enumerate(unit_names):
            unit = app.units[unit_name]
            is_last_unit = unit_index == len(unit_names) - 1
            unit_branch = _TREE_LAST if is_last_unit else _TREE_BRANCH
            unit_status_name = unit.workload_status.current or "unknown"
            leader_marker = " (leader)" if unit.leader else ""
            lines.append(
                {
                    "text": (
                        f"{child_prefix}{unit_branch} {unit_name} "
                        f"({unit_status_name}){leader_marker}"
                    ),
                    "indicator": _status_glyph(unit_status_name),
                    "status": unit_status_name,
                    "kind": "unit",
                }
            )

    relation_entries = _collect_relation_entries(status)
    if relation_entries:
        lines.append({"text": "", "indicator": "", "status": "", "kind": "spacer"})
        lines.append(
            {
                "text": f"Relations ({len(relation_entries)}):",
                "indicator": "",
                "status": "",
                "kind": "heading",
            }
        )
        for source, endpoint, target, interface in relation_entries:
            lines.append(
                {
                    "text": (f"  {source}:{endpoint} ── [{interface}] ──▸ {target}"),
                    "indicator": "",
                    "status": "",
                    "kind": "relation",
                }
            )

    return lines


def _collect_relation_entries(
    status: statustypes.Status,
) -> list[tuple[str, str, str, str]]:
    """Return deduplicated relation tuples (source, endpoint, target, interface).

    Jubilant's ``AppStatus.relations`` reports both sides of every
    relation — we keep the single deterministic (alphabetically first
    source) rendering so a peer relation doesn't print twice.
    """
    seen: set[tuple[str, str, str]] = set()
    out: list[tuple[str, str, str, str]] = []
    for app_name in sorted(status.apps.keys()):
        app = status.apps[app_name]
        for endpoint, related_list in sorted(app.relations.items()):
            for rel in related_list:
                other = rel.related_app
                pair = tuple(sorted([app_name, other]))
                key = (pair[0], pair[1], rel.interface)
                if key in seen:
                    continue
                seen.add(key)
                # Always print the alphabetically-first app as the
                # "source" so the output is deterministic — and pick the
                # endpoint from *that* side, not the side we happen to
                # be iterating.
                if app_name == pair[0]:
                    out.append((app_name, endpoint, other, rel.interface))
                else:
                    # Look up the other side's endpoint for this interface.
                    other_app = status.apps.get(other)
                    if other_app is None:
                        out.append((other, "?", app_name, rel.interface))
                        continue
                    other_endpoint = next(
                        (
                            ep
                            for ep, rels in other_app.relations.items()
                            for r in rels
                            if r.related_app == app_name and r.interface == rel.interface
                        ),
                        "?",
                    )
                    out.append((other, other_endpoint, app_name, rel.interface))
    return out


def _render_status_png(lines: list[dict[str, Any]], model_name: str, cloud: str | None) -> bytes:
    """Render *lines* as a coloured tree PNG.

    Each line draws a status indicator (where set) in its status colour
    and then the line text in the default text colour; ``app`` and
    ``unit`` lines also recolour the parenthesised status word so the
    status label stands out to a reader scanning the image.
    """
    shown = lines[:_STATUS_MAX_LINES]
    total_lines = len(shown) + (1 if len(lines) > _STATUS_MAX_LINES else 0)
    height = _STATUS_HEADER_HEIGHT + _STATUS_LINE_HEIGHT * total_lines + _STATUS_PADDING * 2
    img = PILImage.new("RGB", (_STATUS_WIDTH, height), _COLOUR_BG)
    draw = ImageDraw.Draw(img)

    font = _load_mono_font(12)
    font_header = _load_mono_font(14)

    cloud_suffix = f" ({cloud})" if cloud else ""
    header = f"Model: {model_name}{cloud_suffix}"
    draw.text(
        (_STATUS_PADDING, _STATUS_PADDING),
        header,
        font=font_header,
        fill=_COLOUR_TEXT,
    )

    body_top = _STATUS_HEADER_HEIGHT + _STATUS_PADDING
    for index, line in enumerate(shown):
        y = body_top + index * _STATUS_LINE_HEIGHT
        indicator = line.get("indicator", "")
        if indicator:
            draw.text(
                (_STATUS_PADDING, y),
                indicator,
                font=font,
                fill=_status_colour(line.get("status", "")),
            )
        text_x = _STATUS_PADDING + _STATUS_INDICATOR_WIDTH
        text = line.get("text", "")
        max_chars = (_STATUS_WIDTH - text_x - _STATUS_PADDING) // 7
        draw.text(
            (text_x, y),
            _truncate_label(text, max_chars),
            font=font,
            fill=_COLOUR_TEXT,
        )

    if len(lines) > _STATUS_MAX_LINES:
        y = body_top + len(shown) * _STATUS_LINE_HEIGHT
        truncated = len(lines) - _STATUS_MAX_LINES
        draw.text(
            (_STATUS_PADDING + _STATUS_INDICATOR_WIDTH, y),
            f"… ({truncated} more lines omitted — run juju_status for the full view)",
            font=font,
            fill=_COLOUR_MUTED,
        )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _status_cache_path(model_name: str) -> pathlib.Path:
    """Build the cache path for a rendered Juju status PNG."""
    _SCREENSHOT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_model = re.sub(r"[^A-Za-z0-9_-]+", "", model_name)[:32] or "model"
    return _SCREENSHOT_CACHE_DIR / f"juju-status-{safe_model}-{ts}.png"


class JujuStatusRenderTool(Tool):
    """Render the current ``juju status`` as a coloured tree PNG.

    Useful when the text output from :class:`JujuStatusTool` runs off
    the screen or loses structure — the image lays out model, apps,
    units, and relations in a fixed tree with status-coloured glyphs,
    so a vision-capable provider can read the model shape at a glance.
    Saves the PNG to ``~/.cache/cantrip/screenshots/`` and attaches the
    image bytes to the :class:`ToolResult` for providers that support
    image input (Phase 48.1).
    """

    @property
    def name(self) -> str:
        return "juju_status_render"

    @property
    def description(self) -> str:
        return (
            "Render the current juju status as a coloured tree PNG. "
            "Apps are grouped with their units; each node carries a "
            "status-coloured glyph (● active, ○ waiting, ◌ blocked, "
            "◐ maintenance, ✗ error). Relations are listed below. "
            "Saves the PNG to ~/.cache/cantrip/screenshots/ and "
            "returns a caption (model, app count, unit count, blocked "
            "apps) plus the image bytes. Useful when a long status "
            "table would lose structure in a text response."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified).",
                },
            },
        }

    async def execute(self, model: str | None = None) -> ToolResult:
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = jubilant.Juju(model=model)
            status = await asyncio.wait_for(
                asyncio.to_thread(functools.partial(juju.status)),
                timeout=_HTTP_TIMEOUT_SECONDS * 3,
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju status timed out — the controller may be unavailable.",
            )
        except (jubilant.CLIError, jubilant.TaskError, OSError, ValueError) as exc:
            return ToolResult(success=False, output="", error=str(exc))

        lines = _juju_status_tree_lines(status)
        try:
            png_bytes = _render_status_png(lines, status.model.name, status.model.cloud)
        except (OSError, ValueError) as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Could not render status PNG: {exc}",
            )

        path = _status_cache_path(status.model.name)
        path.write_bytes(png_bytes)

        app_count = len(status.apps)
        unit_count = sum(len(app.units) for app in status.apps.values())
        blocked_apps = sorted(
            name
            for name, app in status.apps.items()
            if (app.app_status.current or "") in {"blocked", "error"}
        )
        relation_count = len(_collect_relation_entries(status))

        caption_parts = [
            f"Rendered status for model ``{status.model.name}``.",
            f"Apps: {app_count}. Units: {unit_count}. Relations: {relation_count}.",
            f"Saved to: {path}",
            f"Size: {len(png_bytes):,} bytes.",
        ]
        if blocked_apps:
            caption_parts.append("Blocked or errored apps: " + ", ".join(blocked_apps) + ".")
        caption = "\n".join(caption_parts)

        return ToolResult(
            success=True,
            output=caption,
            data={
                "path": str(path),
                "model": status.model.name,
                "apps": app_count,
                "units": unit_count,
                "relations": relation_count,
                "blocked_apps": blocked_apps,
                "bytes": len(png_bytes),
            },
            images=[Image(data=png_bytes, mime="image/png")],
        )
