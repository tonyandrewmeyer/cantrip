"""Charmlint agent tool — run the standalone charm linter."""

from __future__ import annotations

import json
import logging
import pathlib
import shutil
import subprocess
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


class CharmlintTool(Tool):
    """Run charmlint against a charm directory.

    This exposes the standalone charmlint linter as an agent tool,
    returning ruff-style diagnostics with rule IDs, severities, and
    fix hints.  Supports filtering by category and severity.

    Prefers the Rust binary (``charmlint-rs`` on PATH, or the in-tree
    release build) for speed, falling back to the Python library.

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
            "Returns diagnostics with rule IDs (COS001, TEST001, DEP001, etc.), "
            "severities (error/warning/info), and fix hints. Supports filtering "
            "by category (e.g. COS, META, TEST) and minimum severity."
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
                        "Comma-separated categories to check "
                        "(e.g. 'COS,META,TEST'). Empty means all."
                    ),
                },
                "ignore": {
                    "type": "string",
                    "description": (
                        "Comma-separated rule IDs or categories to skip (e.g. 'STR002,DOC')"
                    ),
                },
                "severity": {
                    "type": "string",
                    "enum": ["error", "warning", "info"],
                    "description": "Minimum severity to report (default: all)",
                },
            },
        }

    @staticmethod
    def _find_rust_binary() -> str | None:
        """Return the path to the Rust charmlint binary, or None."""
        rust_bin = shutil.which("charmlint-rs")
        if rust_bin:
            return rust_bin
        # Check the in-tree build location.
        import cantrip

        pkg_dir = pathlib.Path(cantrip.__file__).resolve().parent
        candidate = pkg_dir.parent.parent / "charmlint-rs" / "target" / "release" / "charmlint"
        if candidate.is_file():
            return str(candidate)
        return None

    async def execute(
        self,
        path: str = ".",
        select: str = "",
        ignore: str = "",
        severity: str = "",
    ) -> ToolResult:
        """Run charmlint, preferring the Rust binary when available."""
        charm_dir = pathlib.Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Path not found: {path}",
            )

        rust_bin = self._find_rust_binary()
        if rust_bin is not None:
            local = self._execute_rust(rust_bin, charm_dir, select, ignore, severity)
        else:
            local = self._execute_python(charm_dir, select, ignore, severity)

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

        The block is plain text so it composes with both the Rust- and
        Python-backed local outputs unchanged.  The structured
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

    def _execute_rust(
        self,
        binary: str,
        charm_dir: pathlib.Path,
        select: str,
        ignore: str,
        severity: str,
    ) -> ToolResult:
        """Lint using the compiled Rust binary."""
        cmd = [binary, str(charm_dir), "--format", "json"]
        if select:
            cmd.extend(["--select", select])
        if ignore:
            cmd.extend(["--ignore", ignore])
        if severity:
            cmd.extend(["--severity", severity])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            return self._execute_python(charm_dir, select, ignore, severity)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error="charmlint timed out")

        # Parse JSON output from the Rust binary.
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            # Fallback on unparseable output.
            return self._execute_python(charm_dir, select, ignore, severity)

        # Format text output from the parsed diagnostics.
        lines: list[str] = []
        for d in data.get("diagnostics", []):
            location = d.get("path", "")
            if d.get("line") is not None:
                location = f"{location}:{d['line']}"
            prefix = f"{location}: " if location else ""
            lines.append(f"{prefix}{d['rule_id']} {d['message']}")

        total = data.get("total", 0)
        errors = data.get("errors", 0)
        warnings = data.get("warnings", 0)
        infos = data.get("info", 0)

        if total == 0:
            lines.append("No issues found.")
        else:
            parts = []
            if errors:
                s = "s" if errors != 1 else ""
                parts.append(f"{errors} error{s}")
            if warnings:
                s = "s" if warnings != 1 else ""
                parts.append(f"{warnings} warning{s}")
            if infos:
                parts.append(f"{infos} info")
            s = "s" if total != 1 else ""
            lines.append(f"Found {total} issue{s} ({', '.join(parts)})")

        if total == 0:
            caption = "clean"
        else:
            caption_parts: list[str] = []
            if errors:
                caption_parts.append(f"{errors} error{'s' if errors != 1 else ''}")
            if warnings:
                caption_parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
            if infos:
                caption_parts.append(f"{infos} info")
            caption = ", ".join(caption_parts)
        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={**data, "backend": "rust"},
            caption=caption,
        )

    @staticmethod
    def _execute_python(
        charm_dir: pathlib.Path,
        select: str,
        ignore: str,
        severity: str,
    ) -> ToolResult:
        """Lint using the Python charmlint library."""
        from charmlint import LintConfig, lint

        config = LintConfig(
            select=[s.strip() for s in select.split(",") if s.strip()],
            ignore=[s.strip() for s in ignore.split(",") if s.strip()],
        )
        if severity:
            from charmlint.models import Severity

            config.min_severity = Severity(severity)

        report = lint(charm_dir, config)

        lines: list[str] = [d.format_text(charm_dir) for d in report.diagnostics]
        if lines:
            lines.append("")
        lines.append(report.summary_line())

        d = report.to_dict()
        total = d.get("total", 0)
        if total == 0:
            caption = "clean"
        else:
            caption_parts: list[str] = []
            if d.get("errors"):
                n = d["errors"]
                caption_parts.append(f"{n} error{'s' if n != 1 else ''}")
            if d.get("warnings"):
                n = d["warnings"]
                caption_parts.append(f"{n} warning{'s' if n != 1 else ''}")
            if d.get("info"):
                caption_parts.append(f"{d['info']} info")
            caption = ", ".join(caption_parts) or f"{total} issue{'s' if total != 1 else ''}"
        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={**d, "backend": "python"},
            caption=caption,
        )
