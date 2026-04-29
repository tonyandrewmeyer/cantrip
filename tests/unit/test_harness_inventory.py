"""Tests for the harness_inventory tool (Phase 92.4)."""

from __future__ import annotations

import pathlib

import pytest

from cantrip.agent.tools.harness_inventory import (
    HarnessInventoryTool,
    harness_inventory,
)


@pytest.fixture
def tmp_charm(tmp_path: pathlib.Path) -> pathlib.Path:
    charm = tmp_path / "charm"
    charm.mkdir()
    (charm / "tests" / "unit").mkdir(parents=True)
    return charm


def _write_test(charm: pathlib.Path, name: str, body: str) -> None:
    (charm / "tests" / "unit" / name).write_text(body)


def test_no_tests_returns_empty(tmp_charm: pathlib.Path) -> None:
    report = harness_inventory(tmp_charm)
    assert report == {"files": [], "total_remaining": 0, "mixed_count": 0}


def test_pure_harness_file_counted(tmp_charm: pathlib.Path) -> None:
    _write_test(
        tmp_charm,
        "test_a.py",
        "import ops.testing.Harness as Harness\n\ndef test_x():\n    h = Harness(MyCharm)\n",
    )
    report = harness_inventory(tmp_charm)
    assert report["total_remaining"] == 1
    assert report["mixed_count"] == 0
    assert report["files"][0]["harness"] >= 2  # ops.testing.Harness + Harness(
    assert report["files"][0]["scenario"] == 0


def test_pure_scenario_file_not_counted_as_remaining(tmp_charm: pathlib.Path) -> None:
    _write_test(
        tmp_charm,
        "test_b.py",
        "from ops import testing\n\ndef test_y():\n    "
        "ctx = testing.Context(MyCharm)\n    state = testing.State()\n",
    )
    report = harness_inventory(tmp_charm)
    assert report["total_remaining"] == 0
    assert len(report["files"]) == 1
    assert report["files"][0]["scenario"] >= 1
    assert report["files"][0]["harness"] == 0


def test_mixed_file_flagged(tmp_charm: pathlib.Path) -> None:
    _write_test(
        tmp_charm,
        "test_mixed.py",
        "from ops.testing import Harness\n"
        "from ops import testing\n\n"
        "def test_old():\n    h = Harness(MyCharm)\n\n"
        "def test_new():\n    ctx = testing.Context(MyCharm)\n",
    )
    report = harness_inventory(tmp_charm)
    assert report["total_remaining"] == 1
    assert report["mixed_count"] == 1
    assert report["files"][0]["mixed"] is True


@pytest.mark.asyncio
async def test_tool_returns_caption(tmp_charm: pathlib.Path) -> None:
    _write_test(
        tmp_charm,
        "test_a.py",
        "from ops.testing import Harness\n\ndef test_x():\n    h = Harness(c)\n",
    )
    tool = HarnessInventoryTool()
    result = await tool.execute(path=str(tmp_charm))
    assert result.success
    assert result.caption is not None
    assert "remaining" in result.caption
    assert "harness" in result.output.lower()


@pytest.mark.asyncio
async def test_tool_clean_caption(tmp_charm: pathlib.Path) -> None:
    tool = HarnessInventoryTool()
    result = await tool.execute(path=str(tmp_charm))
    assert result.success
    assert result.caption == "harness_inventory → clean"


@pytest.mark.asyncio
async def test_tool_missing_path_errors(tmp_path: pathlib.Path) -> None:
    tool = HarnessInventoryTool()
    result = await tool.execute(path=str(tmp_path / "nonexistent"))
    assert not result.success
    assert result.error is not None
