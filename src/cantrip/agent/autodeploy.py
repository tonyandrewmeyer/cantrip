"""Auto-deploy loop — pure follow-up logic for autonomous task chaining.

Provides functions that inspect completed tasks and produce follow-up tasks,
closing the deploy → verify → diagnose feedback loop.  All functions are pure
(no side effects, no executor/watcher dependencies) so they are trivial to
test without mocking.
"""

from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.agent.state import AgentState
from cantrip.agent.watcher import WatcherEvent, format_event_for_agent

# Verification task title prefix, used to identify verify tasks in follow-up logic.
_VERIFY_PREFIX = "Verify deployment:"

# Watcher-generated task title prefix.
_WATCHER_PREFIX = "[Watcher]"

# Event categories that map to DEBUG tasks.
_DEBUG_CATEGORIES = frozenset({"hook_failure", "status_change", "log_error"})

# Event categories that map to INFRA tasks.
_INFRA_CATEGORIES = frozenset(
    {
        "new_app",
        "removed_app",
        "new_relation",
        "new_unit",
        "removed_unit",
    }
)


# ---------------------------------------------------------------------------
# Post-task follow-up functions
# ---------------------------------------------------------------------------


def tasks_after_deploy(task: AgentTask) -> list[AgentTask]:
    """Return verification tasks to run after a successful DEPLOY task.

    Only produces follow-ups for DEPLOY tasks that completed successfully.
    The verification task checks ``juju_status`` and ``juju_wait`` to confirm
    the deployment reached active/idle.
    """
    if task.category != TaskCategory.DEPLOY:
        return []
    if task.status != TaskStatus.DONE:
        return []

    return [
        AgentTask(
            title=f"{_VERIFY_PREFIX} {task.title}",
            category=TaskCategory.DEPLOY,
            description=(
                "Verify the deployment reached active/idle status.\n\n"
                "1. Run `juju_status` to check current unit statuses.\n"
                "2. Run `juju_wait` to confirm the application is ready.\n"
                "3. Report success or failure with details."
            ),
            dependencies=[task.id],
        ),
    ]


def tasks_after_verify(task: AgentTask) -> list[AgentTask]:
    """Return diagnostic tasks when a verification task fails.

    Only produces follow-ups for failed verification tasks (title starts
    with the verify prefix).  The diagnostic task uses COS-driven tools
    to investigate the failure.
    """
    if not task.title.startswith(_VERIFY_PREFIX):
        return []
    if task.status != TaskStatus.FAILED:
        return []

    failure_detail = task.result or "No failure details recorded."

    return [
        AgentTask(
            title=f"Diagnose deployment failure: {task.title.removeprefix(_VERIFY_PREFIX).strip()}",
            category=TaskCategory.DEBUG,
            description=(
                "The deployment verification failed. Investigate the root cause.\n\n"
                f"**Failure details:** {failure_detail}\n\n"
                "1. Check `juju_debug_log` for error tracebacks.\n"
                "2. Query `loki_query` for related log entries.\n"
                "3. Query `tempo_query` for recent traces.\n"
                "4. Diagnose the root cause and report findings."
            ),
            dependencies=[task.id],
        ),
    ]


def tasks_after_build(task: AgentTask) -> list[AgentTask]:
    """Return a deploy task to run after a successful BUILD task.

    Closes the build → deploy gap so that code changes are automatically
    deployed without waiting for the user to request it.  Only fires for
    BUILD tasks that completed successfully.
    """
    if task.category != TaskCategory.BUILD:
        return []
    if task.status != TaskStatus.DONE:
        return []

    return [
        AgentTask(
            title=f"Deploy changes: {task.title}",
            category=TaskCategory.DEPLOY,
            description=(
                "The build task completed. Pack and deploy the updated charm.\n\n"
                "1. Run `charmcraft_pack` to produce a .charm file.\n"
                "2. Run `juju_refresh` with the new charm path.\n"
                "3. Run `juju_wait` to confirm the application is ready.\n"
                "4. Report success or failure with details."
            ),
            dependencies=[task.id],
        ),
    ]


def followup_tasks(task: AgentTask) -> list[AgentTask]:
    """Return any follow-up tasks for a completed or failed task.

    Single entry point that dispatches to the specific handlers.  The chain
    is bounded: BUILD → DEPLOY → Verify → (fail) → DEBUG → done.  DEBUG
    tasks produce no further follow-ups.
    """
    results: list[AgentTask] = []
    results.extend(tasks_after_build(task))
    results.extend(tasks_after_deploy(task))
    results.extend(tasks_after_verify(task))
    return results


# ---------------------------------------------------------------------------
# Watcher event → task conversion
# ---------------------------------------------------------------------------


def task_for_watcher_event(event: WatcherEvent, state: AgentState) -> AgentTask | None:
    """Convert a watcher event into an agent task.

    Returns ``None`` if no ``dev_model`` is set or the event category is
    unrecognised.  Uses ``format_event_for_agent()`` to build the task
    description so subagents receive the same investigation instructions
    as the conversation loop previously did.
    """
    if not state.dev_model:
        return None

    if event.category in _DEBUG_CATEGORIES:
        category = TaskCategory.DEBUG
    elif event.category in _INFRA_CATEGORIES:
        category = TaskCategory.INFRA
    else:
        return None

    description = format_event_for_agent(event)

    return AgentTask(
        title=f"{_WATCHER_PREFIX} {event.summary}",
        category=category,
        description=description,
    )
