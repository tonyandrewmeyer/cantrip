"""Tests for load test generation tool."""

import tempfile
from pathlib import Path
from typing import Any

import pytest

from cantrip.agent.tools.loadtest import (
    GenerateLoadTestTool,
    _detect_http_port,
    generate_load_test,
)

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
    "containers": {
        "workload": {"resource": "oci-image"},
    },
}


# ===================================================================
# TestGenerateLoadTest
# ===================================================================


class TestGenerateLoadTest:
    """Tests for generate_load_test — pure function."""

    def test_produces_conftest(self) -> None:
        files = generate_load_test("my-app", _SAMPLE_METADATA)
        assert "tests/load/conftest.py" in files
        conftest = files["tests/load/conftest.py"]
        assert "jubilant" in conftest
        assert "my-app-load" in conftest

    def test_produces_test_load(self) -> None:
        files = generate_load_test("my-app", _SAMPLE_METADATA)
        assert "tests/load/test_load.py" in files

    def test_action_throughput_tests(self) -> None:
        files = generate_load_test("my-app", _SAMPLE_METADATA)
        test = files["tests/load/test_load.py"]
        assert "test_action_backup_throughput" in test
        assert "test_action_restore_throughput" in test
        assert "run_action" in test

    def test_config_settling_test(self) -> None:
        files = generate_load_test("my-app", _SAMPLE_METADATA)
        test = files["tests/load/test_load.py"]
        assert "test_config_change_settling_time" in test
        assert "juju.config" in test

    def test_scaling_test(self) -> None:
        files = generate_load_test("my-app", _SAMPLE_METADATA)
        test = files["tests/load/test_load.py"]
        assert "test_scale_up_settling_time" in test
        assert "juju.scale" in test

    def test_k6_script_for_web_charm(self) -> None:
        """Charms with an HTTP port get a k6 script."""
        files = generate_load_test("my-app", _SAMPLE_METADATA)
        assert "tests/load/k6_http.js" in files
        k6 = files["tests/load/k6_http.js"]
        assert "import http" in k6
        assert "8080" in k6

    def test_no_k6_without_port(self) -> None:
        """Charms without an HTTP port don't get a k6 script."""
        meta: dict[str, Any] = {"name": "simple"}
        files = generate_load_test("simple", meta)
        assert "tests/load/k6_http.js" not in files

    def test_no_actions_skips_action_tests(self) -> None:
        meta: dict[str, Any] = {"name": "simple"}
        files = generate_load_test("simple", meta)
        test = files["tests/load/test_load.py"]
        assert "test_action" not in test

    def test_no_config_skips_config_test(self) -> None:
        meta: dict[str, Any] = {"name": "simple"}
        files = generate_load_test("simple", meta)
        test = files["tests/load/test_load.py"]
        assert "test_config_change" not in test

    def test_scaling_always_present(self) -> None:
        """Scaling test is always generated regardless of metadata."""
        meta: dict[str, Any] = {"name": "simple"}
        files = generate_load_test("simple", meta)
        test = files["tests/load/test_load.py"]
        assert "test_scale_up" in test

    def test_boolean_config_values(self) -> None:
        meta: dict[str, Any] = {
            "config": {"options": {"debug": {"type": "boolean"}}},
        }
        files = generate_load_test("x", meta)
        test = files["tests/load/test_load.py"]
        assert "true" in test
        assert "false" in test

    def test_minimal_produces_two_files(self) -> None:
        """Minimal metadata produces conftest + test_load (no k6)."""
        files = generate_load_test("bare", {})
        assert len(files) == 2
        assert "tests/load/conftest.py" in files
        assert "tests/load/test_load.py" in files


class TestDetectHttpPort:
    """Tests for _detect_http_port."""

    def test_detects_port_from_config(self) -> None:
        config = {"port": {"type": "int", "default": 8080}}
        assert _detect_http_port(config, {}) == 8080

    def test_detects_port_from_container_ports(self) -> None:
        containers = {
            "app": {"resource": "oci-image", "ports": [{"target": 8000}]},
        }
        assert _detect_http_port({}, containers) == 8000

    def test_config_takes_precedence_over_containers(self) -> None:
        config = {"http_port": {"type": "int", "default": 9090}}
        containers = {"app": {"ports": [{"target": 8000}]}}
        assert _detect_http_port(config, containers) == 9090

    def test_returns_none_without_port(self) -> None:
        assert _detect_http_port({}, {}) is None

    def test_ignores_non_dict_container(self) -> None:
        assert _detect_http_port({}, {"app": "not-a-dict"}) is None

    def test_ignores_port_outside_valid_range(self) -> None:
        config = {"port": {"type": "int", "default": 10}}
        assert _detect_http_port(config, {}) is None

    def test_non_dict_config_value_skipped(self) -> None:
        """Config options with non-dict values are skipped without crashing."""
        config = {"port": "not-a-dict", "http_port": {"type": "int", "default": 8080}}
        assert _detect_http_port(config, {}) == 8080

    def test_all_non_dict_config_values(self) -> None:
        """When all config values are non-dict, returns None."""
        config = {"port": "string-value", "debug": True}
        assert _detect_http_port(config, {}) is None


# ===================================================================
# TestGenerateLoadTestTool
# ===================================================================


class TestGenerateLoadTestTool:
    """Tests for GenerateLoadTestTool."""

    @pytest.fixture
    def tool(self):
        return GenerateLoadTestTool()

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.mark.asyncio
    async def test_generates_load_test_files(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text(
            "name: my-charm\nactions:\n  backup:\n    description: backup data\n"
        )

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert (temp_dir / "tests" / "load" / "conftest.py").exists()
        assert (temp_dir / "tests" / "load" / "test_load.py").exists()

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

    @pytest.mark.asyncio
    async def test_k6_detection(self, tool, temp_dir) -> None:
        """Charm with HTTP port config gets a k6 script."""
        (temp_dir / "charmcraft.yaml").write_text(
            "name: web-app\nconfig:\n  options:\n    port:\n      type: int\n      default: 8080\n"
        )

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["has_k6"] is True
        assert (temp_dir / "tests" / "load" / "k6_http.js").exists()

    @pytest.mark.asyncio
    async def test_no_k6_without_port(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text("name: worker\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["has_k6"] is False
