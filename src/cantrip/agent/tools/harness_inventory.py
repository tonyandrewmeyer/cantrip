"""Inventory tool — count remaining Harness usages across a charm's tests.

The ``harness-migration`` skill spells out a regex the agent runs
through ``grep`` every turn to enumerate Harness call-sites that
still need to migrate to Scenario.  Lifting that into a
deterministic tool deletes the recurring "scan tests/, summarise
counts, decide what's left" reasoning loop the agent does by hand.

Output shape per file: ``{path, harness, scenario, mixed}`` plus
a top-level ``total_remaining`` so the agent can render a
checklist without re-counting.  ``mixed`` (a single file imports
both ``ops.testing.Harness`` and ``scenario`` constructs) is the
key signal — those files are mid-migration and need the most
attention.
"""

import dataclasses
import pathlib
import re
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Lifted from the upstream
# ``migrate-harness-tests-to-state-transition-test`` skill (part of
# canonical/copilot-collections) that the ``harness-migration`` skill
# already cites.  Counts every distinct Harness call-site as one hit,
# and Scenario constructs as one hit each so a "mixed" classification
# is robust against single-line files that only import either.
_HARNESS_RE = re.compile(r"\btesting\.Harness\b|\bops\.testing\.Harness\b|\bHarness\(")
_SCENARIO_RE = re.compile(
    r"\btesting\.Scenario\b|\bScenario\(|\btesting\.Context\b|\btesting\.State\b"
)


@dataclasses.dataclass(frozen=True)
class HarnessFileReport:
    """Per-file Harness-vs-Scenario counts."""

    path: str
    harness: int
    scenario: int
    mixed: bool


def harness_inventory(charm_dir: pathlib.Path) -> dict[str, Any]:
    """Walk ``tests/`` under *charm_dir* and tally Harness vs Scenario hits.

    Returns a dict with ``files`` (one entry per test file with at least
    one Harness or Scenario hit), ``total_remaining`` (number of files
    still containing any Harness reference), and ``mixed_count``.
    Files with zero hits are omitted to keep the report short — the
    agent can re-run the inventory after each migration step.
    """
    tests_root = charm_dir / "tests"
    files: list[HarnessFileReport] = []
    if not tests_root.is_dir():
        return {"files": [], "total_remaining": 0, "mixed_count": 0}

    for path in sorted(tests_root.rglob("*.py")):
        try:
            content = path.read_text(errors="replace")
        except OSError:
            continue
        harness_count = len(_HARNESS_RE.findall(content))
        scenario_count = len(_SCENARIO_RE.findall(content))
        if harness_count == 0 and scenario_count == 0:
            continue
        files.append(
            HarnessFileReport(
                path=str(path.relative_to(charm_dir)),
                harness=harness_count,
                scenario=scenario_count,
                mixed=harness_count > 0 and scenario_count > 0,
            )
        )

    total_remaining = sum(1 for f in files if f.harness > 0)
    mixed_count = sum(1 for f in files if f.mixed)
    return {
        "files": [dataclasses.asdict(f) for f in files],
        "total_remaining": total_remaining,
        "mixed_count": mixed_count,
    }


class HarnessInventoryTool(Tool):
    """Survey ``tests/`` for remaining Harness usages.

    Mirrors the regex the ``harness-migration`` skill spells out, so
    the agent gets a one-shot count instead of grepping and
    summarising every turn.
    """

    @property
    def name(self) -> str:
        return "harness_inventory"

    @property
    def description(self) -> str:
        return (
            "Inventory remaining ops.testing.Harness usages under a charm's "
            "tests/ directory. Returns one entry per file with non-zero "
            "Harness/Scenario hits and flags 'mixed' files (mid-migration). "
            "Replaces the recurring grep loop the harness-migration skill "
            "would otherwise do by hand."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the charm directory (defaults to '.').",
                    "default": ".",
                },
            },
        }

    async def execute(self, path: str = ".") -> ToolResult:
        charm_dir = pathlib.Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(success=False, output="", error=f"Path not found: {path}")
        report = harness_inventory(charm_dir)

        files = report["files"]
        lines: list[str] = []
        if not files:
            lines.append("No Harness or Scenario references found under tests/.")
        else:
            lines.append(
                f"{report['total_remaining']} file(s) still contain Harness references "
                f"({report['mixed_count']} mixed):"
            )
            for entry in files:
                tag = " [mixed]" if entry["mixed"] else ""
                lines.append(
                    f"  {entry['path']}: harness={entry['harness']} "
                    f"scenario={entry['scenario']}{tag}"
                )

        if report["total_remaining"] == 0:
            caption = "harness_inventory → clean"
        else:
            caption = (
                f"harness_inventory → {report['total_remaining']} file(s) remaining, "
                f"{report['mixed_count']} mixed"
            )
        return ToolResult(
            success=True,
            output="\n".join(lines),
            data=report,
            caption=caption,
        )
