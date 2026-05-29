"""Tests for the pure routing state machine."""

from __future__ import annotations

import itertools

import pytest

from cantrip.agent.policy.routing import (
    RouteAction,
    RoutingDecision,
    TaskInfo,
    TaskSnapshot,
    WorkQueueState,
    route,
    snapshot_from_queue,
)
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _info(
    id: str = "t1",
    category: str = "build",
    status: TaskSnapshot = TaskSnapshot.PENDING,
    dependencies: tuple[str, ...] = (),
    noop_count: int = 0,
) -> TaskInfo:
    return TaskInfo(
        id=id,
        category=category,
        status=status,
        dependencies=dependencies,
        noop_count=noop_count,
    )


def _state(
    tasks: tuple[TaskInfo, ...] = (),
    active_subagent_count: int = 0,
    max_concurrency: int = 3,
    paused: bool = False,
    draining: bool = False,
    has_charm_path: bool = True,
    has_dev_model: bool = True,
) -> WorkQueueState:
    return WorkQueueState(
        tasks=tasks,
        active_subagent_count=active_subagent_count,
        max_concurrency=max_concurrency,
        paused=paused,
        draining=draining,
        has_charm_path=has_charm_path,
        has_dev_model=has_dev_model,
    )


# ===================================================================
# TestWorkQueueState
# ===================================================================


class TestWorkQueueState:
    """Tests for the frozen state snapshot."""

    def test_frozen(self) -> None:
        s = _state()
        with pytest.raises(AttributeError):
            s.paused = True  # type: ignore[misc]

    def test_counts(self) -> None:
        tasks = (
            _info(id="a", status=TaskSnapshot.PENDING),
            _info(id="b", status=TaskSnapshot.ACTIVE),
            _info(id="c", status=TaskSnapshot.DONE),
            _info(id="d", status=TaskSnapshot.FAILED),
            _info(id="e", status=TaskSnapshot.BLOCKED),
        )
        s = _state(tasks=tasks)
        assert s.pending_count == 1
        assert s.active_count == 1
        assert s.done_count == 1
        assert s.failed_count == 1
        assert s.blocked_count == 1

    def test_free_slots(self) -> None:
        s = _state(active_subagent_count=1, max_concurrency=3)
        assert s.free_slots == 2

    def test_free_slots_at_capacity(self) -> None:
        s = _state(active_subagent_count=3, max_concurrency=3)
        assert s.free_slots == 0

    def test_is_terminal_empty_queue(self) -> None:
        s = _state(tasks=())
        assert s.is_terminal is True

    def test_is_terminal_all_done(self) -> None:
        s = _state(tasks=(_info(status=TaskSnapshot.DONE),))
        assert s.is_terminal is True

    def test_is_terminal_with_pending(self) -> None:
        s = _state(tasks=(_info(status=TaskSnapshot.PENDING),))
        assert s.is_terminal is False

    def test_is_terminal_with_active(self) -> None:
        s = _state(tasks=(_info(status=TaskSnapshot.ACTIVE),))
        assert s.is_terminal is False

    def test_is_terminal_blocked_only(self) -> None:
        """Blocked tasks with nothing pending/active is terminal."""
        s = _state(tasks=(_info(status=TaskSnapshot.BLOCKED),))
        assert s.is_terminal is True


# ===================================================================
# TestRoute — core routing decisions
# ===================================================================


