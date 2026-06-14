"""Log and query observability tools (debug-log, stream, Tempo, Loki)."""

import asyncio
import datetime
import json
import logging
import re
import urllib.parse
from typing import Any

import jubilant

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.observability import _common
from cantrip.agent.tools.observability._common import (
    _HTTP_TIMEOUT_SECONDS,
    _ssh_fetch_url,
    _truncate,
)

log = logging.getLogger(__name__)


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
        if not _common._juju_available():
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
                error=(
                    f"juju debug-log failed (exit {proc.returncode}): "
                    f"{stderr.decode('utf-8', errors='replace').strip()}"
                ),
            )

        output = stdout.decode("utf-8", errors="replace")
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

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        if arguments.get("trace_id"):
            return f"Fetching Tempo trace {arguments['trace_id']}…"
        if arguments.get("service_name"):
            return f"Querying Tempo for {arguments['service_name']}…"
        return "Querying Tempo…"

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
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju, unit_name = _common._find_cos_unit(cos_model, "tempo")
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

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        del arguments
        return "Querying Loki…"

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
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju, unit_name = _common._find_cos_unit(cos_model, "loki")
        except ValueError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        # Loki's ``query_range`` parses ``start`` / ``end`` as either
        # nanosecond Unix epochs, RFC3339 timestamps, or a bare
        # Prometheus-style duration like ``1h``.  ``now`` and
        # ``now-1h`` are Grafana shortcuts that look natural but
        # 400 here — convert relative hours to nanoseconds at the
        # agent so the API gets a shape it understands, regardless
        # of fractional input or Loki version.
        end_dt = datetime.datetime.now(datetime.UTC)
        start_dt = end_dt - datetime.timedelta(hours=hours)
        params = {
            "query": query,
            "limit": str(limit),
            "start": str(int(start_dt.timestamp() * 1_000_000_000)),
            "end": str(int(end_dt.timestamp() * 1_000_000_000)),
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
