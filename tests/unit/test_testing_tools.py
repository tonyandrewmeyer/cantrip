"""Tests for the charm test runner and test template generation tools."""

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from cantrip.agent.tools.testing import (
    GenerateTestsTool,
    RunCharmTestsTool,
    _build_pytest_target,
    _parse_coverage_total,
    _parse_pytest_summary,
    _truncate_output,
    generate_integration_tests,
)


class TestParsePytestSummary:
    """Tests for _parse_pytest_summary helper."""

    def test_all_passed(self):
        output = "============================= 5 passed in 0.12s =============================="
        assert _parse_pytest_summary(output) == {"passed": 5}

    def test_mixed_results(self):
        output = "=================== 3 passed, 2 failed, 1 skipped in 1.5s ==================="
        result = _parse_pytest_summary(output)
        assert result == {"passed": 3, "failed": 2, "skipped": 1}

    def test_with_errors(self):
        output = "================== 1 passed, 1 failed, 2 error in 0.8s ==================="
        result = _parse_pytest_summary(output)
        assert result == {"passed": 1, "failed": 1, "error": 2}

    def test_no_summary_line(self):
        output = "Some random output\nwith no pytest summary"
        assert _parse_pytest_summary(output) == {}

    def test_only_failed(self):
        output = "============================= 3 failed in 0.5s =============================="
        assert _parse_pytest_summary(output) == {"failed": 3}

    def test_multiline_output_finds_last_summary(self):
        output = (
            "tests/unit/test_charm.py::test_install PASSED\n"
            "tests/unit/test_charm.py::test_start FAILED\n"
            "============================= 1 passed, 1 failed in 0.3s =============================="
        )
        result = _parse_pytest_summary(output)
        assert result == {"passed": 1, "failed": 1}


class TestTruncateOutput:
    """Tests for _truncate_output helper."""

    def test_short_output_unchanged(self):
        output = "short output"
        assert _truncate_output(output) == output

    def test_long_output_truncated(self):
        # Build output that exceeds the 5000 char threshold.
        lines = [f"line {i}" for i in range(1000)]
        output = "\n".join(lines)
        result = _truncate_output(output)
        assert result.startswith("[...truncated")
        assert "line 999" in result
        # Should contain at most 200 lines of actual content.
        content_lines = result.splitlines()[1:]  # Skip the truncation header.
        assert len(content_lines) == 200