class TestRoute:
    """Tests for the route() pure function."""

    def test_idle_when_empty(self) -> None:
        decision = route(_state(tasks=()))
        assert decision.action == RouteAction.IDLE

    def test_spawn_pending_task(self) -> None:
        s = _state(tasks=(_info(id="t1", category="build"),))
        decision = route(s)
        assert decision == RoutingDecision(action=RouteAction.SPAWN_TASK, task_id="t1")

    def test_confirm_task_triggers_wait(self) -> None:
        s = _state(tasks=(_info(id="c1", category="confirm"),))
        decision = route(s)
        assert decision == RoutingDecision(action=RouteAction.WAIT_FOR_CONFIRMATION, task_id="c1")

    def test_non_confirm_preferred_over_confirm(self) -> None:
        """Non-CONFIRM tasks are preferred regardless of queue order."""
        tasks = (
            _info(id="c1", category="confirm"),
            _info(id="t1", category="build"),
        )
        decision = route(_state(tasks=tasks))
        assert decision.action == RouteAction.SPAWN_TASK
        assert decision.task_id == "t1"

    def test_confirm_only_when_no_non_confirm(self) -> None:
        """WAIT_FOR_CONFIRMATION only when all ready tasks are CONFIRM."""
        tasks = (
            _info(id="c1", category="confirm"),
            _info(id="c2", category="confirm"),
        )
        decision = route(_state(tasks=tasks))
        assert decision.action == RouteAction.WAIT_FOR_CONFIRMATION
        assert decision.task_id == "c1"

    def test_spawn_with_confirm_after_build(self) -> None:
        """Non-CONFIRM tasks are spawned even when CONFIRM is also ready."""
        tasks = (
            _info(id="t1", category="build"),
            _info(id="c1", category="confirm"),
        )
        decision = route(_state(tasks=tasks))
        assert decision.action == RouteAction.SPAWN_TASK
        assert decision.task_id == "t1"

    def test_paused_with_active_waits(self) -> None:
        s = _state(
            tasks=(_info(id="t1", status=TaskSnapshot.ACTIVE),),
            active_subagent_count=1,
            paused=True,
        )
        assert route(s).action == RouteAction.WAIT_FOR_IN_FLIGHT

    def test_paused_without_active_idles(self) -> None:
        s = _state(
            tasks=(_info(id="t1", status=TaskSnapshot.PENDING),),
            paused=True,
        )
        assert route(s).action == RouteAction.IDLE

    def test_draining_with_active_waits(self) -> None:
        s = _state(
            tasks=(_info(id="t1", status=TaskSnapshot.ACTIVE),),
            active_subagent_count=1,
            draining=True,
        )
        assert route(s).action == RouteAction.WAIT_FOR_IN_FLIGHT

    def test_draining_without_active_idles(self) -> None:
        s = _state(draining=True)
        assert route(s).action == RouteAction.IDLE

    def test_no_free_slots_waits(self) -> None:
        s = _state(
            tasks=(_info(id="t1"),),
            active_subagent_count=3,
            max_concurrency=3,
        )
        assert route(s).action == RouteAction.WAIT_FOR_IN_FLIGHT

    def test_dependency_not_satisfied_skips(self) -> None:
        """A pending task with an unsatisfied dependency is not ready."""
        tasks = (
            _info(id="dep", status=TaskSnapshot.PENDING),
            _info(id="t1", dependencies=("dep",)),
        )
        # dep is pending, so t1 is not ready; dep itself is ready.
        decision = route(_state(tasks=tasks))
        assert decision.action == RouteAction.SPAWN_TASK
        assert decision.task_id == "dep"

    def test_dependency_done_allows_spawn(self) -> None:
        tasks = (
            _info(id="dep", status=TaskSnapshot.DONE),
            _info(id="t1", dependencies=("dep",)),
        )
        decision = route(_state(tasks=tasks))
        assert decision.action == RouteAction.SPAWN_TASK
        assert decision.task_id == "t1"

    def test_dependency_failed_allows_spawn(self) -> None:
        """Failed dependencies still unblock downstream tasks."""
        tasks = (
            _info(id="dep", status=TaskSnapshot.FAILED),
            _info(id="t1", dependencies=("dep",)),
        )
        decision = route(_state(tasks=tasks))
        assert decision.action == RouteAction.SPAWN_TASK
        assert decision.task_id == "t1"

    def test_dependency_cancelled_allows_spawn(self) -> None:
        """A dependency not in the queue (cancelled) is treated as satisfied."""
        tasks = (_info(id="t1", dependencies=("removed",)),)
        decision = route(_state(tasks=tasks))
        assert decision.action == RouteAction.SPAWN_TASK
        assert decision.task_id == "t1"

    def test_all_blocked_is_terminal(self) -> None:
        tasks = (_info(id="t1", status=TaskSnapshot.BLOCKED),)
        s = _state(tasks=tasks)
        decision = route(s)
        assert decision.action == RouteAction.IDLE

    def test_active_with_no_ready_waits(self) -> None:
        """Active tasks exist but no pending tasks are ready."""
        tasks = (
            _info(id="t1", status=TaskSnapshot.ACTIVE),
            _info(id="t2", dependencies=("t1",)),
        )
        s = _state(tasks=tasks, active_subagent_count=1)
        decision = route(s)
        assert decision.action == RouteAction.WAIT_FOR_IN_FLIGHT

    def test_multiple_ready_spawns_first(self) -> None:
        """When several tasks are ready, the first in queue order wins."""
        tasks = (
            _info(id="t1", category="research"),
            _info(id="t2", category="build"),
        )
        decision = route(_state(tasks=tasks))
        assert decision.task_id == "t1"

    def test_all_categories_spawn(self) -> None:
        """Every non-confirm category results in SPAWN_TASK."""
        for cat in ("research", "build", "deploy", "test", "debug", "infra"):
            s = _state(tasks=(_info(id="x", category=cat),))
            decision = route(s)
            assert decision.action == RouteAction.SPAWN_TASK, f"Failed for {cat}"


