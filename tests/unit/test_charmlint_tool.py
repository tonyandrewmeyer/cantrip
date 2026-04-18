"""Tests for the charmlint agent-tool wrapper."""

import json
import subprocess
from pathlib import Path
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
    def test_prefers_path_binary(self, tmp_path: Path) -> None:
        with mock.patch(
            "cantrip.agent.tools.charmlint_tool.shutil.which",
            return_value="/usr/bin/charmlint-rs",
        ):
            assert CharmlintTool._find_rust_binary() == "/usr/bin/charmlint-rs"

    def test_falls_back_to_in_tree_build(self, tmp_path: Path) -> None:
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

    def test_returns_none_when_nothing_found(self, tmp_path: Path) -> None:
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
    async def test_path_not_found(self, tool: CharmlintTool, tmp_path: Path) -> None:
        result = await tool.execute(path=str(tmp_path / "missing"))
        assert not result.success
        assert "path not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_rust_backend_clean_report(self, tool: CharmlintTool, tmp_path: Path) -> None:
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
        self, tool: CharmlintTool, tmp_path: Path
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
        self, tool: CharmlintTool, tmp_path: Path
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
        self, tool: CharmlintTool, tmp_path: Path
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
        self, tool: CharmlintTool, tmp_path: Path
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
        self, tool: CharmlintTool, tmp_path: Path
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
    async def test_python_backend_passes_config(self, tool: CharmlintTool, tmp_path: Path) -> None:
        """Python backend renders each diagnostic plus summary line."""
        diag = SimpleNamespace(format_text=lambda _root: "charmcraft.yaml:1:1 COS001 missing")
        fake_report = SimpleNamespace(
            diagnostics=[diag],
            summary_line=lambda: "Found 1 issue (1 error)",
            to_dict=lambda: {"diagnostics": [{"rule_id": "COS001"}], "total": 1},
        )

        captured: dict[str, object] = {}

        def _fake_lint(root: Path, config: object) -> SimpleNamespace:
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
    async def test_python_backend_clean_report(self, tool: CharmlintTool, tmp_path: Path) -> None:
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
