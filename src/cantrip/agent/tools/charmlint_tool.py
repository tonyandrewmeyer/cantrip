"""Charmlint agent tool — run the standalone charm linter.

charmlint is a dependency installed from PyPI.  It documents no stable
Python API, so cantrip always drives it through its CLI and parses the
``--format json`` report.
"""

from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import subprocess
import sys
from typing import TYPE_CHECKING, Any

from cantrip.agent.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from cantrip.mcp.registry import MCPRegistry

log = logging.getLogger(__name__)

# Phase 95.3: when the user has configured the charmcraft MCP server
# (``examples/mcp/canonical/marketplace.json`` ships a descriptor),
# the local lint result is enriched with a "second opinion" section
# rendered from the MCP server's ``lint`` and ``analyse`` outputs.
# The MCP call is best-effort — local lint stays authoritative.
_CHARMCRAFT_MCP_SERVER = "charmcraft"
_CHARMCRAFT_MCP_TOOLS = ("lint", "analyse")

# charmlint exits 1 when it reports an error-severity finding; only other
# non-zero codes (2 for a bad selector or config) mean the run failed.
_CHARMLINT_OK_EXIT_CODES = (0, 1)


class CharmlintError(RuntimeError):
    """charmlint could not be run, or did not produce a report."""


def charmlint_command(
    charm_dir: pathlib.Path,
    *,
    select: str = "",
    ignore: str = "",
    severity: str = "",
) -> list[str]:
    """Return the argv that lints *charm_dir* and prints a JSON report.

    The linter runs as ``python -m charmlint`` under cantrip's own
    interpreter, so it is found even when cantrip is installed as a uv
    tool and charmlint's console script is not on ``PATH``.
    """
    cmd = [sys.executable, "-m", "charmlint", str(charm_dir), "--format", "json"]
    if select:
        cmd.extend(["--select", select])
    if ignore:
        cmd.extend(["--ignore", ignore])
    if severity:
        cmd.extend(["--min-severity", severity])
    return cmd