class TestRunCharmTestsTool:
    """Tests for RunCharmTestsTool."""

    def test_tool_metadata(self):
        tool = RunCharmTestsTool()
        assert tool.name == "run_charm_tests"
        assert "unit" in tool.description
        assert "integration" in tool.description
        params = tool.parameters
        assert "test_type" in params["properties"]
        assert params["properties"]["test_type"]["enum"] == ["unit", "integration"]

    @pytest.mark.asyncio
    async def test_path_not_found(self, tmp_path):
        tool = RunCharmTestsTool()
        result = await tool.execute(path=str(tmp_path / "nonexistent"))
        assert not result.success
        assert result.error is not None
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_tox_success(self, tmp_path):
        """Tox is used when tox.ini exists and tox is on PATH."""
        (tmp_path / "tox.ini").write_text("[tox]\n")

        fake_result = type(
            "CompletedProcess",
            (),
            {"returncode": 0, "stdout": "=== 3 passed in 0.1s ===", "stderr": ""},
        )()

        with (
            patch("cantrip.agent.tools.testing.shutil.which", return_value="/usr/bin/tox"),
            patch(
                "cantrip.agent.tools.testing.subprocess.run", return_value=fake_result
            ) as mock_run,
        ):
            tool = RunCharmTestsTool()
            result = await tool.execute(path=str(tmp_path), test_type="unit")

        assert result.success
        assert result.data["runner"] == "tox"
        assert result.data["summary"] == {"passed": 3}
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["tox", "-e", "unit"]

    @pytest.mark.asyncio
    async def test_tox_failure(self, tmp_path):
        """Non-zero exit from tox is reported as failure."""
        (tmp_path / "tox.ini").write_text("[tox]\n")

        fake_result = type(
            "CompletedProcess",
            (),
            {
                "returncode": 1,
                "stdout": "=== 1 passed, 2 failed in 0.5s ===",
                "stderr": "",
            },
        )()

        with (
            patch("cantrip.agent.tools.testing.shutil.which", return_value="/usr/bin/tox"),
            patch("cantrip.agent.tools.testing.subprocess.run", return_value=fake_result),
        ):
            tool = RunCharmTestsTool()
            result = await tool.execute(path=str(tmp_path))

        assert not result.success
        assert result.error is not None
        assert "exit code 1" in result.error
        assert result.data["summary"]["failed"] == 2

    @pytest.mark.asyncio
    async def test_pytest_fallback_no_tox(self, tmp_path):
        """Falls back to pytest when tox.ini is absent."""
        test_dir = tmp_path / "tests" / "unit"
        test_dir.mkdir(parents=True)

        fake_result = type(
            "CompletedProcess",
            (),
            {"returncode": 0, "stdout": "=== 2 passed in 0.1s ===", "stderr": ""},
        )()

        def which_side_effect(cmd):
            if cmd == "tox":
                return None
            return f"/usr/bin/{cmd}"

        with (
            patch("cantrip.agent.tools.testing.shutil.which", side_effect=which_side_effect),
            patch(
                "cantrip.agent.tools.testing.subprocess.run", return_value=fake_result
            ) as mock_run,
        ):
            tool = RunCharmTestsTool()
            result = await tool.execute(path=str(tmp_path), test_type="unit")

        assert result.success
        assert result.data["runner"] == "pytest"
        cmd = mock_run.call_args[0][0]
        assert "pytest" in cmd[2]

    @pytest.mark.asyncio
    async def test_test_dir_not_found(self, tmp_path):
        """Reports error when test directory does not exist (pytest fallback)."""

        def which_side_effect(cmd):
            if cmd == "tox":
                return None
            return f"/usr/bin/{cmd}"

        with patch("cantrip.agent.tools.testing.shutil.which", side_effect=which_side_effect):
            tool = RunCharmTestsTool()
            result = await tool.execute(path=str(tmp_path), test_type="unit")

        assert not result.success
        assert result.error is not None
        assert "Test directory not found" in result.error

    @pytest.mark.asyncio
    async def test_timeout(self, tmp_path):
        """Reports error when tests time out."""
        import subprocess

        (tmp_path / "tox.ini").write_text("[tox]\n")

        with (
            patch("cantrip.agent.tools.testing.shutil.which", return_value="/usr/bin/tox"),
            patch(
                "cantrip.agent.tools.testing.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="tox", timeout=120),
            ),
        ):
            tool = RunCharmTestsTool()
            result = await tool.execute(path=str(tmp_path))

        assert not result.success
        assert result.error is not None
        assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_no_runner_available(self, tmp_path):
        """Reports error when neither tox nor python is available."""
        with patch("cantrip.agent.tools.testing.shutil.which", return_value=None):
            tool = RunCharmTestsTool()
            result = await tool.execute(path=str(tmp_path))

        assert not result.success
        assert result.error is not None
        assert "Neither tox nor python" in result.error

    @pytest.mark.asyncio
    async def test_output_truncation(self, tmp_path):
        """Long output is truncated to the last 200 lines."""
        (tmp_path / "tox.ini").write_text("[tox]\n")

        long_stdout = "\n".join(f"line {i}" for i in range(1000))
        long_stdout += "\n=== 500 passed in 10.0s ==="

        fake_result = type(
            "CompletedProcess",
            (),
            {"returncode": 0, "stdout": long_stdout, "stderr": ""},
        )()

        with (
            patch("cantrip.agent.tools.testing.shutil.which", return_value="/usr/bin/tox"),
            patch("cantrip.agent.tools.testing.subprocess.run", return_value=fake_result),
        ):
            tool = RunCharmTestsTool()
            result = await tool.execute(path=str(tmp_path))

        assert result.success
        assert "[...truncated" in result.output
        assert result.data["summary"] == {"passed": 500}

    @pytest.mark.asyncio
    async def test_integration_timeout_is_longer(self, tmp_path):
        """Integration tests use the 900s timeout."""
        (tmp_path / "tox.ini").write_text("[tox]\n")

        fake_result = type(
            "CompletedProcess",
            (),
            {"returncode": 0, "stdout": "=== 1 passed in 5.0s ===", "stderr": ""},
        )()

        with (
            patch("cantrip.agent.tools.testing.shutil.which", return_value="/usr/bin/tox"),
            patch(
                "cantrip.agent.tools.testing.subprocess.run", return_value=fake_result
            ) as mock_run,
        ):
            tool = RunCharmTestsTool()
            await tool.execute(path=str(tmp_path), test_type="integration")

        # Check the timeout kwarg.
        assert mock_run.call_args[1]["timeout"] == 900


# ===================================================================
# TestGenerateIntegrationTests
# ===================================================================

