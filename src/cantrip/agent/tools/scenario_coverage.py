"""Coverage tool — map charm observers to their unit tests.

The ``scenario-tests`` skill teaches that every charm should
have at least one test per observer registration plus tests for
two specific event shapes: ``container.can_connect=False`` and
``relation-broken``.  ``pytest-cov`` measures *line* coverage —
this tool measures *event-shape* coverage, which pytest-cov
cannot see (a charm with 100% line coverage can still ship
without a single relation-broken test).

Output shape: ``{observers, unexercised_handlers,
event_shape_gaps, total_observers}``.  ``unexercised_handlers``
is the per-handler list of observers whose method name does not
appear in any tests/unit/ test function.  ``event_shape_gaps``
flags the missing ``can_connect=False`` test (when the charm
has containers) and the missing ``relation-broken`` test (when
the charm has any relation).
"""

import ast
import dataclasses
import pathlib
from typing import Any

import yaml

from cantrip.agent.tools.base import Tool, ToolResult


@dataclasses.dataclass(frozen=True)
class ObserverInfo:
    """One ``self.framework.observe(self.on.X, self._on_Y)`` registration."""

    event: str
    handler: str
    path: str
    line: int


def _walk_observers(
    sources: dict[pathlib.Path, str], charm_dir: pathlib.Path
) -> list[ObserverInfo]:
    """Find every ``framework.observe(*.on.<event>, self.<handler>)`` call."""
    observers: list[ObserverInfo] = []
    for path, content in sources.items():
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "observe"
                and len(node.args) >= 2
            ):
                continue
            event_node = node.args[0]
            if not (
                isinstance(event_node, ast.Attribute)
                and isinstance(event_node.value, ast.Attribute)
                and event_node.value.attr == "on"
            ):
                continue
            handler_node = node.args[1]
            if not (
                isinstance(handler_node, ast.Attribute)
                and isinstance(handler_node.value, ast.Name)
                and handler_node.value.id == "self"
            ):
                continue
            try:
                rel_path = path.relative_to(charm_dir).as_posix()
            except ValueError:
                rel_path = path.as_posix()
            observers.append(
                ObserverInfo(
                    event=event_node.attr,
                    handler=handler_node.attr,
                    path=rel_path,
                    line=node.lineno,
                )
            )
    return observers


def _collect_test_text(charm_dir: pathlib.Path) -> str:
    """Concatenate every ``tests/unit/`` Python file's source for substring searches."""
    unit_dir = charm_dir / "tests" / "unit"
    if not unit_dir.is_dir():
        return ""
    chunks: list[str] = []
    for path in sorted(unit_dir.rglob("*.py")):
        try:
            chunks.append(path.read_text(errors="replace"))
        except OSError:
            continue
    return "\n".join(chunks)


def _charm_has_containers(metadata: dict[str, Any]) -> bool:
    containers = metadata.get("containers")
    return isinstance(containers, dict) and bool(containers)


def _charm_has_relations(metadata: dict[str, Any]) -> bool:
    return any(
        isinstance(metadata.get(key), dict) and metadata[key]
        for key in ("requires", "provides", "peers")
    )


def _load_metadata(charm_dir: pathlib.Path) -> dict[str, Any]:
    for filename in ("charmcraft.yaml", "metadata.yaml"):
        path = charm_dir / filename
        if not path.exists():
            continue
        try:
            with path.open() as f:
                data = yaml.safe_load(f)
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def scenario_coverage(charm_dir: pathlib.Path) -> dict[str, Any]:
    """Audit observer-to-test coverage and event-shape gaps.

    Returns: ``observers`` (list[{event, handler, path, line}]),
    ``unexercised_handlers`` (list of handler names not referenced
    anywhere under ``tests/unit/``), ``event_shape_gaps`` (list of
    missing-shape diagnostic strings), and ``total_observers``.
    """
    sources: dict[pathlib.Path, str] = {}
    src_dir = charm_dir / "src"
    if src_dir.is_dir():
        for path in sorted(src_dir.rglob("*.py")):
            try:
                sources[path] = path.read_text(errors="replace")
            except OSError:
                continue

    observers = _walk_observers(sources, charm_dir)
    test_text = _collect_test_text(charm_dir)
    metadata = _load_metadata(charm_dir)

    unexercised: list[ObserverInfo] = []
    for obs in observers:
        # A test "exercises" the handler if the handler name OR the
        # event name (with hyphen↔underscore tolerance) appears in
        # any test file.  This is intentionally inclusive — false
        # negatives erode trust faster than false positives.
        candidates = {obs.handler, obs.event, obs.event.replace("_", "-")}
        if not any(c and c in test_text for c in candidates):
            unexercised.append(obs)

    gaps: list[str] = []
    if _charm_has_containers(metadata) and "can_connect=False" not in test_text:
        gaps.append(
            "No test where `container.can_connect=False` — early-hook behaviour is unverified"
        )
    if _charm_has_relations(metadata) and (
        "relation_broken" not in test_text and "relation-broken" not in test_text
    ):
        gaps.append(
            "No test exercising a `relation-broken` event — teardown behaviour is unverified"
        )

    return {
        "observers": [dataclasses.asdict(o) for o in observers],
        "unexercised_handlers": [dataclasses.asdict(o) for o in unexercised],
        "event_shape_gaps": gaps,
        "total_observers": len(observers),
    }


class ScenarioCoverageTool(Tool):
    """Audit a charm's observer-to-test coverage and event-shape gaps.

    Complements ``pytest-cov``: line coverage cannot see whether a
    handler has *any* tests, nor whether the suite covers the
    can-connect-False and relation-broken event shapes.  This tool
    reads ``src/charm.py`` for ``framework.observe(...)`` calls,
    correlates them with handler-name references in
    ``tests/unit/``, and flags the observer / event-shape gaps the
    ``scenario-tests`` skill spells out.
    """

    @property
    def name(self) -> str:
        return "scenario_coverage"

    @property
    def description(self) -> str:
        return (
            "Audit observer-to-test coverage for a charm. Returns the list "
            "of observe() registrations in src/, which handlers are not "
            "referenced by any tests/unit/ file, and whether the test suite "
            "exercises `container.can_connect=False` and `relation-broken` "
            "shapes (when the charm has containers / relations). Replaces "
            "the recurring 'grep observers, grep tests, compare' loop the "
            "scenario-tests skill would otherwise drive."
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
        report = scenario_coverage(charm_dir)

        lines: list[str] = []
        total = report["total_observers"]
        unexercised = report["unexercised_handlers"]
        gaps = report["event_shape_gaps"]
        if total == 0:
            lines.append("No observe() registrations found in src/.")
        else:
            lines.append(
                f"Found {total} observer(s); "
                f"{len(unexercised)} unexercised, {len(gaps)} event-shape gap(s)."
            )
        if unexercised:
            lines.append("Unexercised handlers:")
            lines.extend(
                f"  {obs['path']}:{obs['line']}: {obs['handler']} (on={obs['event']})"
                for obs in unexercised
            )
        if gaps:
            lines.append("Event-shape gaps:")
            lines.extend(f"  - {gap}" for gap in gaps)

        if total == 0:
            caption = "scenario_coverage → no observers"
        elif not unexercised and not gaps:
            caption = "scenario_coverage → clean"
        else:
            parts: list[str] = []
            if unexercised:
                parts.append(f"{len(unexercised)} unexercised")
            if gaps:
                parts.append(f"{len(gaps)} shape gap(s)")
            caption = "scenario_coverage → " + ", ".join(parts)
        return ToolResult(
            success=True,
            output="\n".join(lines),
            data=report,
            caption=caption,
        )