def parse_charmlint_output(returncode: int, stdout: str, stderr: str) -> dict[str, Any]:
    """Return the JSON report from a finished charmlint run.

    Raises :class:`CharmlintError` when the exit code says the run
    failed or the output is not a JSON object.
    """
    if returncode not in _CHARMLINT_OK_EXIT_CODES:
        detail = stderr.strip() or f"exit code {returncode}"
        raise CharmlintError(f"charmlint failed: {detail}")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise CharmlintError(f"charmlint output was not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CharmlintError("charmlint output was not a JSON object")
    return data


def run_charmlint(
    charm_dir: pathlib.Path,
    *,
    select: str = "",
    ignore: str = "",
    severity: str = "",
    timeout: float = 30,
) -> dict[str, Any]:
    """Lint *charm_dir* and return charmlint's JSON report as a dict."""
    cmd = charmlint_command(charm_dir, select=select, ignore=ignore, severity=severity)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise CharmlintError("charmlint timed out") from exc
    except OSError as exc:
        raise CharmlintError(f"charmlint could not be run: {exc}") from exc
    return parse_charmlint_output(result.returncode, result.stdout, result.stderr)


class CharmlintTool(Tool):
    """Run charmlint against a charm directory.

    This exposes the standalone charmlint linter as an agent tool,
    returning ruff-style diagnostics with rule IDs, severities, and
    fix hints.  Supports filtering by category and severity.

    When a ``charmcraft`` MCP server is configured and connected
    (Phase 95.3), its ``lint`` / ``analyse`` outputs are appended as a
    second-opinion section after the local result.  The MCP call is
    best-effort — local lint remains authoritative on its own.
    """

    def __init__(self, *, mcp_registry: MCPRegistry | None = None) -> None:
        self._mcp_registry = mcp_registry

    @property
    def name(self) -> str:
        return "charmlint"

    @property
    def description(self) -> str:
        return (
            "Lint a charm directory for best practices using charmlint. "
            "Returns diagnostics with rule IDs (SECURITY-001, METADATA-003, "
            "TESTING-001, etc.), severities (error/warning/info), and fix hints. "
            "Supports filtering by category (e.g. METADATA, CONFIG, TESTING), "
            "rule ID, or rule name, and by minimum severity."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the charm directory",
                    "default": ".",
                },
                "select": {
                    "type": "string",
                    "description": (
                        "Comma-separated categories, rule IDs, or rule names to "
                        "check (e.g. 'METADATA,SECURITY,TESTING'). Empty means all."
                    ),
                },
                "ignore": {
                    "type": "string",
                    "description": (
                        "Comma-separated categories, rule IDs, or rule names to skip "
                        "(e.g. 'STRUCTURE-002,DOCUMENTATION')"
                    ),
                },
                "severity": {
                    "type": "string",
                    "enum": ["error", "warning", "info"],
                    "description": "Minimum severity to report (default: all)",
                },
            },
        }

    async def execute(
        self,
        path: str = ".",
        select: str = "",
        ignore: str = "",
        severity: str = "",
    ) -> ToolResult:
        """Run charmlint against *path*."""
        charm_dir = pathlib.Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Path not found: {path}",
            )

        # charmlint runs as a subprocess; keep the event loop free meanwhile.
        local = await asyncio.to_thread(self._execute_cli, charm_dir, select, ignore, severity)

        second_opinion = await self._charmcraft_mcp_second_opinion(charm_dir)
        if second_opinion is None:
            return local
        return self._merge_second_opinion(local, second_opinion)

    async def _charmcraft_mcp_second_opinion(
        self, charm_dir: pathlib.Path
    ) -> dict[str, Any] | None:
        """Call the charmcraft MCP server's ``lint`` + ``analyse`` tools.

        Returns ``None`` when no charmcraft server is configured, when
        the server is not connected, or when every probed tool errors.
        The local lint result is unaffected on any failure path — the
        MCP integration is strictly additive.
        """
        registry = self._mcp_registry
        if registry is None:
            return None
        client = registry.get_client(_CHARMCRAFT_MCP_SERVER)
        if client is None:
            return None
        available = {tool.name for tool in client.tools}
        sections: list[dict[str, str]] = []
        for tool_name in _CHARMCRAFT_MCP_TOOLS:
            if tool_name not in available:
                continue
            try:
                result = await client.call_tool(tool_name, {"path": str(charm_dir)})
            except Exception as exc:
                log.debug(
                    "charmcraft MCP %s call failed: %s",
                    tool_name,
                    exc,
                    exc_info=True,
                )
                sections.append({"tool": tool_name, "error": str(exc)})
                continue
            sections.append({"tool": tool_name, "text": result.text or ""})
        if not sections:
            return None
        return {"server": _CHARMCRAFT_MCP_SERVER, "sections": sections}

    @staticmethod
    def _merge_second_opinion(local: ToolResult, second_opinion: dict[str, Any]) -> ToolResult:
        """Append a Markdown-shaped second-opinion block to *local*.

        The block is plain text so it composes with the local output
        unchanged.  The structured
        ``data`` dict gains a ``mcp_second_opinion`` key so downstream
        consumers can inspect MCP findings without re-parsing the text.
        """
        if not local.success:
            return local
        blocks = [
            f"\n--- Second opinion (mcp__{second_opinion['server']}) ---",
        ]
        for section in second_opinion.get("sections", []):
            tool = section.get("tool", "?")
            if "error" in section:
                blocks.append(f"[{tool}] failed: {section['error']}")
                continue
            text = (section.get("text") or "").strip()
            if not text:
                blocks.append(f"[{tool}] (no output)")
                continue
            blocks.append(f"[{tool}]\n{text}")
        merged_output = (local.output or "") + "\n" + "\n\n".join(blocks)
        merged_data: dict[str, Any] = dict(local.data or {})
        merged_data["mcp_second_opinion"] = second_opinion
        return ToolResult(
            success=local.success,
            output=merged_output,
            data=merged_data,
            caption=local.caption,
            error=local.error,
        )

    @staticmethod
    def _execute_cli(
        charm_dir: pathlib.Path,
        select: str,
        ignore: str,
        severity: str,
    ) -> ToolResult:
        """Lint with the ``charmlint`` CLI and render its JSON report."""
        try:
            data = run_charmlint(charm_dir, select=select, ignore=ignore, severity=severity)
        except CharmlintError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        lines: list[str] = []
        for d in data.get("diagnostics", []):
            location = d.get("path", "")
            if d.get("line") is not None:
                location = f"{location}:{d['line']}"
            prefix = f"{location}: " if location else ""
            lines.append(f"{prefix}{d['rule_id']} {d['message']}")

        total = data.get("total", 0)
        counts: list[str] = []
        if errors := data.get("errors", 0):
            counts.append(f"{errors} error{'s' if errors != 1 else ''}")
        if warnings := data.get("warnings", 0):
            counts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
        if infos := data.get("info", 0):
            counts.append(f"{infos} info")

        if total == 0:
            lines.append("No issues found.")
            caption = "clean"
        else:
            lines.append("")
            lines.append(f"Found {total} issue{'s' if total != 1 else ''} ({', '.join(counts)})")
            caption = ", ".join(counts) or f"{total} issue{'s' if total != 1 else ''}"
        return ToolResult(
            success=True,
            output="\n".join(lines),
            data=data,
            caption=caption,
        )
