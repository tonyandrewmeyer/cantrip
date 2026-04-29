"""Preflight-snapshot helpers for kubectl, Juju, local tools, and a registry.

Adapted from the canonical/skills repository:
``skills/engineering/12factor-fit/scripts/preflight_targets.py``
(PR #4, https://github.com/canonical/skills/pull/4), Apache-2.0 licensed.

Cantrip-specific changes:
- ``express`` replaces upstream ``expressjs`` in the experimental-framework
  set and tool framework arg.
- The rockcraft-embedded skopeo path detection is dropped — Cantrip's
  registry tools call ``shutil.which("skopeo")`` directly and don't need
  the rockcraft-snap fallback.
- Each check is split into its own function so tests can monkeypatch
  ``subprocess.run`` / ``shutil.which`` / network probes one symbol at a
  time without exercising the full preflight tree.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Frameworks that require ``ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=1``
# and an edge-channel rockcraft / charmcraft snap.  Mirrors
# ``charm.py``'s ``_EXPERIMENTAL_FRAMEWORKS`` (with the upstream
# ``expressjs`` renamed to Cantrip's ``express``).
EXPERIMENTAL_FRAMEWORKS: frozenset[str] = frozenset({"express", "fastapi", "go", "spring-boot"})

# Frameworks accepted as the ``framework`` arg.  Includes the stable
# ones too — they don't trigger the experimental-extension subtree but
# the agent should still be able to pass them through to record what
# was being preflighted.
SUPPORTED_FRAMEWORKS: frozenset[str] = frozenset(
    {"flask", "django", "fastapi", "express", "go", "spring-boot"}
)

_ENV_REQUIREMENTS: dict[str, str] = {
    "rockcraft": "ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS",
    "charmcraft": "CHARMCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS",
}

# Truthy spellings that satisfy ``ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS``
# / ``CHARMCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS``.  Lowercased before
# comparison so ``True`` / ``YES`` / ``1`` all pass.
_ENV_TRUTHY: frozenset[str] = frozenset({"1", "true", "yes"})


@dataclasses.dataclass(frozen=True)
class PreflightReport:
    """Outcome of running :func:`preflight` end-to-end."""

    ok: bool
    checks: dict[str, Any]


def preflight(
    *,
    framework: str | None = None,
    kubernetes_context: str | None = None,
    kubectl_cmd: str = "kubectl",
    juju_controller: str | None = None,
    registry: str | None = None,
    timeout: float = 3.0,
) -> PreflightReport:
    """Run every preflight check and return the combined report.

    Each check is delegated to a single-purpose helper so the same
    function the tool calls is the one tests target.  ``ok`` is
    ``True`` only when every relevant check passed: kubectl available
    (and the named context exists when one is supplied); juju
    available (and the named controller exists when one is supplied);
    rockcraft and charmcraft installed; the experimental subtree
    satisfied when *framework* is in :data:`EXPERIMENTAL_FRAMEWORKS`;
    the registry probe succeeded when *registry* is supplied.
    """
    checks: dict[str, Any] = {}
    ok = True

    kubectl_check = check_kubectl(kubectl_cmd, kubernetes_context)
    checks["kubectl"] = kubectl_check["kubectl"]
    if "kubernetes_contexts" in kubectl_check:
        checks["kubernetes_contexts"] = kubectl_check["kubernetes_contexts"]
    if not kubectl_check["ok"]:
        ok = False

    juju_check = check_juju(juju_controller)
    checks["juju"] = juju_check["juju"]
    if "juju_controllers" in juju_check:
        checks["juju_controllers"] = juju_check["juju_controllers"]
    if not juju_check["ok"]:
        ok = False

    local_tools = check_local_tools()
    checks["local_tools"] = local_tools
    for tool_name, details in local_tools.items():
        if tool_name == "skopeo":
            # Skopeo absence is not a hard fail: registry pushes need
            # it, but the agent might never reach that step.  Mirrors
            # the upstream's behaviour.
            continue
        if not details["present"]:
            ok = False

    if framework in EXPERIMENTAL_FRAMEWORKS:
        extension_checks = check_experimental_extensions(framework, local_tools)
        checks["experimental_extensions"] = extension_checks
        if not extension_checks["ok"]:
            ok = False

    if registry:
        registry_check = check_registry(registry, timeout=timeout)
        checks["registry"] = registry_check
        ok = ok and bool(registry_check["ok"])

    return PreflightReport(ok=ok, checks=checks)


def check_kubectl(
    kubectl_cmd: str,
    selected_context: str | None,
) -> dict[str, Any]:
    """Probe kubectl: present, contexts, current context, selected match."""
    result: dict[str, Any] = {
        "kubectl": {"command": kubectl_cmd, "present": False},
        "ok": True,
    }
    if shutil.which(kubectl_cmd) is None:
        result["ok"] = False
        return result

    result["kubectl"]["present"] = True
    contexts_cmd = _run([kubectl_cmd, "config", "get-contexts", "-o", "name"])
    current_cmd = _run([kubectl_cmd, "config", "current-context"])
    contexts = [line.strip() for line in contexts_cmd.stdout.splitlines() if line.strip()]
    selected_ok = selected_context in contexts if selected_context else True
    result["kubernetes_contexts"] = {
        "contexts": contexts,
        "current": current_cmd.stdout.strip() or None,
        "selected": selected_context,
        "selected_ok": selected_ok,
    }
    if selected_context and not selected_ok:
        result["ok"] = False
    return result


def check_juju(selected_controller: str | None) -> dict[str, Any]:
    """Probe juju: present, controllers, selected controller match."""
    result: dict[str, Any] = {"juju": {"present": False}, "ok": True}
    if shutil.which("juju") is None:
        result["ok"] = False
        return result

    result["juju"]["present"] = True
    controllers_cmd = _run(["juju", "controllers", "--format", "json"])
    controllers: list[str] = []
    if controllers_cmd.returncode == 0:
        try:
            data = json.loads(controllers_cmd.stdout or "{}")
        except json.JSONDecodeError:
            data = {}
        controllers_data = data.get("controllers", {})
        if isinstance(controllers_data, dict):
            controllers = sorted(controllers_data)
    selected_ok = selected_controller in controllers if selected_controller else True
    result["juju_controllers"] = {
        "controllers": controllers,
        "selected": selected_controller,
        "selected_ok": selected_ok,
    }
    if selected_controller and not selected_ok:
        result["ok"] = False
    return result


def check_local_tools() -> dict[str, Any]:
    """Probe rockcraft, charmcraft, and skopeo for presence and snap channel."""
    return {
        "rockcraft": _check_tool("rockcraft", snap_name="rockcraft"),
        "charmcraft": _check_tool("charmcraft", snap_name="charmcraft"),
        "skopeo": _check_tool("skopeo"),
    }


def check_experimental_extensions(
    framework: str | None,
    local_tools: dict[str, Any],
) -> dict[str, Any]:
    """Verify the experimental extensions are wired up for *framework*.

    Each of rockcraft and charmcraft must be installed with the edge
    channel and the matching ``..._ENABLE_EXPERIMENTAL_EXTENSIONS`` env
    var set to a truthy value.  ``ok`` is the AND of every per-tool
    check.  Pass an empty *framework* string or ``None`` and the caller
    should not have invoked this — the helper still returns a report
    but with ``framework`` echoed back.
    """
    extension_checks: dict[str, Any] = {
        "framework": framework,
        "experimental_required": True,
        "ok": True,
    }
    for tool_name, env_name in _ENV_REQUIREMENTS.items():
        tool_details = local_tools.get(tool_name, {"present": False})
        env_value = os.environ.get(env_name, "")
        env_ok = env_value.lower() in _ENV_TRUTHY
        snap_section = tool_details.get("snap")
        snap_tracking = snap_section.get("tracking") if isinstance(snap_section, dict) else None
        tracking_ok = isinstance(snap_tracking, str) and snap_tracking.endswith("/edge")
        extension_checks[tool_name] = {
            "env_name": env_name,
            "env_value": env_value or None,
            "env_ok": env_ok,
            "tracking": snap_tracking,
            "tracking_ok": tracking_ok,
        }
        if not tool_details.get("present") or not env_ok or not tracking_ok:
            extension_checks["ok"] = False
    return extension_checks


def check_registry(target: str, timeout: float = 3.0) -> dict[str, Any]:
    """Probe an OCI registry: TCP connectivity then ``/v2/`` HTTP reachability."""
    probes: list[dict[str, Any]] = []
    candidates: list[str] = []
    if "://" in target:
        candidates.append(target)
    else:
        candidates.extend([f"http://{target}", f"https://{target}"])

    for candidate in candidates:
        parsed = urllib.parse.urlparse(candidate)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        probe: dict[str, Any] = {"url": candidate, "host": host, "port": port}
        try:
            with socket.create_connection((host, port), timeout=timeout):
                probe["tcp"] = "ok"
        except OSError as exc:
            probe["tcp"] = f"failed: {exc}"
            probes.append(probe)
            continue
        try:
            with urllib.request.urlopen(
                f"{candidate.rstrip('/')}/v2/",
                timeout=timeout,
            ) as response:
                probe["http"] = response.status
                probe["ok"] = True
        except urllib.error.URLError as exc:
            probe["http"] = f"failed: {exc}"
        probes.append(probe)
        if probe.get("ok"):
            return {
                "ok": True,
                "registry": target,
                "probes": probes,
                "note": (
                    "Registry reachability is verified at the host level. "
                    "Credential path matching still needs app-specific review."
                ),
            }
    return {
        "ok": False,
        "registry": target,
        "probes": probes,
        "note": ("Registry reachability failed. Credential and path checks were not attempted."),
    }


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """Thin wrapper so tests can monkeypatch a single symbol."""
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def _check_tool(name: str, snap_name: str | None = None) -> dict[str, Any]:
    """Probe a CLI tool's presence on PATH and (optionally) its snap tracking."""
    present = shutil.which(name) is not None
    result: dict[str, Any] = {"command": name, "present": present}
    if snap_name:
        result["snap"] = _parse_snap_tracking(snap_name)
    return result


