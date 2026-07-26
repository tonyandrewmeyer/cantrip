"""Kubernetes pod-layer diagnostics tool via the cantrip-kdiag binary.

Invokes the ``cantrip-kdiag`` Go binary directly via ``subprocess.run``,
bypassing the bwrap sandbox so that kubeconfig and the API server are
reachable.  Mirrors the same environment-bypass pattern used by the Juju
tools — see ``design/K8S_DIAGNOSTICS_BINARY.md`` for the full design
rationale, JSON contract, and exit-code table.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import shutil
import subprocess
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# The binary is looked up in PATH first, then adjacent to this file's package
# root, then in XDG_BIN_HOME / ~/.local/bin.  This covers both installed
# releases (binary on PATH) and development checkouts (built in-tree).
_BINARY_NAME = "cantrip-kdiag"

# Default timeout passed to the binary.  A long-running kubectl call will be
# hard-killed by the binary's own --timeout flag before we hit this limit.
_DEFAULT_TIMEOUT_SECS = 60

# JSON schema version this wrapper expects.  Bump if the Go contract changes.
_EXPECTED_SCHEMA_VERSION = 1


def _find_binary() -> str | None:
    """Return the absolute path to the cantrip-kdiag binary, or None."""
    # 1. PATH lookup — works for installed releases.
    on_path = shutil.which(_BINARY_NAME)
    if on_path:
        return on_path

    # 2. Built in-tree at src/cantrip-kdiag/<binary> — works during dev.
    repo_root = pathlib.Path(__file__).parents[4]
    in_tree = repo_root / "src" / "cantrip-kdiag" / _BINARY_NAME
    if in_tree.exists():
        return str(in_tree)

    # 3. ~/.local/bin — common user install location.
    home = pathlib.Path.home()
    user_bin = home / ".local" / "bin" / _BINARY_NAME
    if user_bin.exists():
        return str(user_bin)

    return None


def _kubeconfig_path(override: str | None) -> str | None:
    """Return the effective kubeconfig path, or None if not configured."""
    if override:
        return override
    if env := os.environ.get("KUBECONFIG"):
        return env
    default = pathlib.Path.home() / ".kube" / "config"
    if default.exists():
        return str(default)
    return None


def _build_caption(report: dict[str, Any]) -> str:
    """Build a concise one-line caption from a diagnostic report."""
    warnings = report.get("warnings", [])
    summary = report.get("summary", {})
    ns = report.get("context", {}).get("namespace", "")
    pod_count = summary.get("pod_count", 0)
    ready = summary.get("ready_pods", 0)

    if warnings:
        return f"k8s diagnostics ({ns}): {warnings[0]}" + (
            f" (+{len(warnings) - 1} more)" if len(warnings) > 1 else ""
        )
    if pod_count:
        return f"k8s diagnostics ({ns}): {ready}/{pod_count} pods ready"
    return f"k8s diagnostics ({ns}): no pods found"


@dataclasses.dataclass
class _RunResult:
    """Raw result of running the binary."""

    returncode: int
    stdout: str
    stderr: str


def _run_binary(
    binary: str,
    args: list[str],
    kubeconfig: str | None,
    timeout: int,
) -> _RunResult:
    """Invoke the cantrip-kdiag binary without sandbox wrapping."""
    env = os.environ.copy()
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig

    try:
        proc = subprocess.run(
            [binary, *args],
            capture_output=True,
            text=True,
            timeout=timeout + 5,  # outer budget is binary's timeout + margin
            env=env,
        )
    except subprocess.TimeoutExpired:
        return _RunResult(returncode=10, stdout="", stderr="binary timed out")
    except OSError as exc:
        return _RunResult(returncode=10, stdout="", stderr=str(exc))

    return _RunResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def _parse_json_output(stdout: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse JSON stdout.  Returns (parsed, error_message)."""
    if not stdout.strip():
        return None, "binary produced no output"
    try:
        return json.loads(stdout), None
    except json.JSONDecodeError as exc:
        return None, f"binary produced malformed JSON: {exc}"


