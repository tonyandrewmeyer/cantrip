"""Tests for the charmlint agent-tool wrapper."""

import json
import pathlib
import subprocess
from types import SimpleNamespace
from unittest import mock

import pytest

from cantrip.agent.tools.charmlint_tool import CharmlintTool


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


class TestFindRustBinary:
    def test_prefers_path_binary(self, tmp_path: pathlib.Path) -> None:
        with mock.patch(
            "cantrip.agent.tools.charmlint_tool.shutil.which",
            return_value="/usr/bin/charmlint-rs",
        ):
            assert CharmlintTool._find_rust_binary() == "/usr/bin/charmlint-rs"

    def test_falls_back_to_in_tree_build(self, tmp_path: pathlib.Path) -> None:
        """In-tree target/release/charmlint is used when PATH has nothing."""
        # Build a fake package structure with the expected layout.
        pkg_dir = tmp_path / "site-packages" / "cantrip"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")
        tree_root = tmp_path / "site-packages"
        # charmlint-rs/target/release/charmlint sits at pkg_dir.parent.parent
        rust_dir = tree_root.parent / "charmlint-rs" / "target" / "release"
        rust_dir.mkdir(parents=True)
        rust_bin = rust_dir / "charmlint"
        rust_bin.write_text("stub")

        fake_cantrip = SimpleNamespace(__file__=str(pkg_dir / "__init__.py"))
        with (
            mock.patch("cantrip.agent.tools.charmlint_tool.shutil.which", return_value=None),
            mock.patch.dict("sys.modules", {"cantrip": fake_cantrip}),
        ):
            assert CharmlintTool._find_rust_binary() == str(rust_bin)

    def test_returns_none_when_nothing_found(self, tmp_path: pathlib.Path) -> None:
        pkg_dir = tmp_path / "pkg" / "cantrip"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")
        fake_cantrip = SimpleNamespace(__file__=str(pkg_dir / "__init__.py"))
        with (
            mock.patch("cantrip.agent.tools.charmlint_tool.shutil.which", return_value=None),
            mock.patch.dict("sys.modules", {"cantrip": fake_cantrip}),
        ):
            assert CharmlintTool._find_rust_binary() is None


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
    async def test_rust_backend_clean_report(
        self, tool: CharmlintTool, tmp_path: pathlib.Path
    ) -> None:
        """Rust binary returns zero-diagnostic JSON → 'No issues found'."""
        payload = {"diagnostics": [], "total": 0, "errors": 0, "warnings": 0, "info": 0}
        with (
            mock.patch.object(
                CharmlintTool, "_find_rust_binary", return_value="/usr/bin/charmlint-rs"
            ),
            mock.patch(
                "cantrip.agent.tools.charmlint_tool.subprocess.run",
                return_value=_fake_proc(stdout=json.dumps(payload)),
            ),
        ):
            result = await tool.execute(path=str(tmp_path))

        assert result.success
        assert "No issues found" in result.output
        assert result.data["backend"] == "rust"

    @pytest.mark.asyncio
    async def test_rust_backend_reports_diagnostics(
        self, tool: CharmlintTool, tmp_path: pathlib.Path
    ) -> None:
        """Diagnostic summary includes counts for each severity."""
        payload = {
            "diagnostics": [
                {
                    "rule_id": "COS001",
                    "message": "missing COS integration",
                    "path": "charmcraft.yaml",
                    "line": 3,
                },
                {"rule_id": "TEST001", "message": "no Scenario tests", "path": "tests"},
            ],
            "total": 2,
            "errors": 1,
            "warnings": 1,
            "info": 0,
        }

        with (
            mock.patch.object(
                CharmlintTool, "_find_rust_binary", return_value="/usr/bin/charmlint-rs"
            ),
            mock.patch(
                "cantrip.agent.tools.charmlint_tool.subprocess.run",
                return_value=_fake_proc(stdout=json.dumps(payload)),
            ),
        ):
            result = await tool.execute(
                path=str(tmp_path), select="COS,TEST", ignore="STR", severity="warning"
            )

        assert result.success
        assert "COS001" in result.output
        assert "charmcraft.yaml:3" in result.output
        assert "Found 2 issues" in result.output
        assert "1 error" in result.output
        assert "1 warning" in result.output

    @pytest.mark.asyncio
    async def test_rust_backend_forwards_filters(
        self, tool: CharmlintTool, tmp_path: pathlib.Path
    ) -> None:
        """CLI flags are forwarded to the Rust binary."""
        payload = {"diagnostics": [], "total": 0, "errors": 0, "warnings": 0, "info": 0}
        with (
            mock.patch.object(
                CharmlintTool, "_find_rust_binary", return_value="/usr/bin/charmlint-rs"
            ),
            mock.patch(
                "cantrip.agent.tools.charmlint_tool.subprocess.run",
                return_value=_fake_proc(stdout=json.dumps(payload)),
            ) as run,
        ):
            await tool.execute(
                path=str(tmp_path),
                select="COS",
                ignore="STR002",
                severity="error",
            )

        cmd = run.call_args[0][0]
        assert cmd[0] == "/usr/bin/charmlint-rs"
        assert "--select" in cmd and cmd[cmd.index("--select") + 1] == "COS"
        assert "--ignore" in cmd and cmd[cmd.index("--ignore") + 1] == "STR002"
        assert "--severity" in cmd and cmd[cmd.index("--severity") + 1] == "error"

    @pytest.mark.asyncio
    async def test_rust_backend_timeout_returns_error(
        self, tool: CharmlintTool, tmp_path: pathlib.Path
    ) -> None:
        with (
            mock.patch.object(
                CharmlintTool, "_find_rust_binary", return_value="/usr/bin/charmlint-rs"
            ),
            mock.patch(
                "cantrip.agent.tools.charmlint_tool.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="charmlint-rs", timeout=30),
            ),
        ):
            result = await tool.execute(path=str(tmp_path))

        assert not result.success
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_rust_backend_file_not_found_falls_back(
        self, tool: CharmlintTool, tmp_path: pathlib.Path
    ) -> None:
        """If the Rust binary disappears mid-run, fall back to Python."""
        fake_report = SimpleNamespace(
            diagnostics=[],
            summary_line=lambda: "No issues found.",
            to_dict=lambda: {"diagnostics": [], "total": 0},
        )

        with (
            mock.patch.object(
                CharmlintTool, "_find_rust_binary", return_value="/usr/bin/charmlint-rs"
            ),
            mock.patch(
                "cantrip.agent.tools.charmlint_tool.subprocess.run",
                side_effect=FileNotFoundError,
            ),
            mock.patch("charmlint.lint", return_value=fake_report),
        ):
            result = await tool.execute(path=str(tmp_path))

        assert result.success
        assert result.data["backend"] == "python"

    @pytest.mark.asyncio
    async def test_rust_backend_bad_json_falls_back(
        self, tool: CharmlintTool, tmp_path: pathlib.Path
    ) -> None:
        fake_report = SimpleNamespace(
            diagnostics=[],
            summary_line=lambda: "No issues found.",
            to_dict=lambda: {"diagnostics": [], "total": 0},
        )

        with (
            mock.patch.object(
                CharmlintTool, "_find_rust_binary", return_value="/usr/bin/charmlint-rs"
            ),
            mock.patch(
                "cantrip.agent.tools.charmlint_tool.subprocess.run",
                return_value=_fake_proc(stdout="not json at all"),
            ),
            mock.patch("charmlint.lint", return_value=fake_report),
        ):
            result = await tool.execute(path=str(tmp_path))

        assert result.success
        assert result.data["backend"] == "python"

    @pytest.mark.asyncio
    async def test_python_backend_passes_config(
        self, tool: CharmlintTool, tmp_path: pathlib.Path
    ) -> None:
        """Python backend renders each diagnostic plus summary line."""
        diag = SimpleNamespace(format_text=lambda _root: "charmcraft.yaml:1:1 COS001 missing")
        fake_report = SimpleNamespace(
            diagnostics=[diag],
            summary_line=lambda: "Found 1 issue (1 error)",
            to_dict=lambda: {"diagnostics": [{"rule_id": "COS001"}], "total": 1},
        )

        captured: dict[str, object] = {}

        def _fake_lint(root: pathlib.Path, config: object) -> SimpleNamespace:
            captured["root"] = root
            captured["select"] = list(config.select)
            captured["ignore"] = list(config.ignore)
            captured["min_severity"] = getattr(config, "min_severity", None)
            return fake_report

        with (
            mock.patch.object(CharmlintTool, "_find_rust_binary", return_value=None),
            mock.patch("charmlint.lint", side_effect=_fake_lint),
        ):
            result = await tool.execute(
                path=str(tmp_path), select="COS,TEST", ignore="STR002", severity="warning"
            )

        assert result.success
        assert "COS001" in result.output
        assert "Found 1 issue (1 error)" in result.output
        assert captured["select"] == ["COS", "TEST"]
        assert captured["ignore"] == ["STR002"]
        assert captured["min_severity"] is not None
        assert result.data["backend"] == "python"

    @pytest.mark.asyncio
    async def test_python_backend_clean_report(
        self, tool: CharmlintTool, tmp_path: pathlib.Path
    ) -> None:
        """Empty diagnostics → no blank separator inserted."""
        fake_report = SimpleNamespace(
            diagnostics=[],
            summary_line=lambda: "No issues found.",
            to_dict=lambda: {"diagnostics": [], "total": 0},
        )

        with (
            mock.patch.object(CharmlintTool, "_find_rust_binary", return_value=None),
            mock.patch("charmlint.lint", return_value=fake_report),
        ):
            result = await tool.execute(path=str(tmp_path))

        assert result.success
        assert result.output == "No issues found."


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

    @pytest.fixture
    def fake_report(self) -> SimpleNamespace:
        return SimpleNamespace(
            diagnostics=[],
            summary_line=lambda: "No issues found.",
            to_dict=lambda: {"diagnostics": [], "total": 0},
        )

    @pytest.mark.asyncio
    async def test_no_registry_falls_back_to_local_only(
        self, tmp_path: pathlib.Path, fake_report: SimpleNamespace
    ) -> None:
        tool = CharmlintTool(mcp_registry=None)
        with (
            mock.patch.object(CharmlintTool, "_find_rust_binary", return_value=None),
            mock.patch("charmlint.lint", return_value=fake_report),
        ):
            result = await tool.execute(path=str(tmp_path))
        assert result.success
        assert "Second opinion" not in result.output
        assert "mcp_second_opinion" not in result.data

    @pytest.mark.asyncio
    async def test_no_charmcraft_server_falls_back_to_local_only(
        self, tmp_path: pathlib.Path, fake_report: SimpleNamespace
    ) -> None:
        registry = _FakeRegistry({})  # no charmcraft server registered
        tool = CharmlintTool(mcp_registry=registry)
        with (
            mock.patch.object(CharmlintTool, "_find_rust_binary", return_value=None),
            mock.patch("charmlint.lint", return_value=fake_report),
        ):
            result = await tool.execute(path=str(tmp_path))
        assert "Second opinion" not in result.output
        assert "mcp_second_opinion" not in result.data

    @pytest.mark.asyncio
    async def test_appends_second_opinion_when_server_responds(
        self, tmp_path: pathlib.Path, fake_report: SimpleNamespace
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
        with (
            mock.patch.object(CharmlintTool, "_find_rust_binary", return_value=None),
            mock.patch("charmlint.lint", return_value=fake_report),
        ):
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
    async def test_skips_tools_not_advertised_by_server(
        self, tmp_path: pathlib.Path, fake_report: SimpleNamespace
    ) -> None:
        """If the server only advertises ``lint``, ``analyse`` is skipped silently."""
        client = _FakeMCPClient(
            tools=["lint"],  # no ``analyse``
            responses={"lint": "Charmcraft lint: clean."},
        )
        registry = _FakeRegistry({"charmcraft": client})
        tool = CharmlintTool(mcp_registry=registry)
        with (
            mock.patch.object(CharmlintTool, "_find_rust_binary", return_value=None),
            mock.patch("charmlint.lint", return_value=fake_report),
        ):
            result = await tool.execute(path=str(tmp_path))
        assert "[lint]" in result.output
        assert "[analyse]" not in result.output
        assert [name for name, _ in client.calls] == ["lint"]

    @pytest.mark.asyncio
    async def test_records_error_section_when_call_raises(
        self, tmp_path: pathlib.Path, fake_report: SimpleNamespace
    ) -> None:
        """An MCP-side exception surfaces inline and does not break local lint."""
        from cantrip.mcp.exceptions import MCPInvocationError

        client = _FakeMCPClient(
            tools=["lint", "analyse"],
            responses={"analyse": "all good"},
            errors={"lint": MCPInvocationError("server refused")},
        )
        registry = _FakeRegistry({"charmcraft": client})
        tool = CharmlintTool(mcp_registry=registry)
        with (
            mock.patch.object(CharmlintTool, "_find_rust_binary", return_value=None),
            mock.patch("charmlint.lint", return_value=fake_report),
        ):
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
