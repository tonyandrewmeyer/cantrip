"""Charmhub API tools for searching and inspecting charms."""

import json
from typing import Any

import httpx
import yaml

from cantrip.agent.tools.base import Tool, ToolResult

# Cap search results to avoid blowing up the LLM context window.
MAX_SEARCH_RESULTS = 20

_BASE_URL = "https://api.charmhub.io/v2/charms"


class CharmhubSearchTool(Tool):
    """Search Charmhub for existing charms."""

    @property
    def name(self) -> str:
        return "charmhub_search"

    @property
    def description(self) -> str:
        return (
            "Search Charmhub for existing charms matching a query."
            " Returns name, summary, publisher, and categories for each result."
            " Use this before building an infrastructure charm to check whether"
            " a suitable charm already exists."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g. 'postgresql', 'redis', 'kafka').",
                },
                "category": {
                    "type": "string",
                    "description": ("Optional category filter (e.g. 'databases', 'monitoring')."),
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, category: str | None = None) -> ToolResult:
        """Search Charmhub for charms matching *query*."""
        params: dict[str, str] = {
            "q": query,
            "fields": "result.categories,result.summary,result.publisher.display-name",
        }
        if category:
            params["category"] = category

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "Cantrip/0.1"},
            ) as client:
                response = await client.get(f"{_BASE_URL}/find", params=params)
                response.raise_for_status()
        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                output="",
                error=f"Request timed out searching Charmhub for '{query}'",
            )
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"HTTP {exc.response.status_code} searching Charmhub for '{query}'",
                data={"status_code": exc.response.status_code, "query": query},
            )
        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Connection error searching Charmhub: {exc}",
            )

        try:
            body = response.json()
        except (ValueError, json.JSONDecodeError):
            return ToolResult(
                success=False,
                output="",
                error=f"Charmhub returned non-JSON response (HTTP {response.status_code})",
            )
        raw_results = body.get("results", [])
        total = len(raw_results)
        truncated = total > MAX_SEARCH_RESULTS
        results = raw_results[:MAX_SEARCH_RESULTS]

        formatted: list[dict[str, Any]] = []
        lines: list[str] = []
        for item in results:
            name = item.get("name", "unknown")
            result_block = item.get("result", {})
            summary = result_block.get("summary", "")
            publisher = result_block.get("publisher", {}).get("display-name", "unknown")
            categories = [c.get("name", "") for c in result_block.get("categories", [])]

            formatted.append(
                {
                    "name": name,
                    "summary": summary,
                    "publisher": publisher,
                    "categories": categories,
                }
            )
            cat_str = ", ".join(categories) if categories else "uncategorised"
            lines.append(f"- **{name}** ({cat_str}) — {summary} [by {publisher}]")

        if not lines:
            output = f"No charms found for '{query}'."
        else:
            header = f"Found {total} charm(s) for '{query}'"
            if truncated:
                header += f" (showing first {MAX_SEARCH_RESULTS})"
            header += ":\n"
            output = header + "\n".join(lines)

        return ToolResult(
            success=True,
            output=output,
            data={"results": formatted, "total": total, "query": query},
        )


class CharmhubInfoTool(Tool):
    """Retrieve detailed information about a specific charm from Charmhub."""

    @property
    def name(self) -> str:
        return "charmhub_info"

    @property
    def description(self) -> str:
        return (
            "Get detailed information about a charm on Charmhub including its"
            " relations, config options, storage, and containers."
            " Use this after charmhub_search to evaluate whether an existing"
            " charm meets requirements."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Charm name on Charmhub (e.g. 'postgresql-k8s').",
                },
            },
            "required": ["name"],
        }

    async def execute(self, name: str) -> ToolResult:
        """Fetch detailed info for the charm called *name*."""
        fields = "default-release.revision.metadata-yaml,default-release.revision.config-yaml"
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "Cantrip/0.1"},
            ) as client:
                response = await client.get(
                    f"{_BASE_URL}/info/{name}",
                    params={"fields": fields},
                )
                response.raise_for_status()
        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                output="",
                error=f"Request timed out fetching Charmhub info for '{name}'",
            )
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code == 404:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Charm '{name}' not found on Charmhub",
                    data={"status_code": 404, "name": name},
                )
            return ToolResult(
                success=False,
                output="",
                error=f"HTTP {code} fetching Charmhub info for '{name}'",
                data={"status_code": code, "name": name},
            )
        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Connection error fetching Charmhub info: {exc}",
            )

        try:
            body = response.json()
        except (ValueError, json.JSONDecodeError):
            return ToolResult(
                success=False,
                output="",
                error=f"Charmhub returned non-JSON response (HTTP {response.status_code})",
            )
        revision = body.get("default-release", {}).get("revision", {})

        # Parse metadata YAML.
        metadata: dict[str, Any] = {}
        metadata_raw = revision.get("metadata-yaml")
        if metadata_raw:
            try:
                metadata = yaml.safe_load(metadata_raw) or {}
            except yaml.YAMLError:
                metadata = {}

        # Parse config YAML.
        config: dict[str, Any] = {}
        config_raw = revision.get("config-yaml")
        if config_raw:
            try:
                config = yaml.safe_load(config_raw) or {}
            except yaml.YAMLError:
                config = {}

        summary = metadata.get("summary", metadata.get("description", "No description available"))

        # Build human-readable output.
        lines: list[str] = [f"# {name}", ""]
        if summary:
            lines.append(summary)
            lines.append("")

        description = metadata.get("description", "")
        if description and description != summary:
            lines.append(description)
            lines.append("")

        # Relations.
        for section in ("provides", "requires", "peers"):
            relations = metadata.get(section, {})
            if relations:
                lines.append(f"## {section.title()}")
                for rel_name, rel_data in relations.items():
                    iface = (
                        rel_data.get("interface", "unknown")
                        if isinstance(rel_data, dict)
                        else "unknown"
                    )
                    lines.append(f"- **{rel_name}**: `{iface}`")
                lines.append("")

        # Storage.
        storage = metadata.get("storage", {})
        if storage:
            lines.append("## Storage")
            for store_name, store_data in storage.items():
                stype = (
                    store_data.get("type", "unknown")
                    if isinstance(store_data, dict)
                    else "unknown"
                )
                lines.append(f"- **{store_name}**: {stype}")
            lines.append("")

        # Containers.
        containers = metadata.get("containers", {})
        if containers:
            lines.append("## Containers")
            for cname in containers:
                lines.append(f"- {cname}")
            lines.append("")

        # Config options.
        options = config.get("options", {})
        if options:
            lines.append("## Config Options")
            for opt_name, opt_data in options.items():
                opt_type = (
                    opt_data.get("type", "string") if isinstance(opt_data, dict) else "string"
                )
                opt_desc = opt_data.get("description", "") if isinstance(opt_data, dict) else ""
                lines.append(f"- **{opt_name}** ({opt_type}): {opt_desc}")
            lines.append("")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={
                "name": name,
                "metadata": metadata,
                "config": config,
                "summary": summary,
            },
        )
