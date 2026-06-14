"""Turn-execution engine for the agent.

``TurnEngineMixin`` is the heart of a user turn: the provider
complete/stream retry helpers, the tool-failure streak tracking and
runaway-cap escalation, executor pause/resume around a turn, the
parliament entry point, and the streaming and non-streaming conversation
loops themselves (send a message, run tool calls, compact, repeat until
the model answers without tools or the round cap is hit).  Mixed into
:class:`~cantrip.agent.core.CantripAgent`; every collaborator —
``_run_architect_editor_turn``, the tool map, the hook runner, the
context manager, the work queue — is reached through ``self``.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from cantrip.agent import core
from cantrip.agent.emotions import ParliamentResult, run_parliament
from cantrip.agent.policy.retry import RetryEvent, complete_with_retry, stream_with_retry
from cantrip.agent.queue import TaskStatus
from cantrip.agent.tools import ToolResult, resolve_subcommand
from cantrip.hooks import HookEvent, final_arguments, first_veto
from cantrip.llm import base as llm
from cantrip.llm.base import Chunk, LLMProvider, Message, Response, Role
from cantrip.ui import events as ui_events
from cantrip.ui import flavour

log = logging.getLogger("cantrip.agent.core")

# Maximum tool-call rounds before we force the model to respond with text.
MAX_TOOL_ROUNDS = 20


class TurnEngineMixin:
    """Retry helpers, failure-cap escalation, and the conversation loops."""

    async def _complete_with_retry(
        self,
        messages: list[Message],
        tools: list[llm.Tool] | None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        provider: LLMProvider | None = None,
    ) -> Response:
        """Call ``provider.complete()`` with retry and linear backoff for transient errors.

        ``provider`` overrides the default :attr:`self.provider`; used
        by the Phase 71.2 architect/editor split to route the architect
        pass through the main provider and the editor pass through a
        cheaper one.

        ``temperature`` defaults to the active provider's
        :attr:`LLMProvider.conversation_temperature` — frontier APIs
        keep that at 0.7, local quantised snaps clamp it down to
        steady tool-call formatting.

        Phase 102.2: when the chosen provider's
        ``conversation_temperature`` is below 0.7 (i.e. an inference
        snap or any other slow local backend), route through
        :func:`stream_with_retry` instead of
        :func:`complete_with_retry`.  Streaming keeps a TCP heartbeat
        alive so a long single-turn generation doesn't trip the
        backend's keep-alive, and partial assistant text persists to
        the session store as it arrives so a mid-stream disconnect
        leaves a recoverable transcript instead of an empty turn.

        Phase 102.4: a transient retry (rate limit, mid-stream drop)
        publishes a ``[provider reconnect]`` system message on the
        chat surface so the operator sees what's happening rather
        than staring at a frozen UI.
        """
        chosen_provider = provider or self.provider
        if temperature is None:
            temperature = chosen_provider.conversation_temperature

        if chosen_provider.conversation_temperature < 0.7:
            return await self._stream_with_retry_and_writeback(
                chosen_provider,
                messages,
                tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        return await complete_with_retry(
            chosen_provider,
            messages,
            tools,
            temperature=temperature,
            max_tokens=max_tokens,
            on_retry=self._publish_provider_retry,
        )

    async def _stream_with_retry_and_writeback(
        self,
        chosen_provider: LLMProvider,
        messages: list[Message],
        tools: list[llm.Tool] | None,
        *,
        temperature: float,
        max_tokens: int | None,
    ) -> Response:
        """Slow-path streaming wrapper with partial-message persistence.

        Pre-records an empty assistant row, runs
        :func:`stream_with_retry` with a closure that updates that row
        as chunks arrive, then deletes the placeholder on success — so
        the conversation loop's existing canonical-record step writes
        the final row unchanged.  On exception (retries exhausted) the
        partial row is left in place so resume can recover the
        in-flight transcript instead of regenerating from scratch.

        The placeholder is metadata-flagged ``partial: True`` so a
        future inspector tool (or migration) can identify rows left
        behind by an aborted slow-path turn.
        """
        partial_id: int | None = None
        if self._store is not None:
            partial_msg = Message(
                role=Role.ASSISTANT,
                content="",
                metadata={"partial": True},
            )
            partial_id = self._record_message(partial_msg)

        on_partial: Callable[[str], None] | None = None
        if partial_id is not None and self._store is not None:
            store = self._store
            row_id = partial_id

            def _writeback(text: str) -> None:
                try:
                    store.update_message_content(row_id, text)
                except sqlite3.Error:
                    log.debug("partial writeback failed", exc_info=True)

            on_partial = _writeback

        response = await stream_with_retry(
            chosen_provider,
            messages,
            tools,
            temperature=temperature,
            max_tokens=max_tokens,
            on_retry=self._publish_provider_retry,
            on_partial=on_partial,
        )

        # Successful generation — clean up the placeholder so the
        # conversation loop's canonical ``_record_message`` writes the
        # final row without leaving a duplicate behind.  An exception
        # above skips this, leaving the partial content on disk for
        # resume to find.
        if partial_id is not None and self._store is not None:
            try:
                self._store.delete_messages_from(partial_id)
            except sqlite3.Error:
                log.debug("partial-row cleanup failed", exc_info=True)
        return response

    def _publish_provider_retry(self, event: RetryEvent) -> None:
        """Publish a ``[provider reconnect]`` chat row for a retry event.

        Phase 102.4: a slow local snap dropping mid-stream used to
        surface only as a stack trace.  This handler converts the
        retry-layer signal into an inline system message so the user
        sees the reconnect attempt and the wait time before the loop
        resumes.
        """
        kind = (
            "rate-limited"
            if isinstance(event.exception, llm.ProviderRateLimitError)
            else (
                "overloaded"
                if isinstance(event.exception, llm.ProviderOverloadedError)
                else "disconnected"
            )
        )
        delay_str = f"{event.delay:.0f}s" if event.delay >= 1 else f"{event.delay:.1f}s"
        message = (
            f"[provider reconnect] {event.provider_name} {kind} "
            f"(attempt {event.attempt}/{event.max_retries}); "
            f"retrying in {delay_str}…"
        )
        self._event_bus.publish(ui_events.chat_message(role="system", content=message))
        self._event_bus.publish(
            ui_events.status_bar_changed(task_label=f"reconnecting ({delay_str})")
        )

    # ─── Phase 107: Tool-call failure cap ────────────────────────────

    def _track_tool_failure_streak(
        self, tool_name: str, arguments: dict[str, Any], success: bool
    ) -> None:
        return self._usage.track_tool_failure_streak(tool_name, arguments, success)

    def _maybe_warn_before_failure_cap(self) -> None:
        return self._usage.maybe_warn_before_failure_cap()

    def _consecutive_failure_cap_exceeded(self) -> str | None:
        return self._usage.consecutive_failure_cap_exceeded()

    def _mark_active_task_blocked(self, reason: str) -> None:
        """Flip the currently-active work-queue task to ``BLOCKED``.

        Used by Phase 107 to escalate a runaway tool-failure streak so
        Phase 106's exit/escalation paths fire downstream.  No-op when
        no task is active — that case is logged but doesn't unwind the
        loop because the caller is already breaking out of it.
        """
        for task in self._work_queue.all_tasks():
            if task.status == TaskStatus.ACTIVE:
                self._work_queue.set_blocked(task.id, reason=reason)
                log.info("Marked task %r BLOCKED (Phase 107): %s", task.id, reason)
                return
        log.info("Phase 107 cap fired with no active task (reason: %s)", reason)

    def _pause_executor(self) -> None:
        """Pause the background executor while handling a user message."""
        self._executor_ctl.pause()

    def _resume_executor(self) -> None:
        """Resume the background executor after handling a user message."""
        self._executor_ctl.resume()

    async def run_parliament(self, enabled: list[str]) -> ParliamentResult:
        """Convene the inner parliament over the current charm state.

        Experimental feature: each enabled emotion (joy, fear, anger,
        disgust, sadness) reviews the charm through its own lens and
        emits structured suggestions. The emotions run in parallel on
        the light model and have no tools — they react only to the
        context assembled from ``AgentState``.
        """
        provider = self._light_provider or self.provider
        return await run_parliament(
            enabled=enabled,
            provider=provider,
            charm_name=self.state.charm_name,
            charm_type=self.state.charm_type,
            framework=self.state.framework,
            charm_path=self.state.charm_path,
            decisions=[decision.to_dict() for decision in self.state.decisions],
        )

    async def process_message(self, user_message: str) -> str:
        """Process a user message and return the response.

        This handles the full conversation loop including tool calls.
        The loop continues until the model responds without tool calls
        or the maximum number of rounds is reached.

        The background executor is paused while the conversation loop is
        active so that user steering takes priority over autonomous work.
        """
        # Phase 110.1: a new user turn always gets a fresh chance to
        # re-plan, even after a previous turn produced a packed charm.
        self.state.pack_succeeded = False
        self._pause_executor()
        try:
            response = await self._process_message_inner(user_message)
        finally:
            self._resume_executor()
        self._maybe_schedule_correction_writer(user_message)
        return response

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

        # Phase 70.2: oracle's per-turn budget resets here so each
        # user message gets a fresh allowance.  Session totals and
        # cost cap survive across turns intentionally.
        self.state.oracle_calls_this_turn = 0

        # Phase 71.3: pre-turn dirty-commit so the agent's edits land
        # on a clean base.  Runs before the snapshot is taken so the
        # snapshot itself captures the post-pre-cantrip-commit state
        # (working tree clean, history advanced).  No-op when
        # ``git_auto_commit`` is off, when we're not in a git repo,
        # or when the working tree is already clean.
        self._maybe_pre_turn_commit_dirty()

        # Phase 104: in short-session mode each turn is near-fresh —
        # fold the prior conversation into the ledger and clear the
        # working set before the new user message lands.
        self._collapse_messages_for_short_session()

        user_msg = Message(role=Role.USER, content=user_message)
        user_msg = self._context_manager.virtualise_message(user_msg)
        self._snapshot_before_user_turn(user_msg)
        self.state.messages.append(user_msg)
        self._record_message(user_msg)
        # Track where this turn starts so the post-turn auto-commit
        # only stages files the agent actually touched (rather than
        # walking the whole history).
        turn_start_idx = len(self.state.messages) - 1

        messages = self._build_llm_messages(include_budget=True)
        llm_tools = self._tools_for_llm() if self._tools else None

        # Phase 71.2: when architect_mode is on, every LLM call routes
        # through the dual-pass orchestrator.  Otherwise the existing
        # single-call path runs unchanged.
        if self.state.architect_mode:
            self.state.architect_consecutive_failures = 0
            response = await self._run_architect_editor_turn(messages, llm_tools)
        else:
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

            # Bundled-tool rewrite: ``juju(subcommand="deploy", ...)``
            # \u2192 ``juju_deploy(...)`` so permissions, audit, hooks and
            # plan mode all see the canonical leaf name they were
            # written against.  Mutation is in-place; the transcript
            # still replays cleanly because ``resolve_subcommand`` is
            # a no-op on a leaf-name call (the leaf lives in
            # ``tool_map`` thanks to ``expand_leaves``).
            for tc in response.tool_calls:
                tc.name, tc.arguments = resolve_subcommand(self._tool_map, tc.name, tc.arguments)

            # Execute each tool and build TOOL result messages.
            tool_results = []
            for tc in response.tool_calls:
                self._publish_activity(f"\u27f3 running: {tc.name}")
                pre_results = await self._hook_runner.fire(
                    HookEvent.PRE_TOOL_CALL,
                    {"tool": tc.name, "arguments": tc.arguments, "source": "main"},
                )
                veto = first_veto(pre_results)
                # Hook-rewritten arguments (Phase 46.4b) flow into both
                # the tool invocation and the post_tool_call payload so
                # audit logs reflect what actually ran.
                effective_arguments = final_arguments(pre_results) or tc.arguments
                # Phase 68.4: plan mode refuses non-read-only tools.
                # We gate after the hook so a hook-rewritten argument
                # stays visible, and before execution so the tool body
                # never runs in read-only mode.  Subagents already hit
                # the full Phase 68.2 permission gate via their own
                # ``PermissionRuleset``; the main agent only consults
                # the plan-mode flag for scope reasons.
                plan_block = core._plan_mode_refusal(self.state, tc.name)
                tool_start = time.monotonic()
                # Phase 82: emit the "running now" block before
                # dispatch so slow tools (charmcraft_pack, juju_wait,
                # web_fetch) produce visible feedback immediately.  The
                # matching TOOL_INVOKED below carries the same
                # tool_call_id so the renderer updates the same block
                # in place rather than appending a fresh line.
                self._publish_tool_invoked_pending(
                    tc.name,
                    effective_arguments,
                    source="main",
                    tool_call_id=tc.id,
                )
                if veto is not None:
                    # A pre-hook blocked the call \u2014 synthesise an error
                    # ToolResult so the LLM sees the veto on its next turn
                    # and can react (apologise, retry with different args,
                    # ask the user).  ``post_tool_call`` still fires with
                    # ``success: false`` and a ``vetoed_by`` field so
                    # observability hooks see the full decision record.
                    log.warning(
                        "Tool call %r vetoed by %s",
                        tc.name,
                        veto.veto_reason,
                    )
                    result = ToolResult(
                        success=False,
                        output="",
                        error=f"Blocked by {veto.veto_reason}",
                    )
                elif plan_block is not None:
                    log.info("Tool call %r refused by plan mode", tc.name)
                    result = plan_block
                else:
                    result = await self._execute_tool(tc.name, effective_arguments)
                tool_elapsed_ms = int((time.monotonic() - tool_start) * 1000)
                post_payload: dict[str, Any] = {
                    "tool": tc.name,
                    "arguments": effective_arguments,
                    "success": result.success,
                    "error": result.error,
                    "source": "main",
                }
                if veto is not None:
                    post_payload["vetoed_by"] = veto.name
                await self._hook_runner.fire(HookEvent.POST_TOOL_CALL, post_payload)
                self._publish_activity(f"\u27f3 {flavour.pick_activity_label()}...")
                self._capture_test_results(tc.name, result)
                self._publish_tool_invoked(
                    tc.name,
                    effective_arguments,
                    result,
                    source="main",
                    duration_ms=tool_elapsed_ms,
                    tool_call_id=tc.id,
                )
                self._track_tool_failure_streak(tc.name, effective_arguments, result.success)
                content = result.output if result.success else (result.error or "Unknown error")
                # Wrap tool output in delimiters to reduce prompt injection risk.
                content = f"<tool_result name={tc.name!r}>\n{content}\n</tool_result>"
                tool_results.append(
                    llm.ToolResult(
                        tool_call_id=tc.id,
                        content=content,
                        is_error=not result.success,
                        images=list(result.images),
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

            # Phase 104: in short-session mode, fold the oldest in-turn
            # tool round into the ledger once the turn has built up more
            # than a couple — keeps the live working set tiny.
            self._maybe_fold_oldest_round_into_ledger(turn_start_idx)

            # Phase 107.3: one round before the cap, nudge the model to
            # change approach instead of retrying into a BLOCKED state.
            self._maybe_warn_before_failure_cap()
            # Phase 107: bail when the cap is hit.  Marks the active
            # work-queue task BLOCKED so Phase 106's loop-exit logic
            # fires; ``process_message`` returns its current response
            # text (which we accumulated through earlier rounds even
            # if the most recent rounds all failed).
            cap_reason = self._consecutive_failure_cap_exceeded()
            if cap_reason is not None:
                log.warning("Phase 107 cap fired: %s", cap_reason)
                self._mark_active_task_blocked(cap_reason)
                break

            # Compact if the context window is getting full.
            if self._context_manager.should_compact(self.state.messages):
                log.info("Compacting conversation context")
                tokens_before = self._context_manager.estimate_tokens(self.state.messages)
                pre_compact_results = await self._hook_runner.fire(
                    HookEvent.PRE_COMPACT,
                    {"tokens_before": tokens_before, "source": "main"},
                )
                compact_veto = first_veto(pre_compact_results)
                if compact_veto is not None:
                    # A ``pre_compact`` veto preserves the context as-is —
                    # users pin critical messages with this hook so they
                    # survive the summary rewrite.  No ``post_compact``
                    # fires because compaction didn't run.
                    log.info(
                        "Compaction blocked by %s; context preserved (%d tokens)",
                        compact_veto.veto_reason,
                        tokens_before,
                    )
                else:
                    await self._run_compaction(tokens_before=tokens_before, source="main")
                    await self._hook_runner.fire(
                        HookEvent.POST_COMPACT,
                        {
                            "tokens_before": tokens_before,
                            "tokens_after": self._context_manager.estimate_tokens(
                                self.state.messages
                            ),
                            "source": "main",
                        },
                    )

            # Phase 71.2: track editor-pass failures across rounds so
            # the dual-pass orchestrator can escalate to the architect
            # provider when the cheap editor keeps producing
            # unapplyable patches.  Reset on a turn that succeeded.
            if self.state.architect_mode:
                if self._all_tool_calls_failed(tool_results):
                    self.state.architect_consecutive_failures += 1
                else:
                    self.state.architect_consecutive_failures = 0

            # Call the LLM again with the updated history.
            messages = self._build_llm_messages(include_budget=True)
            if self.state.architect_mode:
                response = await self._run_architect_editor_turn(messages, llm_tools)
            else:
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
        # Phase 68.4: harvest a "Proposed changes" section whenever the
        # agent produces one while plan mode is on, so /build can splice
        # it back into context on the switch-over turn.
        if self.state.plan_mode:
            captured = core._extract_proposed_changes(response.content or "")
            if captured:
                self.state.plan_summary = captured

        # Phase 71.3: agent commit lands at the very end of the turn,
        # after the final assistant message is recorded so the body's
        # "Touched:" list and the SHA stamped on ``state`` reflect the
        # complete turn.  No-op when no file-mutating tools fired,
        # when ``git_auto_commit`` is off, or when not in a git repo.
        await self._maybe_post_turn_commit_agent_edits(user_message, turn_start_idx)
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
        # Phase 110.1: same per-turn reset as the non-streaming path.
        self.state.pack_succeeded = False
        self._pause_executor()
        try:
            async for chunk in self._run_conversation_loop_streaming(user_message):
                yield chunk
        finally:
            self._resume_executor()
        self._maybe_schedule_correction_writer(user_message)

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

        # Phase 70.2: oracle's per-turn budget resets here so each
        # user message gets a fresh allowance.  Session totals and
        # cost cap survive across turns intentionally.
        self.state.oracle_calls_this_turn = 0

        # Phase 71.3: pre-turn dirty-commit (see non-streaming loop
        # for rationale).  Same hook drives both paths.
        self._maybe_pre_turn_commit_dirty()

        # Phase 104: short-session per-turn collapse (see non-streaming loop).
        self._collapse_messages_for_short_session()

        user_msg = Message(role=Role.USER, content=user_message)
        user_msg = self._context_manager.virtualise_message(user_msg)
        self._snapshot_before_user_turn(user_msg)
        self.state.messages.append(user_msg)
        self._record_message(user_msg)
        turn_start_idx = len(self.state.messages) - 1

        messages = self._build_llm_messages(include_budget=True)
        llm_tools = self._tools_for_llm() if self._tools else None

        # Phase 71.2: architect mode bypasses streaming and runs a
        # dual-pass turn instead.  We yield the editor's content as a
        # single chunk; the architect's proposal is captured in the
        # transcript via ``architect_pass``.  Streaming loses
        # token-by-token rendering inside an architect-mode session,
        # but the dual-pass overhead dominates that cosmetic cost.
        if self.state.architect_mode:
            self.state.architect_consecutive_failures = 0
            response = await self._run_architect_editor_turn(messages, llm_tools)
            if response.content:
                yield response.content
        else:
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

            # Bundled-tool rewrite \u2014 same as the non-stream path.
            for tc in response.tool_calls:
                tc.name, tc.arguments = resolve_subcommand(self._tool_map, tc.name, tc.arguments)

            # Execute each tool and build TOOL result messages.
            tool_results = []
            for tc in response.tool_calls:
                self._publish_activity(f"\u27f3 running: {tc.name}")
                pre_results = await self._hook_runner.fire(
                    HookEvent.PRE_TOOL_CALL,
                    {"tool": tc.name, "arguments": tc.arguments, "source": "main-stream"},
                )
                veto = first_veto(pre_results)
                effective_arguments = final_arguments(pre_results) or tc.arguments
                plan_block = core._plan_mode_refusal(self.state, tc.name)
                tool_start = time.monotonic()
                self._publish_tool_invoked_pending(
                    tc.name,
                    effective_arguments,
                    source="main-stream",
                    tool_call_id=tc.id,
                )
                if veto is not None:
                    log.warning(
                        "Tool call %r vetoed by %s",
                        tc.name,
                        veto.veto_reason,
                    )
                    result = ToolResult(
                        success=False,
                        output="",
                        error=f"Blocked by {veto.veto_reason}",
                    )
                elif plan_block is not None:
                    log.info("Tool call %r refused by plan mode (stream)", tc.name)
                    result = plan_block
                else:
                    result = await self._execute_tool(tc.name, effective_arguments)
                tool_elapsed_ms = int((time.monotonic() - tool_start) * 1000)
                post_payload: dict[str, Any] = {
                    "tool": tc.name,
                    "arguments": effective_arguments,
                    "success": result.success,
                    "error": result.error,
                    "source": "main-stream",
                }
                if veto is not None:
                    post_payload["vetoed_by"] = veto.name
                await self._hook_runner.fire(HookEvent.POST_TOOL_CALL, post_payload)
                self._publish_activity(f"\u27f3 {flavour.pick_activity_label()}...")
                self._capture_test_results(tc.name, result)
                self._publish_tool_invoked(
                    tc.name,
                    effective_arguments,
                    result,
                    source="main-stream",
                    duration_ms=tool_elapsed_ms,
                    tool_call_id=tc.id,
                )
                self._track_tool_failure_streak(tc.name, effective_arguments, result.success)
                content = result.output if result.success else (result.error or "Unknown error")
                content = f"<tool_result name={tc.name!r}>\n{content}\n</tool_result>"
                tool_results.append(
                    llm.ToolResult(
                        tool_call_id=tc.id,
                        content=content,
                        is_error=not result.success,
                        images=list(result.images),
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

            # Phase 104: short-session in-turn ledger fold (see non-streaming loop).
            self._maybe_fold_oldest_round_into_ledger(turn_start_idx)

            # Phase 107.3 / 107: pre-cap nudge then cap check, as in the
            # non-streaming loop.
            self._maybe_warn_before_failure_cap()
            cap_reason = self._consecutive_failure_cap_exceeded()
            if cap_reason is not None:
                log.warning("Phase 107 cap fired (stream): %s", cap_reason)
                self._mark_active_task_blocked(cap_reason)
                break

            # Compact if the context window is getting full.
            if self._context_manager.should_compact(self.state.messages):
                log.info("Compacting conversation context")
                tokens_before = self._context_manager.estimate_tokens(self.state.messages)
                pre_compact_results = await self._hook_runner.fire(
                    HookEvent.PRE_COMPACT,
                    {"tokens_before": tokens_before, "source": "main-stream"},
                )
                compact_veto = first_veto(pre_compact_results)
                if compact_veto is not None:
                    log.info(
                        "Compaction blocked by %s; context preserved (%d tokens)",
                        compact_veto.veto_reason,
                        tokens_before,
                    )
                else:
                    await self._run_compaction(tokens_before=tokens_before, source="main-stream")
                    await self._hook_runner.fire(
                        HookEvent.POST_COMPACT,
                        {
                            "tokens_before": tokens_before,
                            "tokens_after": self._context_manager.estimate_tokens(
                                self.state.messages
                            ),
                            "source": "main-stream",
                        },
                    )

            # Phase 71.2: same fall-through tracking as the
            # non-streaming loop — count editor passes whose tools
            # all failed so the next pass can escalate.
            if self.state.architect_mode:
                if self._all_tool_calls_failed(tool_results):
                    self.state.architect_consecutive_failures += 1
                else:
                    self.state.architect_consecutive_failures = 0

            # Separate this round's text from the previous round's, since
            # each round is an independent LLM response with no leading
            # whitespace — without this, sentences run together visually.
            if response.content and not response.content[-1].isspace():
                yield "\n\n"

            # Stream the next LLM call.
            messages = self._build_llm_messages(include_budget=True)
            if self.state.architect_mode:
                response = await self._run_architect_editor_turn(messages, llm_tools)
                if response.content:
                    yield response.content
            else:
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

        # Phase 71.3: agent commit at end of streaming turn (mirrors
        # the non-streaming loop).
        await self._maybe_post_turn_commit_agent_edits(user_message, turn_start_idx)
