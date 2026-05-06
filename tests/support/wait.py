"""Polling helpers for async tests.

Replaces fixed ``asyncio.sleep`` waits in executor / queue tests with
explicit predicate polling.  A test that wants "the executor has done
X" should ask for X directly rather than guess a sleep duration that's
"probably" long enough on a fast laptop and structurally flaky on a
slow CI runner.

The helpers return as soon as the predicate holds, with a default
timeout that's well above the executor's 1-second poll interval so
real waits don't spuriously trip.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from cantrip.agent.queue import AgentTask, TaskStatus, WorkQueue

DEFAULT_TIMEOUT = 5.0
DEFAULT_INTERVAL = 0.02


async def wait_until(
    predicate: Callable[[], bool],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_INTERVAL,
    message: str | None = None,
) -> None:
    """Poll *predicate* until it returns True or *timeout* elapses.

    Raises ``TimeoutError`` (with *message* if given) when the deadline
    passes without the predicate going true.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        if predicate():
            return
        if asyncio.get_event_loop().time() >= deadline:
            raise TimeoutError(message or f"predicate did not hold within {timeout}s")
        await asyncio.sleep(interval)


async def wait_for_task_status(
    task: AgentTask,
    status: TaskStatus,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_INTERVAL,
) -> None:
    """Wait until *task* reaches *status*."""
    await wait_until(
        lambda: task.status == status,
        timeout=timeout,
        interval=interval,
        message=(
            f"task {task.id!r} did not reach status {status.value} within {timeout}s "
            f"(current: {task.status.value})"
        ),
    )


async def wait_for_queue_state(
    queue: WorkQueue,
    *,
    done_count: int | None = None,
    failed_count: int | None = None,
    blocked_count: int | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_INTERVAL,
) -> None:
    """Wait until the queue's status counts hit the requested thresholds.

    Each ``*_count`` argument is treated as a lower bound: the predicate
    holds when every requested count is at least the given value.
    """

    def _counts() -> tuple[int, int, int]:
        done = failed = blocked = 0
        for t in queue.all_tasks():
            if t.status == TaskStatus.DONE:
                done += 1
            elif t.status == TaskStatus.FAILED:
                failed += 1
            elif t.status == TaskStatus.BLOCKED:
                blocked += 1
        return done, failed, blocked

    def _ready() -> bool:
        done, failed, blocked = _counts()
        if done_count is not None and done < done_count:
            return False
        if failed_count is not None and failed < failed_count:
            return False
        return not (blocked_count is not None and blocked < blocked_count)

    try:
        await wait_until(_ready, timeout=timeout, interval=interval)
    except TimeoutError:
        done, failed, blocked = _counts()
        raise TimeoutError(
            f"queue did not reach expected state within {timeout}s "
            f"(want done>={done_count}, failed>={failed_count}, "
            f"blocked>={blocked_count}; "
            f"got done={done}, failed={failed}, blocked={blocked}; "
            f"tasks={[(t.id, t.title, t.status.value) for t in queue.all_tasks()]})"
        ) from None


async def wait_for_value(
    getter: Callable[[], int],
    *,
    at_least: int,
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_INTERVAL,
    name: str = "value",
) -> None:
    """Wait until ``getter()`` returns at least *at_least*.

    Useful when a test wants to wait on a counter (e.g. "the executor
    has called ``_execute_task`` at least twice") rather than on task
    state directly.
    """
    await wait_until(
        lambda: getter() >= at_least,
        timeout=timeout,
        interval=interval,
        message=f"{name} did not reach {at_least} within {timeout}s (last: {getter()})",
    )
