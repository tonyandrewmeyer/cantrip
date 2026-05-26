"""Auto-deploy loop — pure follow-up logic for autonomous task chaining.

Provides functions that inspect completed tasks and produce follow-up tasks,
closing the deploy → verify → diagnose feedback loop.  All functions are pure
(no side effects, no executor/watcher dependencies) so they are trivial to
test without mocking.
"""

import re

from cantrip.agent.planner import OPERABILITY_PREFIX, SPRINT_BUILD_PREFIX
from cantrip.agent.queue import AgentTask, ModelHint, TaskCategory, TaskStatus
from cantrip.agent.state import AgentState
from cantrip.agent.subagent import _ACCEPTANCE_PREFIX
from cantrip.agent.watcher import WatcherEvent, format_event_for_agent

# Title prefix for demo generation tasks — used to prevent loops.
_DEMO_TITLE_PREFIX = "Generate demo"

# Phase 97.3: OpenStack-specific acceptance task.  Title format mirrors
# the base ``_ACCEPTANCE_PREFIX`` shape so the loop-prevention guard in
# ``tasks_after_test`` skips it on follow-up just like the base task.
_OPENSTACK_ACCEPTANCE_TITLE = (
    f"{_ACCEPTANCE_PREFIX} verify against AZ loss and volume detach (OpenStack)"
)

# Clouds that surface as "Canonical OpenStack tenant" — Sunbeam shares
# the same tenant API, so both should trigger the OpenStack acceptance
# task.  Kept in sync with ``preflight._OPENSTACK_CLOUD_NAMES``.
_OPENSTACK_TARGET_CLOUDS = frozenset({"openstack", "sunbeam"})

# Prefix for retry tasks — used to prevent infinite retry chains.
_RETRY_PREFIX = "[Red/Green retry]"

# Prefix for acceptance fix tasks — used to prevent infinite fix chains.
_ACCEPTANCE_FIX_PREFIX = "[Acceptance fix]"

# Verification task title prefix, used to identify verify tasks in follow-up logic.
_VERIFY_PREFIX = "Verify deployment:"

# Watcher-generated task title prefix.
_WATCHER_PREFIX = "[Watcher]"

# Event categories that map to DEBUG tasks.
_DEBUG_CATEGORIES = frozenset(
    {
        "hook_failure",
        "status_change",
        "log_error",
        "databag_change",
    }
)

