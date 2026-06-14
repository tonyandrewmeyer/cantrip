"""Background executor — picks ready tasks and runs subagents."""

import asyncio
import contextlib
import logging
import pathlib
import time
from collections.abc import Callable

from cantrip.agent.context import lint_context
from cantrip.agent.executor._race import RaceMixin
from cantrip.agent.executor._worktree import WorktreeMixin
from cantrip.agent.executor.git_service import _DefaultGitService
from cantrip.agent.executor.policies import (
    _DefaultEnvironmentChecker,
    _DefaultFollowupPlanner,
)
from cantrip.agent.executor.store_adapter import _SessionStoreAdapter
from cantrip.agent.git.worktree import _DefaultWorktreeAllocator
from cantrip.agent.policy import routing
from cantrip.agent.policy.policy import (
    MCP_TOOL_PREFIX,
    ORG_WIDE_POLICY,
    compose_policies,
    discover_policies,
)
from cantrip.agent.policy.routing import RouteAction, route, snapshot_from_queue
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.race import race
from cantrip.agent.runtime.goal_budget import check_budget
from cantrip.agent.safety.permissions import (
    PLAN_MODE_OVERLAY,
    PermissionDecision,
    PermissionManager,
    PermissionRuleset,
    compose_rulesets,
    discover_permissions,
)
from cantrip.agent.services import (
    EnvironmentChecker,
    FollowupPlanner,
    GitService,
    StateService,
    WorktreeAllocator,
)
from cantrip.agent.state import AgentState
from cantrip.agent.store import SessionStore
from cantrip.agent.subagent import (
    MAX_BUILD_ROUNDS,
    ExitState,
    ProviderThrottle,
    Subagent,
    SubagentContext,
    SubagentResult,
    ToolInvokedCallback,
    ToolInvokedPendingCallback,
)
from cantrip.agent.tools.base import Tool
from cantrip.hooks import HookRunner
from cantrip.llm import base as llm

log = logging.getLogger(__name__)

_POLL_INTERVAL = 1.0  # seconds between checking for ready tasks
DEFAULT_MAX_CONCURRENCY = 3

# Per-category wall-clock limits.  Research is cheaper so gets a shorter
# leash; build and deploy may run charmcraft/juju and need more headroom.
_TASK_TIMEOUTS: dict[TaskCategory, int] = {
    TaskCategory.RESEARCH: 300,
    TaskCategory.BUILD: 900,
    TaskCategory.DEPLOY: 900,
    TaskCategory.TEST: 600,
    TaskCategory.DEBUG: 600,
}
_DEFAULT_TASK_TIMEOUT = 600

# Maximum number of consecutive noops before escalating to the user.
_MAX_NOOP_COUNT = 2

# After this many consecutive loop errors the executor gives up.
_MAX_CONSECUTIVE_ERRORS = 10

# Cooldown after an unexpected loop error to prevent tight spin.
_ERROR_COOLDOWN = 5.0

# Called when a task completes or fails, for TUI/conversation-loop coordination.
TaskEventCallback = Callable[[AgentTask], None] | None

# Phase 55.3: callback fired when the goal budget trips before a task
# spawn.  ``reason`` is the block string from ``goal_budget.check_budget``,
# suitable for display in the TUI / Web chat.  The executor has already
# marked the task BLOCKED by the time the callback fires.
BudgetExceededCallback = Callable[[AgentTask, str], None] | None

# Phase 80.3: callback fired when the per-goal tool-call counter trips
# the composed policy's ``max_calls_per_request`` cap before a task
# spawn.  Args: (task, tool_calls_made, cap, policy_name).  The
# executor has already marked the task BLOCKED by the time the
# callback fires.
RateLimitedCallback = Callable[[AgentTask, int, int, str], None] | None


# ---------------------------------------------------------------------------
# BackgroundExecutor
# ---------------------------------------------------------------------------


