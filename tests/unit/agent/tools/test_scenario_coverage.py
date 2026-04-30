"""Tests for the scenario_coverage tool (Phase 92.4)."""

from __future__ import annotations

import pathlib

import pytest
import yaml

from cantrip.agent.tools.scenario_coverage import (
    ScenarioCoverageTool,
    scenario_coverage,
)


@pytest.fixture
def tmp_charm(tmp_path: pathlib.Path) -> pathlib.Path:
    charm = tmp_path / "charm"
    charm.mkdir()
    (charm / "src").mkdir()
    (charm / "tests" / "unit").mkdir(parents=True)
    return charm


def _write_metadata(charm: pathlib.Path, data: dict[str, object]) -> None:
    with (charm / "charmcraft.yaml").open("w") as f:
        yaml.dump(data, f)


def _write_charm_source(charm: pathlib.Path, body: str) -> None:
    (charm / "src" / "charm.py").write_text(body)


def _write_test(charm: pathlib.Path, name: str, body: str) -> None:
    (charm / "tests" / "unit" / name).write_text(body)


def test_no_observers(tmp_charm: pathlib.Path) -> None:
    _write_metadata(tmp_charm, {"name": "test"})
    _write_charm_source(tmp_charm, "import ops\n\nclass C(ops.CharmBase): pass\n")
    report = scenario_coverage(tmp_charm)
    assert report["total_observers"] == 0
    assert report["unexercised_handlers"] == []


def test_observer_with_test_passes(tmp_charm: pathlib.Path) -> None:
    _write_metadata(tmp_charm, {"name": "test"})
    _write_charm_source(
        tmp_charm,
        "import ops\n\nclass C(ops.CharmBase):\n"
        "    def __init__(self, *args):\n        super().__init__(*args)\n"
        "        self.framework.observe(self.on.config_changed, self._on_config_changed)\n"
        "    def _on_config_changed(self, event): pass\n",
    )
    _write_test(
        tmp_charm,
        "test_charm.py",
        "def test_config_changed():\n    pass  # exercises _on_config_changed\n",
    )
    report = scenario_coverage(tmp_charm)
    assert report["total_observers"] == 1
    assert report["unexercised_handlers"] == []


def test_observer_without_test_flagged(tmp_charm: pathlib.Path) -> None:
    _write_metadata(tmp_charm, {"name": "test"})
    _write_charm_source(
        tmp_charm,
        "import ops\n\nclass C(ops.CharmBase):\n"
        "    def __init__(self, *args):\n        super().__init__(*args)\n"
        "        self.framework.observe(self.on.install, self._on_install)\n"
        "    def _on_install(self, event): pass\n",
    )
    _write_test(tmp_charm, "test_other.py", "def test_other(): pass\n")
    report = scenario_coverage(tmp_charm)
    assert report["total_observers"] == 1
    assert len(report["unexercised_handlers"]) == 1
    assert report["unexercised_handlers"][0]["handler"] == "_on_install"


def test_can_connect_false_gap_flagged(tmp_charm: pathlib.Path) -> None:
    """Charm with containers but no can_connect=False test → gap."""
    _write_metadata(
        tmp_charm,
        {
            "name": "test",
            "containers": {"workload": {"resource": "workload-image"}},
        },
    )
    _write_charm_source(tmp_charm, "import ops\n\nclass C(ops.CharmBase): pass\n")
    _write_test(tmp_charm, "test_x.py", "def test_x(): pass\n")
    report = scenario_coverage(tmp_charm)
    gaps = report["event_shape_gaps"]
    assert any("can_connect" in g for g in gaps)


def test_can_connect_false_present_passes(tmp_charm: pathlib.Path) -> None:
    _write_metadata(
        tmp_charm,
        {"name": "test", "containers": {"w": {"resource": "img"}}},
    )
    _write_charm_source(tmp_charm, "import ops\n\nclass C(ops.CharmBase): pass\n")
    _write_test(
        tmp_charm,
        "test_x.py",
        "def test_no_connect():\n    container = testing.Container('w', can_connect=False)\n",
    )
    report = scenario_coverage(tmp_charm)
    assert not any("can_connect" in g for g in report["event_shape_gaps"])


def test_relation_broken_gap_flagged(tmp_charm: pathlib.Path) -> None:
    _write_metadata(
        tmp_charm,
        {"name": "test", "requires": {"db": {"interface": "mysql"}}},
    )
    _write_charm_source(tmp_charm, "import ops\n\nclass C(ops.CharmBase): pass\n")
    _write_test(tmp_charm, "test_x.py", "def test_x(): pass\n")
    report = scenario_coverage(tmp_charm)
    assert any("relation-broken" in g for g in report["event_shape_gaps"])


def test_relation_broken_present_passes(tmp_charm: pathlib.Path) -> None:
    _write_metadata(
        tmp_charm,
        {"name": "test", "requires": {"db": {"interface": "mysql"}}},
    )
    _write_charm_source(tmp_charm, "import ops\n\nclass C(ops.CharmBase): pass\n")
    _write_test(
        tmp_charm,
        "test_x.py",
        "def test_break():\n    ctx.run(ctx.on.relation_broken(rel), state)\n",
    )
    report = scenario_coverage(tmp_charm)
    assert not any("relation-broken" in g for g in report["event_shape_gaps"])


@pytest.mark.asyncio
async def test_tool_caption_clean(tmp_charm: pathlib.Path) -> None:
    _write_metadata(tmp_charm, {"name": "test"})
    _write_charm_source(tmp_charm, "import ops\n\nclass C(ops.CharmBase): pass\n")
    tool = ScenarioCoverageTool()
    result = await tool.execute(path=str(tmp_charm))
    assert result.success
    assert result.caption == "scenario_coverage → no observers"


@pytest.mark.asyncio
async def test_tool_caption_with_gaps(tmp_charm: pathlib.Path) -> None:
    _write_metadata(
        tmp_charm,
        {"name": "test", "requires": {"db": {"interface": "mysql"}}},
    )
    _write_charm_source(
        tmp_charm,
        "import ops\n\nclass C(ops.CharmBase):\n"
        "    def __init__(self, *args):\n        super().__init__(*args)\n"
        "        self.framework.observe(self.on.install, self._on_install)\n"
        "    def _on_install(self, event): pass\n",
    )
    _write_test(tmp_charm, "test_x.py", "def test_x(): pass\n")
    tool = ScenarioCoverageTool()
    result = await tool.execute(path=str(tmp_charm))
    assert result.success
    assert "unexercised" in result.caption
    assert "shape gap" in result.caption