_SAMPLE_METADATA: dict[str, Any] = {
    "name": "my-app",
    "config": {
        "options": {
            "port": {"type": "int", "default": 8080, "description": "Listen port"},
            "debug": {"type": "boolean", "default": False},
        },
    },
    "actions": {
        "backup": {"description": "Create a backup"},
        "restore": {"description": "Restore from backup"},
    },
    "requires": {
        "db": {"interface": "pgsql"},
    },
    "provides": {
        "metrics-endpoint": {"interface": "prometheus_scrape"},
    },
}


class TestGenerateIntegrationTests:
    """Tests for generate_integration_tests — pure function."""

    def test_produces_conftest(self) -> None:
        files = generate_integration_tests("my-app", _SAMPLE_METADATA)
        assert "tests/integration/conftest.py" in files
        conftest = files["tests/integration/conftest.py"]
        assert "jubilant" in conftest
        assert "my-app-test" in conftest

    def test_produces_deploy_test(self) -> None:
        files = generate_integration_tests("my-app", _SAMPLE_METADATA)
        assert "tests/integration/test_deploy.py" in files
        deploy = files["tests/integration/test_deploy.py"]
        assert "def test_deploy" in deploy
        assert "my-app" in deploy

    def test_produces_relation_tests(self) -> None:
        files = generate_integration_tests("my-app", _SAMPLE_METADATA)
        assert "tests/integration/test_relations.py" in files
        rels = files["tests/integration/test_relations.py"]
        assert "test_relate_db" in rels
        assert "test_provide_metrics_endpoint" in rels

    def test_no_relations_file_when_empty(self) -> None:
        files = generate_integration_tests("simple", {"name": "simple"})
        assert "tests/integration/test_relations.py" not in files

    def test_produces_action_tests(self) -> None:
        files = generate_integration_tests("my-app", _SAMPLE_METADATA)
        assert "tests/integration/test_actions.py" in files
        actions = files["tests/integration/test_actions.py"]
        assert "test_action_backup" in actions
        assert "test_action_restore" in actions

    def test_no_actions_file_when_empty(self) -> None:
        files = generate_integration_tests("simple", {"name": "simple"})
        assert "tests/integration/test_actions.py" not in files

    def test_produces_config_tests(self) -> None:
        files = generate_integration_tests("my-app", _SAMPLE_METADATA)
        assert "tests/integration/test_config.py" in files
        cfg = files["tests/integration/test_config.py"]
        assert "test_config_port" in cfg
        assert "test_config_debug" in cfg

    def test_no_config_file_when_empty(self) -> None:
        files = generate_integration_tests("simple", {"name": "simple"})
        assert "tests/integration/test_config.py" not in files

    def test_config_test_uses_boolean_value(self) -> None:
        """Boolean config options get 'true' as a test value."""
        meta: dict[str, Any] = {
            "config": {"options": {"debug": {"type": "boolean"}}},
        }
        files = generate_integration_tests("x", meta)
        assert '"true"' in files["tests/integration/test_config.py"]

    def test_config_test_uses_int_value(self) -> None:
        """Integer config options get '42' as a test value."""
        meta: dict[str, Any] = {
            "config": {"options": {"port": {"type": "int"}}},
        }
        files = generate_integration_tests("x", meta)
        assert '"42"' in files["tests/integration/test_config.py"]

    def test_minimal_metadata_produces_two_files(self) -> None:
        """With no relations/actions/config, only conftest + deploy test."""
        files = generate_integration_tests("bare", {})
        assert len(files) == 2
        assert "tests/integration/conftest.py" in files
        assert "tests/integration/test_deploy.py" in files

    def test_action_test_uses_run_action(self) -> None:
        files = generate_integration_tests("my-app", _SAMPLE_METADATA)
        assert "run_action" in files["tests/integration/test_actions.py"]

    def test_deploy_test_uses_wait(self) -> None:
        files = generate_integration_tests("my-app", _SAMPLE_METADATA)
        assert "juju.wait" in files["tests/integration/test_deploy.py"]


# ===================================================================
# TestGenerateTestsTool
# ===================================================================