class BackgroundExecutor(RaceMixin, WorktreeMixin):
    """Orchestrator that picks tasks from the work queue and runs subagents.

    Runs as a background ``asyncio.Task`` concurrently with the conversation
    loop.  Each ready task is executed in an isolated ``Subagent`` context;
    results and failures are recorded back on the queue and persisted.

    When multiple independent tasks are ready (all dependencies met), the
    executor runs them concurrently up to *max_concurrency*.  A semaphore
    enforces the limit so LLM providers are not overwhelmed.

    The executor can be *paused* (e.g. while the user is steering via chat)
    and *resumed* afterwards.  While paused the poll loop sleeps without
    picking new tasks, but any task already running continues to completion.

    Services (git, environment checker, state persistence, follow-up
    planning) are injected via constructor parameters.  When not supplied,
    default implementations are used that delegate to subprocess calls
    and the ``SessionStore`` / ``AgentState``.
    """

    def __init__(
        self,
        queue: WorkQueue,
        tools: list[Tool],
        provider: llm.LLMProvider,
        state: AgentState,
        store: SessionStore | None = None,
        light_provider: llm.LLMProvider | None = None,
        on_task_done: TaskEventCallback = None,
        on_task_failed: TaskEventCallback = None,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        *,
        git_service: GitService | None = None,
        env_checker: EnvironmentChecker | None = None,
        state_service: StateService | None = None,
        followup_planner: FollowupPlanner | None = None,
        worktree_allocator: WorktreeAllocator | None = None,
        race_config: race.RaceConfig | None = None,
        extra_providers: list[llm.LLMProvider] | None = None,
        hook_runner: HookRunner | None = None,
        on_tool_invoked: ToolInvokedCallback | None = None,
        on_tool_invoked_pending: ToolInvokedPendingCallback | None = None,
        on_budget_exceeded: BudgetExceededCallback = None,
        on_rate_limited: RateLimitedCallback = None,
        on_cache_usage: Callable[[int, int], None] | None = None,
    ) -> None:
        self._queue = queue
        self._tools = tools
        self._provider = provider
        self._state = state
        self._store = store
        self._light_provider = light_provider
        self._on_task_done = on_task_done
        self._on_task_failed = on_task_failed
        self._max_concurrency = max(1, max_concurrency)
        self._hook_runner = hook_runner if hook_runner is not None else HookRunner()
        self._on_budget_exceeded = on_budget_exceeded
        self._on_rate_limited = on_rate_limited
        # Folds each subagent turn's prompt-cache tokens into the agent's
        # session-level accumulators so /cost counts subagent cache spend,
        # not just the main conversation loop's.
        self._on_cache_usage = on_cache_usage
        # Phase 80.3: compose the policy stack once per executor run to
        # read its ``max_calls_per_request`` cap.  The subagent's own
        # per-run enforcer still does tool-level ALLOW/DENY/REVIEW; the
        # rate limit is *goal-scoped*, so the counter has to live on
        # the executor where it can span subagent boundaries.
        charm_dir: pathlib.Path | None = (
            pathlib.Path(state.charm_path) if state.charm_path else None
        )
        composed = compose_policies(ORG_WIDE_POLICY, *discover_policies(charm_path=charm_dir))
        self._rate_limit_cap: int | None = composed.max_calls_per_request
        self._rate_limit_policy_name: str = composed.name
        self._tool_calls_made: int = 0
        # Phase 68.2: load the declarative permission stack once and
        # share it across every subagent dispatched by this executor.
        # Empty ruleset when discovery finds nothing — the evaluator's
        # default is "no rule → allow" so loading no files preserves
        # pre-Phase-68.2 behaviour.
        self._permissions: PermissionRuleset = discover_permissions(charm_path=charm_dir)
        # One manager per executor so a CONFIRM resolved on the
        # conversation loop can unblock whichever subagent asked.
        self._permission_manager: PermissionManager = PermissionManager()
        # Phase 80.3: wrap the user's ``on_tool_invoked`` so every
        # non-MCP tool call bumps the counter on its way through.  MCP
        # tools bypass — they're gated by the per-server
        # ``allowed_tools`` config (Phase 45.2), not by the policy
        # stack's rate limit.
        self._on_tool_invoked = self._wrap_tool_invoked(on_tool_invoked)
        # Phase 82: forward "running now" events to the chat surfaces;
        # no rate-limit accounting on the pending side — the count is
        # bumped only when the tool returns (post-call wrapper above).
        self._on_tool_invoked_pending = on_tool_invoked_pending

        # Injected services — fall back to defaults when not provided.
        self._git: GitService = git_service or _DefaultGitService()
        self._env_checker: EnvironmentChecker = env_checker or _DefaultEnvironmentChecker(state)
        self._state_service: StateService | None = state_service
        if self._state_service is None and store is not None:
            self._state_service = _SessionStoreAdapter(store)
        self._followup_planner: FollowupPlanner = followup_planner or _DefaultFollowupPlanner(
            state
        )
        self._worktrees: WorktreeAllocator = worktree_allocator or _DefaultWorktreeAllocator()
        # Serialises worktree-to-main merges so concurrent subagents do not
        # race on the main tree.
        self._merge_lock = asyncio.Lock()
        # Best-of-N racing is opt-in: the default RaceConfig has an empty
        # enabled_categories set so should_race() always returns False and
        # every task takes the single-subagent path.
        self._race_config = race_config or race.RaceConfig()
        self._extra_providers: list[llm.LLMProvider] = list(extra_providers or [])
        # The coordinator reuses the executor's allocator so composite-id
        # race worktrees live in the same bookkeeping as single-task ones
        # and the startup orphan-reaper sees both.
        self._race_coordinator = race.RaceCoordinator(
            allocator=self._worktrees,
            config=self._race_config,
        )

        self._running = False
        self._paused = False
        self._draining = False
        self._task: asyncio.Task | None = None
        # Track in-flight async tasks so the loop knows how many slots are free.
        self._active_tasks: set[asyncio.Task[None]] = set()
        self._semaphore: asyncio.Semaphore | None = None
        # Shared throttle so concurrent subagents coordinate on rate limits.
        self._throttle = ProviderThrottle()
        # Consecutive loop-level errors; used to detect persistent failures.
        self._consecutive_errors = 0
        # Phase 68.2: callback for permission events — consumed by the
        # agent layer (core.py) which forwards to the UI event bus and
        # drops a CONFIRM task when a subagent parks on an ``ask``.
        # Left ``None`` by default so unit tests that construct an
        # executor without a UI wiring still work.
        self._permission_callback: (
            Callable[[str, PermissionDecision, dict[str, object]], None] | None
        ) = None

    # -- Lifecycle -----------------------------------------------------------

    @property
    def running(self) -> bool:
        """Whether the executor loop is currently running."""
        return self._running

    @property
    def paused(self) -> bool:
        """Whether the executor is paused (not picking new tasks)."""
        return self._paused

    @property
    def max_concurrency(self) -> int:
        """Maximum number of tasks that can run concurrently."""
        return self._max_concurrency

    @property
    def draining(self) -> bool:
        """Whether the executor is draining (finishing in-flight, no new tasks)."""
        return self._draining

    @property
    def healthy(self) -> bool:
        """Whether the executor is running and not in a persistent error state."""
        return self.running and self._consecutive_errors < _MAX_CONSECUTIVE_ERRORS

    @property
    def permissions(self) -> PermissionRuleset:
        """Active permission ruleset — exposed for ``/permissions`` introspection.

        Includes the Phase 68.4 plan-mode overlay when
        ``state.plan_mode`` is ``True`` so callers (subagents, the
        custom-command shell gate, the main-agent tool dispatcher)
        automatically see read-only enforcement without each site
        remembering to compose it.
        """
        return self._effective_permissions()

    def _effective_permissions(self) -> PermissionRuleset:
        """Compose the base ruleset with the plan-mode overlay if active."""
        if self._state.plan_mode:
            return compose_rulesets(self._permissions, PLAN_MODE_OVERLAY)
        return self._permissions

    @property
    def permission_manager(self) -> PermissionManager:
        """Manager tracking outstanding permission ``ask`` requests."""
        return self._permission_manager

    def set_permission_callback(
        self,
        callback: Callable[[str, PermissionDecision, dict[str, object]], None] | None,
    ) -> None:
        """Register a UI-facing callback for permission decisions.

        Invoked every time a Phase 68.2 gate reaches a non-allow
        verdict.  The callback receives ``(tool_name, decision,
        arguments)``.  Set to ``None`` to clear.
        """
        self._permission_callback = callback

    def resolve_permission_ask(self, request_id: str, *, approved: bool) -> bool:
        """Resolve an outstanding ``ask`` with the user's decision.

        Returns ``True`` when a pending request matched *request_id*;
        ``False`` when the request timed out, was already answered, or
        never existed.
        """
        return self._permission_manager.resolve(request_id, approved=approved)

    def set_yolo(self, enabled: bool) -> None:
        """Phase 69.2: flip unattended mode on the shared manager.

        Thin pass-through used by the ``/yolo`` slash command and the
        ``--yolo`` CLI flag.  When enabled, every outstanding
        ``ask`` future resolves to approved so subagents already
        parked on a prompt don't stall the session.  ``deny``
        decisions still block — they never reach the manager.
        """
        self._permission_manager.set_yolo(enabled)

    def _on_permission_decided(
        self,
        tool_name: str,
        decision: PermissionDecision,
        arguments: dict[str, object],
    ) -> None:
        """Forward subagent permission decisions to the UI callback.

        Swallows callback errors so a broken UI hook can never crash
        the subagent loop — pattern matches ``_wrap_tool_invoked``.
        """
        if self._permission_callback is None:
            return
        try:
            self._permission_callback(tool_name, decision, arguments)
        except (TypeError, ValueError, RuntimeError, AttributeError):
            log.exception("permission_callback raised for tool %s", tool_name)

    def start(self) -> None:
        """Start the background poll-and-execute loop.

        Resets any tasks stuck in ACTIVE status back to PENDING so they
        are re-dispatched (they were interrupted by a previous shutdown).
        """
        if self._running:
            return
        self._cleanup_active_tasks()
        self._running = True
        self._paused = False
        self._draining = False
        self._semaphore = asyncio.Semaphore(self._max_concurrency)
        self._task = asyncio.create_task(self._run_loop())
        log.info("Background executor started (concurrency=%d)", self._max_concurrency)

    async def stop(self) -> None:
        """Stop the background loop gracefully.

        Cancels the poll loop and waits for any in-flight tasks to finish.
        """
        if not self._running:
            return
        self._running = False
        self._paused = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        # Wait for any subagent tasks still running.
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
            self._active_tasks.clear()
        log.info("Background executor stopped")

    def pause(self) -> None:
        """Pause the executor — it will stop picking new tasks.

        Any task already running continues to completion.  Call
        ``resume()`` to allow new tasks to be picked again.
        """
        if not self._running or self._paused:
            return
        self._paused = True
        log.info("Background executor paused")

    def resume(self) -> None:
        """Resume a paused executor so it picks tasks again."""
        if not self._paused:
            return
        self._paused = False
        self._draining = False
        log.info("Background executor resumed")

    async def drain(self) -> None:
        """Drain the executor: stop scheduling new tasks and wait for in-flight ones.

        This is the first stage of a graceful shutdown.  The poll loop
        stops picking new tasks, but any subagent already running is
        allowed to finish.  After all in-flight tasks complete, the
        executor saves state and stops.
        """
        if not self._running:
            return
        self._draining = True
        self._paused = True
        log.info(
            "Background executor draining — waiting for %d in-flight task(s)",
            len(self._active_tasks),
        )
        # Wait for all in-flight tasks to finish.
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
        self._persist()
        await self.stop()
        log.info("Background executor drained and stopped")

    async def force_stop(self) -> None:
        """Force-stop the executor: cancel all in-flight tasks and save state.

        This is the second stage of shutdown (e.g. second SIGINT).
        In-flight subagent tasks are cancelled immediately.  Any task
        marked ACTIVE is reset to PENDING for the next session.
        """
        if not self._running:
            return
        log.warning(
            "Force-stopping executor — cancelling %d in-flight task(s)", len(self._active_tasks)
        )
        # Cancel all in-flight async tasks.
        for at in self._active_tasks:
            at.cancel()
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
            self._active_tasks.clear()
        # Reset active tasks to pending so they are retried next session.
        self._cleanup_active_tasks()
        self._persist()
        self._running = False
        self._paused = False
        self._draining = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        log.info("Background executor force-stopped")

    def _cleanup_active_tasks(self) -> None:
        """Reset any ACTIVE tasks back to PENDING.

        Called on startup and on force-stop to ensure interrupted tasks
        are retried rather than stuck forever.
        """
        reset_count = 0
        for task in self._queue.all_tasks():
            if task.status == TaskStatus.ACTIVE:
                self._queue.set_pending(task.id)
                reset_count += 1
        if reset_count:
            log.info("Reset %d active task(s) to pending", reset_count)

    # -- Core loop -----------------------------------------------------------

    def _snapshot(self) -> routing.WorkQueueState:
        """Build a frozen snapshot of the current queue + executor state."""
        return snapshot_from_queue(
            tasks=self._queue.all_tasks(),
            active_subagent_count=len(self._active_tasks),
            max_concurrency=self._max_concurrency,
            paused=self._paused,
            draining=self._draining,
            has_charm_path=bool(self._state.charm_path),
            has_dev_model=bool(self._state.dev_model),
        )

    async def _run_loop(self) -> None:
        """Poll for ready tasks and execute them concurrently until stopped."""
        await self._reap_worktree_orphans()
        while self._running:
            try:
                decision = route(self._snapshot())

                if decision.action == RouteAction.SPAWN_TASK:
                    task = self._queue.get_task(decision.task_id)
                    if task is not None and task.status == TaskStatus.PENDING:
                        # Phase 55.3: per-goal budget gate.  If the
                        # operator set a ``goal_budget`` and any cap
                        # has been reached, block the task with the
                        # budget reason instead of spawning it.  The
                        # task stays blocked until the operator raises
                        # the cap via ``/budget`` (which clears the
                        # block as a side effect).
                        budget_veto = self._check_goal_budget()
                        if budget_veto is not None:
                            self._queue.set_blocked(task.id, budget_veto)
                            self._record_status_change(
                                task, "blocked", old_status="pending", error=budget_veto
                            )
                            if self._on_budget_exceeded is not None:
                                self._on_budget_exceeded(task, budget_veto)
                            self._persist()
                            await asyncio.sleep(_POLL_INTERVAL)
                            continue
                        # Phase 80.3: per-goal rate-limit gate.  If the
                        # composed policy stack set
                        # ``max_calls_per_request`` and the executor's
                        # counter has hit that cap, block the task
                        # with ``policy rate limit exceeded`` so the
                        # user sees the stop in the chat.
                        rate_trip = self._check_rate_limit()
                        if rate_trip is not None:
                            count, cap = rate_trip
                            reason = (
                                f"Policy rate limit exceeded: {count} tool calls "
                                f"(cap: {cap}).  Raise ``max_calls_per_request`` in a "
                                "policy file or clear the stack to continue."
                            )
                            self._queue.set_blocked(task.id, reason)
                            self._record_status_change(
                                task, "blocked", old_status="pending", error=reason
                            )
                            if self._on_rate_limited is not None:
                                self._on_rate_limited(
                                    task, count, cap, self._rate_limit_policy_name
                                )
                            self._persist()
                            await asyncio.sleep(_POLL_INTERVAL)
                            continue
                        self._queue.set_active(task.id)
                        self._record_status_change(task, "active", old_status="pending")
                        at = asyncio.create_task(self._run_task_with_semaphore(task))
                        self._active_tasks.add(at)
                        at.add_done_callback(self._active_tasks.discard)
                        # Check for more ready tasks without sleeping.
                        self._consecutive_errors = 0
                        continue

                elif decision.action == RouteAction.WAIT_FOR_CONFIRMATION:
                    task = self._queue.get_task(decision.task_id)
                    if task is not None and task.status == TaskStatus.PENDING:
                        self._handle_confirm(task)

                # A successful iteration — reset the error counter.
                self._consecutive_errors = 0

                # WAIT_FOR_IN_FLIGHT and IDLE both sleep before re-checking.
                await asyncio.sleep(_POLL_INTERVAL)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — executor loop must absorb any per-iteration error; the consecutive-error counter handles repeated failures.
                self._consecutive_errors += 1
                log.error(
                    "Unexpected error in executor loop (%d/%d): %s",
                    self._consecutive_errors,
                    _MAX_CONSECUTIVE_ERRORS,
                    exc,
                    exc_info=True,
                )
                if self._consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                    log.critical(
                        "Executor hit %d consecutive errors — stopping work loop",
                        self._consecutive_errors,
                    )
                    break
                # Cooldown to avoid a tight error spin.
                await asyncio.sleep(_ERROR_COOLDOWN)

        # Wait for in-flight tasks to finish on shutdown.
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)

    async def _run_task_with_semaphore(self, task: AgentTask) -> None:
        """Acquire the semaphore, execute the task, then release."""
        assert self._semaphore is not None  # noqa: S101
        async with self._semaphore:
            await self._execute_task(task)

    def _wrap_tool_invoked(self, inner: ToolInvokedCallback | None) -> ToolInvokedCallback | None:
        """Return a wrapper that increments the rate-limit counter.

        MCP tools (``mcp__``-prefixed) are skipped — they're gated by
        the per-server ``allowed_tools`` config (Phase 45.2) rather
        than by the policy stack's ``max_calls_per_request``.  The
        original callback still fires for every tool so UI consumers
        see MCP calls too.
        """

        def _wrapped(
            tool_name: str,
            arguments: dict[str, object],
            result: object,
            duration_ms: int,
            tool_call_id: str,
        ) -> None:
            if not tool_name.startswith(MCP_TOOL_PREFIX):
                self._tool_calls_made += 1
            if inner is not None:
                inner(tool_name, arguments, result, duration_ms, tool_call_id)

        return _wrapped

    def _check_rate_limit(self) -> tuple[int, int] | None:
        """Phase 80.3: return ``(count, cap)`` when the rate limit trips, else ``None``.

        Unlike :meth:`_check_goal_budget`, which reads from the
        persisted token_usage table, the rate limit is an in-memory
        counter — the cap is per-goal / per-session and doesn't need
        to survive a process restart.
        """
        if self._rate_limit_cap is None:
            return None
        if self._tool_calls_made >= self._rate_limit_cap:
            return self._tool_calls_made, self._rate_limit_cap
        return None

    def _check_goal_budget(self) -> str | None:
        """Phase 55.3: consult the per-goal budget before a task spawn.

        Returns a block reason when the budget is exceeded, or
        ``None`` when there's no budget set or every cap is still
        clear.  Without a ``SessionStore`` the gate is a no-op —
        budget evaluation depends on the persisted token-usage rows.
        """
        budget = self._state.goal_budget
        if budget is None or self._store is None:
            return None
        return check_budget(self._store, budget)

    # -- Confirm handling ----------------------------------------------------

    def _handle_confirm(self, task: AgentTask) -> None:
        """Block a CONFIRM task so the conversation loop can present it."""
        self._queue.set_blocked(task.id, "Waiting for user confirmation")
        if self._on_task_done:
            self._on_task_done(task)
        self._persist()

    # -- Pre-task environment checks -----------------------------------------

    def _pre_check_environment(self, task: AgentTask) -> str | None:
        """Verify the environment is usable before launching a subagent."""
        return self._env_checker.check(task)

    # -- Event recording helpers -----------------------------------------------

    def _record_status_change(
        self,
        task: AgentTask,
        new_status: str,
        *,
        old_status: str = "active",
        error: str | None = None,
    ) -> None:
        """Record a task status change event in the session store.

        Phase 106.3: BLOCKED transitions log at ``warning`` so the
        reason lands in stderr without ``--verbose`` — the Phase 105.1
        smoke had to grovel through NDJSON to find which of six failed
        ``run_charm_tests`` rounds tipped the threshold.
        """
        if new_status == "blocked":
            log.warning(
                "Task %r blocked: %s",
                task.title,
                error or "<no reason>",
            )
        if not self._state_service:
            return
        detail: dict[str, str] = {
            "task_id": task.id,
            "task_title": task.title,
            "old_status": old_status,
            "new_status": new_status,
        }
        if error is not None:
            detail["error"] = error[:500]
        self._state_service.record_event("task_status_change", detail)

    def _record_task_error(self, task: AgentTask, exc: BaseException) -> None:
        """Record a task error event in the session store."""
        if not self._state_service:
            return
        self._state_service.record_event(
            "error",
            {
                "task_id": task.id,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            },
        )

    # -- Noop detection -------------------------------------------------------

    def _fingerprint(self, path: str | pathlib.Path | None = None) -> str:
        """Capture a lightweight fingerprint of *path*.

        Defaults to the main charm directory.  When a subagent runs inside a
        worktree, pass the worktree path so the before/after comparison sees
        changes the subagent actually made.
        """
        target = path if path is not None else self._state.charm_path
        return self._git.fingerprint(target)

    def _is_noop(self, before: str, after: str) -> bool:
        """Return True if the fingerprints are identical (no observable change)."""
        return bool(before) and before == after

    # -- Task execution ------------------------------------------------------

    _SNAPSHOT_CATEGORIES = frozenset({TaskCategory.BUILD, TaskCategory.DEBUG})

    def _fail_task(
        self,
        task: AgentTask,
        error: str,
        exc: BaseException | None,
        snapshot: str | None,
    ) -> None:
        """Record a task failure: revert, mark failed, notify callback."""
        if snapshot and task.category in self._SNAPSHOT_CATEGORIES:
            self._revert_on_failure(snapshot, task)
        self._queue.set_failed(task.id, error)
        self._record_status_change(task, "failed", error=error)
        if exc is not None:
            self._record_task_error(task, exc)
        if self._on_task_failed:
            self._on_task_failed(task)

    def _handle_result(
        self,
        task: AgentTask,
        result: SubagentResult,
        fp_before: str,
        effective_path: str | pathlib.Path | None = None,
    ) -> None:
        """Process a subagent result: handle exit states, noop detection, success.

        *effective_path* is the directory the subagent wrote to — the main
        charm path, or a per-task worktree if one was allocated.  The noop
        fingerprint comparison must target the same directory as *fp_before*.
        """
        if result.exit_state == ExitState.BLOCKED:
            self._queue.set_blocked(task.id, result.summary)
            self._record_status_change(task, "blocked", error=result.summary)
            if self._on_task_failed:
                self._on_task_failed(task)
            return

        if result.exit_state == ExitState.FAILED:
            self._queue.set_failed(task.id, result.text)
            self._record_status_change(task, "failed", error=result.summary)
            if self._on_task_failed:
                self._on_task_failed(task)
            return

        # Noop detection: check both the exit state signal and
        # the filesystem fingerprint for observable changes.
        fp_after = self._fingerprint(effective_path)
        is_noop = result.exit_state == ExitState.NOOP or self._is_noop(fp_before, fp_after)
        if is_noop:
            task.noop_count += 1
            log.warning(
                "Task '%s' completed without observable changes (noop %d/%d)",
                task.title,
                task.noop_count,
                _MAX_NOOP_COUNT,
            )
            if task.noop_count >= _MAX_NOOP_COUNT:
                self._queue.set_blocked(
                    task.id,
                    f"Attempted {task.noop_count} time(s) without progress — needs user guidance",
                )
                self._record_status_change(task, "blocked", error="noop escalation")
                if self._on_task_failed:
                    self._on_task_failed(task)
                return
            self._queue.set_pending(task.id)
            self._record_status_change(task, "pending", error="noop — retrying")
            return

        self._queue.set_done(task.id, result.text)
        self._record_status_change(task, "done")
        if task.category in (TaskCategory.BUILD, TaskCategory.DEBUG):
            self._check_uncommitted(task)
        if self._on_task_done:
            self._on_task_done(task)

    async def _execute_task(self, task: AgentTask) -> None:
        """Run a single task via a subagent, recording the outcome.

        The caller is responsible for setting the task to ACTIVE before
        calling this method.

        When possible the subagent runs in a dedicated ``git worktree``
        allocated from the current HEAD.  Successful tasks are merged back
        into the main charm branch; failed tasks drop the worktree without
        touching main.  For non-git charm paths the allocator returns
        ``None`` and the subagent falls back to the main tree, in which case
        BUILD/DEBUG failures use the older snapshot/revert path.
        """
        error = self._pre_check_environment(task)
        if error is not None:
            self._fail_task(task, error, exc=None, snapshot=None)
            if task.category == TaskCategory.DEPLOY and not self._state.dev_model:
                self._queue.add_task(
                    AgentTask(title="Set up development model", category=TaskCategory.INFRA)
                )
            self._persist()
            return

        # Best-of-N racing dispatches to its own path.  The coordinator
        # allocates per-candidate worktrees itself, so the
        # allocate/merge/revert logic below is skipped entirely.  The
        # gate classifies the task against the race's cost thresholds
        # before dispatching: the estimate might clear both thresholds
        # (race), cross the confirm threshold only (CONFIRM surfaced,
        # parent blocked), or exceed the hard budget (downgrade to a
        # single-subagent run).
        specs = self._race_candidate_specs()
        if self._should_race(task, specs):
            clamped = self._race_config.clamp_candidates(specs)
            gate = self._dispatch_race_gate(task, clamped)
            if gate == race.RaceGate.RACE:
                await self._execute_race(task, clamped)
                return
            if gate == race.RaceGate.CONFIRM:
                # ``_dispatch_race_gate`` emitted the CONFIRM task and
                # blocked ``task``.  The conversation layer resolves the
                # CONFIRM, flips ``task.race_decision``, and unblocks us
                # for re-entry.
                self._persist()
                return
            # DOWNGRADE — fall through to the single-subagent path.

        handle = await self._try_allocate_worktree(task)
        effective_path: str | pathlib.Path | None = (
            handle.path if handle is not None else self._state.charm_path
        )
        # Reflect the allocated worktree on the task so the TUI and Web
        # task widgets can display it.
        if handle is not None:
            task.worktree_path = str(handle.path)
            self._queue.notify_task(task)

        # Snapshot/revert only applies when the subagent writes to the main
        # tree directly — worktree failures are cleaned up by dropping the
        # worktree in the ``finally`` block below.
        snapshot: str | None = None
        if handle is None and task.category in self._SNAPSHOT_CATEGORIES:
            snapshot = self._snapshot_head()

        fp_before = self._fingerprint(effective_path)

        context = self._build_context(task, effective_path)
        await self._attach_diagnostics_brief(context)
        max_rounds = MAX_BUILD_ROUNDS if task.category == TaskCategory.BUILD else None
        subagent = Subagent(
            context,
            self._tools,
            self._provider,
            light_provider=self._light_provider,
            on_usage=self._record_usage,
            throttle=self._throttle,
            store=self._store,
            on_phase_change=self._queue.notify_task,
            hook_runner=self._hook_runner,
            on_tool_invoked=self._on_tool_invoked,
            on_tool_invoked_pending=self._on_tool_invoked_pending,
            permissions=self._effective_permissions(),
            permission_manager=self._permission_manager,
            on_permission_decided=self._on_permission_decided,
            **({"max_rounds": max_rounds} if max_rounds is not None else {}),
        )
        t0 = time.monotonic()
        merge_error: str | None = None
        try:
            timeout = _TASK_TIMEOUTS.get(task.category, _DEFAULT_TASK_TIMEOUT)
            result = await asyncio.wait_for(subagent.run(), timeout=timeout)
            elapsed = time.monotonic() - t0
            log.info("Task '%s' %s in %.1fs", task.title, result.exit_state.value, elapsed)
            self._handle_result(task, result, fp_before, effective_path)
            # On a successful task with a worktree, merge the ephemeral branch
            # back into main.  Block the task if the merge cannot proceed.
            if handle is not None:
                current = self._queue.get_task(task.id)
                if current is not None and current.status == TaskStatus.DONE:
                    merge_error = await self._merge_worktree(handle, task)
                    if merge_error is not None:
                        self._queue.set_blocked(task.id, merge_error)
                        self._record_status_change(task, "blocked", error=merge_error)
                        if self._on_task_failed:
                            self._on_task_failed(task)
        except TimeoutError as exc:
            log.warning("Task '%s' timed out after %.1fs", task.title, time.monotonic() - t0)
            self._fail_task(task, "Task timed out", exc, snapshot)
        except (
            llm.ProviderError,
            llm.ProviderRateLimitError,
            llm.ProviderOverloadedError,
            llm.ProviderConnectionError,
        ) as exc:
            # Transient errors only reach here when ``complete_with_retry``
            # has already exhausted its budget — re-raised as the original
            # type, which is *not* a ``ProviderError`` subclass.  Without
            # this clause the task coroutine would die unhandled and the
            # task stay stuck in ``IN_PROGRESS`` instead of going FAILED.
            log.warning(
                "Task '%s' failed (provider) after %.1fs: %s",
                task.title,
                time.monotonic() - t0,
                exc,
            )
            self._fail_task(task, str(exc), exc, snapshot)
        except (OSError, RuntimeError, ValueError, KeyError, AttributeError) as exc:
            log.warning("Task '%s' failed after %.1fs: %s", task.title, time.monotonic() - t0, exc)
            self._fail_task(task, str(exc), exc, snapshot)
        finally:
            if handle is not None:
                # Preserve the branch when a merge could not complete so the
                # user can inspect it; otherwise remove it alongside the
                # worktree directory.
                keep_branch = merge_error is not None
                try:
                    await self._worktrees.release(task.id, keep_branch=keep_branch)
                except (OSError, RuntimeError) as exc:
                    log.warning("Worktree release failed for task %s: %s", task.id, exc)
                task.worktree_path = None
                self._queue.notify_task(task)
            self._create_followups(task)
            self._persist()

    # -- Git snapshot / revert -----------------------------------------------

    def _snapshot_head(self) -> str | None:
        """Return the current HEAD commit hash for the charm directory."""
        return self._git.snapshot_head(self._state.charm_path)

    def _revert_on_failure(self, snapshot: str, task: AgentTask) -> None:
        """Revert tracked files to their committed state after a failed task."""
        if self._state.charm_path:
            self._git.revert_to_clean(self._state.charm_path, task, snapshot)

    # -- Follow-up creation --------------------------------------------------

    def _create_followups(self, task: AgentTask) -> None:
        """Create follow-up tasks for a completed or failed task."""
        new_tasks = self._followup_planner.followup_tasks(task)
        if new_tasks:
            self._queue.add_tasks(new_tasks)
            log.info(
                "Created %d follow-up task(s) for '%s'",
                len(new_tasks),
                task.title,
            )

    # -- Uncommitted change detection -----------------------------------------

    def _check_uncommitted(self, task: AgentTask) -> None:
        """Log a warning if the charm directory has uncommitted changes."""
        if not self._state.charm_path:
            return
        if self._git.has_uncommitted_changes(self._state.charm_path):
            log.warning(
                "Task '%s' completed but left uncommitted changes in %s",
                task.title,
                self._state.charm_path,
            )

    # -- Context building ----------------------------------------------------

    def _build_context(
        self,
        task: AgentTask,
        charm_path: str | pathlib.Path | None = None,
    ) -> SubagentContext:
        """Construct a ``SubagentContext`` from the current agent state.

        *charm_path* overrides the main ``AgentState.charm_path`` so a
        subagent can be pointed at a per-task worktree.  Defaults to the main
        charm path when no override is supplied.
        """
        prior_results: dict[str, str] = {}
        for dep_id in task.dependencies:
            dep = self._queue.get_task(dep_id)
            if dep is not None and dep.result is not None:
                prior_results[dep_id] = dep.result

        # Extract design content for build/deploy/test subagents.
        design_content: str | None = None
        if self._state.design_proposal is not None:
            design_md = getattr(self._state.design_proposal, "to_design_md", None)
            if callable(design_md):
                design_content = design_md()

        effective = charm_path if charm_path is not None else self._state.charm_path
        return SubagentContext(
            task=task,
            charm_name=self._state.charm_name,
            charm_path=str(effective) if effective else None,
            charm_type=self._state.charm_type,
            framework=self._state.framework,
            dev_model=self._state.dev_model,
            cos_model=self._state.cos_model,
            decisions=[d.to_dict() for d in self._state.decisions],
            prior_results=prior_results,
            design_content=design_content,
        )

    async def _attach_diagnostics_brief(self, context: SubagentContext) -> None:
        """Attach a compact ruff/ty/charmlint snapshot to *context* (Phase 72.4).

        BUILD and DEBUG subagents start a turn already knowing what's
        broken across the project; other categories skip the lint pass
        because the cost wouldn't pay back (RESEARCH doesn't edit;
        DEPLOY operates on built artefacts; TEST runs its own
        pytest).  Failures inside the aggregator never block subagent
        launch — the briefing simply omits the section.
        """
        if context.task.category not in (TaskCategory.BUILD, TaskCategory.DEBUG):
            return
        if not context.charm_path:
            return
        try:
            block = await lint_context.gather_project_diagnostics(pathlib.Path(context.charm_path))
        except (OSError, RuntimeError, TimeoutError) as exc:
            # The aggregator already absorbs missing binaries / parse
            # failures into ``skipped`` notes, so reaching this branch
            # implies the asyncio plumbing itself failed.  Log and
            # carry on without the section.
            log.warning("Diagnostics brief unavailable for %s: %s", context.task.title, exc)
            return
        if block.is_empty():
            return
        context.diagnostics_text = block.to_text()

    # -- Usage tracking ------------------------------------------------------

    def _record_usage(self, response: llm.Response) -> None:
        """Record token usage from a subagent LLM response.

        The subagent stamps the actual provider identity and the active
        task's category into ``response.metadata`` so we record the
        correct model (even when the subagent used the light provider)
        and the right category for the Phase 31.4 cost breakdown.

        Prompt-cache tokens are persisted alongside (so cost survives a
        resume) and folded into the session-level accumulators via
        ``on_cache_usage`` so ``/cost`` reflects subagent cache spend, not
        just the main conversation loop's.
        """
        if not response.usage:
            return
        cache_read = response.usage.get("cache_read_input_tokens", 0) or 0
        cache_creation = response.usage.get("cache_creation_input_tokens", 0) or 0
        if self._state_service:
            provider_name = response.metadata.get("_provider_name", self._provider.name)
            model_name = response.metadata.get("_provider_model", self._provider.model_name)
            category = response.metadata.get("_task_category")
            self._state_service.record_usage(
                provider=provider_name,
                model=model_name,
                prompt_tokens=response.usage.get("prompt_tokens", 0),
                completion_tokens=response.usage.get("completion_tokens", 0),
                category=category if isinstance(category, str) else None,
                cache_read_tokens=cache_read,
                cache_creation_tokens=cache_creation,
            )
        if self._on_cache_usage is not None and (cache_read or cache_creation):
            self._on_cache_usage(cache_creation, cache_read)

    # -- Persistence ---------------------------------------------------------

    def _persist(self) -> None:
        """Save tasks via the state service if one is available."""
        if self._state_service is not None:
            self._state_service.save_tasks(self._queue.all_tasks())
