"""Core agent logic."""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from cantrip.agent.autodeploy import task_for_watcher_event
from cantrip.agent.context import ContextManager, VirtualFileStore
from cantrip.agent.design import parse_design_from_result
from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.planner import PlanningContext, TaskPlanner
from cantrip.agent.preflight import (
    DEFAULT_PRESET,
    PreflightCallback,
    PreflightResult,
    PreflightRunner,
)
from cantrip.agent.prompts import build_system_prompt, claude_md
from cantrip.agent.queue import AgentTask, WorkQueue
from cantrip.agent.skills import SkillsIndex
from cantrip.agent.state import AgentState, Decision, TestResults
from cantrip.agent.store import SessionStore
from cantrip.agent.tools import (
    AnalyseFrameworkTool,
    CharmcraftFetchLibsTool,
    CharmcraftInitTool,
    CharmcraftPackTool,
    CharmcraftReleaseTool,
    CharmcraftUploadTool,
    CharmhubInfoTool,
    CharmhubSearchTool,
    CharmSyncTool,
    CharmValidateTool,
    ConciergePrepareTool,
    ConciergeStatusTool,
    EditFileTool,
    GenerateReadmeTool,
    GhIssueListTool,
    GhPrCreateTool,
    GhRepoCreateTool,
    GitAddTool,
    GitCloneTool,
    GitCommitTool,
    GitDiffTool,
    GitInitTool,
    GitLogTool,
    GitPushTool,
    GitStatusTool,
    JujuAddModelTool,
    JujuConfigTool,
    JujuConsumeTool,
    JujuDebugLogTool,
    JujuDeployTool,
    JujuDestroyModelTool,
    JujuDispatchTool,
    JujuOfferTool,
    JujuRefreshTool,
    JujuRelateTool,
    JujuRunActionTool,
    JujuSSHTool,
    JujuStatusTool,
    JujuWaitTool,
    ListDirectoryTool,
    LoadSkillTool,
    LokiQueryTool,
    ManageTasksTool,
    PlanTasksTool,
    ReadFileTool,
    RegistryImageInfoTool,
    RegistrySearchTool,
    RockcraftInitTool,
    RockcraftPackTool,
    RunCharmTestsTool,
    SkopeoRegistryPushTool,
    TempoQueryTool,
    Tool,
    ToolResult,
    VirtualFileReadTool,
    VirtualFileSearchTool,
    WebFetchTool,
    WriteFileTool,
)
from cantrip.agent.watcher import EventWatcher, WatcherConfig, WatcherEvent
from cantrip.llm.base import (
    LLMProvider,
    Message,
    ProviderOverloadedError,
    ProviderRateLimitError,
    Response,
    Role,
)
from cantrip.llm.base import Tool as LLMTool
from cantrip.llm.base import ToolResult as LLMToolResult

log = logging.getLogger(__name__)

# Re-export for backwards compatibility.
__all__ = ["AgentState", "CantripAgent", "Decision"]

# Maximum tool-call rounds before we force the model to respond with text.
MAX_TOOL_ROUNDS = 20

# Retry settings for transient LLM errors (rate limits, overload) during the tool loop.
_TRANSIENT_RETRIES = 3
_TRANSIENT_BASE_DELAY = 30  # seconds

# Tools whose results may contain a test summary to surface in the TUI.
_TEST_RESULT_TOOLS = frozenset({"run_charm_tests", "charm_validate"})

# Purposes that can use the light model.
_LIGHT_PURPOSES = frozenset({"compaction"})