def _parse_snap_tracking(snap_name: str) -> dict[str, Any]:
    """Return ``{present, installed, tracking}`` for *snap_name*.

    Reads the second line of ``snap list <name>`` and picks the first
    column with a slash — that's the ``track/risk`` field (e.g.
    ``latest/edge``).  Mirrors the upstream's heuristic exactly so the
    tracking-channel check stays comparable.
    """
    if shutil.which("snap") is None:
        return {"present": False}
    command = _run(["snap", "list", snap_name])
    if command.returncode != 0:
        return {
            "present": True,
            "installed": False,
            "stderr": command.stderr.strip() or None,
        }

    lines = [line.strip() for line in command.stdout.splitlines() if line.strip()]
    result: dict[str, Any] = {"present": True, "installed": True}
    if len(lines) >= 2:
        parts = lines[1].split()
        result["tracking"] = next((part for part in parts if "/" in part), None)
    return result


class PreflightTargetsTool(Tool):
    """Run an environment-readiness sweep before kicking off a 12-factor build.

    Probes kubectl (current + named context), the juju controllers
    list, ``rockcraft`` / ``charmcraft`` / ``skopeo`` presence and snap
    channel, the experimental-extension env vars when the chosen
    framework needs them, and (optionally) an OCI registry's TCP +
    ``/v2/`` reachability.  Returns a single ``ok`` flag plus a
    structured ``checks`` tree; the agent uses the tree to call out
    *which* gate failed instead of the user staring at a generic
    "preflight failed" line.
    """

    @property
    def name(self) -> str:
        return "preflight_targets"

    @property
    def description(self) -> str:
        return (
            "Snapshot the local environment for a 12-factor build: "
            "kubectl context, juju controller, rockcraft / charmcraft / "
            "skopeo presence and snap channel, the "
            "ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS / "
            "CHARMCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS env vars when "
            "the framework needs them, and (optionally) an OCI registry's "
            "TCP + /v2/ reachability. Returns ``ok`` plus a structured "
            "``checks`` tree."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "framework": {
                    "type": "string",
                    "description": "Optional framework name; gates the experimental-extension subtree.",
                    "enum": sorted(SUPPORTED_FRAMEWORKS),
                },
                "kubernetes_context": {
                    "type": "string",
                    "description": "Optional kubectl context name to verify exists.",
                },
                "kubectl_cmd": {
                    "type": "string",
                    "description": "Override the kubectl binary name.",
                    "default": "kubectl",
                },
                "juju_controller": {
                    "type": "string",
                    "description": "Optional juju controller name to verify exists.",
                },
                "registry": {
                    "type": "string",
                    "description": "Optional OCI registry to probe (host[:port] or URL).",
                },
                "timeout": {
                    "type": "number",
                    "description": "Per-probe network timeout in seconds.",
                    "default": 3.0,
                },
            },
        }

    async def execute(
        self,
        framework: str | None = None,
        kubernetes_context: str | None = None,
        kubectl_cmd: str = "kubectl",
        juju_controller: str | None = None,
        registry: str | None = None,
        timeout: float = 3.0,
    ) -> ToolResult:
        report = preflight(
            framework=framework,
            kubernetes_context=kubernetes_context,
            kubectl_cmd=kubectl_cmd,
            juju_controller=juju_controller,
            registry=registry,
            timeout=timeout,
        )

        verdict = "OK" if report.ok else "NOT OK"
        gates = sorted(report.checks)
        lines = [f"Preflight: {verdict}"]
        lines.append(f"Gates checked: {', '.join(gates)}")
        if not report.ok:
            failures = _summarise_failures(report.checks)
            if failures:
                lines.append("Failed:")
                lines.extend(f"  - {f}" for f in failures)

        caption = (
            "preflight_targets → ok"
            if report.ok
            else f"preflight_targets → {len(_summarise_failures(report.checks))} gate(s) failing"
        )
        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"ok": report.ok, "checks": report.checks},
            caption=caption,
        )


