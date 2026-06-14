"""Relation smoke-test acceptance tool."""

import contextlib
import pathlib
import shutil
import subprocess
from typing import Any

from cantrip.agent.tools import juju_subprocess
from cantrip.agent.tools.acceptance import _common
from cantrip.agent.tools.acceptance._common import (
    _INTERFACE_PARTNERS,
    _load_charm_metadata,
)
from cantrip.agent.tools.base import Tool, ToolResult

# ---------------------------------------------------------------------------
# 17.2 Relation Smoke Tests
# ---------------------------------------------------------------------------


class RelationSmokeTool(Tool):
    """Deploy partner charms and verify relation integrations."""

    @property
    def name(self) -> str:
        return "relation_smoke_test"

    @property
    def description(self) -> str:
        return (
            "Test relation integrations by deploying well-known partner "
            "charms for each relation endpoint and verifying both sides "
            "settle to active/idle. Uses a built-in mapping of common "
            "interfaces to Charmhub charms."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "Application name",
                },
                "path": {
                    "type": "string",
                    "description": "Path to the charm directory (for reading metadata)",
                    "default": ".",
                },
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
                "skip_endpoints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Endpoint names to skip",
                    "default": [],
                },
                "timeout": {
                    "type": "integer",
                    "description": "Per-relation timeout in seconds (default 600)",
                    "default": 600,
                },
            },
            "required": ["app"],
        }

    async def execute(
        self,
        app: str = "",
        path: str = ".",
        model: str | None = None,
        skip_endpoints: list[str] | None = None,
        timeout: int = 600,
    ) -> ToolResult:
        """Deploy partners and test each relation endpoint."""
        if not shutil.which("juju"):
            return ToolResult(success=False, output="", error="juju CLI not found on PATH.")
        if not app:
            return ToolResult(success=False, output="", error="app parameter is required.")

        skip = set(skip_endpoints or [])
        charm_dir = pathlib.Path(path).resolve()
        metadata = _load_charm_metadata(charm_dir)

        requires = metadata.get("requires", {}) if metadata else {}
        provides = metadata.get("provides", {}) if metadata else {}
        peers = metadata.get("peers", {}) if metadata else {}

        all_endpoints: dict[str, dict[str, Any]] = {}
        for name, spec in requires.items():
            if isinstance(spec, dict):
                all_endpoints[name] = {"interface": spec.get("interface", ""), "role": "requires"}
        for name, spec in provides.items():
            if isinstance(spec, dict):
                all_endpoints[name] = {"interface": spec.get("interface", ""), "role": "provides"}
        for name, spec in peers.items():
            if isinstance(spec, dict):
                all_endpoints[name] = {"interface": spec.get("interface", ""), "role": "peers"}

        if not all_endpoints:
            return ToolResult(
                success=True,
                output="# Relation Smoke Test Report\n\nNo relation endpoints — nothing to test.",
                data={"app": app, "endpoints_tested": 0, "results": []},
            )

        results: list[dict[str, Any]] = []
        skipped_names: list[str] = []

        for ep_name, ep_info in all_endpoints.items():
            if ep_name in skip:
                skipped_names.append(ep_name)
                continue

            interface = ep_info["interface"]
            role = ep_info["role"]

            # Peers cannot be tested via deploy + relate.
            if role == "peers":
                results.append(
                    {
                        "endpoint": ep_name,
                        "interface": interface,
                        "role": role,
                        "partner": "—",
                        "status": "skipped",
                        "notes": "Peer relations are tested via scaling",
                    }
                )
                continue

            partner = _INTERFACE_PARTNERS.get(interface)
            if not partner:
                results.append(
                    {
                        "endpoint": ep_name,
                        "interface": interface,
                        "role": role,
                        "partner": "—",
                        "status": "skipped",
                        "notes": f"No known partner for interface '{interface}'",
                    }
                )
                continue

            # Deploy partner (ignore failure if already deployed).
            with contextlib.suppress(subprocess.TimeoutExpired):
                juju_subprocess.run_juju(["deploy", partner], model)

            # Relate.
            try:
                relate_result = juju_subprocess.run_juju(
                    ["relate", f"{app}:{ep_name}", partner], model
                )
                if relate_result.returncode != 0 and "already exists" not in relate_result.stderr:
                    results.append(
                        {
                            "endpoint": ep_name,
                            "interface": interface,
                            "role": role,
                            "partner": partner,
                            "status": "failed",
                            "notes": f"Relate failed: {relate_result.stderr[:200]}",
                        }
                    )
                    continue
            except subprocess.TimeoutExpired:
                results.append(
                    {
                        "endpoint": ep_name,
                        "interface": interface,
                        "role": role,
                        "partner": partner,
                        "status": "timeout",
                        "notes": "Relate command timed out",
                    }
                )
                continue

            # Wait for both to settle.
            settled = juju_subprocess.wait_for_app(app, model, timeout)

            if settled:
                # Verify data actually flowed through the relation databag.
                unit_name = f"{app}/0"
                has_data, data_notes = _common._verify_relation_data(unit_name, ep_name, model)
                if has_data:
                    notes = f"Active/idle, data flowing ({data_notes})"
                else:
                    notes = f"Active/idle but {data_notes}"
            else:
                notes = "Did not settle"

            results.append(
                {
                    "endpoint": ep_name,
                    "interface": interface,
                    "role": role,
                    "partner": partner,
                    "status": "pass" if settled else "failed",
                    "notes": notes,
                }
            )

        tested = [r for r in results if r["status"] not in ("skipped",)]
        passed = sum(1 for r in tested if r["status"] == "pass")
        failed = len(tested) - passed
        all_ok = failed == 0

        lines = [
            "# Relation Smoke Test Report",
            "",
            f"**Application:** {app}",
            f"**Endpoints tested:** {len(tested)} ({len(results) - len(tested)} skipped)",
            "",
            "## Results",
            "",
            "| Endpoint | Interface | Role | Partner | Status | Notes |",
            "|----------|-----------|------|---------|--------|-------|",
        ]
        for r in results:
            lines.append(
                f"| {r['endpoint']} | {r['interface']} | {r['role']} "
                f"| {r['partner']} | {r['status']} | {r['notes']} |"
            )

        lines.extend(
            [
                "",
                "## Verdict",
                "",
                f"**{'PASS' if all_ok else 'FAIL'}** — {passed} of {len(tested)} relations passed",
                "",
            ]
        )

        return ToolResult(
            success=all_ok,
            output="\n".join(lines),
            error=None if all_ok else f"{failed} relation(s) failed",
            caption=f"{passed} passed, {failed} failed",
            data={
                "app": app,
                "endpoints_tested": len(tested),
                "endpoints_passed": passed,
                "endpoints_failed": failed,
                "results": results,
                "verdict": "pass" if all_ok else "fail",
            },
        )
