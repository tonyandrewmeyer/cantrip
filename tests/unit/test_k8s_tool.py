"""Tests for K8sDiagnosticsTool — the cantrip-kdiag Python wrapper."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from cantrip.agent.tools.k8s import K8sDiagnosticsTool, _build_caption

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tool() -> K8sDiagnosticsTool:
    return K8sDiagnosticsTool()


def _make_report(
    *,
    namespace: str = "dev",
    pod_count: int = 1,
    ready: int = 1,
    restarting: int = 0,
    warnings: list[str] | None = None,
    pvc_pending: int = 0,
    warning_events: int = 0,
) -> dict:
    """Build a minimal valid summary report matching the binary's JSON contract."""
    return {
        "schema_version": 1,
        "generated_at": "2026-05-01T10:00:00Z",
        "context": {
            "kubeconfig": "/home/user/.kube/config",
            "context": "dev",
            "namespace": namespace,
        },
        "query": {"app": None, "unit": None, "pod": None},
        "metrics_available": False,
        "pods": [],
        "pvcs": [],
        "events": [],
        "warnings": warnings or [],
        "summary": {
            "pod_count": pod_count,
            "ready_pods": ready,
            "restarting_pods": restarting,
            "warning_event_count": warning_events,
            "pvc_pending_count": pvc_pending,
        },
    }