class TestGenerateTestsTool:
    """Tests for GenerateTestsTool."""

    @pytest.fixture
    def tool(self):
        return GenerateTestsTool()

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.mark.asyncio
    async def test_generates_test_files(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text(
            "name: my-charm\nactions:\n  backup:\n    description: backup data\n"
        )

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert (temp_dir / "tests" / "integration" / "conftest.py").exists()
        assert (temp_dir / "tests" / "integration" / "test_deploy.py").exists()
        assert (temp_dir / "tests" / "integration" / "test_actions.py").exists()
        assert result.data["test_count"] >= 2

    @pytest.mark.asyncio
    async def test_reads_name_from_yaml(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text("name: redis-k8s\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["charm_name"] == "redis-k8s"

    @pytest.mark.asyncio
    async def test_explicit_name_overrides(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text("name: redis-k8s\n")

        result = await tool.execute(path=str(temp_dir), charm_name="custom")

        assert result.data["charm_name"] == "custom"

    @pytest.mark.asyncio
    async def test_missing_charmcraft_yaml(self, tool, temp_dir) -> None:
        result = await tool.execute(path=str(temp_dir))

        assert not result.success
        assert "charmcraft.yaml" in result.error

    @pytest.mark.asyncio
    async def test_nonexistent_directory(self, tool) -> None:
        result = await tool.execute(path="/nonexistent/path")

        assert not result.success
        assert "not found" in result.error.lower()


# ===================================================================
# TestBuildPytestTarget
# ===================================================================


class TestBuildPytestTarget:
    """Tests for _build_pytest_target — selective test execution."""

    @pytest.fixture
    def test_dir(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "tests" / "integration"
            d.mkdir(parents=True)
            (d / "test_deploy.py").write_text("def test_deploy(): pass\n")
            (d / "test_relations.py").write_text("def test_db(): pass\n")
            yield d

    def test_no_pattern_returns_whole_directory(self, test_dir):
        result = _build_pytest_target(test_dir, None)
        assert result == [str(test_dir) + "/"]

    def test_file_name_match(self, test_dir):
        """Plain name matching an existing file resolves to that file."""
        result = _build_pytest_target(test_dir, "test_deploy")
        assert result == [str(test_dir / "test_deploy.py")]

    def test_file_function_form(self, test_dir):
        """file::function form resolves to pytest node ID."""
        result = _build_pytest_target(test_dir, "test_deploy::test_smoke")
        assert result == [f"{test_dir / 'test_deploy.py'}::test_smoke"]

    def test_file_function_nonexistent_file_falls_back_to_k(self, test_dir):
        """file::function with a missing file falls back to -k."""
        result = _build_pytest_target(test_dir, "missing::test_foo")
        assert result == [str(test_dir) + "/", "-k", "test_foo"]

    def test_k_expression_with_or(self, test_dir):
        """Boolean expressions with 'or' are passed to -k."""
        result = _build_pytest_target(test_dir, "deploy or relation")
        assert result == [str(test_dir) + "/", "-k", "deploy or relation"]

    def test_k_expression_with_spaces(self, test_dir):
        """Expressions with spaces are passed to -k."""
        result = _build_pytest_target(test_dir, "test deploy")
        assert result == [str(test_dir) + "/", "-k", "test deploy"]

    def test_unknown_name_falls_back_to_k(self, test_dir):
        """A name that doesn't match any file falls back to -k."""
        result = _build_pytest_target(test_dir, "test_nonexistent")
        assert result == [str(test_dir) + "/", "-k", "test_nonexistent"]

    def test_file_name_with_py_suffix(self, test_dir):
        """Handles .py suffix in file::function form gracefully."""
        result = _build_pytest_target(test_dir, "test_deploy.py::test_smoke")
        assert result == [f"{test_dir / 'test_deploy.py'}::test_smoke"]


# ===================================================================
# TestParseCoverageTotal
# ===================================================================


class TestParseCoverageTotal:
    """Tests for _parse_coverage_total — coverage percentage extraction."""

    def test_typical_coverage_report(self):
        output = (
            "Name             Stmts   Miss  Cover\n"
            "------------------------------------\n"
            "src/charm.py        50      5    90%\n"
            "TOTAL              100     10    90%\n"
        )
        assert _parse_coverage_total(output) == 90

    def test_zero_coverage(self):
        output = "TOTAL    100    100    0%\n"
        assert _parse_coverage_total(output) == 0

    def test_full_coverage(self):
        output = "TOTAL    100    0    100%\n"
        assert _parse_coverage_total(output) == 100

    def test_no_coverage_output(self):
        output = "=== 5 passed in 0.3s ===\n"
        assert _parse_coverage_total(output) is None

    def test_embedded_in_tox_output(self):
        """Coverage line buried in larger tox output is still found."""
        output = (
            "unit: commands[0]> coverage run ...\n"
            "========= 10 passed in 1.2s =========\n"
            "unit: commands[1]> coverage report\n"
            "Name             Stmts   Miss  Cover\n"
            "------------------------------------\n"
            "src/charm.py        80      4    95%\n"
            "TOTAL              200     10    95%\n"
            "unit: OK\n"
        )
        assert _parse_coverage_total(output) == 95