class CantripAgent:
    """Main Cantrip agent."""

    def __init__(
        self,
        provider: LLMProvider,
        charm_path: Path | None = None,
        light_provider: LLMProvider | None = None,
    ):
        """Initialise the agent.

        Heavy work (skills discovery, tool creation, session store) is
        deferred until first use so that startup stays fast.

        When *light_provider* is given it is used for internal tasks
        like context compaction, saving cost on the primary model.
        """
        self.provider = provider
        self._light_provider = light_provider
        self.state = AgentState(charm_path=charm_path)
        self._work_queue = WorkQueue()
        self._preflight = PreflightRunner(self.state)

        # Context window management.
        self._virtual_store = VirtualFileStore()
        self._context_manager = ContextManager(
            virtual_store=self._virtual_store,
            context_window_tokens=provider.context_window_tokens,
        )

        # Lazy-initialised on first access via properties.
        self._skills_index_cache: SkillsIndex | None = None
        self._tools_cache: list[Tool] | None = None
        self._tool_map_cache: dict[str, Tool] | None = None
        self._store: SessionStore | None = None
        self._store_initialised = False

        self._watcher: EventWatcher | None = None
        self._executor: BackgroundExecutor | None = None

        if charm_path:
            self._ensure_claude_md(charm_path)

    @property
    def work_queue(self) -> WorkQueue:
        """The agent's work queue, for TUI and executor access."""
        return self._work_queue

    @property
    def context_manager(self) -> ContextManager:
        """The agent's context manager, for TUI status display."""
        return self._context_manager

    @property
    def _skills_index(self) -> SkillsIndex:
        """Skills index, discovered lazily on first access."""
        if self._skills_index_cache is None:
            self._skills_index_cache = SkillsIndex()
            self._skills_index_cache.discover()
        return self._skills_index_cache

    @property
    def _tools(self) -> list[Tool]:
        """Tool instances, built lazily on first access."""
        if self._tools_cache is None:
            self._tools_cache = self._build_tools()
            self._tool_map_cache = {t.name: t for t in self._tools_cache}
        return self._tools_cache

    @property
    def _tool_map(self) -> dict[str, Tool]:
        """Tool lookup by name, built lazily alongside _tools."""
        if self._tool_map_cache is None:
            # Accessing _tools triggers the build.
            _ = self._tools
        return self._tool_map_cache  # type: ignore[return-value]

    def _ensure_store(self) -> None:
        """Initialise the session store on first need."""
        if self._store_initialised:
            return
        self._store_initialised = True
        if self.state.charm_path:
            self._init_store(self.state.charm_path)

    def _init_store(self, charm_path: Path) -> None:
        """Initialise the session store, migrating from JSON if necessary."""
        db_path = charm_path / ".cantrip"

        # Migrate from the old directory-based layout.
        old_dir = charm_path / ".cantrip"
        if old_dir.is_dir():
            json_file = old_dir / "session.json"
            backup = charm_path / ".cantrip.bak"
            if json_file.exists():
                temp_db = charm_path / ".cantrip.tmp"
                SessionStore.migrate_from_json(json_file, temp_db)
                old_dir.rename(backup)
                temp_db.rename(db_path)
                log.info("Migrated .cantrip/ to SQLite (old directory saved as .cantrip.bak)")
            else:
                old_dir.rename(backup)

        self._store = SessionStore(db_path)

    def _ensure_claude_md(self, charm_path: Path) -> None:
        """Write a CLAUDE.md into the charm directory if one does not exist."""
        target = charm_path / "CLAUDE.md"
        if target.exists():
            return
        charm_name = self.state.charm_name or charm_path.name
        content = claude_md.render_claude_md(charm_name, charm_type=self.state.charm_type)
        target.write_text(content)
        log.info("Wrote CLAUDE.md to %s", charm_path)

    def _record_usage(self, response: Response) -> None:
        """Record token usage from a provider response if a store is active."""
        self._ensure_store()
        if self._store and response.usage:
            self._store.record_usage(
                provider=self.provider.name,
                model=self.provider.model_name,
                prompt_tokens=response.usage.get("prompt_tokens", 0),
                completion_tokens=response.usage.get("completion_tokens", 0),
            )

    def _get_provider(self, purpose: str) -> LLMProvider:
        """Select the appropriate provider for a given purpose.

        Purposes listed in ``_LIGHT_PURPOSES`` are routed to the light
        provider when one is available; everything else uses the primary.
        """
        if self._light_provider and purpose in _LIGHT_PURPOSES:
            return self._light_provider
        return self.provider

    def _build_tools(self) -> list[Tool]:
        """Build available tools."""
        base_path = self.state.charm_path

        return [
            # File operations
            ReadFileTool(base_path=base_path),
            WriteFileTool(base_path=base_path),
            ListDirectoryTool(base_path=base_path),
            EditFileTool(base_path=base_path),
            # Charm operations
            CharmcraftInitTool(),
            CharmcraftPackTool(),
            CharmValidateTool(),
            CharmcraftFetchLibsTool(),
            AnalyseFrameworkTool(),
            # Publishing
            CharmcraftUploadTool(),
            CharmcraftReleaseTool(),
            GenerateReadmeTool(),
            # Web
            WebFetchTool(),
            # Charmhub
            CharmhubSearchTool(),
            CharmhubInfoTool(),
            # Skills
            LoadSkillTool(self._skills_index),
            # Virtual files
            VirtualFileReadTool(self._virtual_store),
            VirtualFileSearchTool(self._virtual_store),
            # Registry
            RegistrySearchTool(),
            RegistryImageInfoTool(),
            # Rockcraft operations
            RockcraftInitTool(),
            RockcraftPackTool(),
            SkopeoRegistryPushTool(),
            # Environment
            ConciergePrepareTool(),
            ConciergeStatusTool(),
            # Git operations
            GitCloneTool(),
            GitInitTool(),
            GitStatusTool(),
            GitDiffTool(),
            GitLogTool(),
            GitAddTool(),
            GitCommitTool(),
            GitPushTool(),
            # GitHub operations
            GhRepoCreateTool(),
            GhPrCreateTool(),
            GhIssueListTool(),
            # Juju operations
            JujuStatusTool(),
            JujuDeployTool(),
            JujuRefreshTool(),
            JujuRelateTool(),
            JujuSSHTool(),
            JujuRunActionTool(),
            JujuAddModelTool(),
            JujuDestroyModelTool(),
            JujuOfferTool(),
            JujuConsumeTool(),
            JujuConfigTool(),
            JujuWaitTool(),
            CharmSyncTool(),
            JujuDispatchTool(),
            # Observability
            JujuDebugLogTool(),
            TempoQueryTool(),
            LokiQueryTool(),
            # Testing
            RunCharmTestsTool(),
            # Planning
            PlanTasksTool(
                provider=self.provider,
                state=self.state,
                queue=self._work_queue,
            ),
            # Task management
            ManageTasksTool(queue=self._work_queue),
        ]

    def _build_system_prompt(self) -> str:
        """Build the current system prompt."""
        return build_system_prompt(
            charm_name=self.state.charm_name,
            charm_path=str(self.state.charm_path) if self.state.charm_path else None,
            charm_type=self.state.charm_type,
            framework=self.state.framework,
            dev_model=self.state.dev_model,
            cos_model=self.state.cos_model,
            recent_decisions=[d.to_dict() for d in self.state.decisions],
            skills_index=self._skills_index.format_for_prompt(),
            environment_ready=self.state.environment_ready,
            watcher_enabled=self.state.watcher_enabled,
        )

    def _tools_for_llm(self) -> list[LLMTool]:
        """Convert tools to LLM format."""
        return [
            LLMTool(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters,
            )
            for tool in self._tools
        ]

    async def _execute_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool by name."""
        tool = self._tool_map.get(name)
        if not tool:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown tool: {name}",
            )

        try:
            return await tool.execute(**arguments)
        except TypeError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Invalid arguments for {name}: {e}",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Tool execution failed: {e}",
            )

    def _capture_test_results(self, tool_name: str, result: ToolResult) -> None:
        """Update state with test results if the tool produced a test summary."""
        if tool_name not in _TEST_RESULT_TOOLS:
            return
        data = result.data if hasattr(result, "data") else {}
        if tool_name == "charm_validate":
            summary = data.get("tests", {}).get("summary", {})
        else:
            summary = data.get("summary", {})
        if not summary:
            return
        self.state.test_results = TestResults(
            test_type="unit",
            passed=summary.get("passed", 0),
            failed=summary.get("failed", 0),
            error=summary.get("error", 0),
            skipped=summary.get("skipped", 0),
        )

    def _build_llm_messages(self, include_budget: bool = False) -> list[Message]:
        """Build the full message list for the LLM including system prompt.

        When *include_budget* is True, a transient context budget message
        is appended (not stored in state.messages).
        """
        messages = [
            Message(role=Role.SYSTEM, content=self._build_system_prompt()),
            *self.state.messages,
        ]
        if include_budget:
            messages.append(self._context_manager.build_budget_message(messages))
        return messages

    async def _complete_with_retry(
        self,
        messages: list[Message],
        tools: list[LLMTool] | None,
        temperature: float = 0.7,
    ) -> Response:
        """Call provider.complete() with retry and exponential backoff for transient errors."""
        last_error: ProviderRateLimitError | ProviderOverloadedError | None = None
        for attempt in range(1, _TRANSIENT_RETRIES + 1):
            try:
                return await self.provider.complete(
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                )
            except (ProviderRateLimitError, ProviderOverloadedError) as exc:
                last_error = exc
                if attempt == _TRANSIENT_RETRIES:
                    raise
                delay = _TRANSIENT_BASE_DELAY * attempt
                log.warning(
                    "Provider unavailable — retrying in %ds (attempt %d/%d): %s",
                    delay,
                    attempt,
                    _TRANSIENT_RETRIES,
                    exc,
                )
                await asyncio.sleep(delay)
        # All retries exhausted (should be unreachable due to the raise above).
        raise last_error  # type: ignore[misc]

    def _pause_executor(self) -> None:
        """Pause the background executor while handling a user message."""
        if self._executor and self._executor.running:
            self._executor.pause()

    def _resume_executor(self) -> None:
        """Resume the background executor after handling a user message."""
        if self._executor and self._executor.running:
            self._executor.resume()

    async def process_message(self, user_message: str) -> str:
        """Process a user message and return the response.

        This handles the full conversation loop including tool calls.
        The loop continues until the model responds without tool calls
        or the maximum number of rounds is reached.

        The background executor is paused while the conversation loop is
        active so that user steering takes priority over autonomous work.
        """
        self._pause_executor()
        try:
            return await self._process_message_inner(user_message)
        finally:
            self._resume_executor()

    async def _process_message_inner(self, user_message: str) -> str:
        """Inner implementation of process_message (executor already paused)."""
        user_msg = Message(role=Role.USER, content=user_message)
        user_msg = self._context_manager.virtualise_message(user_msg)
        self.state.messages.append(user_msg)

        messages = self._build_llm_messages(include_budget=True)
        llm_tools = self._tools_for_llm() if self._tools else None

        response = await self._complete_with_retry(messages, llm_tools)
        self._record_usage(response)

        rounds = 0
        while response.tool_calls and rounds < MAX_TOOL_ROUNDS:
            rounds += 1

            # Record the assistant message with its tool calls.
            assistant_msg = Message(
                role=Role.ASSISTANT,
                content=response.content,
                tool_calls=response.tool_calls,
                metadata=response.metadata,
            )
            self.state.messages.append(assistant_msg)

            # Execute each tool and build TOOL result messages.
            tool_results = []
            for tc in response.tool_calls:
                result = await self._execute_tool(tc.name, tc.arguments)
                self._capture_test_results(tc.name, result)
                content = result.output if result.success else (result.error or "Unknown error")
                tool_results.append(
                    LLMToolResult(
                        tool_call_id=tc.id,
                        content=content,
                        is_error=not result.success,
                    )
                )

            tool_msg = Message(
                role=Role.TOOL,
                content="",
                tool_results=tool_results,
            )
            # Virtualise large tool results before storing.
            tool_msg = self._context_manager.virtualise_message(tool_msg)
            self.state.messages.append(tool_msg)

            # Compact if the context window is getting full.
            if self._context_manager.should_compact(self.state.messages):
                log.info("Compacting conversation context")
                self.state.messages = await self._context_manager.compact(
                    self.state.messages,
                    system_prompt=self._build_system_prompt(),
                    provider=self._get_provider("compaction"),
                )

            # Call the LLM again with the updated history.
            messages = self._build_llm_messages(include_budget=True)
            response = await self._complete_with_retry(messages, llm_tools)
            self._record_usage(response)

        # Store the final assistant response.
        self.state.messages.append(
            Message(role=Role.ASSISTANT, content=response.content, metadata=response.metadata)
        )
        return response.content

    async def process_message_streaming(self, user_message: str) -> AsyncIterator[str]:
        """Process a message with streaming response.

        Yields text chunks as they arrive. If the model requests tool calls,
        those are executed and the model is called again (non-streaming for
        intermediate rounds, streaming for the final text response).

        The background executor is paused while the conversation loop is
        active so that user steering takes priority over autonomous work.
        """
        self._pause_executor()
        try:
            async for chunk in self._process_message_streaming_inner(user_message):
                yield chunk
        finally:
            self._resume_executor()

    async def _process_message_streaming_inner(self, user_message: str) -> AsyncIterator[str]:
        """Inner implementation of streaming (executor already paused)."""
        user_msg = Message(role=Role.USER, content=user_message)
        user_msg = self._context_manager.virtualise_message(user_msg)
        self.state.messages.append(user_msg)

        llm_tools = self._tools_for_llm() if self._tools else None

        # Use non-streaming complete for potential tool call rounds.
        messages = self._build_llm_messages(include_budget=True)
        response = await self._complete_with_retry(messages, llm_tools)
        self._record_usage(response)

        rounds = 0
        while response.tool_calls and rounds < MAX_TOOL_ROUNDS:
            rounds += 1

            assistant_msg = Message(
                role=Role.ASSISTANT,
                content=response.content,
                tool_calls=response.tool_calls,
                metadata=response.metadata,
            )
            self.state.messages.append(assistant_msg)

            tool_results = []
            for tc in response.tool_calls:
                result = await self._execute_tool(tc.name, tc.arguments)
                self._capture_test_results(tc.name, result)
                content = result.output if result.success else (result.error or "Unknown error")
                tool_results.append(
                    LLMToolResult(
                        tool_call_id=tc.id,
                        content=content,
                        is_error=not result.success,
                    )
                )

            tool_msg = Message(
                role=Role.TOOL,
                content="",
                tool_results=tool_results,
            )
            # Virtualise large tool results before storing.
            tool_msg = self._context_manager.virtualise_message(tool_msg)
            self.state.messages.append(tool_msg)

            # Compact if the context window is getting full.
            if self._context_manager.should_compact(self.state.messages):
                log.info("Compacting conversation context")
                self.state.messages = await self._context_manager.compact(
                    self.state.messages,
                    system_prompt=self._build_system_prompt(),
                    provider=self._get_provider("compaction"),
                )

            messages = self._build_llm_messages(include_budget=True)
            response = await self._complete_with_retry(messages, llm_tools)
            self._record_usage(response)

        # Now stream the final text response.
        # Since we already have the content from complete(), just yield it.
        full_response = response.content
        self.state.messages.append(
            Message(
                role=Role.ASSISTANT,
                content=full_response,
                metadata=response.metadata,
            )
        )
        yield full_response

    # -- Design confirmation ---------------------------------------------------

    async def handle_design_confirmation(
        self,
        confirm_task_id: str,
        overrides: str | None = None,
    ) -> list[AgentTask]:
        """Process an approved design-confirm task and generate build tasks.

        1. Finds the synthesis task result from the dependency chain.
        2. Parses it into a ``DesignProposal``.
        3. Records key decisions.
        4. Generates build tasks via the planner.
        5. Adds build tasks to the work queue.
        """
        confirm_task = self._work_queue.get_task(confirm_task_id)
        if confirm_task is None:
            log.warning("Design confirm task %s not found", confirm_task_id)
            return []

        # Walk dependencies to find the synthesis result.
        design_text = ""
        for dep_id in confirm_task.dependencies:
            dep = self._work_queue.get_task(dep_id)
            if dep is not None and dep.result:
                design_text = dep.result
                break

        if not design_text:
            log.warning("No synthesis result found for design confirmation")
            return []

        # Parse the design and store on state.
        proposal = parse_design_from_result(design_text)
        self.state.design_proposal = proposal

        # Record key decisions.
        if proposal.substrate:
            self.state.add_decision(
                "substrate", proposal.substrate, proposal.substrate_reasoning or None
            )
        if proposal.charm_path:
            self.state.add_decision(
                "charm_path", proposal.charm_path, proposal.charm_path_reasoning or None
            )
        if proposal.charmhub_recommendation:
            self.state.add_decision("charmhub", proposal.charmhub_recommendation)

        # Generate build tasks from the approved design.
        planner = TaskPlanner(self.provider)
        context = PlanningContext(
            intent=f"Build a charm for {proposal.workload_name or 'the workload'}",
            charm_name=self.state.charm_name,
            charm_type=self.state.charm_type or proposal.substrate or None,
            framework=self.state.framework,
            dev_model=self.state.dev_model,
            cos_model=self.state.cos_model,
            environment_ready=self.state.environment_ready,
        )
        build_tasks = await planner.plan_from_design(
            design_content=proposal.to_design_md(),
            context=context,
            overrides=overrides,
        )
        self._work_queue.add_tasks(build_tasks)
        return build_tasks

    # -- Watcher integration ---------------------------------------------------

    @property
    def watcher_running(self) -> bool:
        """Whether the event watcher is currently running."""
        return self._watcher is not None and self._watcher.running

    def start_watcher(
        self,
        config: WatcherConfig | None = None,
        on_event: Callable | None = None,
    ) -> bool:
        """Create and start the event watcher.

        Returns ``False`` if no ``dev_model`` is set (the watcher requires a
        development model to monitor).  Every watcher event is automatically
        routed to the task queue before the external callback fires.
        """
        if not self.state.dev_model:
            return False

        def _auto_route(event: WatcherEvent) -> None:
            """Route the event to the task queue, then fire the external callback."""
            self.route_watcher_event(event)
            if on_event is not None:
                on_event(event)

        self._watcher = EventWatcher(
            dev_model=self.state.dev_model,
            cos_model=self.state.cos_model,
            config=config,
            on_event=_auto_route,
        )
        self._watcher.start()
        self.state.watcher_enabled = True
        return True

    async def stop_watcher(self) -> None:
        """Stop the event watcher if it is running."""
        if self._watcher:
            await self._watcher.stop()
            self._watcher = None
        self.state.watcher_enabled = False

    def route_watcher_event(self, event: WatcherEvent) -> AgentTask | None:
        """Convert a watcher event into a task and add it to the work queue.

        Returns the created task, or ``None`` if the event did not map to a
        task (e.g. no dev_model or unrecognised category).
        """
        task = task_for_watcher_event(event, self.state)
        if task is not None:
            self._work_queue.add_task(task)
        return task

    async def process_watcher_event(self) -> str | None:
        """Dequeue one watcher event and route it to the task queue.

        Returns the task title, or ``None`` if no events are pending.
        """
        if not self._watcher:
            return None
        event = await self._watcher.dequeue()
        if event is None:
            return None
        task = self.route_watcher_event(event)
        if task is not None:
            return task.title
        return None

    # -- Executor integration -------------------------------------------------

    @property
    def executor_running(self) -> bool:
        """Whether the background executor is currently running."""
        return self._executor is not None and self._executor.running

    def start_executor(
        self,
        on_task_changed: Callable[[AgentTask], None] | None = None,
        max_concurrency: int | None = None,
    ) -> None:
        """Create and start the background executor.

        Mirrors the ``start_watcher`` / ``stop_watcher`` pattern.  The
        *on_task_changed* callback is installed on the work queue so every
        task mutation can drive TUI updates.  *max_concurrency* controls
        how many subagent tasks run in parallel (default 3).
        """
        if self._executor is not None and self._executor.running:
            return
        self._ensure_store()
        self._work_queue._on_task_changed = on_task_changed
        kwargs: dict[str, object] = {
            "queue": self._work_queue,
            "tools": self._tools,
            "provider": self.provider,
            "state": self.state,
            "store": self._store,
            "light_provider": self._light_provider,
        }
        if max_concurrency is not None:
            kwargs["max_concurrency"] = max_concurrency
        self._executor = BackgroundExecutor(**kwargs)
        self._executor.start()

    async def stop_executor(self) -> None:
        """Stop the background executor if it is running."""
        if self._executor:
            await self._executor.stop()
            self._executor = None

    def save_state(self) -> None:
        """Save agent state to the session store."""
        self._ensure_store()
        if self._store:
            self._store.save_session(self.state)

    def load_state(self) -> bool:
        """Load agent state from the session store.

        Returns True if state was loaded, False if no state exists.
        """
        self._ensure_store()
        if not self._store:
            return False

        loaded = self._store.load_session()
        if loaded is None:
            return False

        self.state.charm_name = loaded.charm_name
        self.state.charm_path = loaded.charm_path
        self.state.charm_type = loaded.charm_type
        self.state.framework = loaded.framework
        self.state.dev_model = loaded.dev_model
        self.state.cos_model = loaded.cos_model
        self.state.decisions = loaded.decisions

        # Restore persisted tasks into the work queue.
        tasks = self._store.load_tasks()
        if tasks:
            self._work_queue.add_tasks(tasks)

        return True

    async def prepare(
        self,
        preset: str = DEFAULT_PRESET,
        callback: PreflightCallback | None = None,
    ) -> PreflightResult:
        """Run the full environment preparation eagerly.

        Calls ``concierge prepare --preset {preset}`` (installing snaps *and*
        bootstrapping) so the environment is ready by the time the user
        finishes describing their charm.
        """
        self._preflight = PreflightRunner(self.state, callback=callback)
        result = await self._preflight.prepare(preset)
        self.state.environment_ready = result.fully_ready
        return result

    async def warm_up(self, callback: PreflightCallback | None = None) -> PreflightResult:
        """Run phase 1 preflight: install snaps without bootstrapping."""
        self._preflight = PreflightRunner(self.state, callback=callback)
        return await self._preflight.warm_up()

    async def bootstrap_environment(
        self,
        preset: str,
        callback: PreflightCallback | None = None,
    ) -> PreflightResult:
        """Run phase 2 preflight: bootstrap controller and deploy COS.

        If ``prepare()`` already completed with the same preset, this is a
        no-op.
        """
        if self._preflight.result.fully_ready and self._preflight.result.preset == preset:
            return self._preflight.result

        self._preflight._callback = callback
        result = await self._preflight.bootstrap(preset)
        self.state.environment_ready = result.fully_ready
        return result

    @property
    def preflight_result(self) -> PreflightResult:
        """Current preflight result."""
        return self._preflight.result
