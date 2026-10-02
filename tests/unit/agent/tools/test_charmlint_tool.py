"""Tests for the charmlint agent-tool wrapper."""

import json
import pathlib
import subprocess
import sys
from collections.abc import Iterator
from types import SimpleNamespace
from unittest import mock

import pytest

from cantrip.agent.tools import charmlint_tool
from cantrip.agent.tools.charmlint_tool import CharmlintTool

_CLEAN_REPORT = json.dumps({"diagnostics": [], "total": 0, "errors": 0, "warnings": 0, "info": 0})


def _fake_proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class TestCharmlintToolMetadata:
    def test_tool_name(self) -> None:
        assert CharmlintTool().name == "charmlint"

    def test_description_mentions_lint(self) -> None:
        assert "lint" in CharmlintTool().description.lower()

    def test_parameters_schema(self) -> None:
        params = CharmlintTool().parameters
        props = params["properties"]
        assert {"path", "select", "ignore", "severity"} <= props.keys()
        assert props["severity"]["enum"] == ["error", "warning", "info"]


class TestCharmlintCommand:
    def test_runs_module_under_current_interpreter(self, tmp_path: pathlib.Path) -> None:
        cmd = charmlint_tool.charmlint_command(tmp_path)
        assert cmd[:3] == [sys.executable, "-m", "charmlint"]
        assert cmd[3] == str(tmp_path)
        assert cmd[cmd.index("--format") + 1] == "json"

    def test_omits_empty_filters(self, tmp_path: pathlib.Path) -> None:
        cmd = charmlint_tool.charmlint_command(tmp_path)
        assert "--select" not in cmd
        assert "--ignore" not in cmd
        assert "--min-severity" not in cmd


class TestParseCharmlintOutput:
    def test_exit_one_is_a_report_with_errors(self) -> None:
        payload = {"diagnostics": [{"rule_id": "SECURITY-001"}], "total": 1, "errors": 1}
        data = charmlint_tool.parse_charmlint_output(1, json.dumps(payload), "")
        assert data["errors"] == 1

    def test_exit_two_raises_with_stderr(self) -> None:
        with pytest.raises(charmlint_tool.CharmlintError, match="not a known rule ID"):
            charmlint_tool.parse_charmlint_output(
                2, "", "error: not a known rule ID, rule name or category: COS\n"
            )

    def test_exit_two_without_stderr_names_the_code(self) -> None:
        with pytest.raises(charmlint_tool.CharmlintError, match="exit code 2"):
            charmlint_tool.parse_charmlint_output(2, "", "")

    def test_bad_json_raises(self) -> None:
        with pytest.raises(charmlint_tool.CharmlintError, match="not JSON"):
            charmlint_tool.parse_charmlint_output(0, "not json at all", "")

    def test_non_object_json_raises(self) -> None:
        with pytest.raises(charmlint_tool.CharmlintError, match="not a JSON object"):
            charmlint_tool.parse_charmlint_output(0, "[]", "")