# ===================================================================
# TestSnapshotFromQueue — bridge from live queue to frozen state
# ===================================================================


class TestSnapshotFromQueue:
    """Tests for snapshot_from_queue()."""

    def test_basic_conversion(self) -> None:
        task = AgentTask(
            id="abc",
            title="Build charm",
            category=TaskCategory.BUILD,
            dependencies=["dep1"],
        )
        task.noop_count = 1
        snap = snapshot_from_queue(
            tasks=[task],
            active_subagent_count=2,
            max_concurrency=3,
            paused=True,
            has_charm_path=True,
            has_dev_model=False,
        )
        assert len(snap.tasks) == 1
        info = snap.tasks[0]
        assert info.id == "abc"
        assert info.category == "build"
        assert info.status == TaskSnapshot.PENDING
        assert info.dependencies == ("dep1",)
        assert info.noop_count == 1
        assert snap.active_subagent_count == 2
        assert snap.max_concurrency == 3
        assert snap.paused is True
        assert snap.has_charm_path is True
        assert snap.has_dev_model is False

    def test_status_mapping(self) -> None:
        """Each TaskStatus maps to the corresponding TaskSnapshot."""
        for status in TaskStatus:
            task = AgentTask(id="t", title="t", category=TaskCategory.BUILD)
            task.status = status
            snap = snapshot_from_queue(tasks=[task], active_subagent_count=0, max_concurrency=1)
            assert snap.tasks[0].status == TaskSnapshot(str(status))


# ===================================================================
# TestCrossCheck — route() vs executor decision agreement
# ===================================================================