def _make_error_response(code: str, message: str) -> dict:
    return {"schema_version": 1, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# Happy path — summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_happy_path(tool):
    """Happy-path summary: binary runs, JSON parsed, ToolResult success."""
    report = _make_report(ready=1)
    with (
        mock.patch("cantrip.agent.tools.k8s._find_binary", return_value="/usr/bin/cantrip-kdiag"),
        mock.patch(
            "cantrip.agent.tools.k8s._kubeconfig_path", return_value="/home/user/.kube/config"
        ),
        mock.patch(
            "cantrip.agent.tools.k8s._run_binary",
            return_value=mock.Mock(returncode=0, stdout=json.dumps(report), stderr=""),
        ),
    ):
        result = await tool.execute(namespace="dev")

    assert result.success
    assert result.data == report
    assert "dev" in result.output


@pytest.mark.asyncio
async def test_summary_with_warnings_in_caption(tool):
    """Caption surfaces the first warning when the report has warnings."""
    warnings = ["pod redis-k8s-0 container redis waiting: CrashLoopBackOff"]
    report = _make_report(ready=0, restarting=1, warnings=warnings)
    with (
        mock.patch("cantrip.agent.tools.k8s._find_binary", return_value="/usr/bin/cantrip-kdiag"),
        mock.patch(
            "cantrip.agent.tools.k8s._kubeconfig_path", return_value="/home/user/.kube/config"
        ),
        mock.patch(
            "cantrip.agent.tools.k8s._run_binary",
            return_value=mock.Mock(returncode=0, stdout=json.dumps(report), stderr=""),
        ),
    ):
        result = await tool.execute(namespace="dev")

    assert result.success
    assert result.caption is not None
    assert "CrashLoopBackOff" in result.caption


# ---------------------------------------------------------------------------
# Happy path — pod drilldown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pod_mode_passes_pod_flag(tool):
    """Pod mode passes --pod flag to the binary."""
    report = _make_report()
    run_mock = mock.Mock(returncode=0, stdout=json.dumps(report), stderr="")

    with (
        mock.patch("cantrip.agent.tools.k8s._find_binary", return_value="/usr/bin/cantrip-kdiag"),
        mock.patch(
            "cantrip.agent.tools.k8s._kubeconfig_path", return_value="/home/user/.kube/config"
        ),
        mock.patch("cantrip.agent.tools.k8s._run_binary", return_value=run_mock) as run_fn,
    ):
        result = await tool.execute(namespace="dev", mode="pod", pod="redis-k8s-0")

    assert result.success
    args_passed = run_fn.call_args[0][1]  # positional 'args' list
    assert "--pod" in args_passed
    assert "redis-k8s-0" in args_passed


# ---------------------------------------------------------------------------
# Happy path — preflight
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preflight_mode(tool):
    """Preflight mode returns API reachability info."""
    preflight = {
        "schema_version": 1,
        "kubeconfig": "/home/user/.kube/config",
        "context": "dev",
        "api_reachable": True,
        "metrics_available": False,
    }
    with (
        mock.patch("cantrip.agent.tools.k8s._find_binary", return_value="/usr/bin/cantrip-kdiag"),
        mock.patch("cantrip.agent.tools.k8s._kubeconfig_path", return_value=None),
        mock.patch(
            "cantrip.agent.tools.k8s._run_binary",
            return_value=mock.Mock(returncode=0, stdout=json.dumps(preflight), stderr=""),
        ),
    ):
        result = await tool.execute(namespace="dev", mode="preflight")

    assert result.success
    assert result.data["api_reachable"] is True


# ---------------------------------------------------------------------------
# Error: binary missing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_binary_returns_error(tool):
    """When cantrip-kdiag is absent the tool fails with a helpful message."""
    with mock.patch("cantrip.agent.tools.k8s._find_binary", return_value=None):
        result = await tool.execute(namespace="dev")

    assert not result.success
    assert result.error is not None
    assert "cantrip-kdiag" in result.error
    assert "go build" in result.error


# ---------------------------------------------------------------------------
# Error: missing kubeconfig
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_kubeconfig_returns_error(tool):
    """When no kubeconfig is found the tool fails clearly."""
    with (
        mock.patch("cantrip.agent.tools.k8s._find_binary", return_value="/usr/bin/cantrip-kdiag"),
        mock.patch("cantrip.agent.tools.k8s._kubeconfig_path", return_value=None),
    ):
        result = await tool.execute(namespace="dev")

    assert not result.success
    assert result.error is not None
    assert "kubeconfig" in result.error.lower()


# ---------------------------------------------------------------------------
# Error: non-zero exit code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nonzero_exit_without_error_json(tool):
    """A non-zero exit with no structured error body is reported cleanly."""
    with (
        mock.patch("cantrip.agent.tools.k8s._find_binary", return_value="/usr/bin/cantrip-kdiag"),
        mock.patch(
            "cantrip.agent.tools.k8s._kubeconfig_path", return_value="/home/user/.kube/config"
        ),
        mock.patch(
            "cantrip.agent.tools.k8s._run_binary",
            return_value=mock.Mock(returncode=5, stdout="", stderr="connection refused"),
        ),
    ):
        result = await tool.execute(namespace="dev")

    assert not result.success
    assert result.error is not None


@pytest.mark.asyncio
async def test_structured_error_response_from_binary(tool):
    """A structured error JSON from the binary is surfaced as a clean failure."""
    error_json = _make_error_response(
        "context_not_found", "Context 'prod' not found in kubeconfig."
    )
    with (
        mock.patch("cantrip.agent.tools.k8s._find_binary", return_value="/usr/bin/cantrip-kdiag"),
        mock.patch(
            "cantrip.agent.tools.k8s._kubeconfig_path", return_value="/home/user/.kube/config"
        ),
        mock.patch(
            "cantrip.agent.tools.k8s._run_binary",
            return_value=mock.Mock(returncode=4, stdout=json.dumps(error_json), stderr=""),
        ),
    ):
        result = await tool.execute(namespace="dev", context="prod")

    assert not result.success
    assert result.error is not None
    assert "context_not_found" in result.error
    assert "prod" in result.error


# ---------------------------------------------------------------------------
# Error: malformed JSON output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_json_returns_error(tool):
    """Malformed JSON stdout is reported as an error."""
    with (
        mock.patch("cantrip.agent.tools.k8s._find_binary", return_value="/usr/bin/cantrip-kdiag"),
        mock.patch(
            "cantrip.agent.tools.k8s._kubeconfig_path", return_value="/home/user/.kube/config"
        ),
        mock.patch(
            "cantrip.agent.tools.k8s._run_binary",
            return_value=mock.Mock(returncode=0, stdout="not valid json {{{", stderr=""),
        ),
    ):
        result = await tool.execute(namespace="dev")

    assert not result.success
    assert result.error is not None
    assert "malformed" in result.error


@pytest.mark.asyncio
async def test_empty_stdout_returns_error(tool):
    """Empty stdout is reported as an error."""
    with (
        mock.patch("cantrip.agent.tools.k8s._find_binary", return_value="/usr/bin/cantrip-kdiag"),
        mock.patch(
            "cantrip.agent.tools.k8s._kubeconfig_path", return_value="/home/user/.kube/config"
        ),
        mock.patch(
            "cantrip.agent.tools.k8s._run_binary",
            return_value=mock.Mock(returncode=0, stdout="", stderr=""),
        ),
    ):
        result = await tool.execute(namespace="dev")

    assert not result.success
    assert result.error is not None
    assert "no output" in result.error


# ---------------------------------------------------------------------------
# Arg building
# ---------------------------------------------------------------------------


def test_build_args_summary_with_app():
    """Summary mode with --app passes the right flags."""
    args = K8sDiagnosticsTool._build_args("summary", "dev", "redis-k8s", "", "", 50, False, "")
    assert "summary" in args
    assert "--namespace" in args
    assert "dev" in args
    assert "--app" in args
    assert "redis-k8s" in args


def test_build_args_pod_mode():
    """Pod mode passes --pod and skips app/unit flags."""
    args = K8sDiagnosticsTool._build_args("pod", "dev", "", "", "redis-k8s-0", 100, False, "")
    assert "pod" in args
    assert "--pod" in args
    assert "redis-k8s-0" in args
    assert "--app" not in args


def test_build_args_preflight_minimal():
    """Preflight mode produces minimal args (no namespace)."""
    args = K8sDiagnosticsTool._build_args("preflight", "", "", "", "", 50, False, "")
    assert "preflight" in args
    assert "--namespace" not in args


def test_build_args_with_context():
    """Context flag is always included when set."""
    args = K8sDiagnosticsTool._build_args("summary", "dev", "", "", "", 50, False, "my-cluster")
    assert "--context" in args
    assert "my-cluster" in args


def test_build_args_include_metrics():
    """--include-metrics flag is set when requested."""
    args = K8sDiagnosticsTool._build_args("summary", "dev", "", "", "", 50, True, "")
    assert "--include-metrics" in args


# ---------------------------------------------------------------------------
# Caption
# ---------------------------------------------------------------------------


def test_caption_with_warnings():
    """Caption surfaces the first warning."""
    report = _make_report(warnings=["pod redis-k8s-0 container redis waiting: CrashLoopBackOff"])
    caption = _build_caption(report)
    assert "CrashLoopBackOff" in caption


def test_caption_no_pods():
    """Caption notes 'no pods found' when count is 0."""
    report = _make_report(pod_count=0, ready=0)
    caption = _build_caption(report)
    assert "no pods" in caption.lower()


def test_caption_pods_ready():
    """Caption shows ready/total when no warnings."""
    report = _make_report(pod_count=3, ready=3)
    caption = _build_caption(report)
    assert "3/3" in caption


def test_caption_multiple_warnings_shows_overflow():
    """Caption shows (+N more) when there are multiple warnings."""
    report = _make_report(
        warnings=[
            "pod a waiting: CrashLoopBackOff",
            "pod b waiting: OOMKilled",
            "pvc data phase Pending",
        ]
    )
    caption = _build_caption(report)
    assert "+2 more" in caption


# ---------------------------------------------------------------------------
# Tool metadata
# ---------------------------------------------------------------------------


def test_tool_name():
    assert K8sDiagnosticsTool().name == "k8s_diagnostics"


def test_tool_description_mentions_crashloopbackoff():
    assert "CrashLoopBackOff" in K8sDiagnosticsTool().description


def test_tool_parameters_namespace_required():
    params = K8sDiagnosticsTool().parameters
    assert "namespace" in params.get("required", [])


def test_intro_caption_summary():
    caption = K8sDiagnosticsTool().intro_caption({"namespace": "dev", "app": "redis-k8s"})
    assert caption is not None
    assert "redis-k8s" in caption


def test_intro_caption_preflight():
    caption = K8sDiagnosticsTool().intro_caption({"namespace": "dev", "mode": "preflight"})
    assert caption is not None
    assert "Kubernetes" in caption
