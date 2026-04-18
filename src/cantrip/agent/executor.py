"""Background executor — picks ready tasks and runs subagents."""

import asyncio
import contextlib
import logging
import pathlib
import subprocess
import time
from collections.abc import Callable

from cantrip.agent import routing
from cantrip.agent.autodeploy import followup_tasks
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.routing import RouteAction, route, snapshot_from_queue
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
)
from cantrip.agent.tools.base import Tool
from cantrip.agent.tools.git import _gpg_sign_enabled
from cantrip.agent.worktree import WorktreeHandle, _DefaultWorktreeAllocator
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


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------


async def _run_git_async(
    args: list[str],
    *,
    cwd: str | pathlib.Path,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    """Run a git subcommand off the event loop without blocking other tasks."""

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    return await asyncio.to_thread(_run)


# ---------------------------------------------------------------------------
# Default service implementations (used when no protocol impl is injected)
# ---------------------------------------------------------------------------


class _DefaultGitService:
    """Git operations using subprocess calls."""

    def fingerprint(self, charm_path: str | pathlib.Path | None) -> str:
        if not charm_path:
            return ""
        charm_dir = str(charm_path)
        parts: list[str] = []
        for cmd in (["git", "rev-parse", "HEAD"], ["git", "status", "--porcelain"]):
            try:
                result = subprocess.run(
                    cmd,
                    cwd=charm_dir,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    parts.append(result.stdout.strip())
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass
        return "\n".join(parts)

    def snapshot_head(self, charm_path: str | pathlib.Path | None) -> str | None:
        if not charm_path:
            return None
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(charm_path),
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def revert_to_clean(
        self,
        charm_path: str | pathlib.Path,
        task: AgentTask,
        snapshot: str,
    ) -> None:
        charm_dir = str(charm_path)

        # Capture the diff so the failure can be diagnosed.
        diff_text = ""
        try:
            diff_result = subprocess.run(
                ["git", "diff"],
                cwd=charm_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if diff_result.returncode == 0 and diff_result.stdout.strip():
                diff_text = diff_result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

        if diff_text:
            existing = task.result or ""
            task.result = f"[reverted diff]\n{diff_text}\n\n{existing}"

        # Restore tracked files to their committed state.
        with contextlib.suppress(subprocess.TimeoutExpired, FileNotFoundError, OSError):
            subprocess.run(
                ["git", "checkout", "."],
                cwd=charm_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )

        # Remove untracked files left behind by failing subagents.
        with contextlib.suppress(subprocess.TimeoutExpired, FileNotFoundError, OSError):
            subprocess.run(
                ["git", "clean", "-fd"],
                cwd=charm_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )

        log.warning(
            "Reverted working tree in %s after failed task '%s' (snapshot %s)",
            charm_dir,
            task.title,
            snapshot[:12],
        )

    def has_uncommitted_changes(self, charm_path: str | pathlib.Path) -> bool:
        charm_dir = str(charm_path)
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=charm_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False
        if result.returncode != 0:
            return False
        return bool(result.stdout.strip())


class _DefaultEnvironmentChecker:
    """Pre-task environment validation using AgentState."""

    def __init__(self, state: AgentState) -> None:
        self._state = state

    def check(self, task: AgentTask) -> str | None:
        if task.category == TaskCategory.DEPLOY:
            if not self._state.dev_model:
                return "No development model set \u2014 cannot deploy"
            if not self._state.charm_path:
                return "No charm path set \u2014 cannot deploy"
            if not pathlib.Path(self._state.charm_path).exists():
                return f"Charm path {self._state.charm_path} does not exist"

        if task.category == TaskCategory.TEST:
            if not self._state.charm_path:
                return "No charm path set \u2014 cannot test"
            charm_dir = pathlib.Path(self._state.charm_path)
            if not charm_dir.exists():
                return f"Charm path {self._state.charm_path} does not exist"
            if not list(charm_dir.glob("*.charm")):
                return "No packed charm found \u2014 run charmcraft_pack first"

        return None


class _DefaultFollowupPlanner:
    """Creates follow-up tasks using autodeploy.followup_tasks()."""

    def __init__(self, state: AgentState) -> None:
        self._state = state

    def followup_tasks(self, task: AgentTask) -> list[AgentTask]:
        if not self._state.dev_model:
            return []
        return followup_tasks(task)


class _SessionStoreAdapter:
    """Adapts a SessionStore to the StateService protocol."""

    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def record_event(self, event_type: str, detail: dict[str, str]) -> None:
        self._store.record_event(event_type, detail)

    def record_usage(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        self._store.record_usage(
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def save_tasks(self, tasks: list[AgentTask]) -> None:
        self._store.save_tasks(tasks)


# ---------------------------------------------------------------------------
# BackgroundExecutor
# ---------------------------------------------------------------------------


class BackgroundExecutor:
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
        while self._running:
            try:
                decision = route(self._snapshot())

                if decision.action == RouteAction.SPAWN_TASK:
                    task = self._queue.get_task(decision.task_id)
                    if task is not None and task.status == TaskStatus.PENDING:
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
            except Exception as exc:
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
        """Record a task status change event in the session store."""
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

        handle = await self._try_allocate_worktree(task)
        effective_path: str | pathlib.Path | None = (
            handle.path if handle is not None else self._state.charm_path
        )

        # Snapshot/revert only applies when the subagent writes to the main
        # tree directly — worktree failures are cleaned up by dropping the
        # worktree in the ``finally`` block below.
        snapshot: str | None = None
        if handle is None and task.category in self._SNAPSHOT_CATEGORIES:
            snapshot = self._snapshot_head()

        fp_before = self._fingerprint(effective_path)

        context = self._build_context(task, effective_path)
        max_rounds = MAX_BUILD_ROUNDS if task.category == TaskCategory.BUILD else None
        subagent = Subagent(
            context,
            self._tools,
            self._provider,
            light_provider=self._light_provider,
            on_usage=self._record_usage,
            throttle=self._throttle,
            store=self._store,
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
        except (llm.ProviderError, llm.ProviderRateLimitError) as exc:
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
            self._create_followups(task)
            self._persist()

    async def _try_allocate_worktree(self, task: AgentTask) -> WorktreeHandle | None:
        """Attempt to allocate a worktree for *task*, returning None on failure.

        The allocator itself handles the "not a git repo" fallback.  This
        wrapper additionally suppresses unexpected ``ValueError`` (duplicate
        task id) and ``OSError`` so a broken allocator never blocks the
        executor — the worst-case behaviour is running in the main tree.
        """
        if self._state.charm_path is None:
            return None
        try:
            return await self._worktrees.allocate(task.id, self._state.charm_path)
        except (ValueError, OSError, RuntimeError) as exc:
            log.warning("Worktree allocation failed for '%s': %s", task.title, exc)
            return None

    async def _merge_worktree(self, handle: WorktreeHandle, task: AgentTask) -> str | None:
        """Merge the worktree branch back into the main charm branch.

        Returns ``None`` on clean merge, or an error message describing why
        the merge could not complete (main tree dirty, or merge conflict).
        When an error is returned the ephemeral branch is preserved so the
        user can resolve it manually.
        """
        main = self._state.charm_path
        if main is None:
            return None

        async with self._merge_lock:
            # 1. Auto-commit any uncommitted changes in the worktree so the
            #    subsequent ``git merge`` sees them.  Subagents that call
            #    ``GitCommitTool`` already committed on ``handle.branch``;
            #    this catches the common case of bare file writes.
            add_result = await _run_git_async(["add", "-A"], cwd=handle.path)
            if add_result.returncode == 0:
                staged = await _run_git_async(["diff", "--cached", "--quiet"], cwd=handle.path)
                # ``--quiet`` exits with 1 when there are staged changes.
                if staged.returncode == 1:
                    commit_args = ["commit", "-m", f"cantrip: {task.title[:72]}"]
                    if not _gpg_sign_enabled():
                        commit_args.append("--no-gpg-sign")
                    await _run_git_async(commit_args, cwd=handle.path)

            # 2. Skip the merge if main has uncommitted work — overwriting it
            #    would silently lose the user's state.
            status = await _run_git_async(["status", "--porcelain"], cwd=main)
            if status.returncode == 0 and status.stdout.strip():
                return (
                    f"Main tree has uncommitted changes; worktree branch "
                    f"{handle.branch!r} kept for manual merge"
                )

            # 3. ``--no-ff`` preserves the subagent's commits on the main
            #    branch as a merge commit rather than collapsing them.
            merge_args = ["merge", "--no-ff", "--no-edit", handle.branch]
            if not _gpg_sign_enabled():
                merge_args.append("--no-gpg-sign")
            merge = await _run_git_async(merge_args, cwd=main)
            if merge.returncode != 0:
                # Return the main tree to its pre-merge state so the next
                # task starts from a clean slate.
                await _run_git_async(["merge", "--abort"], cwd=main)
                return (
                    f"Merge conflict with worktree branch {handle.branch!r}; "
                    "main tree reset and branch preserved for manual merge"
                )

            return None

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

    # -- Usage tracking ------------------------------------------------------

    def _record_usage(self, response: llm.Response) -> None:
        """Record token usage from a subagent LLM response.

        The subagent stamps the actual provider identity into
        ``response.metadata`` so we record the correct model even when
        the subagent used the light provider instead of the primary one.
        """
        if self._state_service and response.usage:
            provider_name = response.metadata.get("_provider_name", self._provider.name)
            model_name = response.metadata.get("_provider_model", self._provider.model_name)
            self._state_service.record_usage(
                provider=provider_name,
                model=model_name,
                prompt_tokens=response.usage.get("prompt_tokens", 0),
                completion_tokens=response.usage.get("completion_tokens", 0),
            )

    # -- Persistence ---------------------------------------------------------

    def _persist(self) -> None:
        """Save tasks via the state service if one is available."""
        if self._state_service is not None:
            self._state_service.save_tasks(self._queue.all_tasks())
