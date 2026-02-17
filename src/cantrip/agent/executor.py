"""Background executor — picks ready tasks and runs subagents."""

import asyncio
import contextlib
import logging
from collections.abc import Callable

from cantrip.agent.autodeploy import followup_tasks
from cantrip.agent.queue import AgentTask, TaskCategory, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.store import SessionStore
from cantrip.agent.subagent import Subagent, SubagentContext
from cantrip.agent.tools.base import Tool
from cantrip.llm import base as llm

log = logging.getLogger(__name__)

_POLL_INTERVAL = 1.0  # seconds between checking for ready tasks
_TASK_TIMEOUT = 600  # seconds — max wall-clock time per task (10 min)

# Called when a task completes or fails, for TUI/conversation-loop coordination.
TaskEventCallback = Callable[[AgentTask], None] | None


class BackgroundExecutor:
    """Orchestrator that picks tasks from the work queue and runs subagents.

    Runs as a background ``asyncio.Task`` concurrently with the conversation
    loop.  Each ready task is executed in an isolated ``Subagent`` context;
    results and failures are recorded back on the queue and persisted.
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
    ) -> None:
        self._queue = queue
        self._tools = tools
        self._provider = provider
        self._state = state
        self._store = store
        self._light_provider = light_provider
        self._on_task_done = on_task_done
        self._on_task_failed = on_task_failed

        self._running = False
        self._task: asyncio.Task | None = None

    # -- Lifecycle -----------------------------------------------------------

    @property
    def running(self) -> bool:
        """Whether the executor loop is currently running."""
        return self._running

    def start(self) -> None:
        """Start the background poll-and-execute loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        log.info("Background executor started")

    async def stop(self) -> None:
        """Stop the background loop gracefully."""
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        log.info("Background executor stopped")

    # -- Core loop -----------------------------------------------------------

    async def _run_loop(self) -> None:
        """Poll for ready tasks and execute them until stopped."""
        while self._running:
            try:
                task = self._queue.next_ready()
                if task is None:
                    await asyncio.sleep(_POLL_INTERVAL)
                    continue

                if task.category == TaskCategory.CONFIRM:
                    self._handle_confirm(task)
                    continue

                await self._execute_task(task)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Unexpected error in executor loop")

    # -- Confirm handling ----------------------------------------------------

    def _handle_confirm(self, task: AgentTask) -> None:
        """Block a CONFIRM task so the conversation loop can present it."""
        self._queue.set_blocked(task.id, "Waiting for user confirmation")
        if self._on_task_done:
            self._on_task_done(task)
        self._persist()

    # -- Task execution ------------------------------------------------------

    async def _execute_task(self, task: AgentTask) -> None:
        """Run a single task via a subagent, recording the outcome."""
        self._queue.set_active(task.id)
        context = self._build_context(task)
        subagent = Subagent(
            context,
            self._tools,
            self._provider,
            light_provider=self._light_provider,
        )
        try:
            result = await asyncio.wait_for(subagent.run(), timeout=_TASK_TIMEOUT)
            self._queue.set_done(task.id, result)
            if self._on_task_done:
                self._on_task_done(task)
        except TimeoutError:
            self._queue.set_failed(task.id, "Task timed out")
            if self._on_task_failed:
                self._on_task_failed(task)
        except Exception as exc:
            self._queue.set_failed(task.id, str(exc))
            if self._on_task_failed:
                self._on_task_failed(task)
        finally:
            self._create_followups(task)
            self._persist()

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

    # -- Context building ----------------------------------------------------

    def _build_context(self, task: AgentTask) -> SubagentContext:
        """Construct a ``SubagentContext`` from the current agent state."""
        prior_results: dict[str, str] = {}
        for dep_id in task.dependencies:
            dep = self._queue.get_task(dep_id)
            if dep is not None and dep.result is not None:
                prior_results[dep_id] = dep.result

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
        )

    # -- Persistence ---------------------------------------------------------

    def _persist(self) -> None:
        """Save tasks via the session store if one is available."""
        if self._store is not None:
            self._store.save_tasks(self._queue.all_tasks())
