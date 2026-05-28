"""Snapshot test for the deterministic one-shot-build task generator.

``plan_one_shot_build`` turns an approved design into a single BUILD
``AgentTask`` whose ``description`` is a rendered ``one_shot_build``
prompt.  That parsed-design output used to be pinned with scattered
``.find()`` / substring assertions (see ``test_design.py``); this
snapshot freezes the whole structured result so a template or
sequencing change surfaces as a readable diff.

The task ``id`` carries a per-call uuid suffix, so it is dropped from
the snapshot — everything else is deterministic.  Regenerate after an
intentional change with::

    uv run pytest tests/unit/planner/test_one_shot_build_snapshot.py --snapshot-update
"""

from __future__ import annotations

from cantrip.agent.planner import PlanningContext, plan_one_shot_build
from cantrip.agent.queue import AgentTask


def _normalise(task: AgentTask) -> dict[str, object]:
    """Stable view of a generated task — everything bar the uuid ``id``."""
    return {
        "title": task.title,
        "category": task.category.value,
        "model_hint": task.model_hint.value,
        "dependencies": list(task.dependencies),
        "description": task.description,
    }


def test_one_shot_build_structure_snapshot(snapshot) -> None:
    context = PlanningContext(intent="build", framework="flask", charm_name="my-app")
    tasks = plan_one_shot_build(context, "## Design\nA Flask charm with COS.")
    assert [_normalise(t) for t in tasks] == snapshot
