"""Tests for the fuzz testing tool."""

import tempfile
from pathlib import Path

import pytest

from cantrip.agent.tools.fuzz import (
    FuzzTestTool,
    _fuzz_action_params,
    _fuzz_config_values,
)


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def tool():
    return FuzzTestTool()


class TestFuzzConfigValues:
    """Tests for _fuzz_config_values."""

    def test_empty_config(self) -> None:
        assert _fuzz_config_values({}) == []

    def test_generates_cases_for_string_option(self) -> None:
        config = {"options": {"name": {"type": "string", "default": "hello"}}}
        cases = _fuzz_config_values(config)
        assert len(cases) > 0
        assert all("name" in case for case in cases)

    def test_generates_cases_for_int_option(self) -> None:
        config = {"options": {"port": {"type": "int", "default": 8080}}}
        cases = _fuzz_config_values(config)
        assert len(cases) > 0

    def test_no_options_key(self) -> None:
        assert _fuzz_config_values({"something": "else"}) == []


class TestFuzzActionParams:
    """Tests for _fuzz_action_params."""

    def test_empty_actions(self) -> None:
        assert _fuzz_action_params({}) == []

    def test_generates_cases_for_action(self) -> None:
        actions = {
            "backup": {
                "params": {
                    "properties": {
                        "path": {"type": "string"},
                    },
                },
            },
        }
        cases = _fuzz_action_params(actions)
        assert len(cases) > 0
        assert all(c["action"] == "backup" for c in cases)

    def test_handles_non_dict_action_spec(self) -> None:
        actions = {"simple": "not a dict"}
        assert _fuzz_action_params(actions) == []

    def test_missing_properties_key_falls_back_to_empty(self) -> None:
        """When params has no 'properties' key, fall back to empty dict."""
        actions = {
            "backup": {
                "params": {
                    "required": ["path"],
                },
            },
        }
        cases = _fuzz_action_params(actions)
        # Should not crash; produces cases with empty params since there
        # are no properties to fuzz.
        assert all(c["params"] == {} for c in cases)


class TestFuzzTestTool:
    """Integration tests for FuzzTestTool.execute."""

    @pytest.mark.asyncio
    async def test_nonexistent_path(self, tool) -> None:
        result = await tool.execute(path="/nonexistent")
        assert not result.success

    @pytest.mark.asyncio
    async def test_no_config_or_actions(self, tool, temp_dir) -> None:
        """A charm with no config/actions produces empty fuzz cases."""
        (temp_dir / "charmcraft.yaml").write_text("name: test\ntype: charm\n")
        result = await tool.execute(path=str(temp_dir), seed=42)
        assert result.success
        assert result.data["config_cases"] == 0
        assert result.data["action_cases"] == 0

    @pytest.mark.asyncio
    async def test_with_config(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text(
            "name: test\ntype: charm\n"
            "config:\n  options:\n    port:\n      type: int\n      default: 8080\n"
        )
        result = await tool.execute(path=str(temp_dir), seed=42)
        assert result.success
        assert result.data["config_cases"] > 0

    @pytest.mark.asyncio
    async def test_with_actions(self, tool, temp_dir) -> None:
        (temp_dir / "actions.yaml").write_text(
            "backup:\n  params:\n    properties:\n      path:\n        type: string\n"
        )
        # Need at least a metadata file.
        (temp_dir / "charmcraft.yaml").write_text("name: test\ntype: charm\n")
        result = await tool.execute(path=str(temp_dir), seed=42)
        assert result.success
        assert result.data["action_cases"] > 0

    @pytest.mark.asyncio
    async def test_seed_produces_reproducible_output(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text(
            "name: test\ntype: charm\nconfig:\n  options:\n    name:\n      type: string\n"
        )
        r1 = await tool.execute(path=str(temp_dir), seed=123)
        r2 = await tool.execute(path=str(temp_dir), seed=123)
        assert r1.data["config_fuzz"] == r2.data["config_fuzz"]

    @pytest.mark.asyncio
    async def test_output_is_markdown(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text("name: test\ntype: charm\n")
        result = await tool.execute(path=str(temp_dir))
        assert result.output.startswith("# Fuzz Test Plan")
