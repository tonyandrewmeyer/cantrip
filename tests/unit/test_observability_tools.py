"""Tests for observability tools (juju_debug_log, tempo_query, loki_query)."""

import base64
import json
import re
from unittest import mock

import jubilant
import pytest

from cantrip.agent.tools.observability import (
    _PNG_MAGIC,
    GrafanaScreenshotTool,
    JujuDebugLogTool,
    LokiQueryTool,
    TempoQueryTool,
    _find_cos_unit,
    _grafana_admin_password,
)


def _decode_ssh_script(ssh_command: str) -> str:
    """Extract and decode the base64-encoded Python script from an SSH command."""
    match = re.search(r"base64\.b64decode\('([A-Za-z0-9+/=]+)'\)", ssh_command)
    assert match, f"No base64 payload found in: {ssh_command}"
    return base64.b64decode(match.group(1)).decode()


def _make_fake_process(returncode: int = 0, stdout: str = "", stderr: str = ""):
    """Build a mock async subprocess.

    ``kill`` is a sync method on ``asyncio.subprocess.Process`` — override
    the AsyncMock's inferred async behaviour so the timeout path doesn't
    leak an unawaited coroutine.
    """
    proc = mock.AsyncMock()
    proc.communicate.return_value = (stdout.encode(), stderr.encode())
    proc.returncode = returncode
    proc.kill = mock.MagicMock()
    return proc


def _raise_timeout(coro, *_args, **_kwargs):
    """Side-effect replacement for ``asyncio.wait_for`` that closes the
    pending coroutine before raising, so mocked timeout tests don't
    emit unawaited-coroutine warnings."""
    coro.close()
    raise TimeoutError


def _mock_juju_unavailable():
    """Patch _juju_available to return False."""
    return mock.patch("cantrip.agent.tools.observability._juju_available", return_value=False)


def _mock_juju_available():
    """Patch _juju_available to return True."""
    return mock.patch("cantrip.agent.tools.observability._juju_available", return_value=True)


# ---------------------------------------------------------------------------
# _find_cos_unit helper
# ---------------------------------------------------------------------------


class TestFindCosUnit:
    """Tests for the _find_cos_unit helper."""

    def test_finds_matching_unit(self):
        """Returns the first unit of the matching app."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        unit = mock.MagicMock()
        app = mock.MagicMock()
        app.units = {"tempo-k8s/0": unit}
        status = mock.MagicMock()
        status.apps = {"tempo-k8s": app}
        mock_juju.status.return_value = status

        with mock.patch("cantrip.agent.tools.observability.jubilant.Juju", return_value=mock_juju):
            juju, unit_name = _find_cos_unit("cos", "tempo")

        assert unit_name == "tempo-k8s/0"
        assert juju is mock_juju

    def test_raises_when_not_found(self):
        """Raises ValueError with available apps when no match."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        app = mock.MagicMock()
        app.units = {"grafana/0": mock.MagicMock()}
        status = mock.MagicMock()
        status.apps = {"grafana": app}
        mock_juju.status.return_value = status

        with (
            mock.patch("cantrip.agent.tools.observability.jubilant.Juju", return_value=mock_juju),
            pytest.raises(ValueError, match="grafana"),
        ):
            _find_cos_unit("cos", "tempo")


# ---------------------------------------------------------------------------
# JujuDebugLogTool
# ---------------------------------------------------------------------------