def _summarise_failures(checks: dict[str, Any]) -> list[str]:
    """Pull a flat list of human-readable failure reasons out of *checks*."""
    failures: list[str] = []
    if not checks.get("kubectl", {}).get("present"):
        failures.append("kubectl missing on PATH")
    contexts = checks.get("kubernetes_contexts", {})
    if contexts.get("selected") and not contexts.get("selected_ok"):
        failures.append(f"kubectl context not found: {contexts['selected']!r}")
    if not checks.get("juju", {}).get("present"):
        failures.append("juju missing on PATH")
    controllers = checks.get("juju_controllers", {})
    if controllers.get("selected") and not controllers.get("selected_ok"):
        failures.append(f"juju controller not found: {controllers['selected']!r}")
    for tool_name, details in checks.get("local_tools", {}).items():
        if tool_name == "skopeo":
            continue
        if not details.get("present"):
            failures.append(f"{tool_name} missing on PATH")
    extensions = checks.get("experimental_extensions", {})
    if extensions and not extensions.get("ok"):
        for tool_name in ("rockcraft", "charmcraft"):
            tool_check = extensions.get(tool_name, {})
            if not tool_check.get("env_ok"):
                failures.append(f"{tool_check.get('env_name')} not set to a truthy value")
            if not tool_check.get("tracking_ok"):
                failures.append(f"{tool_name} snap is not tracking an /edge channel")
    registry = checks.get("registry", {})
    if registry and not registry.get("ok"):
        failures.append(f"registry probe failed: {registry.get('registry')}")
    return failures