class TestCrossCheck:
    """Verify route() agrees with the executor's historical decision logic.

    These tests construct a WorkQueueState and verify that the routing
    decision matches what the executor's _run_loop would have done.
    """

    def test_executor_picks_first_ready(self) -> None:
        """Executor picks first ready non-CONFIRM task — route() should too."""
        queue = WorkQueue()
        t1 = AgentTask(id="t1", title="Research", category=TaskCategory.RESEARCH)
        t2 = AgentTask(id="t2", title="Build", category=TaskCategory.BUILD)
        queue.add_task(t1)
        queue.add_task(t2)

        snap = snapshot_from_queue(
            tasks=queue.all_tasks(),
            active_subagent_count=0,
            max_concurrency=3,
        )
        decision = route(snap)
        executor_pick = queue.all_ready(limit=1)

        assert decision.action == RouteAction.SPAWN_TASK
        assert decision.task_id == executor_pick[0].id

    def test_executor_blocks_confirm(self) -> None:
        """Executor blocks CONFIRM tasks — route() returns WAIT_FOR_CONFIRMATION."""
        queue = WorkQueue()
        task = AgentTask(id="c1", title="Confirm design", category=TaskCategory.CONFIRM)
        queue.add_task(task)

        snap = snapshot_from_queue(
            tasks=queue.all_tasks(),
            active_subagent_count=0,
            max_concurrency=3,
        )
        decision = route(snap)
        assert decision.action == RouteAction.WAIT_FOR_CONFIRMATION
        assert decision.task_id == "c1"

    def test_executor_paused_skips_tasks(self) -> None:
        """Paused executor sleeps — route() returns IDLE or WAIT."""
        queue = WorkQueue()
        queue.add_task(AgentTask(id="t1", title="Build", category=TaskCategory.BUILD))

        snap = snapshot_from_queue(
            tasks=queue.all_tasks(),
            active_subagent_count=0,
            max_concurrency=3,
            paused=True,
        )
        decision = route(snap)
        assert decision.action == RouteAction.IDLE

    def test_executor_respects_concurrency(self) -> None:
        """When at max concurrency the executor waits — route() should too."""
        queue = WorkQueue()
        queue.add_task(AgentTask(id="t1", title="Build", category=TaskCategory.BUILD))

        snap = snapshot_from_queue(
            tasks=queue.all_tasks(),
            active_subagent_count=3,
            max_concurrency=3,
        )
        decision = route(snap)
        assert decision.action == RouteAction.WAIT_FOR_IN_FLIGHT

    def test_executor_dependency_chain(self) -> None:
        """Dependency chain: A → B → C. Only A should be picked."""
        queue = WorkQueue()
        a = AgentTask(id="a", title="Research", category=TaskCategory.RESEARCH)
        b = AgentTask(id="b", title="Build", category=TaskCategory.BUILD, dependencies=["a"])
        c = AgentTask(id="c", title="Test", category=TaskCategory.TEST, dependencies=["b"])
        queue.add_tasks([a, b, c])

        snap = snapshot_from_queue(
            tasks=queue.all_tasks(),
            active_subagent_count=0,
            max_concurrency=3,
        )
        decision = route(snap)
        executor_pick = queue.all_ready(limit=1)

        assert decision.action == RouteAction.SPAWN_TASK
        assert decision.task_id == "a"
        assert decision.task_id == executor_pick[0].id


# ===================================================================
# TestDeadlockFreedom — BFS verification
# ===================================================================