class TestJujuDebugLogTool:
    """Tests for JujuDebugLogTool."""

    @pytest.fixture
    def tool(self):
        return JujuDebugLogTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju is not on PATH."""
        with _mock_juju_unavailable():
            result = await tool.execute()

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_default_params(self, tool):
        """Runs with default parameters (50 lines, no filters)."""
        proc = _make_fake_process(stdout="unit-my-app-0: 12:00:00 INFO juju ok\n")

        with (
            _mock_juju_available(),
            mock.patch("asyncio.create_subprocess_exec", return_value=proc),
        ):
            result = await tool.execute()

        assert result.success
        assert "ok" in result.output

    @pytest.mark.asyncio
    async def test_uses_limit_flag_not_no_tail(self, tool):
        """Uses --limit instead of incompatible --no-tail + -n combination."""
        proc = _make_fake_process(stdout="log line\n")

        with (
            _mock_juju_available(),
            mock.patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec,
        ):
            await tool.execute(lines=25)

        call_args = mock_exec.call_args[0]
        assert "--limit=25" in call_args
        assert "--no-tail" not in call_args
        assert "-n25" not in call_args

    @pytest.mark.asyncio
    async def test_unit_filter(self, tool):
        """Passes --include when unit is specified."""
        proc = _make_fake_process(stdout="filtered output\n")

        with (
            _mock_juju_available(),
            mock.patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec,
        ):
            result = await tool.execute(unit="my-app/0")

        assert result.success
        # Check that --include my-app/0 was passed.
        call_args = mock_exec.call_args[0]
        assert "--include" in call_args
        assert "my-app/0" in call_args

    @pytest.mark.asyncio
    async def test_model_filter(self, tool):
        """Passes -m when model is specified."""
        proc = _make_fake_process(stdout="model output\n")

        with (
            _mock_juju_available(),
            mock.patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec,
        ):
            result = await tool.execute(model="dev")

        assert result.success
        call_args = mock_exec.call_args[0]
        assert "-m" in call_args
        assert "dev" in call_args

    @pytest.mark.asyncio
    async def test_level_filter(self, tool):
        """Passes --level when level is specified."""
        proc = _make_fake_process(stdout="error output\n")

        with (
            _mock_juju_available(),
            mock.patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec,
        ):
            result = await tool.execute(level="ERROR")

        assert result.success
        call_args = mock_exec.call_args[0]
        assert "--level" in call_args
        assert "ERROR" in call_args

    @pytest.mark.asyncio
    async def test_command_failure(self, tool):
        """Reports error when debug-log command fails."""
        proc = _make_fake_process(returncode=1, stderr="model not found")

        with (
            _mock_juju_available(),
            mock.patch("asyncio.create_subprocess_exec", return_value=proc),
        ):
            result = await tool.execute()

        assert not result.success
        assert "model not found" in result.error

    @pytest.mark.asyncio
    async def test_timeout(self, tool):
        """Reports error on timeout."""
        with (
            _mock_juju_available(),
            mock.patch("asyncio.create_subprocess_exec", return_value=_make_fake_process()),
            mock.patch("asyncio.wait_for", side_effect=_raise_timeout),
        ):
            result = await tool.execute()

        assert not result.success
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_empty_output(self, tool):
        """Returns informative message when output is empty."""
        proc = _make_fake_process(stdout="")

        with (
            _mock_juju_available(),
            mock.patch("asyncio.create_subprocess_exec", return_value=proc),
        ):
            result = await tool.execute()

        assert result.success
        assert "no log output" in result.output.lower()


# ---------------------------------------------------------------------------
# TempoQueryTool
# ---------------------------------------------------------------------------


class TestTempoQueryTool:
    """Tests for TempoQueryTool."""

    @pytest.fixture
    def tool(self):
        return TempoQueryTool()

    def _mock_find_cos_unit(self):
        """Patch _find_cos_unit to return a mock juju and unit name."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        return mock.patch(
            "cantrip.agent.tools.observability._find_cos_unit",
            return_value=(mock_juju, "tempo-k8s/0"),
        ), mock_juju

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju is not on PATH."""
        with _mock_juju_unavailable():
            result = await tool.execute(query="{}")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_search_by_service_name(self, tool):
        """Searches Tempo by service name."""
        patch, mock_juju = self._mock_find_cos_unit()
        search_result = {"traces": [{"traceID": "abc123", "rootServiceName": "my-charm"}]}
        mock_juju.ssh.return_value = json.dumps(search_result)

        with _mock_juju_available(), patch:
            result = await tool.execute(service_name="my-charm")

        assert result.success
        assert result.data["count"] == 1
        assert "abc123" in result.output

    @pytest.mark.asyncio
    async def test_traceql_query(self, tool):
        """Searches Tempo with a TraceQL query."""
        patch, mock_juju = self._mock_find_cos_unit()
        search_result = {"traces": [{"traceID": "def456"}]}
        mock_juju.ssh.return_value = json.dumps(search_result)

        with _mock_juju_available(), patch:
            result = await tool.execute(query="{ status = error }")

        assert result.success
        assert result.data["count"] == 1

    @pytest.mark.asyncio
    async def test_get_by_trace_id(self, tool):
        """Fetches a specific trace by ID."""
        patch, mock_juju = self._mock_find_cos_unit()
        trace_data = {"batches": [{"resource": {"serviceName": "my-charm"}}]}
        mock_juju.ssh.return_value = json.dumps(trace_data)

        with _mock_juju_available(), patch:
            result = await tool.execute(trace_id="abc123")

        assert result.success
        assert result.data["trace_id"] == "abc123"

    @pytest.mark.asyncio
    async def test_tempo_not_found_in_cos(self, tool):
        """Error when Tempo is not in the COS model."""
        with (
            _mock_juju_available(),
            mock.patch(
                "cantrip.agent.tools.observability._find_cos_unit",
                side_effect=ValueError("No app containing 'tempo' found"),
            ),
        ):
            result = await tool.execute(service_name="my-charm")

        assert not result.success
        assert "tempo" in result.error.lower()

    @pytest.mark.asyncio
    async def test_ssh_error(self, tool):
        """Reports error when SSH fails."""
        patch, mock_juju = self._mock_find_cos_unit()
        mock_juju.ssh.side_effect = jubilant.CLIError(1, "ssh failed")

        with _mock_juju_available(), patch:
            result = await tool.execute(service_name="my-charm")

        assert not result.success
        assert "ssh" in result.error.lower()

    @pytest.mark.asyncio
    async def test_malformed_json(self, tool):
        """Reports error on malformed JSON from Tempo."""
        patch, mock_juju = self._mock_find_cos_unit()
        mock_juju.ssh.return_value = "not valid json{{"

        with _mock_juju_available(), patch:
            result = await tool.execute(service_name="my-charm")

        assert not result.success
        assert "malformed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_empty_results(self, tool):
        """Returns informative message when no traces found."""
        patch, mock_juju = self._mock_find_cos_unit()
        mock_juju.ssh.return_value = json.dumps({"traces": []})

        with _mock_juju_available(), patch:
            result = await tool.execute(service_name="my-charm")

        assert result.success
        assert "no traces" in result.output.lower()

    @pytest.mark.asyncio
    async def test_shell_injection_prevented(self, tool):
        """Queries with shell metacharacters cannot escape the base64 payload."""
        patch, mock_juju = self._mock_find_cos_unit()
        search_result = {"traces": []}
        mock_juju.ssh.return_value = json.dumps(search_result)

        # A malicious query containing double quotes and shell metacharacters.
        malicious_query = '"; rm -rf / #'

        with _mock_juju_available(), patch:
            result = await tool.execute(query=malicious_query)

        assert result.success
        # The SSH command must use base64 encoding, not raw string interpolation.
        ssh_call = mock_juju.ssh.call_args[0][1]
        assert "base64" in ssh_call
        # The malicious string must not appear literally in the shell command.
        assert "rm -rf" not in ssh_call


# ---------------------------------------------------------------------------
# LokiQueryTool
# ---------------------------------------------------------------------------


class TestLokiQueryTool:
    """Tests for LokiQueryTool."""

    @pytest.fixture
    def tool(self):
        return LokiQueryTool()

    def _mock_find_cos_unit(self):
        """Patch _find_cos_unit to return a mock juju and unit name."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        return mock.patch(
            "cantrip.agent.tools.observability._find_cos_unit",
            return_value=(mock_juju, "loki-k8s/0"),
        ), mock_juju

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju is not on PATH."""
        with _mock_juju_unavailable():
            result = await tool.execute(query='{juju_application="my-charm"}')

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_successful_query(self, tool):
        """Returns formatted log entries on success."""
        patch, mock_juju = self._mock_find_cos_unit()
        loki_response = {
            "data": {
                "result": [
                    {
                        "stream": {"app": "my-charm"},
                        "values": [
                            ["1700000000000000000", "ERROR: something went wrong"],
                            ["1700000001000000000", "INFO: recovered"],
                        ],
                    }
                ]
            }
        }
        mock_juju.ssh.return_value = json.dumps(loki_response)

        with _mock_juju_available(), patch:
            result = await tool.execute(query='{juju_application="my-charm"}')

        assert result.success
        assert result.data["count"] == 2
        assert "something went wrong" in result.output

    @pytest.mark.asyncio
    async def test_custom_hours(self, tool):
        """Passes custom hours parameter."""
        patch, mock_juju = self._mock_find_cos_unit()
        loki_response = {
            "data": {
                "result": [
                    {
                        "stream": {"app": "my-charm"},
                        "values": [["1700000000000000000", "log line"]],
                    }
                ]
            }
        }
        mock_juju.ssh.return_value = json.dumps(loki_response)

        with _mock_juju_available(), patch:
            result = await tool.execute(query='{juju_application="my-charm"}', hours=24)

        assert result.success
        # Verify the URL contains the custom hours (inside the base64-encoded script).
        ssh_call = mock_juju.ssh.call_args[0][1]
        script = _decode_ssh_script(ssh_call)
        assert "now-24h" in script

    @pytest.mark.asyncio
    async def test_loki_not_found_in_cos(self, tool):
        """Error when Loki is not in the COS model."""
        with (
            _mock_juju_available(),
            mock.patch(
                "cantrip.agent.tools.observability._find_cos_unit",
                side_effect=ValueError("No app containing 'loki' found"),
            ),
        ):
            result = await tool.execute(query='{app="test"}')

        assert not result.success
        assert "loki" in result.error.lower()

    @pytest.mark.asyncio
    async def test_ssh_error(self, tool):
        """Reports error when SSH fails."""
        patch, mock_juju = self._mock_find_cos_unit()
        mock_juju.ssh.side_effect = jubilant.CLIError(1, "ssh failed")

        with _mock_juju_available(), patch:
            result = await tool.execute(query='{app="test"}')

        assert not result.success
        assert "ssh" in result.error.lower()

    @pytest.mark.asyncio
    async def test_malformed_json(self, tool):
        """Reports error on malformed JSON from Loki."""
        patch, mock_juju = self._mock_find_cos_unit()
        mock_juju.ssh.return_value = "<<not json>>"

        with _mock_juju_available(), patch:
            result = await tool.execute(query='{app="test"}')

        assert not result.success
        assert "malformed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_empty_results(self, tool):
        """Returns informative message when no logs found."""
        patch, mock_juju = self._mock_find_cos_unit()
        mock_juju.ssh.return_value = json.dumps({"data": {"result": []}})

        with _mock_juju_available(), patch:
            result = await tool.execute(query='{app="test"}')

        assert result.success
        assert "no log entries" in result.output.lower()

    @pytest.mark.asyncio
    async def test_shell_injection_prevented(self, tool):
        """Queries with shell metacharacters cannot escape the base64 payload."""
        patch, mock_juju = self._mock_find_cos_unit()
        loki_response = {"data": {"result": []}}
        mock_juju.ssh.return_value = json.dumps(loki_response)

        # A malicious query containing double quotes and shell metacharacters.
        malicious_query = '{app="test"} |= "$(rm -rf /)"'

        with _mock_juju_available(), patch:
            result = await tool.execute(query=malicious_query)

        assert result.success
        # The SSH command must use base64 encoding, not raw string interpolation.
        ssh_call = mock_juju.ssh.call_args[0][1]
        assert "base64" in ssh_call
        # The malicious string must not appear literally in the shell command.
        assert "rm -rf" not in ssh_call


# ---------------------------------------------------------------------------
# GrafanaScreenshotTool  (Phase 48.2)
# ---------------------------------------------------------------------------


class TestGrafanaAdminPassword:
    """Tests for the _grafana_admin_password helper."""

    def test_extracts_admin_password_result(self):
        """Returns the password from the action's ``admin-password`` result key."""
        juju = mock.MagicMock(spec=jubilant.Juju)
        task = mock.MagicMock()
        task.results = {"admin-password": "secret123"}
        juju.run.return_value = task
        assert _grafana_admin_password(juju) == "secret123"

    def test_falls_back_to_password_key(self):
        """Accepts ``password`` as an alternative result key."""
        juju = mock.MagicMock(spec=jubilant.Juju)
        task = mock.MagicMock()
        task.results = {"password": "fallback-pw"}
        juju.run.return_value = task
        assert _grafana_admin_password(juju) == "fallback-pw"

    def test_none_when_action_fails(self):
        """Returns None on TaskError / ValueError / CLIError — caller degrades."""
        juju = mock.MagicMock(spec=jubilant.Juju)
        juju.run.side_effect = ValueError("unknown action")
        assert _grafana_admin_password(juju) is None

    def test_none_when_results_empty(self):
        """Missing ``admin-password`` / ``password`` yields None."""
        juju = mock.MagicMock(spec=jubilant.Juju)
        task = mock.MagicMock()
        task.results = {"unrelated": "x"}
        juju.run.return_value = task
        assert _grafana_admin_password(juju) is None