# Event categories that map to INFRA tasks.
_INFRA_CATEGORIES = frozenset(
    {
        "new_app",
        "removed_app",
        "new_relation",
        "new_unit",
        "removed_unit",
        "new_offer",
        "removed_offer",
        "offer_connection_change",
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
    """Return an acceptance test task after a successful TEST task.

    After the charm passes validation, the acceptance task exercises the
    live deployment: running actions, testing relations, probing endpoints,
    and varying config.  The acceptance task's own completion triggers
    ``tasks_after_acceptance`` which produces the demo.

    Skips if the task is already an acceptance or demo task to prevent loops.
    """
    if task.category != TaskCategory.TEST:
        return []
    if task.status != TaskStatus.DONE:
        return []
    # Don't chain from acceptance or demo tasks.
    if task.title.startswith(_ACCEPTANCE_PREFIX):
        return []
    if _DEMO_TITLE_PREFIX in task.title:
        return []

    return [
        AgentTask(
            title=f"{_ACCEPTANCE_PREFIX} put the charm through its paces",
            category=TaskCategory.TEST,
            model_hint=ModelHint.PRIMARY,
            description=(
                "The charm has been deployed and passed integration tests. "
                "Now exercise it like a real operator would.\n\n"
                "1. Run `action_exerciser` to test all charm actions.\n"
                "2. Run `relation_smoke_test` to verify integrations.\n"
                "3. Run `workload_endpoint_test` to probe endpoints.\n"
                "4. Run `config_variation_test` to verify config options.\n"
                "5. Run `scaling_test` to test scaling behaviour.\n"
                "6. Run `acceptance_report` to consolidate results into "
                "ACCEPTANCE.md.\n\n"
                "Report the overall verdict. Failures become follow-up tasks."
            ),
            dependencies=[task.id],
        ),
    ]


def openstack_acceptance_task(task: AgentTask, *, active_cloud: str) -> list[AgentTask]:
    """Return an OpenStack-specific acceptance task when relevant (Phase 97.3).

    Fires alongside :func:`tasks_after_test` when the active controller's
    cloud is in :data:`_OPENSTACK_TARGET_CLOUDS`.  The new task verifies
    the resilience properties Canonical OpenStack tenants care about
    most — AZ-loss survival and volume-detach recovery — which the
    generic acceptance task doesn't reach for.

    Skips for non-TEST tasks, non-DONE tasks, or when the cloud is
    unknown / not OpenStack.  Avoids chaining off acceptance / demo /
    its own previous outputs so the loop-prevention guarantees the
    base path provides still hold.
    """
    if task.category != TaskCategory.TEST:
        return []
    if task.status != TaskStatus.DONE:
        return []
    if task.title.startswith(_ACCEPTANCE_PREFIX):
        return []
    if _DEMO_TITLE_PREFIX in task.title:
        return []
    if (active_cloud or "").lower() not in _OPENSTACK_TARGET_CLOUDS:
        return []
    return [
        AgentTask(
            title=_OPENSTACK_ACCEPTANCE_TITLE,
            category=TaskCategory.TEST,
            model_hint=ModelHint.PRIMARY,
            description=(
                "The charm has been deployed and passed integration tests on a "
                "Canonical OpenStack / Sunbeam controller. Verify the resilience "
                "properties OpenStack tenants depend on:\n\n"
                "1. Simulate AZ loss: drain one availability zone (or stop the "
                "compute node hosting a unit) and confirm the workload recovers "
                "without manual intervention.\n"
                "2. Volume detach: detach the persistent volume from a unit "
                "(`openstack volume detach …` or via Juju storage), reattach, "
                "and confirm the charm reaches `active/idle` with data intact.\n"
                "3. Record outcomes in ACCEPTANCE.md under an "
                "`## OpenStack resilience` heading. Failures become follow-up "
                "tasks the usual way."
            ),
            dependencies=[task.id],
        ),
    ]


def tasks_after_acceptance(task: AgentTask) -> list[AgentTask]:
    """Return demo and operability tasks after acceptance testing completes.

    Only fires for completed acceptance test tasks (title starts with
    the acceptance prefix).  Produces a demo BUILD task and an operability
    assessment RESEARCH task, both depending on the acceptance task.
    """
    if task.category != TaskCategory.TEST:
        return []
    if task.status != TaskStatus.DONE:
        return []
    if not task.title.startswith(_ACCEPTANCE_PREFIX):
        return []

    results = [
        AgentTask(
            title=f"{_DEMO_TITLE_PREFIX} charm artefacts",
            category=TaskCategory.BUILD,
            model_hint=ModelHint.PRIMARY,
            description=(
                "The charm has been deployed, tested, and acceptance-tested. "
                "Generate demo artefacts from the live deployment.\n\n"
                "Create a `demo/` directory and produce:\n"
                "1. `demo/juju-status.txt` — `juju_status` output\n"
                "2. `demo/config-reference.txt` — `juju_config` dump\n"
                "3. `demo/actions/` — JSON results from each charm action\n"
                "4. `demo/logs/event-log.txt` — recent `juju_debug_log` snippet\n"
                "5. `demo/traces/` — Tempo trace data and span summary "
                "(skip if COS unavailable)\n"
                "6. `demo/screenshots/` — Grafana dashboard and web UI "
                "screenshots via Rodney (skip if unavailable)\n"
                "7. `demo/dashboards/` — Grafana dashboard JSON export "
                "(skip if unavailable)\n"
                "8. `DEMO.md` — annotated walk-through (prefer Showboat if "
                "available) with real command output, relation wiring, "
                "action/config showcases, and embedded screenshots\n"
                "9. `demo.sh` — self-contained deployment script with "
                "`--cleanup` flag\n"
                "10. `TUTORIAL.md` — quick-start section at top, then full "
                "step-by-step guide\n\n"
                "Commit all demo artefacts in a single commit."
            ),
            dependencies=[task.id],
        ),
        # Operability assessment runs in parallel with demo generation.
        AgentTask(
            title=(f"{OPERABILITY_PREFIX} Assess operational readiness"),
            category=TaskCategory.RESEARCH,
            model_hint=ModelHint.PRIMARY,
            description=(
                "Run the `operational_readiness` tool on the charm to evaluate "
                "it against Canonical's Operational Readiness Metrics.\n\n"
                "1. Run `operational_readiness` on the charm directory.\n"
                "2. Review OPERATIONAL_READINESS.md.\n"
                "3. Summarise per-pillar scores and must-fix items for the user."
            ),
            dependencies=[task.id],
        ),
    ]

    return results


def tasks_after_acceptance_failure(task: AgentTask) -> list[AgentTask]:
    """Return a targeted BUILD fix when acceptance tests find failures.

    When an acceptance test task completes (successfully — the subagent ran)
    but its result text mentions failing acceptance sections, we spawn a
    BUILD task to fix the identified issues.  This closes the acceptance →
    fix → redeploy → re-test loop.

    Only fires when:
    - The task is a completed TEST task with the acceptance prefix.
    - The result mentions at least one FAIL verdict.
    - The task title does not already indicate a fix (prevent infinite loops).
    """
    if task.category != TaskCategory.TEST:
        return []
    if task.status != TaskStatus.DONE:
        return []
    if not task.title.startswith(_ACCEPTANCE_PREFIX):
        return []
    # Prevent infinite fix chains.
    if _ACCEPTANCE_FIX_PREFIX in task.title:
        return []
    if not task.result:
        return []

    failures = _extract_acceptance_failures(task.result)
    if not failures:
        return []

    failure_list = "\n".join(f"- {f}" for f in failures)

    return [
        AgentTask(
            title=f"{_ACCEPTANCE_FIX_PREFIX} fix {len(failures)} acceptance failure(s)",
            category=TaskCategory.BUILD,
            model_hint=ModelHint.PRIMARY,
            description=(
                f"Acceptance testing found {len(failures)} failing area(s):\n"
                f"{failure_list}\n\n"
                f"**Acceptance result (excerpt):**\n"
                f"{_tail(task.result, 2000)}\n\n"
                "Steps:\n"
                "1. Read ACCEPTANCE.md and the charm code to understand each failure.\n"
                "2. Fix the charm code to address the failures — do NOT remove or "
                "weaken the acceptance tests.\n"
                "3. Run `charmcraft_pack` and `juju_refresh` to redeploy.\n"
                "4. Run `juju_wait` to confirm the deployment is healthy.\n"
                "5. Re-run the failing acceptance tools to verify the fixes.\n"
                "6. Commit once green."
            ),
            dependencies=[task.id],
        ),
    ]


# Patterns that indicate acceptance test failures in subagent result text.
# Each pattern matches within a single line to avoid cross-line false
# positives.  Both patterns anchor the area keyword with ``\b`` word
# boundaries (plus an optional ``s`` for plurals) so ``actionable`` or
# ``relationship`` no longer match.
_AREA_KEYWORD_GROUP = (
    r"(?P<area>action|relation|endpoint|config|configuration|scaling|lifecycle)s?"
)

# Structured verdict: "Actions: FAIL" or "Relations: FAIL (1/2) — reason".
# The area appears as a whole word before an optional parenthetical count,
# then a ``:`` and FAIL.
_ACCEPTANCE_VERDICT_RE = re.compile(
    rf"\b{_AREA_KEYWORD_GROUP}\b[^\n:]*:\s*FAIL",
    re.IGNORECASE,
)

# Prose: "the relation test failed" or "endpoint checks failed".  The area
# appears before an explicit failure verb (``fail``/``broken``) within 60
# characters on the same line.  ``error`` on its own has been dropped from
# the old pattern — too broad without context, and caused false positives
# like "executed without error".
_ACCEPTANCE_PROSE_FAIL_RE = re.compile(
    rf"\b{_AREA_KEYWORD_GROUP}\b[^\n]{{0,60}}?(?:fail(?:ed|ure|ures|ing|s)?|broken)",
    re.IGNORECASE,
)

# Negation phrases that must disqualify a prose match.  Anchored with
# ``\b`` so ``non-failing`` and "no failures" both trigger; kept
# deliberately small to avoid false *negatives* on slightly exotic
# phrasing.
_NEGATED_FAIL_IN_SNIPPET_RE = re.compile(
    r"\b(?:"
    r"no\s+fail\w*|"
    r"no\s+broken|"
    r"not\s+fail\w*|"
    r"never\s+fail\w*|"
    r"did\s+not\s+fail\w*|"
    r"didn[''']t\s+fail\w*|"
    r"without\s+fail\w*"
    r")\b",
    re.IGNORECASE,
)

# Normalised area labels keyed by the lowercased singular keyword the
# regex captures.
_AREA_LABEL = {
    "action": "actions",
    "relation": "relations",
    "endpoint": "endpoints",
    "config": "config options",
    "configuration": "config options",
    "scaling": "scaling",
    "lifecycle": "lifecycle",
}


def _extract_acceptance_failures(text: str) -> list[str]:
    """Extract failing acceptance areas from free-form subagent result text.

    Returns a deduplicated list of area names (e.g. "actions", "relations")
    whose verdict or prose line mentions a genuine failure.  Matches
    containing obvious negation (``"no failures observed"``) are
    discarded rather than flagged.
    """
    areas: dict[str, None] = {}

    for pattern in (_ACCEPTANCE_VERDICT_RE, _ACCEPTANCE_PROSE_FAIL_RE):
        for match in pattern.finditer(text):
            if pattern is _ACCEPTANCE_PROSE_FAIL_RE and _NEGATED_FAIL_IN_SNIPPET_RE.search(
                match.group(0)
            ):
                continue
            keyword = match.group("area").lower()
            label = _AREA_LABEL.get(keyword)
            if label and label not in areas:
                areas[label] = None

    return list(areas)


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
    results.extend(tasks_after_acceptance(task))
    results.extend(tasks_after_acceptance_failure(task))
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
