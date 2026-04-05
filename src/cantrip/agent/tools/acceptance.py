"""Acceptance testing tools — exercise a deployed charm like a real operator.

Provides five tools for Phase 17 acceptance testing:
- ActionExerciserTool: run every action and verify results
- RelationSmokeTool: deploy partner charms and verify integrations
- WorkloadEndpointTool: probe HTTP/TCP endpoints on the running workload
- ConfigVariationTool: set each config option and verify the charm settles
- AcceptanceReportTool: consolidate results into ACCEPTANCE.md
"""

import contextlib
import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from cantrip.agent.tools.base import Tool, ToolResult

# Subprocess timeout (seconds).
_SUBPROCESS_TIMEOUT = 60

# Wait timeout after changes (seconds).
_SETTLE_TIMEOUT = 300

# Patterns indicating destructive actions that should be skipped by default.
_DESTRUCTIVE_PATTERNS = re.compile(
    r"^(delete|destroy|reset|purge|wipe|remove|drop|erase|nuke)-",
    re.IGNORECASE,
)

# Well-known interface → partner charm mapping for relation smoke tests.
_INTERFACE_PARTNERS: dict[str, str] = {
    "mysql_client": "mysql-k8s",
    "mysql": "mysql-k8s",
    "pgsql": "postgresql-k8s",
    "postgresql_client": "postgresql-k8s",
    "ingress": "traefik-k8s",
    "ingress-per-unit": "traefik-k8s",
    "cos-agent": "grafana-agent-k8s",
    "grafana-dashboard": "grafana-k8s",
    "metrics-endpoint": "prometheus-k8s",
    "logging": "loki-k8s",
    "tracing": "tempo-k8s",
    "mongodb_client": "mongodb-k8s",
    "redis": "redis-k8s",
    "s3": "s3-integrator",
    "certificates": "self-signed-certificates",
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _run_juju(args: list[str], model: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run a juju command and return the result."""
    cmd = ["juju"] + args
    if model:
        cmd.extend(["--model", model])
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
    )


def _wait_for_app(app: str, model: str | None, timeout: int) -> bool:
    """Wait for all units of an application to reach active/idle."""
    cmd = ["juju", "wait-for", "application", app, "--timeout", f"{timeout}s"]
    if model:
        cmd.extend(["--model", model])
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 30,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _load_charm_metadata(charm_dir: Path) -> dict[str, Any] | None:
    """Load and parse charmcraft.yaml from a charm directory."""
    charmcraft_yaml = charm_dir / "charmcraft.yaml"
    if not charmcraft_yaml.exists():
        return None
    try:
        data = yaml.safe_load(charmcraft_yaml.read_text())
        return data if isinstance(data, dict) else None
    except yaml.YAMLError:
        return None


def _verify_relation_data(
    unit: str,
    endpoint: str,
    model: str | None,
) -> tuple[bool, str]:
    """Check whether a relation databag has non-trivial data.

    Returns (has_data, notes) where has_data is True if the related unit
    published at least one key beyond standard address fields.
    """
    cmd = ["juju", "show-unit", unit, "--format", "json"]
    if model:
        cmd.extend(["--model", model])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False, "Could not read relation data"

    if result.returncode != 0:
        return False, "juju show-unit failed"

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False, "Invalid JSON from show-unit"

    unit_data = data.get(unit, {})
    # Standard address-only keys that don't indicate real data flow.
    _ADDRESS_KEYS = {"ingress-address", "private-address", "egress-subnets"}

    for rel in unit_data.get("relation-info", []):
        if rel.get("endpoint") != endpoint:
            continue
        # Check application-level data.
        app_data = rel.get("application-data", {})
        meaningful_app = set(app_data.keys()) - _ADDRESS_KEYS
        if meaningful_app:
            return True, f"App data keys: {', '.join(sorted(meaningful_app))}"
        # Check related unit data.
        for _runit, rdata in rel.get("related-units", {}).items():
            meaningful_unit = set(rdata.get("data", {}).keys()) - _ADDRESS_KEYS
            if meaningful_unit:
                return True, f"Unit data keys: {', '.join(sorted(meaningful_unit))}"
        return False, "Relation established but databag is empty (address-only)"

    return False, "Endpoint not found in relation-info"


def _get_unit_address(app: str, model: str | None) -> str | None:
    """Get the address of the first unit via juju status --format json."""
    result = _run_juju(["status", "--format", "json", app], model)
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        units = data.get("applications", {}).get(app, {}).get("units", {})
        for _unit_name, unit_data in sorted(units.items()):
            addr = unit_data.get("address")
            if addr:
                return addr
    except (ValueError, KeyError):
        pass
    return None


def _generate_action_params(action_spec: dict[str, Any]) -> dict[str, str]:
    """Generate plausible parameter values from an action's parameter schema.

    Uses types, defaults, and descriptions to produce reasonable test values.
    """
    params: dict[str, str] = {}
    properties = action_spec.get("params", action_spec.get("parameters", {}))
    if not isinstance(properties, dict):
        return params

    for name, spec in properties.items():
        if not isinstance(spec, dict):
            continue

        # Use default if available.
        if "default" in spec:
            params[name] = str(spec["default"])
            continue

        # Generate from type.
        param_type = spec.get("type", "string")
        if param_type == "boolean":
            params[name] = "true"
        elif param_type in ("integer", "number"):
            minimum = spec.get("minimum", 1)
            params[name] = str(minimum)
        elif param_type == "string":
            # Use first enum value if available, otherwise a placeholder.
            enum_vals = spec.get("enum", [])
            if enum_vals:
                params[name] = str(enum_vals[0])
            else:
                params[name] = "test"
        elif param_type == "array":
            params[name] = "[]"

    return params


def _generate_test_value(
    opt_type: str,
    default: Any,
) -> str | None:
    """Generate a non-default config test value for a given type.

    Returns ``None`` if no sensible alternative can be produced.
    """
    if opt_type == "boolean":
        # Toggle from default.
        if default is True:
            return "false"
        return "true"
    if opt_type in ("int", "integer"):
        base = int(default) if default is not None else 0
        return str(base + 1)
    if opt_type == "float":
        base = float(default) if default is not None else 0.0
        return str(base + 0.5)
    if opt_type == "string":
        if default:
            return f"{default}-test"
        return "test-value"
    return None


# ---------------------------------------------------------------------------
# 17.1 Action Exerciser
# ---------------------------------------------------------------------------


class ActionExerciserTool(Tool):
    """Run every action a charm exposes and verify the results."""

    @property
    def name(self) -> str:
        return "action_exerciser"

    @property
    def description(self) -> str:
        return (
            "Run every action a deployed charm exposes against a live "
            "deployment. For each action, generate plausible parameters "
            "from the schema, execute via juju run, and report the result. "
            "Destructive-sounding actions are skipped by default."
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
                "skip_destructive": {
                    "type": "boolean",
                    "description": "Skip destructive-sounding actions (default true)",
                    "default": True,
                },
                "timeout": {
                    "type": "integer",
                    "description": "Per-action timeout in seconds (default 300)",
                    "default": 300,
                },
            },
            "required": ["app"],
        }

    async def execute(
        self,
        app: str = "",
        path: str = ".",
        model: str | None = None,
        skip_destructive: bool = True,
        timeout: int = 300,
    ) -> ToolResult:
        """Exercise all actions on the deployed charm."""
        if not shutil.which("juju"):
            return ToolResult(success=False, output="", error="juju CLI not found on PATH.")
        if not app:
            return ToolResult(success=False, output="", error="app parameter is required.")

        charm_dir = Path(path).resolve()
        metadata = _load_charm_metadata(charm_dir)
        actions = metadata.get("actions", {}) if metadata else {}

        if not actions:
            return ToolResult(
                success=True,
                output="# Action Exerciser Report\n\nNo actions defined — nothing to test.",
                data={"app": app, "actions_tested": 0, "actions_skipped": 0, "results": []},
            )

        results: list[dict[str, Any]] = []
        skipped: list[str] = []

        for action_name, action_spec in actions.items():
            if not isinstance(action_spec, dict):
                action_spec = {}

            # Skip destructive actions.
            if skip_destructive and _DESTRUCTIVE_PATTERNS.match(action_name):
                skipped.append(action_name)
                continue

            params = _generate_action_params(action_spec)

            # Build juju run command.
            cmd_args = ["run", f"{app}/leader", action_name, "--format", "json"]
            for k, v in params.items():
                cmd_args.append(f"{k}={v}")
            if model:
                cmd_args.extend(["--model", model])

            try:
                proc = subprocess.run(
                    ["juju"] + cmd_args,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                status = "completed" if proc.returncode == 0 else "failed"
                output_text = proc.stdout[:500] if proc.stdout else proc.stderr[:500]
            except subprocess.TimeoutExpired:
                status = "timeout"
                output_text = f"Timed out after {timeout}s"

            results.append(
                {
                    "action": action_name,
                    "parameters": params,
                    "status": status,
                    "output": output_text,
                }
            )

        # Build report.
        total_ok = sum(1 for r in results if r["status"] == "completed")
        total_fail = len(results) - total_ok
        all_ok = total_fail == 0

        lines = [
            "# Action Exerciser Report",
            "",
            f"**Application:** {app}",
            f"**Actions tested:** {len(results)} ({len(skipped)} skipped as destructive)",
            "",
            "## Results",
            "",
            "| Action | Parameters | Status | Notes |",
            "|--------|-----------|--------|-------|",
        ]
        for r in results:
            param_str = ", ".join(f"{k}={v}" for k, v in r["parameters"].items()) or "—"
            note = r["output"].split("\n")[0][:80] if r["output"] else ""
            lines.append(f"| {r['action']} | {param_str} | {r['status']} | {note} |")

        if skipped:
            lines.append("")
            lines.append(f"**Skipped (destructive):** {', '.join(skipped)}")

        lines.extend(
            [
                "",
                "## Verdict",
                "",
                f"**{'PASS' if all_ok else 'FAIL'}** "
                f"— {total_ok} of {len(results)} actions succeeded",
                "",
            ]
        )

        return ToolResult(
            success=all_ok,
            output="\n".join(lines),
            error=None if all_ok else f"{total_fail} action(s) failed",
            data={
                "app": app,
                "actions_tested": len(results),
                "actions_skipped": len(skipped),
                "actions_passed": total_ok,
                "actions_failed": total_fail,
                "results": results,
                "verdict": "pass" if all_ok else "fail",
            },
        )


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
        charm_dir = Path(path).resolve()
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
                _run_juju(["deploy", partner], model)

            # Relate.
            try:
                relate_result = _run_juju(["relate", f"{app}:{ep_name}", partner], model)
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
            settled = _wait_for_app(app, model, timeout)

            if settled:
                # Verify data actually flowed through the relation databag.
                unit_name = f"{app}/0"
                has_data, data_notes = _verify_relation_data(unit_name, ep_name, model)
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
            data={
                "app": app,
                "endpoints_tested": len(tested),
                "endpoints_passed": passed,
                "endpoints_failed": failed,
                "results": results,
                "verdict": "pass" if all_ok else "fail",
            },
        )


# ---------------------------------------------------------------------------
# 17.3 Workload Endpoint Testing
# ---------------------------------------------------------------------------


class WorkloadEndpointTool(Tool):
    """Probe HTTP and TCP endpoints on the running workload."""

    @property
    def name(self) -> str:
        return "workload_endpoint_test"

    @property
    def description(self) -> str:
        return (
            "Probe workload endpoints on a deployed charm — HTTP health "
            "checks, TCP port liveness, and common paths like /health and "
            "/ready. Discovers endpoints from charm metadata or accepts "
            "explicit endpoint definitions."
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
                "endpoints": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "port": {"type": "integer"},
                            "protocol": {
                                "type": "string",
                                "enum": ["http", "tcp"],
                                "default": "http",
                            },
                        },
                    },
                    "description": (
                        "Explicit endpoints to probe. If empty, discovers from metadata."
                    ),
                    "default": [],
                },
                "timeout": {
                    "type": "integer",
                    "description": "Per-probe timeout in seconds (default 30)",
                    "default": 30,
                },
            },
            "required": ["app"],
        }

    async def execute(
        self,
        app: str = "",
        path: str = ".",
        model: str | None = None,
        endpoints: list[dict[str, Any]] | None = None,
        timeout: int = 30,
    ) -> ToolResult:
        """Probe workload endpoints."""
        if not shutil.which("juju"):
            return ToolResult(success=False, output="", error="juju CLI not found on PATH.")
        if not app:
            return ToolResult(success=False, output="", error="app parameter is required.")

        unit_addr = _get_unit_address(app, model)

        # Discover endpoints if not provided.
        probes = list(endpoints or [])
        if not probes:
            probes = self._discover_endpoints(path, unit_addr)

        if not probes:
            return ToolResult(
                success=True,
                output=(
                    "# Workload Endpoint Test Report\n\n"
                    "No endpoints discovered — nothing to probe."
                ),
                data={"app": app, "endpoints_tested": 0, "results": []},
            )

        results: list[dict[str, Any]] = []
        for probe in probes:
            protocol = probe.get("protocol", "http")
            url = probe.get("url", "")
            port = probe.get("port")

            if not url and port and unit_addr:
                if protocol == "http":
                    url = f"http://{unit_addr}:{port}/"
                else:
                    url = f"{unit_addr}:{port}"

            if not url:
                results.append(
                    {
                        "endpoint": f"port {port}" if port else "unknown",
                        "protocol": protocol,
                        "status": "skipped",
                        "response_time": "—",
                        "notes": "No unit address available",
                    }
                )
                continue

            if protocol == "http":
                result = self._probe_http(url, timeout)
            else:
                result = self._probe_tcp(
                    unit_addr or "",
                    port or 0,
                    timeout,
                    model,
                    app,
                )
            result["endpoint"] = url
            result["protocol"] = protocol
            results.append(result)

        tested = [r for r in results if r["status"] != "skipped"]
        passed = sum(1 for r in tested if r["status"] == "pass")
        failed = len(tested) - passed
        all_ok = failed == 0

        lines = [
            "# Workload Endpoint Test Report",
            "",
            f"**Application:** {app}",
            f"**Endpoints probed:** {len(tested)}",
            "",
            "## Results",
            "",
            "| Endpoint | Protocol | Status | Response Time | Notes |",
            "|----------|----------|--------|--------------|-------|",
        ]
        for r in results:
            lines.append(
                f"| {r['endpoint']} | {r['protocol']} | {r['status']} "
                f"| {r.get('response_time', '—')} | {r.get('notes', '')} |"
            )
        lines.extend(
            [
                "",
                "## Verdict",
                "",
                f"**{'PASS' if all_ok else 'FAIL'}** "
                f"— {passed} of {len(tested)} endpoints responded",
                "",
            ]
        )

        return ToolResult(
            success=all_ok,
            output="\n".join(lines),
            error=None if all_ok else f"{failed} endpoint(s) failed",
            data={
                "app": app,
                "endpoints_tested": len(tested),
                "endpoints_passed": passed,
                "endpoints_failed": failed,
                "results": results,
                "verdict": "pass" if all_ok else "fail",
            },
        )

    @staticmethod
    def _discover_endpoints(path: str, unit_addr: str | None) -> list[dict[str, Any]]:
        """Discover endpoints from charmcraft.yaml containers and config."""
        charm_dir = Path(path).resolve()
        metadata = _load_charm_metadata(charm_dir)
        if not metadata:
            return []

        probes: list[dict[str, Any]] = []

        # Discover ports from containers.
        containers = metadata.get("containers", {})
        for _name, container_spec in containers.items():
            if not isinstance(container_spec, dict):
                continue
            # OCI image containers may declare ports.
            for port_entry in container_spec.get("ports", []):
                if isinstance(port_entry, dict) and "target" in port_entry:
                    probes.append({"port": port_entry["target"], "protocol": "http"})

        # Check config for port options.
        config_opts = metadata.get("config", {}).get("options", {})
        for opt_name, opt_spec in config_opts.items():
            if not isinstance(opt_spec, dict):
                continue
            if "port" in opt_name.lower() and opt_spec.get("default"):
                probes.append({"port": int(opt_spec["default"]), "protocol": "http"})

        # Add common health paths for each HTTP port.
        if probes and unit_addr:
            health_probes = []
            seen_ports: set[int] = set()
            for p in probes:
                port = p.get("port")
                if port and port not in seen_ports:
                    seen_ports.add(port)
                    for health_path in ("/health", "/ready", "/healthz", "/readyz"):
                        health_probes.append(
                            {
                                "url": f"http://{unit_addr}:{port}{health_path}",
                                "protocol": "http",
                            }
                        )
            probes.extend(health_probes)

        return probes

    @staticmethod
    def _probe_http(url: str, timeout: int) -> dict[str, Any]:
        """Probe an HTTP endpoint via curl."""
        try:
            proc = subprocess.run(
                [
                    "curl",
                    "-s",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code} %{time_total}",
                    "--max-time",
                    str(timeout),
                    "--connect-timeout",
                    "10",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=timeout + 5,
            )
            parts = proc.stdout.strip().split()
            http_code = parts[0] if parts else "000"
            response_time = f"{parts[1]}s" if len(parts) > 1 else "—"

            ok = http_code.startswith(("2", "3"))
            return {
                "status": "pass" if ok else "failed",
                "response_time": response_time,
                "notes": f"HTTP {http_code}",
            }
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            return {
                "status": "failed",
                "response_time": "—",
                "notes": f"Probe error: {exc}",
            }

    @staticmethod
    def _probe_tcp(
        host: str,
        port: int,
        timeout: int,
        model: str | None,
        app: str,
    ) -> dict[str, Any]:
        """Probe a TCP port via juju ssh + bash."""
        if not host or not port:
            return {
                "status": "skipped",
                "response_time": "—",
                "notes": "Missing host or port",
            }

        # Use juju ssh to check port from within the model network.
        safe_host = shlex.quote(str(host))
        safe_port = shlex.quote(str(port))
        check_cmd = f"bash -c 'echo > /dev/tcp/{safe_host}/{safe_port}'"
        cmd = ["juju", "ssh", f"{app}/leader", "--", check_cmd]
        if model:
            cmd.extend(["--model", model])
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            ok = proc.returncode == 0
            return {
                "status": "pass" if ok else "failed",
                "response_time": "—",
                "notes": "Port open" if ok else f"Port closed: {proc.stderr[:100]}",
            }
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            return {
                "status": "failed",
                "response_time": "—",
                "notes": f"TCP probe error: {exc}",
            }


# ---------------------------------------------------------------------------
# 17.4 Config Variation Testing
# ---------------------------------------------------------------------------


class ConfigVariationTool(Tool):
    """Set each config option to a non-default value and verify the charm settles."""

    @property
    def name(self) -> str:
        return "config_variation_test"

    @property
    def description(self) -> str:
        return (
            "Test charm config options by setting each to a non-default "
            "value, waiting for the charm to settle, then resetting to the "
            "original. Reports which options caused errors or had no visible "
            "effect."
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
                "skip_options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Config option names to skip",
                    "default": [],
                },
                "timeout": {
                    "type": "integer",
                    "description": ("Seconds to wait for settle after each change (default 120)"),
                    "default": 120,
                },
            },
            "required": ["app"],
        }

    async def execute(
        self,
        app: str = "",
        path: str = ".",
        model: str | None = None,
        skip_options: list[str] | None = None,
        timeout: int = 120,
    ) -> ToolResult:
        """Test each config option with a non-default value."""
        if not shutil.which("juju"):
            return ToolResult(success=False, output="", error="juju CLI not found on PATH.")
        if not app:
            return ToolResult(success=False, output="", error="app parameter is required.")

        skip = set(skip_options or [])
        charm_dir = Path(path).resolve()
        metadata = _load_charm_metadata(charm_dir)
        config_opts = metadata.get("config", {}).get("options", {}) if metadata else {}

        if not config_opts:
            return ToolResult(
                success=True,
                output="# Config Variation Test Report\n\nNo config options — nothing to test.",
                data={"app": app, "options_tested": 0, "results": []},
            )

        results: list[dict[str, Any]] = []
        skipped_names: list[str] = []

        for opt_name, opt_spec in config_opts.items():
            if not isinstance(opt_spec, dict):
                continue
            if opt_name in skip:
                skipped_names.append(opt_name)
                continue

            # Skip risky path/directory options.
            if any(kw in opt_name.lower() for kw in ("path", "dir", "directory", "mount")):
                skipped_names.append(opt_name)
                continue

            opt_type = opt_spec.get("type", "string")
            default = opt_spec.get("default")
            test_value = _generate_test_value(opt_type, default)

            if test_value is None:
                skipped_names.append(opt_name)
                continue

            # Set the config value.
            try:
                set_result = _run_juju(["config", app, f"{opt_name}={test_value}"], model)
                if set_result.returncode != 0:
                    results.append(
                        {
                            "option": opt_name,
                            "type": opt_type,
                            "test_value": test_value,
                            "settled_ok": False,
                            "notes": f"Set failed: {set_result.stderr[:200]}",
                        }
                    )
                    continue
            except subprocess.TimeoutExpired:
                results.append(
                    {
                        "option": opt_name,
                        "type": opt_type,
                        "test_value": test_value,
                        "settled_ok": False,
                        "notes": "Set command timed out",
                    }
                )
                continue

            # Wait for settle.
            settled = _wait_for_app(app, model, timeout)

            results.append(
                {
                    "option": opt_name,
                    "type": opt_type,
                    "test_value": test_value,
                    "settled_ok": settled,
                    "notes": "Settled to active/idle" if settled else "Did not settle",
                }
            )

            # Reset to default.
            try:
                _run_juju(["config", app, "--reset", opt_name], model)
                _wait_for_app(app, model, timeout)
            except subprocess.TimeoutExpired:
                pass

        tested = list(results)
        passed = sum(1 for r in tested if r["settled_ok"])
        failed = len(tested) - passed
        all_ok = failed == 0

        lines = [
            "# Config Variation Test Report",
            "",
            f"**Application:** {app}",
            f"**Options tested:** {len(tested)} ({len(skipped_names)} skipped)",
            "",
            "## Results",
            "",
            "| Option | Type | Test Value | Settled OK | Notes |",
            "|--------|------|-----------|-----------|-------|",
        ]
        for r in results:
            settled_str = "yes" if r["settled_ok"] else "NO"
            lines.append(
                f"| {r['option']} | {r['type']} | {r['test_value']} "
                f"| {settled_str} | {r['notes']} |"
            )

        if skipped_names:
            lines.extend(["", f"**Skipped:** {', '.join(skipped_names)}"])

        lines.extend(
            [
                "",
                "## Verdict",
                "",
                f"**{'PASS' if all_ok else 'FAIL'}** "
                f"— {passed} of {len(tested)} options settled correctly",
                "",
            ]
        )

        return ToolResult(
            success=all_ok,
            output="\n".join(lines),
            error=None if all_ok else f"{failed} config option(s) caused issues",
            data={
                "app": app,
                "options_tested": len(tested),
                "options_passed": passed,
                "options_failed": failed,
                "results": results,
                "verdict": "pass" if all_ok else "fail",
            },
        )


# ---------------------------------------------------------------------------
# 17.5 Config Under Load
# ---------------------------------------------------------------------------


class ConfigUnderLoadTool(Tool):
    """Change a config option while probing a health endpoint for downtime."""

    @property
    def name(self) -> str:
        return "config_under_load_test"

    @property
    def description(self) -> str:
        return (
            "Change a config option while periodically probing a health "
            "endpoint, and report whether there was downtime or errors "
            "during the reconfiguration. Tests that config changes are "
            "applied gracefully without service interruption."
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
                "config_key": {
                    "type": "string",
                    "description": "Config option to change",
                },
                "config_value": {
                    "type": "string",
                    "description": "New value to set",
                },
                "health_url": {
                    "type": "string",
                    "description": (
                        "Health endpoint URL to probe (e.g. http://<unit-ip>:8080/health)"
                    ),
                },
                "model": {
                    "type": "string",
                    "description": "Model name",
                },
                "probe_count": {
                    "type": "integer",
                    "description": "Number of health probes to send (default 10)",
                    "default": 10,
                },
                "probe_interval": {
                    "type": "number",
                    "description": "Seconds between probes (default 3)",
                    "default": 3,
                },
            },
            "required": ["app", "config_key", "config_value", "health_url"],
        }

    async def execute(
        self,
        app: str,
        config_key: str,
        config_value: str,
        health_url: str,
        model: str | None = None,
        probe_count: int = 10,
        probe_interval: float = 3,
    ) -> ToolResult:
        """Apply a config change while probing a health endpoint."""
        if not shutil.which("juju"):
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found.",
            )

        import asyncio
        import time

        probes: list[dict[str, Any]] = []
        errors = 0

        async def _probe_loop() -> None:
            nonlocal errors
            for i in range(probe_count):
                t0 = time.monotonic()
                try:
                    result = subprocess.run(
                        ["curl", "-sf", "-o", "/dev/null", "-w", "%{http_code}", health_url],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    elapsed = time.monotonic() - t0
                    status = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
                    ok = 200 <= status < 400
                    if not ok:
                        errors += 1
                    probes.append(
                        {
                            "probe": i + 1,
                            "status": status,
                            "elapsed_ms": round(elapsed * 1000),
                            "ok": ok,
                        }
                    )
                except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
                    errors += 1
                    probes.append(
                        {
                            "probe": i + 1,
                            "status": 0,
                            "elapsed_ms": 0,
                            "ok": False,
                        }
                    )
                await asyncio.sleep(probe_interval)

        async def _apply_config() -> None:
            # Wait for a few probes to establish baseline, then apply.
            await asyncio.sleep(probe_interval * 2)
            cmd = ["juju", "config", app, f"{config_key}={config_value}"]
            if model:
                cmd.extend(["--model", model])
            subprocess.run(cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)

        # Run probes and config change concurrently.
        await asyncio.gather(_probe_loop(), _apply_config())

        # Reset config.
        reset_cmd = ["juju", "config", app, "--reset", config_key]
        if model:
            reset_cmd.extend(["--model", model])
        with contextlib.suppress(subprocess.TimeoutExpired, FileNotFoundError, OSError):
            subprocess.run(reset_cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)

        verdict = "PASS" if errors == 0 else "FAIL"
        lines = [
            "# Config Under Load Test",
            "",
            f"**Application:** {app}",
            f"**Config change:** {config_key}={config_value}",
            f"**Health endpoint:** {health_url}",
            f"**Probes:** {probe_count} at {probe_interval}s intervals",
            "",
            "## Results",
            "",
            f"**Errors during reconfiguration:** {errors}/{probe_count}",
            "",
            "| Probe | Status | Time (ms) | OK |",
            "|-------|--------|-----------|----|",
        ]
        for p in probes:
            lines.append(
                f"| {p['probe']} | {p['status']} | {p['elapsed_ms']} | "
                f"{'yes' if p['ok'] else 'NO'} |"
            )
        lines.extend(["", f"**Verdict: {verdict}**", ""])

        return ToolResult(
            success=errors == 0,
            output="\n".join(lines),
            error=None if errors == 0 else f"{errors} probe(s) failed during config change",
            data={
                "app": app,
                "config_key": config_key,
                "config_value": config_value,
                "probes": probes,
                "errors": errors,
                "verdict": verdict.lower(),
            },
        )


# ---------------------------------------------------------------------------
# 17.6 Acceptance Report
# ---------------------------------------------------------------------------


class AcceptanceReportTool(Tool):
    """Consolidate acceptance test results into ACCEPTANCE.md."""

    @property
    def name(self) -> str:
        return "acceptance_report"

    @property
    def description(self) -> str:
        return (
            "Consolidate acceptance test results from the individual tools "
            "(action exerciser, relation smoke tests, endpoint probes, config "
            "variation) into a single ACCEPTANCE.md report in the charm directory."
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
                    "description": "Path to the charm directory",
                    "default": ".",
                },
                "actions": {
                    "type": "string",
                    "description": "Markdown output from action_exerciser",
                    "default": "",
                },
                "relations": {
                    "type": "string",
                    "description": "Markdown output from relation_smoke_test",
                    "default": "",
                },
                "endpoints": {
                    "type": "string",
                    "description": "Markdown output from workload_endpoint_test",
                    "default": "",
                },
                "config": {
                    "type": "string",
                    "description": "Markdown output from config_variation_test",
                    "default": "",
                },
                "lifecycle": {
                    "type": "string",
                    "description": ("Markdown output from scaling_test / upgrade_test"),
                    "default": "",
                },
            },
            "required": ["app"],
        }

    async def execute(
        self,
        app: str = "",
        path: str = ".",
        actions: str = "",
        relations: str = "",
        endpoints: str = "",
        config: str = "",
        lifecycle: str = "",
    ) -> ToolResult:
        """Write ACCEPTANCE.md consolidating all acceptance test sections."""
        if not app:
            return ToolResult(success=False, output="", error="app parameter is required.")

        charm_dir = Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(success=False, output="", error=f"Directory not found: {path}")

        sections = [
            f"# Acceptance Test Report — {app}",
            "",
            "This report summarises the acceptance tests performed against "
            f"the deployed **{app}** charm.",
            "",
        ]

        section_count = 0
        section_summaries: list[str] = []

        if actions:
            sections.extend(["---", "", actions, ""])
            section_count += 1
            section_summaries.append("actions exercised")
        if relations:
            sections.extend(["---", "", relations, ""])
            section_count += 1
            section_summaries.append("relations tested")
        if endpoints:
            sections.extend(["---", "", endpoints, ""])
            section_count += 1
            section_summaries.append("endpoints probed")
        if config:
            sections.extend(["---", "", config, ""])
            section_count += 1
            section_summaries.append("config options varied")
        if lifecycle:
            sections.extend(["---", "", lifecycle, ""])
            section_count += 1
            section_summaries.append("lifecycle operations checked")

        if section_count == 0:
            return ToolResult(
                success=False,
                output="",
                error="No acceptance test results provided.",
            )

        report = "\n".join(sections)

        # Write ACCEPTANCE.md.
        acceptance_path = charm_dir / "ACCEPTANCE.md"
        acceptance_path.write_text(report)

        summary = (
            f"Wrote ACCEPTANCE.md ({section_count} sections: {', '.join(section_summaries)})."
        )

        return ToolResult(
            success=True,
            output=summary,
            data={
                "app": app,
                "path": str(acceptance_path),
                "section_count": section_count,
                "sections": section_summaries,
            },
        )
