"""Tests for the preflight-targets tool ported from canonical/skills.

The helpers shell out to ``kubectl`` / ``juju`` / ``snap`` and probe a
registry over TCP and HTTP — every dependency is monkeypatched so the
tests run hermetically and quickly.
"""

from __future__ import annotations

import json
import socket
import subprocess
import urllib.error
from typing import Any

import pytest

from cantrip.agent.tools import preflight as preflight_module
from cantrip.agent.tools.preflight import (
    EXPERIMENTAL_FRAMEWORKS,
    SUPPORTED_FRAMEWORKS,
    PreflightTargetsTool,
    check_experimental_extensions,
    check_juju,
    check_kubectl,
    check_local_tools,
    check_registry,
    preflight,
)


def _completed(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _stub_run(commands: dict[tuple[str, ...], subprocess.CompletedProcess[str]]):
    """Build a ``_run`` replacement that dispatches by argv tuple."""

    def fake_run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        key = tuple(argv)
        if key not in commands:
            raise AssertionError(f"unexpected subprocess call: {key}")
        return commands[key]

    return fake_run


def _ctx_obj():
    """Return a context-manager stub usable for both socket and urlopen."""

    class _CtxStub:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

    return _CtxStub()


class TestCheckKubectl:
    def test_kubectl_missing(self, monkeypatch):
        monkeypatch.setattr(preflight_module.shutil, "which", lambda _x: None)
        result = check_kubectl("kubectl", selected_context=None)
        assert result["ok"] is False
        assert result["kubectl"]["present"] is False
        assert "kubernetes_contexts" not in result

    def test_kubectl_present_no_selected_context(self, monkeypatch):
        monkeypatch.setattr(preflight_module.shutil, "which", lambda _x: "/usr/bin/kubectl")
        monkeypatch.setattr(
            preflight_module,
            "_run",
            _stub_run(
                {
                    ("kubectl", "config", "get-contexts", "-o", "name"): _completed(
                        stdout="dev\nstaging\nprod\n",
                    ),
                    ("kubectl", "config", "current-context"): _completed(stdout="dev\n"),
                }
            ),
        )
        result = check_kubectl("kubectl", selected_context=None)
        assert result["ok"] is True
        assert result["kubernetes_contexts"]["current"] == "dev"
        assert result["kubernetes_contexts"]["contexts"] == ["dev", "staging", "prod"]
        assert result["kubernetes_contexts"]["selected_ok"] is True

    def test_kubectl_selected_context_missing(self, monkeypatch):
        monkeypatch.setattr(preflight_module.shutil, "which", lambda _x: "/usr/bin/kubectl")
        monkeypatch.setattr(
            preflight_module,
            "_run",
            _stub_run(
                {
                    ("kubectl", "config", "get-contexts", "-o", "name"): _completed(
                        stdout="dev\nstaging\n",
                    ),
                    ("kubectl", "config", "current-context"): _completed(stdout="dev\n"),
                }
            ),
        )
        result = check_kubectl("kubectl", selected_context="prod")
        assert result["ok"] is False
        assert result["kubernetes_contexts"]["selected_ok"] is False


class TestCheckJuju:
    def test_juju_missing(self, monkeypatch):
        monkeypatch.setattr(preflight_module.shutil, "which", lambda _x: None)
        result = check_juju(selected_controller=None)
        assert result["ok"] is False
        assert result["juju"]["present"] is False

    def test_juju_present_with_controllers(self, monkeypatch):
        monkeypatch.setattr(preflight_module.shutil, "which", lambda _x: "/snap/bin/juju")
        controllers_payload = {"controllers": {"k8s": {}, "lxd": {}}}
        monkeypatch.setattr(
            preflight_module,
            "_run",
            _stub_run(
                {
                    ("juju", "controllers", "--format", "json"): _completed(
                        stdout=json.dumps(controllers_payload),
                    ),
                }
            ),
        )
        result = check_juju(selected_controller="k8s")
        assert result["ok"] is True
        assert result["juju_controllers"]["controllers"] == ["k8s", "lxd"]
        assert result["juju_controllers"]["selected_ok"] is True

    def test_juju_selected_controller_missing(self, monkeypatch):
        monkeypatch.setattr(preflight_module.shutil, "which", lambda _x: "/snap/bin/juju")
        monkeypatch.setattr(
            preflight_module,
            "_run",
            _stub_run(
                {
                    ("juju", "controllers", "--format", "json"): _completed(
                        stdout='{"controllers": {"dev": {}}}',
                    ),
                }
            ),
        )
        result = check_juju(selected_controller="prod")
        assert result["ok"] is False
        assert result["juju_controllers"]["selected_ok"] is False

    def test_juju_command_returns_invalid_json(self, monkeypatch):
        # If juju is in a weird state the JSON parse must not crash —
        # the helper should fall back to an empty controllers list.
        monkeypatch.setattr(preflight_module.shutil, "which", lambda _x: "/snap/bin/juju")
        monkeypatch.setattr(
            preflight_module,
            "_run",
            _stub_run(
                {
                    ("juju", "controllers", "--format", "json"): _completed(
                        stdout="not valid json",
                    ),
                }
            ),
        )
        result = check_juju(selected_controller=None)
        assert result["ok"] is True
        assert result["juju_controllers"]["controllers"] == []


class TestCheckLocalTools:
    def test_all_three_present_with_snap_tracking(self, monkeypatch):
        monkeypatch.setattr(preflight_module.shutil, "which", lambda name: f"/snap/bin/{name}")

        def fake_run(argv: list[str]):
            if argv[:2] == ["snap", "list"]:
                snap_name = argv[2]
                return _completed(
                    stdout=(
                        "Name        Version  Rev   Tracking      Publisher  Notes\n"
                        f"{snap_name}  1.0      100   latest/edge   canonical  -\n"
                    ),
                )
            raise AssertionError(f"unexpected: {argv}")

        monkeypatch.setattr(preflight_module, "_run", fake_run)
        tools = check_local_tools()
        assert tools["rockcraft"]["snap"]["tracking"] == "latest/edge"
        assert tools["charmcraft"]["snap"]["tracking"] == "latest/edge"
        assert tools["skopeo"]["present"] is True
        # Skopeo is not snap-tracked in our port (the upstream's
        # rockcraft-embedded path detection is dropped).
        assert "snap" not in tools["skopeo"]

    def test_rockcraft_not_installed(self, monkeypatch):
        monkeypatch.setattr(
            preflight_module.shutil,
            "which",
            lambda name: "/snap/bin/snap" if name == "snap" else None,
        )
        monkeypatch.setattr(
            preflight_module,
            "_run",
            lambda _argv: _completed(returncode=1, stderr="error: snap not found"),
        )
        tools = check_local_tools()
        assert tools["rockcraft"]["present"] is False
        assert tools["rockcraft"]["snap"]["installed"] is False


class TestCheckExperimentalExtensions:
    def test_all_gates_satisfied(self, monkeypatch):
        monkeypatch.setenv("ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS", "true")
        monkeypatch.setenv("CHARMCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS", "1")
        local_tools = {
            "rockcraft": {
                "command": "rockcraft",
                "present": True,
                "snap": {"tracking": "latest/edge"},
            },
            "charmcraft": {
                "command": "charmcraft",
                "present": True,
                "snap": {"tracking": "latest/edge"},
            },
        }
        result = check_experimental_extensions("fastapi", local_tools)
        assert result["ok"] is True
        assert result["rockcraft"]["env_ok"] is True
        assert result["charmcraft"]["tracking_ok"] is True

    def test_env_unset_is_a_failure(self, monkeypatch):
        monkeypatch.delenv("ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS", raising=False)
        monkeypatch.delenv("CHARMCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS", raising=False)
        local_tools = {
            "rockcraft": {"present": True, "snap": {"tracking": "latest/edge"}},
            "charmcraft": {"present": True, "snap": {"tracking": "latest/edge"}},
        }
        result = check_experimental_extensions("go", local_tools)
        assert result["ok"] is False
        assert result["rockcraft"]["env_ok"] is False

    def test_stable_channel_is_a_failure(self, monkeypatch):
        monkeypatch.setenv("ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS", "yes")
        monkeypatch.setenv("CHARMCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS", "yes")
        local_tools = {
            "rockcraft": {"present": True, "snap": {"tracking": "latest/stable"}},
            "charmcraft": {"present": True, "snap": {"tracking": "latest/edge"}},
        }
        result = check_experimental_extensions("express", local_tools)
        assert result["ok"] is False
        assert result["rockcraft"]["tracking_ok"] is False
        assert result["charmcraft"]["tracking_ok"] is True

    def test_unrecognised_truthy_value_is_failure(self, monkeypatch):
        monkeypatch.setenv("ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS", "ok")
        monkeypatch.setenv("CHARMCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS", "true")
        local_tools = {
            "rockcraft": {"present": True, "snap": {"tracking": "latest/edge"}},
            "charmcraft": {"present": True, "snap": {"tracking": "latest/edge"}},
        }
        result = check_experimental_extensions("spring-boot", local_tools)
        # ``ok`` is not in the truthy set, so the rockcraft env gate fails.
        assert result["ok"] is False


class TestCheckRegistry:
    def test_http_probe_succeeds(self, monkeypatch):
        monkeypatch.setattr(socket, "create_connection", lambda *_a, **_k: _ctx_obj())
        monkeypatch.setattr(
            preflight_module.urllib.request, "urlopen", lambda *_a, **_k: _ctx_obj()
        )
        result = check_registry("registry.example.com:5000")
        assert result["ok"] is True
        assert result["registry"] == "registry.example.com:5000"
        assert any(probe.get("ok") for probe in result["probes"])

    def test_tcp_failure_continues_to_next_candidate(self, monkeypatch):
        # When a bare host:port is passed, the probe tries http:// then
        # https://.  TCP fails on http, succeeds on https with HTTP 200.
        attempts: list[tuple[Any, Any]] = []

        def fake_create_connection(addr, timeout):
            attempts.append((addr, timeout))
            if len(attempts) == 1:
                raise OSError("connection refused")
            return _ctx_obj()

        monkeypatch.setattr(socket, "create_connection", fake_create_connection)
        monkeypatch.setattr(
            preflight_module.urllib.request, "urlopen", lambda *_a, **_k: _ctx_obj()
        )
        result = check_registry("registry.example.com")
        assert result["ok"] is True
        # http + https.
        assert len(result["probes"]) == 2

    def test_all_probes_fail(self, monkeypatch):
        def raise_oserror(*_args: object, **_kwargs: object):
            raise OSError("no route to host")

        monkeypatch.setattr(socket, "create_connection", raise_oserror)

        def raise_urlerror(*_args: object, **_kwargs: object):
            raise urllib.error.URLError("never reached")

        monkeypatch.setattr(preflight_module.urllib.request, "urlopen", raise_urlerror)
        result = check_registry("registry.example.com:5000")
        assert result["ok"] is False
        assert all(probe["tcp"].startswith("failed") for probe in result["probes"])

    def test_full_url_target_does_not_get_scheme_alternation(self, monkeypatch):
        attempts: list[tuple[Any, Any]] = []

        def fake_create_connection(addr, *, timeout):  # noqa: ARG001  # called by name
            del timeout
            attempts.append(addr)
            return _ctx_obj()

        monkeypatch.setattr(socket, "create_connection", fake_create_connection)
        monkeypatch.setattr(
            preflight_module.urllib.request, "urlopen", lambda *_a, **_k: _ctx_obj()
        )
        result = check_registry("https://registry.example.com")
        assert result["ok"] is True
        assert len(result["probes"]) == 1


@pytest.fixture
def green_environment(monkeypatch):
    """Environment where every preflight gate passes."""

    def which(name: str) -> str | None:
        return f"/usr/bin/{name}"

    monkeypatch.setattr(preflight_module.shutil, "which", which)

    def fake_run(argv: list[str]):
        if argv[:3] == ["kubectl", "config", "get-contexts"]:
            return _completed(stdout="dev\n")
        if argv[:3] == ["kubectl", "config", "current-context"]:
            return _completed(stdout="dev\n")
        if argv[:2] == ["juju", "controllers"]:
            return _completed(stdout='{"controllers": {"k8s": {}}}')
        if argv[:2] == ["snap", "list"]:
            snap_name = argv[2]
            return _completed(
                stdout=(
                    "Name        Version  Rev   Tracking      Publisher  Notes\n"
                    f"{snap_name}  1.0      100   latest/edge   canonical  -\n"
                ),
            )
        raise AssertionError(f"unexpected: {argv}")

    monkeypatch.setattr(preflight_module, "_run", fake_run)
    monkeypatch.setenv("ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS", "true")
    monkeypatch.setenv("CHARMCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS", "true")
    monkeypatch.setattr(socket, "create_connection", lambda *_a, **_k: _ctx_obj())
    monkeypatch.setattr(preflight_module.urllib.request, "urlopen", lambda *_a, **_k: _ctx_obj())


class TestPreflightEndToEnd:
    def test_green_path_full_sweep(self, green_environment):
        report = preflight(
            framework="fastapi",
            kubernetes_context="dev",
            juju_controller="k8s",
            registry="registry.example.com:5000",
        )
        assert report.ok is True
        assert "experimental_extensions" in report.checks
        assert report.checks["experimental_extensions"]["ok"] is True
        assert report.checks["registry"]["ok"] is True

    def test_no_framework_skips_experimental_subtree(self, green_environment):
        report = preflight()
        assert "experimental_extensions" not in report.checks

    def test_stable_framework_skips_experimental_subtree(self, green_environment):
        # Flask is stable, so the experimental subtree must not engage
        # even though the env vars happen to be set.
        report = preflight(framework="flask")
        assert "experimental_extensions" not in report.checks

    def test_kubectl_missing_breaks_overall_ok(self, monkeypatch):
        monkeypatch.setattr(preflight_module.shutil, "which", lambda _name: None)
        report = preflight()
        assert report.ok is False


class TestPreflightTargetsTool:
    @pytest.fixture
    def tool(self):
        return PreflightTargetsTool()

    @pytest.mark.asyncio
    async def test_caption_on_success(self, tool, green_environment):
        result = await tool.execute(framework="fastapi")
        assert result.success is True
        assert "ok" in result.caption

    @pytest.mark.asyncio
    async def test_caption_on_failure(self, tool, monkeypatch):
        monkeypatch.setattr(preflight_module.shutil, "which", lambda _name: None)
        result = await tool.execute()
        # Tool ran cleanly even though the environment fails the sweep.
        assert result.success is True
        assert result.data["ok"] is False
        assert "gate(s) failing" in result.caption

    def test_schema_lists_cantrip_framework_names(self, tool):
        enum = tool.parameters["properties"]["framework"]["enum"]
        assert "express" in enum
        assert "expressjs" not in enum
        assert set(enum) == set(SUPPORTED_FRAMEWORKS)

    def test_experimental_set_uses_cantrip_express_name(self):
        assert "express" in EXPERIMENTAL_FRAMEWORKS
        assert "expressjs" not in EXPERIMENTAL_FRAMEWORKS