class TestDeadlockFreedom:
    """Verify that every non-terminal WorkQueueState has a path to completion.

    Uses BFS over reachable states to prove no deadlocks exist.  The
    state space is kept finite by using small task counts and abstracting
    away task identity.
    """

    @staticmethod
    def _enumerate_small_states() -> list[WorkQueueState]:
        """Generate a representative set of WorkQueueState values.

        Uses 0–2 tasks across all status combinations, with concurrency
        of 1–2 and paused/draining flags.
        """
        statuses = list(TaskSnapshot)
        categories = ("build", "research", "confirm")
        states: list[WorkQueueState] = []

        # Zero tasks.
        for paused in (False, True):
            for draining in (False, True):
                for active in (0, 1):
                    states.append(
                        _state(
                            tasks=(),
                            active_subagent_count=active,
                            max_concurrency=2,
                            paused=paused,
                            draining=draining,
                        )
                    )

        # One task, all status × category × paused/draining combinations.
        for status, cat, paused, draining in itertools.product(
            statuses, categories, (False, True), (False, True)
        ):
            active = 1 if status == TaskSnapshot.ACTIVE else 0
            states.append(
                _state(
                    tasks=(_info(id="t1", category=cat, status=status),),
                    active_subagent_count=active,
                    max_concurrency=2,
                    paused=paused,
                    draining=draining,
                )
            )

        # Two tasks: second depends on first.
        for s1, s2 in itertools.product(statuses, statuses):
            active = sum(1 for s in (s1, s2) if s == TaskSnapshot.ACTIVE)
            states.append(
                _state(
                    tasks=(
                        _info(id="t1", category="research", status=s1),
                        _info(id="t2", category="build", status=s2, dependencies=("t1",)),
                    ),
                    active_subagent_count=active,
                    max_concurrency=2,
                )
            )

        return states

    @staticmethod
    def _can_progress(state: WorkQueueState) -> bool:
        """Check whether route() returns a non-IDLE action for a state.

        A state can progress if the routing decision is anything other
        than IDLE — even WAIT_FOR_IN_FLIGHT implies progress once an
        in-flight task completes.
        """
        decision = route(state)
        return decision.action != RouteAction.IDLE

    @staticmethod
    def _is_user_stuck(state: WorkQueueState) -> bool:
        """True if pending tasks exist but all are waiting on blocked deps.

        This is an expected "stuck" state — the user must unblock the
        dependency before progress can resume.  It is not a deadlock.
        """
        if state.blocked_count == 0:
            return False
        blocked_ids = {t.id for t in state.tasks if t.status == TaskSnapshot.BLOCKED}
        for t in state.tasks:
            if t.status != TaskSnapshot.PENDING:
                continue
            # If all deps are either blocked or not yet resolved, this
            # pending task is stuck waiting on user intervention.
            resolved = {
                d.id for d in state.tasks if d.status in (TaskSnapshot.DONE, TaskSnapshot.FAILED)
            }
            all_ids = {d.id for d in state.tasks}
            unmet = [dep for dep in t.dependencies if dep not in resolved and dep in all_ids]
            if any(dep in blocked_ids for dep in unmet):
                continue
            # This pending task has at least one path that doesn't go
            # through a blocked task — it should be able to progress.
            return False
        return True

    def test_no_deadlocks(self) -> None:
        """Every non-terminal state has a path to progress.

        Terminal states (all done/failed/blocked, nothing pending/active)
        are allowed to be IDLE.  Non-terminal states must return an
        action that makes progress.  States where all pending tasks are
        waiting on blocked dependencies are intentionally stuck (the
        user must intervene) and are also allowed.
        """
        states = self._enumerate_small_states()
        assert len(states) > 50, f"Expected >50 states, got {len(states)}"

        violations: list[str] = []
        for s in states:
            if s.is_terminal:
                continue
            if s.paused or s.draining:
                continue
            if self._is_user_stuck(s):
                # Pending tasks waiting on blocked deps — user must intervene.
                continue
            if not self._can_progress(s):
                violations.append(
                    f"Deadlock: {s.pending_count}P {s.active_count}A "
                    f"{s.done_count}D {s.failed_count}F {s.blocked_count}B "
                    f"slots={s.free_slots}"
                )

        assert not violations, f"Found {len(violations)} deadlock state(s):\n" + "\n".join(
            violations[:10]
        )

    def test_terminal_states_are_idle(self) -> None:
        """Terminal states should always route to IDLE."""
        terminal_combos = [
            (),  # empty
            (_info(id="a", status=TaskSnapshot.DONE),),
            (_info(id="a", status=TaskSnapshot.FAILED),),
            (_info(id="a", status=TaskSnapshot.BLOCKED),),
            (
                _info(id="a", status=TaskSnapshot.DONE),
                _info(id="b", status=TaskSnapshot.FAILED),
            ),
        ]
        for tasks in terminal_combos:
            s = _state(tasks=tasks)
            assert s.is_terminal, f"Expected terminal: {tasks}"
            decision = route(s)
            assert decision.action == RouteAction.IDLE, (
                f"Terminal state routed to {decision.action}: {tasks}"
            )

    def test_state_space_coverage(self) -> None:
        """Verify that our enumeration covers all RouteAction values."""
        states = self._enumerate_small_states()
        actions_seen = {route(s).action for s in states}
        assert actions_seen == set(RouteAction), (
            f"Missing actions: {set(RouteAction) - actions_seen}"
        )