class TestGrafanaScreenshotTool:
    """Phase 48.2: render a Grafana panel via /render and save the PNG."""

    @pytest.fixture
    def tool(self):
        return GrafanaScreenshotTool()

    def _mock_find_cos_unit(self):
        """Patch _find_cos_unit to return a mock juju handle."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        return mock.patch(
            "cantrip.agent.tools.observability._find_cos_unit",
            return_value=(mock_juju, "grafana/0"),
        ), mock_juju

    @pytest.fixture
    def png_payload(self):
        """A minimal byte string that starts with the PNG magic."""
        return _PNG_MAGIC + b"fake-png-pixels"

    def _prime_successful_render(self, mock_juju, payload: bytes, password: str = "secret"):
        """Configure the mock juju handle for a successful render path."""
        task = mock.MagicMock()
        task.results = {"admin-password": password}
        mock_juju.run.return_value = task
        mock_juju.ssh.return_value = base64.b64encode(payload).decode("ascii")

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju is not on PATH."""
        with _mock_juju_unavailable():
            result = await tool.execute(dashboard_uid="abc123")
        assert not result.success
        assert "juju" in result.error.lower()

    @pytest.mark.asyncio
    async def test_happy_path_saves_png(self, tool, tmp_path, png_payload, monkeypatch):
        """Successful render writes the PNG to the cache dir and returns the path."""
        monkeypatch.setattr(
            "cantrip.agent.tools.observability._SCREENSHOT_CACHE_DIR",
            tmp_path,
        )
        patch, mock_juju = self._mock_find_cos_unit()
        self._prime_successful_render(mock_juju, png_payload)

        with _mock_juju_available(), patch:
            result = await tool.execute(
                dashboard_uid="my-dash",
                panel_id=7,
                time_range="6h",
                width=1200,
                height=400,
            )

        assert result.success, result.error
        path = tmp_path / result.data["path"].split("/")[-1]
        assert path.exists()
        assert path.read_bytes() == png_payload
        assert result.data["panel_id"] == 7
        assert result.data["dashboard_uid"] == "my-dash"
        assert result.data["time_range"] == "6h"
        assert result.data["width"] == 1200
        assert result.data["height"] == 400
        assert result.data["bytes"] == len(png_payload)
        assert "my-dash" in result.output
        assert "panel 7" in result.output
        assert "now-6h" in result.output
        # 48.2b: image bytes are attached so vision-capable providers
        # can reason about the panel alongside the caption.
        assert len(result.images) == 1
        assert result.images[0].mime == "image/png"
        assert result.images[0].data == png_payload

    @pytest.mark.asyncio
    async def test_uses_d_solo_endpoint_for_panel(self, tool, tmp_path, png_payload, monkeypatch):
        """Requests with panel_id hit /render/d-solo/ with panelId= query."""
        monkeypatch.setattr(
            "cantrip.agent.tools.observability._SCREENSHOT_CACHE_DIR",
            tmp_path,
        )
        patch, mock_juju = self._mock_find_cos_unit()
        self._prime_successful_render(mock_juju, png_payload)

        with _mock_juju_available(), patch:
            await tool.execute(dashboard_uid="abc", panel_id=3)

        script = _decode_ssh_script(mock_juju.ssh.call_args[0][1])
        assert "/render/d-solo/abc" in script
        assert "panelId=3" in script

    @pytest.mark.asyncio
    async def test_uses_d_endpoint_without_panel(self, tool, tmp_path, png_payload, monkeypatch):
        """Requests without panel_id hit /render/d/ (full dashboard)."""
        monkeypatch.setattr(
            "cantrip.agent.tools.observability._SCREENSHOT_CACHE_DIR",
            tmp_path,
        )
        patch, mock_juju = self._mock_find_cos_unit()
        self._prime_successful_render(mock_juju, png_payload)

        with _mock_juju_available(), patch:
            await tool.execute(dashboard_uid="abc")

        script = _decode_ssh_script(mock_juju.ssh.call_args[0][1])
        assert "/render/d/abc" in script
        assert "panelId" not in script

    @pytest.mark.asyncio
    async def test_auth_header_included_when_password_available(
        self, tool, tmp_path, png_payload, monkeypatch
    ):
        """When the action returns a password, the SSH script adds Basic auth."""
        monkeypatch.setattr(
            "cantrip.agent.tools.observability._SCREENSHOT_CACHE_DIR",
            tmp_path,
        )
        patch, mock_juju = self._mock_find_cos_unit()
        self._prime_successful_render(mock_juju, png_payload, password="pw-42")

        with _mock_juju_available(), patch:
            await tool.execute(dashboard_uid="abc")

        script = _decode_ssh_script(mock_juju.ssh.call_args[0][1])
        expected = base64.b64encode(b"admin:pw-42").decode("ascii")
        assert f"Basic {expected}" in script

    @pytest.mark.asyncio
    async def test_missing_password_proceeds_unauthenticated(
        self, tool, tmp_path, png_payload, monkeypatch
    ):
        """No password from the action → request without Authorization header."""
        monkeypatch.setattr(
            "cantrip.agent.tools.observability._SCREENSHOT_CACHE_DIR",
            tmp_path,
        )
        patch, mock_juju = self._mock_find_cos_unit()
        mock_juju.run.side_effect = ValueError("no such action")
        mock_juju.ssh.return_value = base64.b64encode(png_payload).decode("ascii")

        with _mock_juju_available(), patch:
            result = await tool.execute(dashboard_uid="abc")

        assert result.success
        script = _decode_ssh_script(mock_juju.ssh.call_args[0][1])
        assert "Authorization" not in script

    @pytest.mark.asyncio
    async def test_non_png_response_surfaces_error_snippet(self, tool, tmp_path, monkeypatch):
        """An HTML error page (renderer plugin missing) is surfaced verbatim."""
        monkeypatch.setattr(
            "cantrip.agent.tools.observability._SCREENSHOT_CACHE_DIR",
            tmp_path,
        )
        patch, mock_juju = self._mock_find_cos_unit()
        error_body = b"<html>Error rendering image: no remote rendering plugin</html>"
        task = mock.MagicMock()
        task.results = {"admin-password": "x"}
        mock_juju.run.return_value = task
        mock_juju.ssh.return_value = base64.b64encode(error_body).decode("ascii")

        with _mock_juju_available(), patch:
            result = await tool.execute(dashboard_uid="abc")

        assert not result.success
        assert "did not return a PNG" in result.error
        assert "no remote rendering" in result.error

    @pytest.mark.asyncio
    async def test_non_png_response_hints_at_password_when_absent(
        self, tool, tmp_path, monkeypatch
    ):
        """When we had no password, hint at running the action manually."""
        monkeypatch.setattr(
            "cantrip.agent.tools.observability._SCREENSHOT_CACHE_DIR",
            tmp_path,
        )
        patch, mock_juju = self._mock_find_cos_unit()
        mock_juju.run.side_effect = ValueError("no such action")
        mock_juju.ssh.return_value = base64.b64encode(b"<html>401</html>").decode("ascii")

        with _mock_juju_available(), patch:
            result = await tool.execute(dashboard_uid="abc")

        assert not result.success
        assert "get-admin-password" in result.error

    @pytest.mark.asyncio
    async def test_invalid_time_range_rejected(self, tool):
        """A free-form time_range is rejected before anything reaches Grafana."""
        with _mock_juju_available():
            result = await tool.execute(dashboard_uid="abc", time_range="last hour")
        assert not result.success
        assert "time_range" in result.error

    @pytest.mark.asyncio
    async def test_dimensions_out_of_range_rejected(self, tool):
        """Width/height beyond the 4000-pixel cap are rejected."""
        with _mock_juju_available():
            result = await tool.execute(dashboard_uid="abc", width=99999)
        assert not result.success
        assert "width" in result.error.lower()

    @pytest.mark.asyncio
    async def test_bad_dashboard_uid_rejected(self, tool):
        """Dashboard UIDs with funny characters are rejected."""
        with _mock_juju_available():
            result = await tool.execute(dashboard_uid="../etc/passwd")
        assert not result.success
        assert "dashboard_uid" in result.error

    @pytest.mark.asyncio
    async def test_grafana_not_found_in_cos(self, tool):
        """Clean error when Grafana isn't in the COS model."""
        with (
            _mock_juju_available(),
            mock.patch(
                "cantrip.agent.tools.observability._find_cos_unit",
                side_effect=ValueError("No app containing 'grafana' found"),
            ),
        ):
            result = await tool.execute(dashboard_uid="abc")
        assert not result.success
        assert "grafana" in result.error.lower()