class TestCharmlintToolExecute:
    @pytest.fixture
    def tool(self) -> CharmlintTool:
        return CharmlintTool()

    @pytest.mark.asyncio
    async def test_path_not_found(self, tool: CharmlintTool, tmp_path: pathlib.Path) -> None:
        result = await tool.execute(path=str(tmp_path / "missing"))
        assert not result.success
        assert "path not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_clean_report(self, tool: CharmlintTool, tmp_path: pathlib.Path) -> None:
        """A zero-diagnostic JSON report renders as 'No issues found'."""
        payload = {"diagnostics": [], "total": 0, "errors": 0, "warnings": 0, "info": 0}
        with mock.patch(
            "cantrip.agent.tools.charmlint_tool.subprocess.run",
            return_value=_fake_proc(stdout=json.dumps(payload)),
        ):
            result = await tool.execute(path=str(tmp_path))

        assert result.success
        assert result.output == "No issues found."
        assert result.caption == "clean"

    @pytest.mark.asyncio
    async def test_reports_diagnostics(self, tool: CharmlintTool, tmp_path: pathlib.Path) -> None:
        """Diagnostic summary includes counts for each severity."""
        payload = {
            "diagnostics": [
                {
                    "rule_id": "SECURITY-001",
                    "message": "secret in plain config",
                    "path": "charmcraft.yaml",
                    "line": 3,
                },
                {"rule_id": "TESTING-001", "message": "no unit tests", "path": "tests/unit/"},
            ],
            "total": 2,
            "errors": 1,
            "warnings": 1,
            "info": 0,
        }

        with mock.patch(
            "cantrip.agent.tools.charmlint_tool.subprocess.run",
            return_value=_fake_proc(returncode=1, stdout=json.dumps(payload)),
        ):
            result = await tool.execute(path=str(tmp_path))

        assert result.success
        assert "charmcraft.yaml:3: SECURITY-001 secret in plain config" in result.output
        assert "Found 2 issues (1 error, 1 warning)" in result.output
        assert result.caption == "1 error, 1 warning"

    @pytest.mark.asyncio
    async def test_forwards_filters(self, tool: CharmlintTool, tmp_path: pathlib.Path) -> None:
        """Filters are forwarded as charmlint CLI flags."""
        payload = {"diagnostics": [], "total": 0, "errors": 0, "warnings": 0, "info": 0}
        with mock.patch(
            "cantrip.agent.tools.charmlint_tool.subprocess.run",
            return_value=_fake_proc(stdout=json.dumps(payload)),
        ) as run:
            await tool.execute(
                path=str(tmp_path),
                select="METADATA",
                ignore="STRUCTURE-002",
                severity="error",
            )

        cmd = run.call_args[0][0]
        assert cmd[cmd.index("--select") + 1] == "METADATA"
        assert cmd[cmd.index("--ignore") + 1] == "STRUCTURE-002"
        assert cmd[cmd.index("--min-severity") + 1] == "error"

    @pytest.mark.asyncio
    async def test_timeout_returns_error(
        self, tool: CharmlintTool, tmp_path: pathlib.Path
    ) -> None:
        with mock.patch(
            "cantrip.agent.tools.charmlint_tool.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="charmlint", timeout=30),
        ):
            result = await tool.execute(path=str(tmp_path))

        assert not result.success
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_os_error_returns_error(
        self, tool: CharmlintTool, tmp_path: pathlib.Path
    ) -> None:
        with mock.patch(
            "cantrip.agent.tools.charmlint_tool.subprocess.run",
            side_effect=FileNotFoundError("python"),
        ):
            result = await tool.execute(path=str(tmp_path))

        assert not result.success
        assert "could not be run" in result.error

    @pytest.mark.asyncio
    async def test_unknown_selector_returns_error(
        self, tool: CharmlintTool, tmp_path: pathlib.Path
    ) -> None:
        """charmlint's usage error reaches the model so it can retry."""
        with mock.patch(
            "cantrip.agent.tools.charmlint_tool.subprocess.run",
            return_value=_fake_proc(
                returncode=2, stderr="error: not a known rule ID, rule name or category: COS"
            ),
        ):
            result = await tool.execute(path=str(tmp_path), select="COS")

        assert not result.success
        assert "COS" in result.error

    @pytest.mark.asyncio
    async def test_runs_real_charmlint(self, tool: CharmlintTool, tmp_path: pathlib.Path) -> None:
        """End to end against the installed charmlint package."""
        (tmp_path / "charmcraft.yaml").write_text(
            "name: demo\nconfig:\n  options:\n    admin-password:\n      type: string\n"
        )

        result = await tool.execute(path=str(tmp_path), select="SECURITY")

        assert result.success
        assert "SECURITY-001" in result.output
        assert result.data["errors"] == 1


# ---------------------------------------------------------------------------
# Phase 95.3 — Charmcraft MCP second-opinion integration
# ---------------------------------------------------------------------------


