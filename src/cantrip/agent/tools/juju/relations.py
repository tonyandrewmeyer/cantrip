"""Juju relation and cross-model offer tools."""

import json
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.juju import _common


class JujuRelateTool(Tool):
    """Tool to create a relation between applications."""

    @property
    def name(self) -> str:
        return "juju_relate"

    @property
    def description(self) -> str:
        return "Create a relation (integration) between two applications."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app1": {
                    "type": "string",
                    "description": "First application (optionally with :endpoint)",
                },
                "app2": {
                    "type": "string",
                    "description": "Second application (optionally with :endpoint)",
                },
                "model": {
                    "type": "string",
                    "description": "Model name",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": (
                        "Must be true to integrate when the target controller is "
                        "non-local (or in the operator's production_controllers "
                        "list). Show the operator the controller name and cloud "
                        "and ask them to confirm before setting this."
                    ),
                    "default": False,
                },
            },
            "required": ["app1", "app2"],
        }

    async def execute(
        self,
        app1: str,
        app2: str,
        model: str | None = None,
        confirmed: bool = False,
    ) -> ToolResult:
        """Create a relation."""
        blocked, reason = _common.controller_confirm_required(
            "juju_relate", model=model, confirmed=confirmed
        )
        if blocked:
            return ToolResult(success=False, output="", error=reason)

        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = _common.jubilant.Juju(model=model)
            await _common._run_juju(juju.integrate, app1, app2)

            return ToolResult(
                success=True,
                output=f"Created relation: {app1} <-> {app2}",
                data={"app1": app1, "app2": app2},
                caption=f"Integrated {app1} ↔ {app2}",
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju integrate timed out — the controller may be unavailable.",
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


class JujuOfferTool(Tool):
    """Tool to create a cross-model offer."""

    @property
    def name(self) -> str:
        return "juju_offer"

    @property
    def description(self) -> str:
        return (
            "Create a cross-model offer for an application endpoint. "
            "This makes the endpoint available for consumption from other models."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "Application name to create the offer for",
                },
                "endpoint": {
                    "type": "string",
                    "description": "Endpoint name to offer (e.g. 'grafana-dashboard')",
                },
                "model": {
                    "type": "string",
                    "description": "Model where the application lives (uses current if not set)",
                },
            },
            "required": ["app", "endpoint"],
        }

    async def execute(
        self,
        app: str,
        endpoint: str,
        model: str | None = None,
    ) -> ToolResult:
        """Create a cross-model offer."""
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = _common.jubilant.Juju(model=model)
            await _common._run_juju(juju.offer, app, endpoint=endpoint)

            return ToolResult(
                success=True,
                output=f"Offer created: {app}:{endpoint}",
                data={"app": app, "endpoint": endpoint, "model": model},
                caption=f"Offered {app}:{endpoint}",
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju offer timed out — the controller may be unavailable.",
            )
        except _common.jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class JujuConsumeTool(Tool):
    """Tool to consume a cross-model offer."""

    @property
    def name(self) -> str:
        return "juju_consume"

    @property
    def description(self) -> str:
        return (
            "Consume a cross-model offer in the current model. "
            "After consuming, use juju_relate to integrate with local applications."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model_and_app": {
                    "type": "string",
                    "description": "Remote offer in 'model.app' format (e.g. 'cos.grafana')",
                },
                "alias": {
                    "type": "string",
                    "description": "Local alias for the consumed offer",
                },
                "model": {
                    "type": "string",
                    "description": "Model to consume the offer into (uses current if not set)",
                },
            },
            "required": ["model_and_app"],
        }

    async def execute(
        self,
        model_and_app: str,
        alias: str | None = None,
        model: str | None = None,
    ) -> ToolResult:
        """Consume a cross-model offer."""
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = _common.jubilant.Juju(model=model)
            await _common._run_juju(juju.consume, model_and_app, alias)

            label = alias or model_and_app.split(".")[-1]
            return ToolResult(
                success=True,
                output=f"Consumed offer '{model_and_app}' as '{label}'.",
                data={
                    "model_and_app": model_and_app,
                    "alias": alias,
                    "model": model,
                },
                caption=f"Consumed {model_and_app}" + (f" as {alias}" if alias else ""),
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju consume timed out — the controller may be unavailable.",
            )
        except _common.jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class JujuListOffersTool(Tool):
    """Tool to list cross-model offers."""

    @property
    def name(self) -> str:
        return "juju_list_offers"

    @property
    def description(self) -> str:
        return (
            "List cross-model offers in the current model or controller, with "
            "endpoint details and consumer tracking. Useful for diagnosing "
            "cross-model relation issues."
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
            },
        }

    async def execute(
        self,
        model: str | None = None,
    ) -> ToolResult:
        """List cross-model offers via juju status (offers section)."""
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = _common.jubilant.Juju(model=model)
            status = await _common._run_juju(juju.status)

            offers = status.offers
            if not offers:
                return ToolResult(
                    success=True,
                    output="No cross-model offers found in the model.",
                    data={"offers": [], "count": 0},
                    caption="no offers",
                )

            lines = [f"Found {len(offers)} offer(s):", ""]
            offer_list: list[dict[str, Any]] = []

            for offer_name, offer in offers.items():
                lines.append(f"- **{offer_name}** (app: {offer.app}, charm: {offer.charm})")
                lines.append(
                    f"  Connected: {offer.active_connected_count}/{offer.total_connected_count}"
                )
                if offer.endpoints:
                    for ep_name, ep in offer.endpoints.items():
                        lines.append(f"  Endpoint: {ep_name} ({ep.interface})")
                lines.append("")

                offer_list.append(
                    {
                        "name": offer_name,
                        "app": offer.app,
                        "charm": offer.charm,
                        "active_connected": offer.active_connected_count,
                        "total_connected": offer.total_connected_count,
                        "endpoints": {
                            name: {"interface": ep.interface}
                            for name, ep in (offer.endpoints or {}).items()
                        },
                    }
                )

            return ToolResult(
                success=True,
                output="\n".join(lines),
                data={"offers": offer_list, "count": len(offers)},
                caption=f"{len(offers)} offer{'s' if len(offers) != 1 else ''}",
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


class JujuReadRelationDataTool(Tool):
    """Tool to read relation databag contents."""

    @property
    def name(self) -> str:
        return "juju_read_relation_data"

    @property
    def description(self) -> str:
        return (
            "Read app-level and unit-level relation databags for a deployed "
            "application. Shows both sides of a relation to diagnose integration "
            "failures. Returns structured data including provider and requirer "
            "databags."
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
                "endpoint": {
                    "type": "string",
                    "description": "Relation endpoint to filter (optional — shows all if omitted)",
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
        endpoint: str | None = None,
        model: str | None = None,
    ) -> ToolResult:
        """Read relation data via juju show-unit."""
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )
        parsed = await self._fetch_show_unit_json(model, unit)
        if isinstance(parsed, ToolResult):
            return parsed
        relations = parsed.get(unit, {}).get("relation-info", [])
        if endpoint:
            relations = [r for r in relations if r.get("endpoint") == endpoint]
        if not relations:
            msg = f"No relation data found for {unit}"
            if endpoint:
                msg += f" on endpoint '{endpoint}'"
            return ToolResult(
                success=True,
                output=msg,
                data={"unit": unit, "relations": []},
                caption=f"no relations on {unit}",
            )
        lines = [f"Relation data for {unit}:", ""]
        relation_list: list[dict[str, Any]] = []
        for rel in relations:
            block_lines, block_data = self._format_relation_block(rel, unit)
            lines.extend(block_lines)
            relation_list.append(block_data)
        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"unit": unit, "relations": relation_list},
            caption=f"{len(relation_list)} relation{'s' if len(relation_list) != 1 else ''} on {unit}",
        )

    @staticmethod
    async def _fetch_show_unit_json(model: str | None, unit: str) -> dict[str, Any] | ToolResult:
        """Run ``juju show-unit`` and parse the JSON envelope."""
        try:
            juju = _common.jubilant.Juju(model=model)
            stdout = await _common._run_juju(juju.cli, "show-unit", unit, "--format", "json")
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju show-unit timed out.",
            )
        except (_common.jubilant.CLIError, OSError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=f"juju show-unit failed: {e}",
            )
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            return ToolResult(
                success=False,
                output="",
                error="Failed to parse juju show-unit output.",
            )

    @staticmethod
    def _format_relation_block(rel: dict[str, Any], unit: str) -> tuple[list[str], dict[str, Any]]:
        """Render one relation's databags as Markdown plus structured data."""
        ep = rel.get("endpoint", "unknown")
        rel_id = rel.get("relation-id", "?")
        lines: list[str] = [f"## {ep} (relation {rel_id})", ""]
        related_units = rel.get("related-units", {})
        app_data = rel.get("application-data", {})
        if app_data:
            lines.append("**Application data:**")
            for key, value in app_data.items():
                lines.append(f"  {key}: {value}")
            lines.append("")
        local_unit_data = rel.get("local-unit", {}).get("data", {})
        if local_unit_data:
            lines.append(f"**Local unit data ({unit}):**")
            for key, value in local_unit_data.items():
                lines.append(f"  {key}: {value}")
            lines.append("")
        if related_units:
            for runit, rdata in related_units.items():
                lines.append(f"**Related unit: {runit}**")
                unit_rel_data = rdata.get("data", {})
                for key, value in unit_rel_data.items():
                    lines.append(f"  {key}: {value}")
                lines.append("")
        # Highlight asymmetries — remote keys absent from local, ignoring the
        # three address keys Juju synthesises that the local side never sets.
        expected_keys: set[str] = set()
        for rdata in related_units.values():
            expected_keys.update(rdata.get("data", {}).keys())
        missing_in_local = (
            expected_keys
            - set(local_unit_data.keys())
            - {"ingress-address", "private-address", "egress-subnets"}
        )
        if missing_in_local:
            lines.append(
                f"**Asymmetry:** remote has keys not in local: {', '.join(sorted(missing_in_local))}"
            )
            lines.append("")
        return lines, {
            "endpoint": ep,
            "relation_id": rel_id,
            "application_data": app_data,
            "local_unit_data": local_unit_data,
            "related_units": {
                runit: rdata.get("data", {}) for runit, rdata in related_units.items()
            },
        }
