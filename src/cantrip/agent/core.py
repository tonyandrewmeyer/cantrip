"""Core agent logic."""

import logging
import re
import sqlite3
import subprocess
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from cantrip.agent.autodeploy import task_for_watcher_event
from cantrip.agent.context import ContextManager, VirtualFileStore
from cantrip.agent.design import parse_design_from_result
from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.git_branch import (
    PUSH_CONFIRM_PREFIX,
    PrFeedback,
    bootstrap_github_repo,
    build_pr_body,
    can_bootstrap,
    check_upstream_diverged,
    create_branch,
    create_pull_request,
    gh_issue_comment,
    gh_pr_view,
    push_branch,
)
from cantrip.agent.github_issues import (
    TRIAGE_CONFIRM_PREFIX,
    IssueTriage,
    build_issue_work_tasks,
)
from cantrip.agent.planner import (
    PlanningContext,
    TaskPlanner,
    find_day2_anchor,
    is_one_shot_build,
    plan_day2_ops_phase,
    plan_improvement_fixes,
    plan_one_shot_build,
)
from cantrip.agent.preflight import (
    DEFAULT_PRESET,
    PreflightCallback,
    PreflightResult,
    PreflightRunner,
)
from cantrip.agent.prompts import build_system_prompt, claude_md
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.retry import complete_with_retry
from cantrip.agent.skills import SkillsIndex
from cantrip.agent.state import AgentState, Decision, TestResults
from cantrip.agent.store import SessionStore
from cantrip.agent.tools import Tool, ToolResult, build_tools
from cantrip.agent.watcher import EventWatcher, WatcherConfig, WatcherEvent
from cantrip.llm import base as llm
from cantrip.llm.base import Chunk, LLMProvider, Message, Response, Role
from cantrip.ui import events as ui_events

log = logging.getLogger(__name__)

# Re-export for backwards compatibility.
__all__ = ["AgentState", "CantripAgent", "Decision"]

# Maximum tool-call rounds before we force the model to respond with text.
MAX_TOOL_ROUNDS = 20

# Tools whose results may contain a test summary to surface in the TUI.
_TEST_RESULT_TOOLS = frozenset({"run_charm_tests", "charm_validate"})

# Purposes that can use the light model.
_LIGHT_PURPOSES = frozenset({"compaction"})

