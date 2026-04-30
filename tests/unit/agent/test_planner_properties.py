"""Property-based tests for ``planner._validate_dependencies``.

The function has two jobs — strip dependencies that point at task IDs
not in the current plan, and break any cycles it sees — and the
example-based tests (``tests/unit/test_planner.py``) cover the
named-scenario cases.  These property tests cover the space in
between: arbitrarily shaped graphs, arbitrarily many tasks, and random
mixes of valid and invalid dependencies.  Together they pin the
function's contract down tightly enough that a refactor can break the
cycle-detection algorithm without silent regression.

The invariants under test, restated once here so they don't have to be
re-read from each test body:

* *Task set is preserved.*  The function mutates ``.dependencies`` in
  place on the passed-in objects; it never adds or removes tasks.
* *No phantom dependencies.*  After the call, every dep on every task
  is the ID of some task in the input list.
* *No cycles.*  Kahn's algorithm succeeds on the result — every task
  is reachable.
* *Acyclic input is unchanged.*  A DAG with only valid refs passes
  through untouched; the function never widens the dependency set.
* *Idempotence.*  Running the function a second time is a no-op.
"""

from __future__ import annotations

import copy

from hypothesis import given
from hypothesis import strategies as st

from cantrip.agent.planner.llm import _validate_dependencies
from cantrip.agent.queue import AgentTask, TaskCategory

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def _task_id_strategy() -> st.SearchStrategy[str]:
    """Short alphanumeric IDs.  Real IDs are uuid4 hex; these collapse
    the space so Hypothesis can shrink to minimal failing examples
    without the labels fighting readability."""
    return st.text(
        alphabet="abcdefghijklmnop",
        min_size=1,
        max_size=4,
    )


def _unique_task_ids(min_size: int = 1, max_size: int = 8) -> st.SearchStrategy[list[str]]:
    """A list of *min_size*..*max_size* distinct task IDs."""
    return st.lists(
        _task_id_strategy(),
        min_size=min_size,
        max_size=max_size,
        unique=True,
    )


@st.composite
def _dag_tasks(draw: st.DrawFn) -> list[AgentTask]:
    """Build an acyclic task graph.

    Each task is assigned an index in topological order; a task at
    index *i* may depend only on tasks at lower indices.  That makes
    the resulting graph a DAG by construction, regardless of which
    subset of lower-index tasks Hypothesis picks.
    """
    ids = draw(_unique_task_ids(min_size=1, max_size=8))
    tasks: list[AgentTask] = []
    for i, tid in enumerate(ids):
        earlier = ids[:i]
        deps = (
            draw(st.lists(st.sampled_from(earlier), max_size=len(earlier), unique=True))
            if earlier
            else []
        )
        tasks.append(
            AgentTask(
                id=tid,
                title=f"Task {tid}",
                category=TaskCategory.BUILD,
                dependencies=list(deps),
            )
        )
    return tasks


@st.composite
def _arbitrary_tasks(draw: st.DrawFn) -> list[AgentTask]:
    """Build an arbitrary task graph — may contain cycles, self-deps,
    or references to IDs not in the plan."""
    ids = draw(_unique_task_ids(min_size=1, max_size=8))
    # Pool of candidate dependency targets — mixes valid task IDs with
    # a handful of guaranteed-invalid IDs so the stripping behaviour
    # gets exercised alongside the cycle logic.
    phantom_pool = ["ghost-1", "ghost-2", "ghost-3"]
    pool = ids + phantom_pool
    tasks: list[AgentTask] = []
    for tid in ids:
        deps = draw(
            st.lists(
                st.sampled_from(pool),
                max_size=len(pool),
                unique=True,
            )
        )
        tasks.append(
            AgentTask(
                id=tid,
                title=f"Task {tid}",
                category=TaskCategory.BUILD,
                dependencies=list(deps),
            )
        )
    return tasks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_cycle(tasks: list[AgentTask]) -> bool:
    """Return ``True`` if ``tasks`` contains a dependency cycle.

    Uses Kahn's algorithm so the truth-check here mirrors the one
    ``_validate_dependencies`` performs itself; if the two disagreed
    the tests would be pointless.
    """
    in_degree: dict[str, int] = {t.id: len(t.dependencies) for t in tasks}
    adjacency: dict[str, list[str]] = {t.id: [] for t in tasks}
    ids = set(in_degree)
    for task in tasks:
        for dep in task.dependencies:
            if dep in ids:
                adjacency[dep].append(task.id)
    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for successor in adjacency[node]:
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                queue.append(successor)
    return visited < len(tasks)


def _snapshot(tasks: list[AgentTask]) -> list[tuple[str, tuple[str, ...]]]:
    """Stable (id, deps) snapshot for equality checks."""
    return [(t.id, tuple(t.dependencies)) for t in tasks]


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestValidateDependenciesProperties:
    """Invariants of ``_validate_dependencies`` over arbitrary graphs."""

    @given(tasks=_arbitrary_tasks())
    def test_task_set_is_preserved(self, tasks: list[AgentTask]) -> None:
        """The function mutates in place — no tasks are added or removed."""
        ids_before = [t.id for t in tasks]
        _validate_dependencies(tasks)
        assert [t.id for t in tasks] == ids_before

    @given(tasks=_arbitrary_tasks())
    def test_no_phantom_dependencies_remain(self, tasks: list[AgentTask]) -> None:
        """Every surviving dep must point at some task in the plan."""
        _validate_dependencies(tasks)
        valid_ids = {t.id for t in tasks}
        for task in tasks:
            assert all(dep in valid_ids for dep in task.dependencies), (
                f"Task {task.id!r} has phantom deps: {task.dependencies}"
            )

    @given(tasks=_arbitrary_tasks())
    def test_result_is_acyclic(self, tasks: list[AgentTask]) -> None:
        """Whatever the input graph looks like, the output is a DAG."""
        _validate_dependencies(tasks)
        assert not _has_cycle(tasks), (
            f"cycle survived in: {[(t.id, t.dependencies) for t in tasks]}"
        )

    @given(tasks=_dag_tasks())
    def test_dag_with_valid_refs_passes_through_unchanged(self, tasks: list[AgentTask]) -> None:
        """Acyclic input with only valid deps must not be touched.

        Important shape guarantee: the function never widens the
        dependency set.  If it did, a caller counting on a stable plan
        could have tasks appear to grow extra edges after validation.
        """
        before = _snapshot(tasks)
        _validate_dependencies(tasks)
        after = _snapshot(tasks)
        assert before == after

    @given(tasks=_arbitrary_tasks())
    def test_is_idempotent(self, tasks: list[AgentTask]) -> None:
        """Running the function twice changes nothing the second time."""
        _validate_dependencies(tasks)
        once = _snapshot(tasks)
        _validate_dependencies(tasks)
        twice = _snapshot(tasks)
        assert once == twice

    @given(tasks=_arbitrary_tasks())
    def test_result_is_a_subgraph_of_input(self, tasks: list[AgentTask]) -> None:
        """Only stripping — no edge is ever added.

        Distinct from 'DAG unchanged': this also applies to cyclic
        inputs (the cycle branch must *remove* edges, never invent new
        ones while it reshuffles).
        """
        before = {t.id: set(t.dependencies) for t in copy.deepcopy(tasks)}
        _validate_dependencies(tasks)
        for task in tasks:
            assert set(task.dependencies) <= before[task.id], (
                f"Task {task.id!r} grew a dep: "
                f"before={before[task.id]}, after={set(task.dependencies)}"
            )