class K8sDiagnosticsTool(Tool):
    """Kubernetes pod-layer diagnostics via cantrip-kdiag.

    Collects bounded, read-only pod/PVC/event/metrics diagnostics from a
    Kubernetes namespace and returns structured JSON.  Use this when Juju
    tools surface a unit in error but do not explain the underlying pod-layer
    failure (CrashLoopBackOff, OOMKilled, ImagePullBackOff, PVC pending,
    namespace event storm).

    The tool is strictly read-only.  It never writes to the cluster, does not
    exec into containers, and does not port-forward.

    Requires the ``cantrip-kdiag`` binary to be on PATH, built in-tree at
    ``src/cantrip-kdiag/cantrip-kdiag``, or installed at
    ``~/.local/bin/cantrip-kdiag``.
    """

    @property
    def name(self) -> str:
        return "k8s_diagnostics"

    @property
    def description(self) -> str:
        return (
            "Collect read-only Kubernetes pod-layer diagnostics "
            "(pods, container statuses, warning events, PVC state, previous "
            "log tails for crashed containers, metrics when available) and "
            "return a structured JSON report.\n\n"
            "Use this tool when:\n"
            "- A Juju unit shows error/lost/waiting but juju debug-log does not "
            "explain the root cause.\n"
            "- Symptoms are CrashLoopBackOff, OOMKilled, ImagePullBackOff, PVC "
            "stuck Pending, or unexplained namespace event storms.\n\n"
            "Do NOT use for write operations or general Kubernetes exploration — "
            "this is a targeted charm-debug tool only."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Kubernetes namespace to inspect (usually the Juju model name).",
                },
                "app": {
                    "type": "string",
                    "description": "Juju application name to filter results (e.g. 'redis-k8s').",
                },
                "unit": {
                    "type": "string",
                    "description": "Juju unit name to filter results (e.g. 'redis-k8s/0').",
                },
                "pod": {
                    "type": "string",
                    "description": "Exact Kubernetes pod name to drill into.",
                },
                "previous_logs": {
                    "type": "integer",
                    "description": "Lines of previous container logs to include per crashed container (default 50).",
                    "default": 50,
                },
                "include_metrics": {
                    "type": "boolean",
                    "description": "Include pod CPU/memory metrics (requires metrics-server). Default false.",
                    "default": False,
                },
                "kubeconfig": {
                    "type": "string",
                    "description": "Path to kubeconfig file. Defaults to $KUBECONFIG or ~/.kube/config.",
                },
                "context": {
                    "type": "string",
                    "description": "Kubernetes context name. Defaults to the current context.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["summary", "pod", "preflight"],
                    "description": (
                        "'summary' (default) — namespace/workload overview. "
                        "'pod' — detailed single-pod drilldown (requires pod). "
                        "'preflight' — check kubeconfig/API reachability only."
                    ),
                    "default": "summary",
                },
            },
            "required": ["namespace"],
        }

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        ns = arguments.get("namespace", "")
        mode = arguments.get("mode", "summary")
        if mode == "preflight":
            return "Checking Kubernetes connectivity…"
        target = arguments.get("pod") or arguments.get("unit") or arguments.get("app") or ns
        return f"Collecting Kubernetes diagnostics for {target}…"

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Run cantrip-kdiag and return a structured ToolResult."""
        binary = _find_binary()
        if binary is None:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Binary '{_BINARY_NAME}' not found.  "
                    "Build it with: cd src/cantrip-kdiag && go build -o cantrip-kdiag "
                    "./cmd/cantrip-kdiag/"
                ),
            )

        mode: str = kwargs.get("mode", "summary")
        namespace: str = kwargs.get("namespace", "")
        app: str = kwargs.get("app", "")
        unit: str = kwargs.get("unit", "")
        pod: str = kwargs.get("pod", "")
        previous_logs: int = int(kwargs.get("previous_logs", 50))
        include_metrics: bool = bool(kwargs.get("include_metrics", False))
        kubeconfig: str = kwargs.get("kubeconfig", "")
        context: str = kwargs.get("context", "")
        timeout: int = _DEFAULT_TIMEOUT_SECS

        kubeconfig_path = _kubeconfig_path(kubeconfig or None)
        if mode != "preflight" and not kubeconfig_path:
            return ToolResult(
                success=False,
                output="",
                error=(
                    "No kubeconfig found.  Set KUBECONFIG, pass kubeconfig=, "
                    "or create ~/.kube/config."
                ),
            )

        args = self._build_args(
            mode, namespace, app, unit, pod, previous_logs, include_metrics, context
        )

        result = _run_binary(binary, args, kubeconfig_path, timeout)
        parsed, parse_error = _parse_json_output(result.stdout)

        if parse_error:
            return ToolResult(
                success=False,
                output="",
                error=f"{parse_error} (exit {result.returncode}). stderr: {result.stderr}",
            )

        assert parsed is not None  # parse_error would be set otherwise

        # Check for a structured error response from the binary.
        if "error" in parsed:
            err = parsed["error"]
            code = err.get("code", "error")
            message = err.get("message", "unknown error")
            return ToolResult(
                success=False,
                output="",
                error=f"[{code}] {message}",
                data=parsed,
            )

        # Non-zero exit without a structured error means an unexpected failure.
        if result.returncode not in (0, 7):
            stderr_hint = f" stderr: {result.stderr}" if result.stderr.strip() else ""
            return ToolResult(
                success=False,
                output="",
                error=f"cantrip-kdiag exited with code {result.returncode}.{stderr_hint}",
                data=parsed,
            )

        # Happy path — build a concise caption and return the full report.
        schema_ver = parsed.get("schema_version", 0)
        if schema_ver != _EXPECTED_SCHEMA_VERSION:
            # Forward-compatibility: accept newer schema versions with a note.
            pass

        caption = _build_caption(parsed) if mode != "preflight" else _preflight_caption(parsed)
        output_text = _format_output(parsed, mode)

        return ToolResult(
            success=True,
            output=output_text,
            data=parsed,
            caption=caption,
        )

    @staticmethod
    def _build_args(
        mode: str,
        namespace: str,
        app: str,
        unit: str,
        pod: str,
        previous_logs: int,
        include_metrics: bool,
        context: str,
    ) -> list[str]:
        """Build the argv list for the binary invocation."""
        args: list[str] = [mode, "--format", "json"]

        if context:
            args += ["--context", context]

        if mode == "preflight":
            return args

        if namespace:
            args += ["--namespace", namespace]

        if mode == "summary":
            if app:
                args += ["--app", app]
            if unit:
                args += ["--unit", unit]
            if pod:
                args += ["--pod", pod]
            args += ["--previous-logs", str(previous_logs)]
            if include_metrics:
                args.append("--include-metrics")

        elif mode == "pod":
            if pod:
                args += ["--pod", pod]
            args += ["--previous-logs", str(previous_logs)]

        return args


def _preflight_caption(report: dict[str, Any]) -> str:
    """Build a concise caption for preflight reports."""
    api = "reachable" if report.get("api_reachable") else "unreachable"
    metrics = "metrics available" if report.get("metrics_available") else "no metrics"
    ctx = report.get("context", "<default>")
    return f"k8s preflight ({ctx}): API {api}, {metrics}"


def _format_output(report: dict[str, Any], mode: str) -> str:
    """Format the report into a concise text summary for the agent."""
    if mode == "preflight":
        return (
            f"context: {report.get('context', '<default>')}\n"
            f"api_reachable: {report.get('api_reachable', False)}\n"
            f"metrics_available: {report.get('metrics_available', False)}\n"
        )

    summary = report.get("summary", {})
    warnings = report.get("warnings", [])
    ctx = report.get("context", {})
    ns = ctx.get("namespace", "")
    pod_count = summary.get("pod_count", 0)
    ready = summary.get("ready_pods", 0)
    restarting = summary.get("restarting_pods", 0)
    pvc_pending = summary.get("pvc_pending_count", 0)
    warning_count = summary.get("warning_event_count", 0)

    lines = [
        f"namespace: {ns}",
        f"pods: {pod_count} total, {ready} ready, {restarting} restarting",
    ]
    if pvc_pending:
        lines.append(f"pvcs pending: {pvc_pending}")
    if warning_count:
        lines.append(f"warning events: {warning_count}")
    if warnings:
        lines.append("warnings:")
        lines.extend(f"  - {w}" for w in warnings[:10])
        if len(warnings) > 10:
            lines.append(f"  ... and {len(warnings) - 10} more")

    return "\n".join(lines) + "\n"