# Pattern for GitHub HTTPS and SSH remote URLs.
_GITHUB_HTTPS_RE = re.compile(r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?$")
_GITHUB_SSH_RE = re.compile(r"git@github\.com:([^/]+/[^/]+?)(?:\.git)?$")


def detect_github_repo(charm_path: Path | None) -> str | None:
    """Detect a GitHub owner/repo from the git remote origin URL.

    Parses both HTTPS (``https://github.com/owner/repo``) and SSH
    (``git@github.com:owner/repo``) remote URLs.  Returns a string
    like ``"canonical/grafana-k8s"`` or *None* if the remote is not a
    GitHub URL or git is unavailable.
    """
    if charm_path is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["git", "remote", "get-url", "origin"],
            cwd=str(charm_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    for pattern in (_GITHUB_HTTPS_RE, _GITHUB_SSH_RE):
        m = pattern.match(url)
        if m:
            return m.group(1)
    return None


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
        if charm_path is not None and not isinstance(charm_path, Path):
            charm_path = Path(charm_path)
        self.state = AgentState(charm_path=charm_path)
        self.state.github_repo = detect_github_repo(charm_path)
        if self.state.github_repo:
            log.info("Detected GitHub remote: %s", self.state.github_repo)
        self._work_queue = WorkQueue()
        self._event_bus = ui_events.EventBus()
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
        self._issue_triage: IssueTriage | None = None

        # Session-level prompt cache accumulators (Claude-specific).
        self.cache_creation_tokens: int = 0
        self.cache_read_tokens: int = 0

        if charm_path:
            self._ensure_claude_md(charm_path)

    @property
    def event_bus(self) -> ui_events.EventBus:
        """The shared UI event bus."""
        return self._event_bus

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
        assert self._tool_map_cache is not None
        return self._tool_map_cache

    @property
    def store(self) -> SessionStore | None:
        """Return the session store, initialising lazily if needed."""
        self._ensure_store()
        return self._store

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
        if not charm_path.is_dir():
            return
        charm_name = self.state.charm_name or charm_path.name
        content = claude_md.render_claude_md(charm_name, charm_type=self.state.charm_type)
        target.write_text(content)
        log.info("Wrote CLAUDE.md to %s", charm_path)

    def _record_usage(self, response: Response) -> int | None:
        """Record token usage from a provider response if a store is active."""
        if response.usage:
            self.cache_creation_tokens += response.usage.get("cache_creation_input_tokens", 0)
            self.cache_read_tokens += response.usage.get("cache_read_input_tokens", 0)
        self._ensure_store()
        if self._store and response.usage:
            return self._store.record_usage(
                provider=self.provider.name,
                model=self.provider.model_name,
                prompt_tokens=response.usage.get("prompt_tokens", 0),
                completion_tokens=response.usage.get("completion_tokens", 0),
            )
        return None

    def _record_message(self, msg: Message) -> None:
        """Persist a conversation message to the session store."""
        self._ensure_store()
        if not self._store:
            return
        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in msg.tool_calls
            ]
        tool_results = None
        if msg.tool_results:
            tool_results = [
                {
                    "tool_call_id": tr.tool_call_id,
                    "content": tr.content,
                    "is_error": tr.is_error,
                }
                for tr in msg.tool_results
            ]
        self._store.record_message(
            role=msg.role.value,
            content=msg.content,
            tool_calls=tool_calls,
            tool_results=tool_results,
            metadata=msg.metadata or None,
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
        return build_tools(
            base_path=self.state.charm_path,
            skills_index=self._skills_index,
            virtual_store=self._virtual_store,
            provider=self.provider,
            state=self.state,
            queue=self._work_queue,
        )

    def _build_system_prompt(self) -> str:
        """Build the current system prompt.

        Uses a compact prompt for providers with limited context windows
        to avoid exceeding the model's capacity.
        """
        compact = self.provider.max_tools is not None
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
            compact=compact,
        )

    # Tools that are always included when the provider has a tool limit.
    _CORE_TOOL_NAMES: set[str] = {
        "read_file",
        "write_file",
        "list_directory",
        "edit_file",
        "charmcraft_init",
        "charmcraft_pack",
        "analyse_framework",
        "juju_status",
        "juju_deploy",
        "run_charm_tests",
        "web_fetch",
        "plan_tasks",
    }

    def _tools_for_llm(self) -> list[llm.Tool]:
        """Convert tools to LLM format.

        When the provider declares a ``max_tools`` limit, only the core
        tools are sent to avoid exceeding the model's context window.
        """
        tools = self._tools
        limit = self.provider.max_tools
        if limit is not None and len(tools) > limit:
            tools = [t for t in tools if t.name in self._CORE_TOOL_NAMES][:limit]

        return [
            llm.Tool(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters,
            )
            for tool in tools
        ]

    async def _execute_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool by name."""
        from cantrip.agent.tools.base import execute_tool

        return await execute_tool(self._tool_map, name, arguments)

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
        tools: list[llm.Tool] | None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> Response:
        """Call provider.complete() with retry and linear backoff for transient errors."""
        return await complete_with_retry(
            self.provider,
            messages,
            tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )

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

    async def _run_conversation_loop(self, user_message: str) -> Response:
        """Shared conversation loop: send a message, execute tool calls, repeat.

        Returns the final ``Response`` once the model responds without tool
        calls (or the maximum round count is reached).
        """
        # Record session start event on first message.
        if not self.state.messages:
            self._ensure_store()
            if self._store:
                self._store.record_event(
                    "session_start",
                    {
                        "provider": self.provider.name,
                        "model": self.provider.model_name,
                        "charm_name": self.state.charm_name,
                    },
                )

        user_msg = Message(role=Role.USER, content=user_message)
        user_msg = self._context_manager.virtualise_message(user_msg)
        self.state.messages.append(user_msg)
        self._record_message(user_msg)

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
            self._record_message(assistant_msg)

            # Execute each tool and build TOOL result messages.
            tool_results = []
            for tc in response.tool_calls:
                result = await self._execute_tool(tc.name, tc.arguments)
                self._capture_test_results(tc.name, result)
                content = result.output if result.success else (result.error or "Unknown error")
                # Wrap tool output in delimiters to reduce prompt injection risk.
                content = f"<tool_result name={tc.name!r}>\n{content}\n</tool_result>"
                tool_results.append(
                    llm.ToolResult(
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
            self._record_message(tool_msg)

            # Compact if the context window is getting full.
            if self._context_manager.should_compact(self.state.messages):
                log.info("Compacting conversation context")
                try:
                    self.state.messages = await self._context_manager.compact(
                        self.state.messages,
                        system_prompt=self._build_system_prompt(),
                        provider=self._get_provider("compaction"),
                    )
                except Exception:
                    # Compaction is best-effort; fall back to crude truncation
                    # so the conversation can continue.
                    log.warning(
                        "Compaction failed, falling back to emergency truncation",
                        exc_info=True,
                    )
                    self.state.messages = self._context_manager.emergency_truncate(
                        self.state.messages
                    )

            # Call the LLM again with the updated history.
            messages = self._build_llm_messages(include_budget=True)
            response = await self._complete_with_retry(messages, llm_tools)
            self._record_usage(response)

        # Store the final assistant response.
        final_msg = Message(
            role=Role.ASSISTANT,
            content=response.content,
            metadata=response.metadata,
        )
        self.state.messages.append(final_msg)
        self._record_message(final_msg)
        return response

    async def _process_message_inner(self, user_message: str) -> str:
        """Inner implementation of process_message (executor already paused)."""
        response = await self._run_conversation_loop(user_message)
        return response.content

    async def process_message_streaming(self, user_message: str) -> AsyncIterator[str]:
        """Process a message with streaming response.

        Yields text chunks as they arrive from the provider's ``stream()``
        method.  When the model requests tool calls, those are executed
        and the model is called again — streaming resumes for each
        subsequent LLM call until a text-only response is produced.

        The background executor is paused while the conversation loop is
        active so that user steering takes priority over autonomous work.
        """
        self._pause_executor()
        try:
            async for chunk in self._run_conversation_loop_streaming(user_message):
                yield chunk
        finally:
            self._resume_executor()

    async def _run_conversation_loop_streaming(
        self,
        user_message: str,
    ) -> AsyncIterator[str]:
        """Streaming variant of the conversation loop.

        Yields text chunks as they arrive from the provider.  Tool-call
        rounds are handled internally; only text destined for the user
        is yielded.
        """
        # Record session start event on first message.
        if not self.state.messages:
            self._ensure_store()
            if self._store:
                self._store.record_event(
                    "session_start",
                    {
                        "provider": self.provider.name,
                        "model": self.provider.model_name,
                        "charm_name": self.state.charm_name,
                    },
                )

        user_msg = Message(role=Role.USER, content=user_message)
        user_msg = self._context_manager.virtualise_message(user_msg)
        self.state.messages.append(user_msg)
        self._record_message(user_msg)

        messages = self._build_llm_messages(include_budget=True)
        llm_tools = self._tools_for_llm() if self._tools else None

        # Stream the first LLM call.
        accumulated = ""
        final_chunk = Chunk(is_final=True)
        async for chunk in self.provider.stream(messages=messages, tools=llm_tools):
            if chunk.content:
                accumulated += chunk.content
                yield chunk.content
            if chunk.is_final:
                final_chunk = chunk

        # Build a synthetic Response for bookkeeping.
        response = Response(
            content=accumulated,
            tool_calls=final_chunk.tool_calls,
            usage=final_chunk.usage,
            metadata=final_chunk.metadata,
        )
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
            self._record_message(assistant_msg)

            # Execute each tool and build TOOL result messages.
            tool_results = []
            for tc in response.tool_calls:
                result = await self._execute_tool(tc.name, tc.arguments)
                self._capture_test_results(tc.name, result)
                content = result.output if result.success else (result.error or "Unknown error")
                content = f"<tool_result name={tc.name!r}>\n{content}\n</tool_result>"
                tool_results.append(
                    llm.ToolResult(
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
            tool_msg = self._context_manager.virtualise_message(tool_msg)
            self.state.messages.append(tool_msg)
            self._record_message(tool_msg)

            # Compact if the context window is getting full.
            if self._context_manager.should_compact(self.state.messages):
                log.info("Compacting conversation context")
                try:
                    self.state.messages = await self._context_manager.compact(
                        self.state.messages,
                        system_prompt=self._build_system_prompt(),
                        provider=self._get_provider("compaction"),
                    )
                except Exception:
                    log.warning(
                        "Compaction failed, falling back to emergency truncation",
                        exc_info=True,
                    )
                    self.state.messages = self._context_manager.emergency_truncate(
                        self.state.messages
                    )

            # Stream the next LLM call.
            messages = self._build_llm_messages(include_budget=True)
            accumulated = ""
            final_chunk = Chunk(is_final=True)
            async for chunk in self.provider.stream(messages=messages, tools=llm_tools):
                if chunk.content:
                    accumulated += chunk.content
                    yield chunk.content
                if chunk.is_final:
                    final_chunk = chunk

            response = Response(
                content=accumulated,
                tool_calls=final_chunk.tool_calls,
                usage=final_chunk.usage,
                metadata=final_chunk.metadata,
            )
            self._record_usage(response)

        # Store the final assistant response.
        final_msg = Message(
            role=Role.ASSISTANT,
            content=response.content,
            metadata=response.metadata,
        )
        self.state.messages.append(final_msg)
        self._record_message(final_msg)

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
            log.error(
                "Design confirm task %s not found — cannot generate build tasks", confirm_task_id
            )
            return []

        # Walk dependencies to find the synthesis result.
        design_text = ""
        for dep_id in confirm_task.dependencies:
            dep = self._work_queue.get_task(dep_id)
            if dep is not None and dep.result:
                design_text = dep.result
                break

        if not design_text:
            log.error(
                "No synthesis result found for design confirmation (task %s)", confirm_task_id
            )
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
        context = PlanningContext(
            intent=f"Build a charm for {proposal.workload_name or 'the workload'}",
            charm_name=self.state.charm_name,
            charm_type=self.state.charm_type or proposal.substrate or None,
            framework=self.state.framework,
            dev_model=self.state.dev_model,
            cos_model=self.state.cos_model,
            environment_ready=self.state.environment_ready,
        )

        design_md = proposal.to_design_md()
        if is_one_shot_build(context) and not overrides:
            build_tasks = plan_one_shot_build(context, design_md)
        else:
            planner = TaskPlanner(self.provider)
            build_tasks = await planner.plan_from_design(
                design_content=design_md,
                context=context,
                overrides=overrides,
            )
        self._work_queue.add_tasks(build_tasks)

        # Append day-2 operations research phase after the build/deploy tasks.
        anchor = find_day2_anchor(build_tasks)
        if anchor:
            day2_tasks = plan_day2_ops_phase(context, depends_on=anchor)
            self._work_queue.add_tasks(day2_tasks)

        self._ensure_store()
        if self._store:
            self._store.record_event(
                "design_confirmed",
                {
                    "workload": proposal.workload_name,
                    "substrate": proposal.substrate,
                    "charm_path": proposal.charm_path,
                    "build_task_count": len(build_tasks),
                },
            )

        return build_tasks

    # -- Day-2 operations confirmation -----------------------------------------

    async def handle_day2_confirmation(
        self,
        confirm_task_id: str,
        overrides: str | None = None,
    ) -> list[AgentTask]:
        """Process an approved day-2 confirm task and generate implementation tasks.

        1. Finds the synthesis task result from the dependency chain.
        2. Generates implementation tasks via the planner.
        3. Adds implementation tasks to the work queue.
        """
        confirm_task = self._work_queue.get_task(confirm_task_id)
        if confirm_task is None:
            log.error(
                "Day-2 confirm task %s not found — cannot generate implementation tasks",
                confirm_task_id,
            )
            return []

        # Walk dependencies to find the synthesis result.
        day2_text = ""
        for dep_id in confirm_task.dependencies:
            dep = self._work_queue.get_task(dep_id)
            if dep is not None and dep.result:
                day2_text = dep.result
                break

        if not day2_text:
            log.error(
                "No day-2 synthesis result found for confirmation (task %s)", confirm_task_id
            )
            return []

        context = PlanningContext(
            intent=(f"Implement day-2 operations for {self.state.charm_name or 'the charm'}"),
            charm_name=self.state.charm_name,
            charm_type=self.state.charm_type,
            framework=self.state.framework,
            dev_model=self.state.dev_model,
            cos_model=self.state.cos_model,
            environment_ready=self.state.environment_ready,
        )

        planner = TaskPlanner(self.provider)
        impl_tasks = await planner.plan_from_day2_findings(
            findings=day2_text,
            context=context,
            overrides=overrides,
        )
        self._work_queue.add_tasks(impl_tasks)

        self._ensure_store()
        if self._store:
            self._store.record_event(
                "day2_confirmed",
                {
                    "charm_name": self.state.charm_name,
                    "impl_task_count": len(impl_tasks),
                },
            )

        return impl_tasks

    # -- Improvement confirmation ----------------------------------------------

    async def handle_improvement_confirmation(
        self,
        confirm_task_id: str,
    ) -> list[AgentTask]:
        """Process an approved improvement-confirm task and generate fix tasks.

        1. Finds the audit task result from the dependency chain.
        2. Infers gaps from the audit report text (the structured ``data``
           dict is only available on the tool result, not persisted in the
           task result string — so we re-derive gaps heuristically).
        3. Generates fix tasks via ``plan_improvement_fixes``.
        4. Adds them to the work queue.
        """
        confirm_task = self._work_queue.get_task(confirm_task_id)
        if confirm_task is None:
            log.error(
                "Improvement confirm task %s not found — cannot generate fix tasks",
                confirm_task_id,
            )
            return []

        # Walk dependencies to find the audit result.
        audit_text = ""
        for dep_id in confirm_task.dependencies:
            dep = self._work_queue.get_task(dep_id)
            if dep is not None and dep.result:
                audit_text = dep.result
                break

        if not audit_text:
            log.error(
                "No audit result found for improvement confirmation (task %s)", confirm_task_id
            )
            return []

        self.state.audit_report = audit_text

        # Derive gaps from the audit text.  The subagent's result is
        # free-form Markdown, so we look for keywords to infer gaps.
        gaps = _infer_gaps_from_audit(audit_text)

        context = PlanningContext(
            intent="Improve the existing charm",
            charm_name=self.state.charm_name,
            charm_type=self.state.charm_type,
            framework=self.state.framework,
            dev_model=self.state.dev_model,
            cos_model=self.state.cos_model,
            environment_ready=self.state.environment_ready,
            existing_charm_path=str(self.state.charm_path) if self.state.charm_path else ".",
        )

        fix_tasks = plan_improvement_fixes(context, gaps, confirm_task_id=confirm_task_id)

        # Create a feature branch for improvement work.
        charm_name = self.state.charm_name or "charm"
        branch = self._create_feature_branch(f"improve-{charm_name}")

        # Append push-confirm task if a branch was created.
        if branch and fix_tasks:
            last_task_id = fix_tasks[-1].id
            fix_tasks.append(self._build_push_confirm_task(branch, last_task_id))

        self._work_queue.add_tasks(fix_tasks)

        self._ensure_store()
        if self._store:
            self._store.record_event(
                "improvement_confirmed",
                {
                    "charm_name": self.state.charm_name,
                    "gap_count": sum(1 for v in gaps.values() if v),
                    "fix_task_count": len(fix_tasks),
                    "branch": branch or "",
                },
            )

        return fix_tasks

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
            """Route the event to the task queue, then publish to the bus."""
            self.route_watcher_event(event)
            self._event_bus.publish(
                ui_events.watcher_event(
                    source=event.source,
                    category=event.category,
                    summary=event.summary,
                    detail=getattr(event, "detail", ""),
                    app=getattr(event, "app", ""),
                    unit=getattr(event, "unit", ""),
                )
            )
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
        self._ensure_store()
        if self._store:
            self._store.record_event(
                "watcher_event",
                {
                    "category": event.category,
                    "summary": event.summary,
                },
            )

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

    # -- Issue triage integration -----------------------------------------------

    @property
    def issue_triage_running(self) -> bool:
        """Whether the GitHub issue triage worker is active."""
        return self._issue_triage is not None and self._issue_triage.running

    def start_issue_triage(self) -> bool:
        """Start the background issue triage worker.

        Returns ``False`` if no ``github_repo`` is detected or triage
        has already run this session.
        """
        if not self.state.github_repo:
            return False
        if self._issue_triage is not None:
            return False

        def _on_issues_found(confirm_tasks: list[AgentTask]) -> None:
            for task in confirm_tasks:
                self._work_queue.add_task(task)
            self._event_bus.publish(
                ui_events.chat_message(
                    role="system",
                    content=(
                        f"Found {len(confirm_tasks)} actionable GitHub issue(s) "
                        f"— check the task list to approve."
                    ),
                )
            )
            self._ensure_store()
            if self._store:
                self._store.record_event(
                    "issue_triage_complete",
                    {
                        "repo": self.state.github_repo,
                        "candidates": len(confirm_tasks),
                    },
                )

        self._issue_triage = IssueTriage(
            repo=self.state.github_repo,
            on_issues_found=_on_issues_found,
        )
        self._issue_triage.start()
        log.info("Issue triage started for %s", self.state.github_repo)
        return True

    async def stop_issue_triage(self) -> None:
        """Stop the issue triage worker if running."""
        if self._issue_triage:
            await self._issue_triage.stop()
            self._issue_triage = None

    def retriage_issues(self) -> bool:
        """Re-run issue triage to check for new issues.

        Preserves the set of already-examined issues so the user is
        not re-prompted for issues they have already seen.  Returns
        ``False`` if triage cannot run (no repo or already running).
        """
        if not self.state.github_repo:
            return False
        if self._issue_triage and self._issue_triage.running:
            return False

        # Preserve examined set across triage runs.
        examined: set[int] = set()
        if self._issue_triage:
            examined = self._issue_triage.examined_issues

        def _on_issues_found(confirm_tasks: list[AgentTask]) -> None:
            for task in confirm_tasks:
                self._work_queue.add_task(task)
            if confirm_tasks:
                self._event_bus.publish(
                    ui_events.chat_message(
                        role="system",
                        content=(
                            f"Found {len(confirm_tasks)} new actionable issue(s) "
                            f"— check the task list to approve."
                        ),
                    )
                )

        self._issue_triage = IssueTriage(
            repo=self.state.github_repo,
            on_issues_found=_on_issues_found,
        )
        # Transfer examined set from previous run.
        self._issue_triage._examined = examined  # noqa: SLF001
        self._issue_triage.start()
        log.info("Issue re-triage started for %s", self.state.github_repo)
        return True

    def comment_on_issue(self, issue_number: int, pr_url: str) -> str:
        """Post a comment on a resolved GitHub issue.

        Returns a status message for the user.
        """
        repo = self.state.github_repo
        if not repo:
            return "No GitHub repository detected."

        body = (
            f"This issue has been addressed by {pr_url}.\n\n"
            f"*Automated by [Cantrip](https://github.com/canonical/cantrip)*"
        )
        success, result = gh_issue_comment(repo, issue_number, body)

        self._ensure_store()
        if self._store:
            self._store.record_event(
                "issue_commented" if success else "issue_comment_failed",
                {"issue_number": issue_number, "result": result[:500]},
            )

        if success:
            return f"Commented on issue #{issue_number}."
        return f"Failed to comment on issue #{issue_number}: {result}"

    def check_upstream(self) -> str | None:
        """Check if the default branch has diverged from the remote.

        Returns a warning message if behind, or ``None`` if up to date.
        """
        if not self.state.charm_path:
            return None
        diverged, behind = check_upstream_diverged(str(self.state.charm_path))
        if diverged:
            return (
                f"**Warning:** The default branch is {behind} commit(s) behind "
                f"origin. Consider pulling or rebasing before starting new work."
            )
        return None

    # -- PR feedback loop (Phase 42.7) ----------------------------------------

    def check_pr_feedback(self, pr_number: int) -> PrFeedback | None:
        """Fetch review feedback for a pull request.

        Returns structured feedback or ``None`` if unavailable.
        """
        repo = self.state.github_repo
        if not repo:
            return None
        return gh_pr_view(repo, pr_number)

    def create_pr_fix_tasks(
        self,
        feedback: PrFeedback,
        branch_name: str,
    ) -> list[AgentTask]:
        """Generate BUILD tasks to address PR review feedback.

        Creates one BUILD task that addresses all review comments,
        plus a push-confirm task at the end.
        """
        charm_path = str(self.state.charm_path) if self.state.charm_path else "."

        # Build a description from the review comments.
        comment_text = "\n".join(
            f"- **{c.author}**" + (f" (`{c.path}:{c.line}`)" if c.path else "") + f": {c.body}"
            for c in feedback.comments
            if c.body
        )

        fix_id = f"pr-fix-{feedback.pr_number}"
        fix_task = AgentTask(
            id=fix_id,
            title=f"Address review feedback on PR #{feedback.pr_number}",
            category=TaskCategory.BUILD,
            description=(
                f"Reviewers have requested changes on PR #{feedback.pr_number}.\n\n"
                f"**Review comments:**\n{comment_text}\n\n"
                f"Address each comment in `{charm_path}`. Commit with a message "
                f"referencing the PR (e.g. 'Address review feedback on #{feedback.pr_number}')."
            ),
        )

        tasks: list[AgentTask] = [fix_task]

        # Add push-confirm after the fix.
        tasks.append(self._build_push_confirm_task(branch_name, fix_id))

        self._work_queue.add_tasks(tasks)

        self._ensure_store()
        if self._store:
            self._store.record_event(
                "pr_fix_tasks_created",
                {
                    "pr_number": feedback.pr_number,
                    "comment_count": len(feedback.comments),
                    "task_count": len(tasks),
                },
            )

        return tasks

    def _create_feature_branch(self, description: str) -> str | None:
        """Create a feature branch if a GitHub remote is detected.

        Returns the branch name on success, or ``None`` if branching is
        not applicable (no GitHub remote or no charm path).
        """
        if not self.state.github_repo or not self.state.charm_path:
            return None
        branch = create_branch(str(self.state.charm_path), description)
        if branch:
            self._ensure_store()
            if self._store:
                self._store.record_event(
                    "branch_created",
                    {"branch": branch, "repo": self.state.github_repo or ""},
                )
        return branch

    def _build_push_confirm_task(
        self,
        branch_name: str,
        last_task_id: str,
    ) -> AgentTask:
        """Build a CONFIRM task asking whether to push a feature branch."""
        return AgentTask(
            id=f"{PUSH_CONFIRM_PREFIX}{branch_name}",
            title=f"Push branch {branch_name}?",
            category=TaskCategory.CONFIRM,
            description=(
                f"All work on branch **{branch_name}** is complete and tests have passed.\n\n"
                f"Approve to push the branch to **origin** (for PR creation).\n"
                f"Skip to leave the branch local for manual review."
            ),
            dependencies=[last_task_id],
        )

    def handle_push_confirmation(self, confirm_task_id: str, *, approved: bool) -> str:
        """Handle an approved or skipped push-confirm task.

        Returns a status message for the user.
        """
        branch_name = confirm_task_id.removeprefix(PUSH_CONFIRM_PREFIX)
        charm_path = str(self.state.charm_path) if self.state.charm_path else "."

        if not approved:
            return f"Branch **{branch_name}** left local for manual review."

        success, output = push_branch(charm_path, branch_name)
        self._ensure_store()
        if self._store:
            self._store.record_event(
                "branch_pushed" if success else "branch_push_failed",
                {"branch": branch_name, "output": output[:500]},
            )

        if success:
            return (
                f"Pushed **{branch_name}** to origin.\n\n"
                f"Reply **pr** to open a pull request, **draft** for a draft PR, "
                f"or **skip** to skip."
            )
        return f"Push failed:\n```\n{output}\n```"

    def handle_pr_creation(
        self,
        branch_name: str,
        *,
        draft: bool = False,
    ) -> str:
        """Create a pull request for *branch_name*.

        Gathers task context from the work queue to build the PR title
        and body.  Returns a status message for the user.
        """
        charm_path = str(self.state.charm_path) if self.state.charm_path else "."
        repo = self.state.github_repo or ""

        # Find work tasks associated with this branch (triage or improvement).
        # Convention: branch name encodes issue number or charm name.
        all_tasks = self._work_queue.all_tasks()
        work_tasks = [
            t
            for t in all_tasks
            if t.category.value not in ("confirm",) and t.id.startswith("triage-")
        ]
        # Fall back to all non-confirm done tasks if no triage tasks found.
        if not work_tasks:
            work_tasks = [t for t in all_tasks if t.category.value != "confirm" and t.result]

        # Extract issue number from branch name if present.
        issue_number: int | None = None
        import re

        m = re.search(r"issue-(\d+)", branch_name)
        if m:
            issue_number = int(m.group(1))

        # Build PR title.
        if issue_number:
            # Find the issue title from the triage confirm task.
            confirm_task = self._work_queue.get_task(f"triage-issue-{issue_number}")
            issue_title = ""
            if confirm_task:
                issue_title = confirm_task.title.removeprefix(f"Work on #{issue_number}: ")
            pr_title = (
                f"Fix #{issue_number}: {issue_title}" if issue_title else f"Fix #{issue_number}"
            )
        else:
            pr_title = branch_name.removeprefix("cantrip/").replace("-", " ").capitalize()

        pr_body = build_pr_body(
            work_tasks,
            issue_number=issue_number,
            repo=repo,
        )

        success, url_or_error = create_pull_request(
            charm_path,
            pr_title,
            pr_body,
            draft=draft,
        )

        self._ensure_store()
        if self._store:
            self._store.record_event(
                "pr_created" if success else "pr_creation_failed",
                {
                    "branch": branch_name,
                    "draft": draft,
                    "result": url_or_error[:500],
                },
            )

        if success:
            pr_type = "Draft PR" if draft else "PR"
            return f"{pr_type} created: {url_or_error}"
        return f"PR creation failed:\n```\n{url_or_error}\n```"

    # -- Repository bootstrap (Phase 42.5) ------------------------------------

    def should_offer_bootstrap(self) -> bool:
        """Return ``True`` if repo bootstrap should be offered to the user.

        Bootstrap is offered when a charm has been built (or is being
        improved) but no GitHub remote is configured and ``gh`` is
        available.
        """
        if self.state.github_repo:
            return False
        charm_path = str(self.state.charm_path) if self.state.charm_path else None
        return can_bootstrap(charm_path)

    def handle_repo_bootstrap(
        self,
        name: str,
        *,
        private: bool = True,
        description: str = "",
        org: str = "",
    ) -> str:
        """Create a GitHub repository and push the initial commit.

        Updates ``state.github_repo`` on success so that subsequent
        features (issue triage, branch workflow) activate automatically.
        Returns a status message for the user.
        """
        charm_path = str(self.state.charm_path) if self.state.charm_path else "."

        success, result = bootstrap_github_repo(
            charm_path,
            name,
            private=private,
            description=description,
            org=org,
        )

        self._ensure_store()
        if self._store:
            self._store.record_event(
                "repo_bootstrapped" if success else "repo_bootstrap_failed",
                {
                    "name": name,
                    "private": private,
                    "org": org,
                    "result": result[:500],
                },
            )

        if success:
            # Re-detect the remote now that it exists.
            self.state.github_repo = detect_github_repo(self.state.charm_path)
            visibility = "private" if private else "public"
            return (
                f"Repository created ({visibility}): {result}\n\n"
                f"Remote set to **{self.state.github_repo or name}**."
            )
        return f"Repository creation failed:\n```\n{result}\n```"

    def handle_triage_confirmation(
        self,
        confirm_task_id: str,
    ) -> list[AgentTask]:
        """Process an approved triage-confirm task and generate work tasks.

        Extracts the issue number from the task ID, locates the original
        CONFIRM task description, and builds research → build → test tasks.
        When a GitHub remote is detected, creates a feature branch and
        appends a push-confirmation task.
        """
        confirm_task = self._work_queue.get_task(confirm_task_id)
        if confirm_task is None:
            log.error("Triage confirm task %s not found", confirm_task_id)
            return []

        # Extract issue number from the task ID.
        try:
            issue_number = int(confirm_task_id.removeprefix(TRIAGE_CONFIRM_PREFIX))
        except ValueError:
            log.error("Cannot parse issue number from task ID %s", confirm_task_id)
            return []

        # Build a minimal GitHubIssue from the confirm task description.
        from cantrip.agent.github_issues import GitHubIssue

        issue = GitHubIssue(
            number=issue_number,
            title=confirm_task.title.removeprefix(f"Work on #{issue_number}: "),
            body=confirm_task.description,
        )

        # Create a feature branch for the work.
        branch = self._create_feature_branch(f"issue-{issue_number}-{issue.title}")

        work_tasks = build_issue_work_tasks(
            issue,
            self.state.github_repo or "",
            confirm_task_id,
            charm_path=str(self.state.charm_path) if self.state.charm_path else ".",
        )

        # Append push-confirm task if a branch was created.
        if branch and work_tasks:
            last_task_id = work_tasks[-1].id
            work_tasks.append(self._build_push_confirm_task(branch, last_task_id))

        self._work_queue.add_tasks(work_tasks)

        self._ensure_store()
        if self._store:
            self._store.record_event(
                "triage_issue_approved",
                {
                    "repo": self.state.github_repo,
                    "issue_number": issue_number,
                    "task_count": len(work_tasks),
                    "branch": branch or "",
                },
            )

        return work_tasks

    # -- Executor integration -------------------------------------------------

    @property
    def executor_running(self) -> bool:
        """Whether the background executor is currently running."""
        return self._executor is not None and self._executor.running

    def start_executor(
        self,
        max_concurrency: int | None = None,
    ) -> None:
        """Create and start the background executor.

        Every task mutation is published to the shared ``event_bus`` so
        that both UIs receive updates.  *max_concurrency* controls how
        many subagent tasks run in parallel (default 3).
        """
        if self._executor is not None and self._executor.running:
            return
        self._ensure_store()

        def _notify_bus(task: AgentTask) -> None:
            self._event_bus.publish(ui_events.task_updated_from_task(task))

        self._work_queue._on_task_changed = _notify_bus
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
            self._store.save_tasks(self._work_queue.all_tasks())

    def load_state(self) -> bool:
        """Load agent state from the session store.

        Returns True if state was loaded, False if no state exists
        or the database is corrupt.
        """
        self._ensure_store()
        if not self._store:
            return False

        try:
            loaded = self._store.load_session()
        except (sqlite3.Error, KeyError, ValueError, TypeError):
            log.warning("Failed to load session — .cantrip file may be corrupt")
            self._store = None
            self._store_initialised = False
            return False
        if loaded is None:
            return False

        self.state.charm_name = loaded.charm_name
        self.state.charm_path = loaded.charm_path
        self.state.charm_type = loaded.charm_type
        self.state.framework = loaded.framework
        self.state.dev_model = loaded.dev_model
        self.state.cos_model = loaded.cos_model
        self.state.decisions = loaded.decisions

        # Restore conversation history so the LLM retains context.
        try:
            raw_messages = self._store.load_messages()
            for msg in raw_messages:
                role_str = msg.get("role", "")
                try:
                    role = Role(role_str)
                except ValueError:
                    continue
                content = msg.get("content", "")
                if not content:
                    continue
                self.state.messages.append(Message(role=role, content=str(content)))
            if self.state.messages:
                log.info(
                    "Restored %d conversation messages from prior session",
                    len(self.state.messages),
                )
        except (sqlite3.Error, KeyError, ValueError):
            log.warning("Failed to load conversation history — continuing without it")

        # Restore persisted tasks into the work queue, resetting any that
        # were mid-flight when the previous session ended.
        tasks = self._store.load_tasks()
        for task in tasks:
            if task.status == TaskStatus.ACTIVE:
                log.warning(
                    "Resetting stale active task %s (%s) to pending",
                    task.id,
                    task.title,
                )
                task.status = TaskStatus.PENDING
        if tasks:
            self._work_queue.add_tasks(tasks)

        if self._store:
            self._store.record_event(
                "session_resume",
                {
                    "charm_name": self.state.charm_name,
                    "task_count": len(tasks),
                },
            )

        return True

    def build_resume_summary(self) -> str | None:
        """Build a structured summary of prior session work.

        Returns a Markdown-formatted string suitable for injection as a
        USER message, or ``None`` if the state contains nothing useful
        to summarise.
        """
        state = self.state
        has_content = state.charm_name or state.decisions or self._work_queue.all_tasks()
        if not has_content:
            return None

        parts: list[str] = ["[Session resumed] Previous session context:\n"]

        if state.charm_name:
            charm_type = state.charm_type or "unknown"
            charm_path = state.charm_path or "unknown"
            parts.append(f"**Charm:** {state.charm_name} ({charm_type}) at {charm_path}")
        if state.framework:
            parts.append(f"**Framework:** {state.framework}")
        if state.dev_model or state.cos_model:
            parts.append(
                f"**Models:** dev={state.dev_model or 'none'}, cos={state.cos_model or 'none'}"
            )

        if state.decisions:
            parts.append("\n**Decisions:**")
            for d in state.decisions:
                parts.append(f"- {d.type}: {d.choice}")

        tasks = self._work_queue.all_tasks()
        if tasks:
            counts: dict[str, int] = {}
            for t in tasks:
                counts[t.status.value] = counts.get(t.status.value, 0) + 1
            done = counts.get("done", 0)
            failed = counts.get("failed", 0)
            pending = counts.get("pending", 0) + counts.get("active", 0) + counts.get("blocked", 0)
            parts.append(f"\n**Task progress:** {done} done, {failed} failed, {pending} pending")
            completed = [t.title for t in tasks if t.status == TaskStatus.DONE]
            if completed:
                parts.append("**Recent completed tasks:**")
                for title in completed[-5:]:
                    parts.append(f"- {title}")

        summary = "\n".join(parts)

        # Inject into conversation history so the LLM sees prior context.
        # Use SYSTEM role to avoid breaking alternating user/assistant patterns.
        self.state.messages.append(Message(role=Role.SYSTEM, content=summary))
        return summary

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


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _infer_gaps_from_audit(text: str) -> dict[str, bool]:
    """Derive a gaps dictionary from free-form audit Markdown.

    The ``CharmAuditTool`` emits structured ``data["gaps"]`` on its tool
    result, but subagent task results are plain text summaries.  This
    function heuristically scans the text for keywords to reconstruct
    the boolean gaps map that ``plan_improvement_fixes`` expects.
    """
    t = text.lower()
    return {
        "cos_tracing": "tracing" in t and ("missing" in t or "no tracing" in t),
        "cos_metrics": "metrics" in t and ("missing" in t or "no metrics" in t),
        "cos_logging": "logging" in t and ("missing" in t or "no logging" in t),
        "cos_dashboards": "dashboard" in t and ("missing" in t or "no dashboard" in t),
        "ops_tracing": "ops-tracing" in t and ("missing" in t or "not installed" in t),
        "unit_tests": "unit test" in t and ("missing" in t or "no unit" in t),
        "integration_tests": (
            "integration test" in t and ("missing" in t or "no integration" in t)
        ),
        "deprecated_apis": (
            "deprecated" in t or "storedstate" in t or "harness" in t or "fetch-libs" in t
        ),
        "readme": "readme" in t and ("missing" in t or "no readme" in t),
        "licence": (("licence" in t or "license" in t) and ("missing" in t or "no licen" in t)),
        "listing_metadata": "listing" in t and ("missing" in t or "incomplete" in t),
        "type_annotations": "type annotation" in t and ("missing" in t or "no type" in t),
        "modern_patterns": "modern pattern" in t and ("missing" in t or "no modern" in t),
    }
