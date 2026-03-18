"""Auto-deploy loop — pure follow-up logic for autonomous task chaining.

Provides functions that inspect completed tasks and produce follow-up tasks,
closing the deploy → verify → diagnose feedback loop.  All functions are pure
(no side effects, no executor/watcher dependencies) so they are trivial to
test without mocking.
"""

import re

from cantrip.agent.planner import SPRINT_BUILD_PREFIX
from cantrip.agent.queue import AgentTask, ModelHint, TaskCategory, TaskStatus
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
    # Don't create a verify for a task that is already a verification.
    if task.title.startswith(_VERIFY_PREFIX):
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

    Sprint build tasks already have an explicit DEPLOY task in the plan,
    so no follow-up is needed.
    """
    if task.category != TaskCategory.BUILD:
        return []
    if task.status != TaskStatus.DONE:
        return []
    # Sprint builds already have an explicit deploy task — skip follow-up.
    if task.title.startswith(SPRINT_BUILD_PREFIX):
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


def tasks_after_test(task: AgentTask) -> list[AgentTask]:
    """Return a demo generation task after a successful TEST task.

    After the charm passes validation, the demo task captures live
    deployment output and writes DEMO.md, demo.sh, and TUTORIAL.md.
    Only fires once — the demo BUILD task's own completion triggers
    ``tasks_after_build`` (→ deploy), not another demo.
    """
    if task.category != TaskCategory.TEST:
        return []
    if task.status != TaskStatus.DONE:
        return []
    # Don't generate a demo for a demo-validation task.
    if _DEMO_PREFIX in task.title:
        return []

    return [
        AgentTask(
            title=f"{_DEMO_PREFIX} charm artefacts",
            category=TaskCategory.BUILD,
            model_hint=ModelHint.PRIMARY,
            description=(
                "The charm has been deployed and tested successfully. "
                "Generate demo artefacts from the live deployment.\n\n"
                "Create a `demo/` directory and produce:\n"
                "1. `demo/juju-status.txt` — `juju_status` output with relations\n"
                "2. `demo/config-reference.txt` — `juju_config` dump\n"
                "3. `demo/actions/` — JSON results from each charm action\n"
                "4. `demo/logs/event-log.txt` — recent `juju_debug_log` snippet\n"
                "5. `DEMO.md` — annotated walk-through with real command output "
                "interleaved with explanations from WORKLOAD.md and DESIGN.md\n"
                "6. `demo.sh` — self-contained deployment script (deploy, relate, "
                "configure, verify) with an optional `--cleanup` flag\n"
                "7. `TUTORIAL.md` — step-by-step guide covering prerequisites, "
                "deployment, verification, features, observability, and "
                "troubleshooting\n\n"
                "Commit all demo artefacts in a single commit."
            ),
            dependencies=[task.id],
        ),
    ]


# Title prefix for demo generation tasks — used to prevent loops.
_DEMO_PREFIX = "Generate demo"


def tasks_after_build_failure(task: AgentTask) -> list[AgentTask]:
    """Return a targeted BUILD retry when integration tests partially pass.

    When a BUILD task fails and its result contains a pytest summary showing
    some tests passing and some failing, we spawn a follow-up BUILD task
    focused on the remaining failures rather than a generic DEBUG task.
    This keeps the red/green iteration loop going.

    Only fires when:
    - The task is a failed BUILD task.
    - The result mentions test failures with a recognisable pytest summary.
    - At least one test passed (partial progress — worth iterating).
    - The task title does not already indicate a retry (prevent infinite loops).
    """
    if task.category != TaskCategory.BUILD:
        return []
    if task.status != TaskStatus.FAILED:
        return []
    if not task.result:
        return []
    # Prevent infinite retry chains.
    if task.title.startswith(_RETRY_PREFIX):
        return []

    counts = _extract_test_counts(task.result)
    if not counts:
        return []

    passed = counts.get("passed", 0)
    failed = counts.get("failed", 0) + counts.get("error", 0)
    if passed == 0 or failed == 0:
        # No partial progress, or all passing (shouldn't be here) — skip.
        return []

    return [
        AgentTask(
            title=f"{_RETRY_PREFIX} fix {failed} failing integration test(s)",
            category=TaskCategory.BUILD,
            model_hint=ModelHint.PRIMARY,
            description=(
                f"The previous build task had {passed} integration tests passing "
                f"and {failed} failing. Fix the charm code to make the remaining "
                f"tests pass.\n\n"
                f"**Previous result (excerpt):**\n"
                f"{_tail(task.result, 2000)}\n\n"
                "Steps:\n"
                "1. Read the failing test output to understand what went wrong.\n"
                "2. Read the relevant charm code and integration test files.\n"
                "3. Fix the charm code — do NOT modify the integration tests "
                "(they define the contract).\n"
                "4. Run `run_charm_tests` with `test_type='integration'` to verify.\n"
                "5. Iterate until green, then commit."
            ),
            dependencies=[task.id],
        ),
    ]


# Prefix for retry tasks — used to prevent infinite retry chains.
_RETRY_PREFIX = "[Red/Green retry]"

# Regex matching pytest summary counts in subagent result text.
_PYTEST_COUNTS_RE = re.compile(r"(\d+) (passed|failed|error|skipped)")


def _extract_test_counts(text: str) -> dict[str, int]:
    """Extract pytest-style pass/fail counts from free-form text.

    Looks for patterns like "3 passed", "2 failed", "1 error" anywhere
    in the text — not necessarily on a single line.
    """
    counts: dict[str, int] = {}
    for match in _PYTEST_COUNTS_RE.finditer(text):
        key = match.group(2)
        counts[key] = counts.get(key, 0) + int(match.group(1))
    return counts


def _tail(text: str, max_chars: int) -> str:
    """Return the last *max_chars* characters of *text*."""
    if len(text) <= max_chars:
        return text
    return "..." + text[-max_chars:]


def followup_tasks(task: AgentTask) -> list[AgentTask]:
    """Return any follow-up tasks for a completed or failed task.

    Single entry point that dispatches to the specific handlers.  The chain
    is bounded: BUILD → DEPLOY → Verify → (fail) → DEBUG → done.  DEBUG
    tasks produce no further follow-ups.

    For failed BUILD tasks with partial test progress, a targeted retry
    BUILD task is created instead of falling through to DEBUG.
    """
    results: list[AgentTask] = []
    results.extend(tasks_after_build(task))
    results.extend(tasks_after_build_failure(task))
    results.extend(tasks_after_deploy(task))
    results.extend(tasks_after_verify(task))
    results.extend(tasks_after_test(task))
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
