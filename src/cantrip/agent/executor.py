"""Background executor — picks ready tasks and runs subagents."""

import asyncio
import contextlib
import logging
import pathlib
import subprocess
from collections.abc import Callable

from cantrip.agent.autodeploy import followup_tasks
from cantrip.agent.queue import AgentTask, TaskCategory, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.store import SessionStore
from cantrip.agent.subagent import ProviderThrottle, Subagent, SubagentContext
from cantrip.agent.tools.base import Tool
from cantrip.llm import base as llm

log = logging.getLogger(__name__)

_POLL_INTERVAL = 1.0  # seconds between checking for ready tasks
_TASK_TIMEOUT = 600  # seconds — max wall-clock time per task (10 min)
DEFAULT_MAX_CONCURRENCY = 3

# Called when a task completes or fails, for TUI/conversation-loop coordination.
TaskEventCallback = Callable[[AgentTask], None] | None


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

        self._running = False
        self._paused = False
        self._task: asyncio.Task | None = None
        # Track in-flight async tasks so the loop knows how many slots are free.
        self._active_tasks: set[asyncio.Task[None]] = set()
        self._semaphore: asyncio.Semaphore | None = None
        # Shared throttle so concurrent subagents coordinate on rate limits.
        self._throttle = ProviderThrottle()

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

    def start(self) -> None:
        """Start the background poll-and-execute loop."""
        if self._running:
            return
        self._running = True
        self._paused = False
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
        log.info("Background executor resumed")

    # -- Core loop -----------------------------------------------------------

    async def _run_loop(self) -> None:
        """Poll for ready tasks and execute them concurrently until stopped."""
        while self._running:
            try:
                if self._paused:
                    await asyncio.sleep(_POLL_INTERVAL)
                    continue

                # Determine how many slots are free.
                in_flight = len(self._active_tasks)
                free_slots = self._max_concurrency - in_flight

                if free_slots <= 0:
                    await asyncio.sleep(_POLL_INTERVAL)
                    continue

                ready = self._queue.all_ready(limit=free_slots)
                if not ready:
                    await asyncio.sleep(_POLL_INTERVAL)
                    continue

                for task in ready:
                    if task.category == TaskCategory.CONFIRM:
                        self._handle_confirm(task)
                        continue
                    # Mark active immediately so the next poll doesn't re-pick it.
                    self._queue.set_active(task.id)
                    at = asyncio.create_task(self._run_task_with_semaphore(task))
                    self._active_tasks.add(at)
                    at.add_done_callback(self._active_tasks.discard)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Unexpected error in executor loop")

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
        """Verify the environment is usable before launching a subagent.

        Returns an error string if a pre-condition is not met, or ``None``
        when everything looks fine.  Only DEPLOY and TEST categories have
        pre-checks; all other categories pass unconditionally.
        """
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

    # -- Task execution ------------------------------------------------------

    _SNAPSHOT_CATEGORIES = frozenset({TaskCategory.BUILD, TaskCategory.DEBUG})

    async def _execute_task(self, task: AgentTask) -> None:
        """Run a single task via a subagent, recording the outcome.

        The caller is responsible for setting the task to ACTIVE before
        calling this method.

        For BUILD and DEBUG tasks, a git snapshot is taken before execution
        so that the working tree can be reverted if the subagent fails,
        avoiding broken partial writes.
        """
        error = self._pre_check_environment(task)
        if error is not None:
            self._queue.set_failed(task.id, error)
            if self._on_task_failed:
                self._on_task_failed(task)
            # For deploy failures due to missing model, queue an infra task.
            if task.category == TaskCategory.DEPLOY and not self._state.dev_model:
                fix_task = AgentTask(
                    title="Set up development model",
                    category=TaskCategory.INFRA,
                )
                self._queue.add_task(fix_task)
            self._persist()
            return

        snapshot: str | None = None
        if task.category in self._SNAPSHOT_CATEGORIES:
            snapshot = self._snapshot_head()

        context = self._build_context(task)
        subagent = Subagent(
            context,
            self._tools,
            self._provider,
            light_provider=self._light_provider,
            on_usage=self._record_usage,
            throttle=self._throttle,
        )
        try:
            result = await asyncio.wait_for(subagent.run(), timeout=_TASK_TIMEOUT)
            self._queue.set_done(task.id, result)
            if task.category in (TaskCategory.BUILD, TaskCategory.DEBUG):
                self._check_uncommitted(task)
            if self._on_task_done:
                self._on_task_done(task)
        except TimeoutError:
            if snapshot and task.category in self._SNAPSHOT_CATEGORIES:
                self._revert_on_failure(snapshot, task)
            self._queue.set_failed(task.id, "Task timed out")
            if self._on_task_failed:
                self._on_task_failed(task)
        except Exception as exc:
            if snapshot and task.category in self._SNAPSHOT_CATEGORIES:
                self._revert_on_failure(snapshot, task)
            self._queue.set_failed(task.id, str(exc))
            if self._on_task_failed:
                self._on_task_failed(task)
        finally:
            self._create_followups(task)
            self._persist()

    # -- Git snapshot / revert -----------------------------------------------

    def _snapshot_head(self) -> str | None:
        """Return the current HEAD commit hash for the charm directory.

        Returns ``None`` if no charm path is set or if the git command fails
        (e.g. not a git repository).
        """
        if not self._state.charm_path:
            return None
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(self._state.charm_path),
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _revert_on_failure(self, snapshot: str, task: AgentTask) -> None:
        """Revert tracked files to their committed state after a failed task.

        Captures the current diff as diagnostic information and prepends it
        to the task result, then restores tracked files with ``git checkout``.
        Untracked files are intentionally left alone.
        """
        charm_dir = str(self._state.charm_path)

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

        log.warning(
            "Reverted tracked files in %s after failed task '%s' (snapshot %s)",
            charm_dir,
            task.title,
            snapshot[:12],
        )

    # -- Follow-up creation --------------------------------------------------

    def _create_followups(self, task: AgentTask) -> None:
        """Create follow-up tasks for a completed or failed task.

        Only creates follow-ups when a development model is set (no point
        verifying or diagnosing without a deployment target).
        """
        if not self._state.dev_model:
            return
        new_tasks = followup_tasks(task)
        if new_tasks:
            self._queue.add_tasks(new_tasks)
            log.info(
                "Created %d follow-up task(s) for '%s'",
                len(new_tasks),
                task.title,
            )

    # -- Uncommitted change detection -----------------------------------------

    def _check_uncommitted(self, task: AgentTask) -> None:
        """Log a warning if the charm directory has uncommitted changes.

        Called after successful BUILD or DEBUG tasks to flag cases where
        the subagent forgot to commit its work.
        """
        if not self._state.charm_path:
            return
        charm_dir = str(self._state.charm_path)
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=charm_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return
        if result.returncode != 0:
            return
        if result.stdout.strip():
            log.warning(
                "Task '%s' completed but left uncommitted changes in %s",
                task.title,
                charm_dir,
            )

    # -- Context building ----------------------------------------------------

    def _build_context(self, task: AgentTask) -> SubagentContext:
        """Construct a ``SubagentContext`` from the current agent state."""
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

        return SubagentContext(
            task=task,
            charm_name=self._state.charm_name,
            charm_path=str(self._state.charm_path) if self._state.charm_path else None,
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
        """Record token usage from a subagent LLM response."""
        if self._store and response.usage:
            self._store.record_usage(
                provider=self._provider.name,
                model=self._provider.model_name,
                prompt_tokens=response.usage.get("prompt_tokens", 0),
                completion_tokens=response.usage.get("completion_tokens", 0),
            )

    # -- Persistence ---------------------------------------------------------

    def _persist(self) -> None:
        """Save tasks via the session store if one is available."""
        if self._store is not None:
            self._store.save_tasks(self._queue.all_tasks())
