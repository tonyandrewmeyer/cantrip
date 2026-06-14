"""Workload endpoint probing acceptance tool."""

import pathlib
import shlex
import shutil
import subprocess
from typing import Any

from cantrip.agent.tools.acceptance import _common
from cantrip.agent.tools.acceptance._common import (
    _load_charm_metadata,
)
from cantrip.agent.tools.base import Tool, ToolResult

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

        unit_addr = _common._get_unit_address(app, model)

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

    @staticmethod
    def _discover_endpoints(path: str, unit_addr: str | None) -> list[dict[str, Any]]:
        """Discover endpoints from charmcraft.yaml containers and config."""
        charm_dir = pathlib.Path(path).resolve()
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