class _FakeMCPClient:
    """In-test stand-in for :class:`MCPClient` exposing only the
    surface :class:`CharmlintTool` exercises: a ``tools`` list and an
    awaitable ``call_tool``.
    """

    def __init__(
        self,
        *,
        tools: list[str],
        responses: dict[str, str] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.tools = [SimpleNamespace(name=name) for name in tools]
        self._responses = responses or {}
        self._errors = errors or {}
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
        self.calls.append((name, arguments))
        if name in self._errors:
            raise self._errors[name]
        return SimpleNamespace(text=self._responses.get(name, ""))


class _FakeRegistry:
    def __init__(self, clients: dict[str, _FakeMCPClient]) -> None:
        self._clients = clients

    def get_client(self, name: str) -> _FakeMCPClient | None:
        return self._clients.get(name)


class TestCharmcraftMCPSecondOpinion:
    """Phase 95.3 — second-opinion enrichment from the charmcraft MCP server."""

    @pytest.fixture(autouse=True)
    def clean_lint(self) -> Iterator[None]:
        with mock.patch(
            "cantrip.agent.tools.charmlint_tool.subprocess.run",
            return_value=_fake_proc(stdout=_CLEAN_REPORT),
        ):
            yield

    @pytest.mark.asyncio
    async def test_no_registry_falls_back_to_local_only(self, tmp_path: pathlib.Path) -> None:
        tool = CharmlintTool(mcp_registry=None)
        result = await tool.execute(path=str(tmp_path))
        assert result.success
        assert "Second opinion" not in result.output
        assert "mcp_second_opinion" not in result.data

    @pytest.mark.asyncio
    async def test_no_charmcraft_server_falls_back_to_local_only(
        self, tmp_path: pathlib.Path
    ) -> None:
        registry = _FakeRegistry({})  # no charmcraft server registered
        tool = CharmlintTool(mcp_registry=registry)
        result = await tool.execute(path=str(tmp_path))
        assert "Second opinion" not in result.output
        assert "mcp_second_opinion" not in result.data

    @pytest.mark.asyncio
    async def test_appends_second_opinion_when_server_responds(
        self, tmp_path: pathlib.Path
    ) -> None:
        client = _FakeMCPClient(
            tools=["lint", "analyse"],
            responses={
                "lint": "Charmcraft lint: 1 warning (MD001 missing description).",
                "analyse": "Charmcraft analyse: clean, no recommendations.",
            },
        )
        registry = _FakeRegistry({"charmcraft": client})
        tool = CharmlintTool(mcp_registry=registry)
        result = await tool.execute(path=str(tmp_path))
        assert result.success
        assert "No issues found." in result.output
        assert "Second opinion (mcp__charmcraft)" in result.output
        assert "[lint]" in result.output
        assert "MD001 missing description" in result.output
        assert "[analyse]" in result.output
        assert "clean, no recommendations" in result.output
        # Both MCP tools were probed with the resolved charm path.
        assert [name for name, _ in client.calls] == ["lint", "analyse"]
        assert all(args == {"path": str(tmp_path.resolve())} for _, args in client.calls)
        # Structured data preserves the per-tool sections.
        second_opinion = result.data["mcp_second_opinion"]
        assert second_opinion["server"] == "charmcraft"
        assert {s["tool"] for s in second_opinion["sections"]} == {"lint", "analyse"}

    @pytest.mark.asyncio
    async def test_skips_tools_not_advertised_by_server(self, tmp_path: pathlib.Path) -> None:
        """If the server only advertises ``lint``, ``analyse`` is skipped silently."""
        client = _FakeMCPClient(
            tools=["lint"],  # no ``analyse``
            responses={"lint": "Charmcraft lint: clean."},
        )
        registry = _FakeRegistry({"charmcraft": client})
        tool = CharmlintTool(mcp_registry=registry)
        result = await tool.execute(path=str(tmp_path))
        assert "[lint]" in result.output
        assert "[analyse]" not in result.output
        assert [name for name, _ in client.calls] == ["lint"]

    @pytest.mark.asyncio
    async def test_records_error_section_when_call_raises(self, tmp_path: pathlib.Path) -> None:
        """An MCP-side exception surfaces inline and does not break local lint."""
        from cantrip.mcp.exceptions import MCPInvocationError

        client = _FakeMCPClient(
            tools=["lint", "analyse"],
            responses={"analyse": "all good"},
            errors={"lint": MCPInvocationError("server refused")},
        )
        registry = _FakeRegistry({"charmcraft": client})
        tool = CharmlintTool(mcp_registry=registry)
        result = await tool.execute(path=str(tmp_path))
        assert result.success
        assert "[lint] failed: server refused" in result.output
        assert "[analyse]" in result.output

    @pytest.mark.asyncio
    async def test_local_failure_skips_second_opinion(self, tmp_path: pathlib.Path) -> None:
        """A failed local lint short-circuits before the MCP call.

        We never want a missing-path error to grow a confusing
        "second opinion (empty)" block.
        """
        client = _FakeMCPClient(tools=["lint"], responses={"lint": "should not appear"})
        registry = _FakeRegistry({"charmcraft": client})
        tool = CharmlintTool(mcp_registry=registry)
        result = await tool.execute(path=str(tmp_path / "missing"))
        assert not result.success
        assert client.calls == []
        assert "Second opinion" not in (result.output or "")
