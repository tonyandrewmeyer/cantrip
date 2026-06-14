"""Model-request assembly and tool-call dispatch for the agent.

``ToolingMixin`` builds the model's view of a turn — the curated tool
list, the system prompt, the dynamic-context message, the repo map and
code-intel exposure, and the phase-aware tool curation — and then
dispatches and observes the model's tool calls (execution, edit-miss
tracking, activity / tool-invoked event publishing, test-result
capture).  Mixed into :class:`~cantrip.agent.core.CantripAgent`; the
caches, services, and event bus are reached through ``self``.

``_tool_failure_detail`` and ``_TEST_RESULT_TOOLS`` stay on ``core`` and
are reached through the ``core`` module object at call time.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from cantrip.agent import core
from cantrip.agent.prompts import build_dynamic_context, build_system_prompt
from cantrip.agent.queue import TaskCategory, TaskStatus, WorkflowPhase
from cantrip.agent.state import TestResults
from cantrip.agent.tools import Tool, ToolResult
from cantrip.codeintel import CodeIntel
from cantrip.llm import base as llm
from cantrip.llm.base import Message, Role
from cantrip.repomap import RepoMap
from cantrip.ui import events as ui_events

log = logging.getLogger("cantrip.agent.core")


class ToolingMixin:
    """Tool/prompt/context assembly and tool-call dispatch + observability."""

    def _invalidate_tools_cache(self) -> None:
        return self._tool_builder.invalidate_tools_cache()

    def _build_tools(self) -> list[Tool]:
        return self._tool_builder.build_tools()

    def _build_system_prompt(self) -> str:
        """Build the current system prompt.

        Uses a compact prompt for providers with limited context windows
        to avoid exceeding the model's capacity.  When plan mode is
        active (Phase 68.4) an appendix explains the read-only stance
        and asks for a *Proposed changes* summary so ``/build`` can
        pick up where the plan left off.

        Per-turn-volatile context (the skills index and repo map) is
        *not* built here — it lives in :meth:`_build_dynamic_context_message`
        and rides along as a trailing ephemeral message so this prompt
        stays byte-stable across turns and the provider's prompt cache
        keeps hitting.
        """
        compact = self.provider.max_tools is not None
        memory_index = self._memory_manager.render_prompt_index() or None
        prompt = build_system_prompt(
            charm_name=self.state.charm_name,
            charm_path=str(self.state.charm_path) if self.state.charm_path else None,
            charm_type=self.state.charm_type,
            framework=self.state.framework,
            dev_model=self.state.dev_model,
            cos_model=self.state.cos_model,
            recent_decisions=[d.to_dict() for d in self.state.decisions],
            memory_index=memory_index,
            environment_ready=self.state.environment_ready,
            watcher_enabled=self.state.watcher_enabled and self.state.watcher_reacting,
            substrate=self._get_substrate_cached(),
            compact=compact,
        )
        if self.state.plan_mode:
            prompt = f"{prompt}\n\n{core._PLAN_MODE_GUIDANCE}"
        if self.state.was_resumed:
            prompt = f"{prompt}\n\n{core._RESUMED_MUST_READ_GUIDANCE}"
        return prompt

    def _build_dynamic_context_message(self) -> Message | None:
        """Render the per-turn-volatile context as a trailing ephemeral message.

        The skills index (filtered by the files in play this turn) and the
        repo map (scaled by live context pressure) are recomputed every
        turn, so they cannot live in the cached system prompt without
        invalidating the whole prefix on each call.  They ride along as a
        ``USER`` message flagged :attr:`Message.ephemeral` so the provider
        keeps its cache breakpoint on the stable history before it and only
        this small tail is re-sent at full input price.

        Returns ``None`` when there is nothing to inject (no skills, no
        repo map) so :meth:`_build_llm_messages` can skip it entirely.
        """
        compact = self.provider.max_tools is not None
        current_files = self._current_turn_files()
        skills_index = self._skills_index.format_for_prompt(
            current_files=current_files,
            charm_path=self.state.charm_path,
        )
        self._record_skill_filtering(current_files)
        repo_map = None if compact else self._render_repo_map()
        body = build_dynamic_context(skills_index=skills_index, repo_map=repo_map)
        if not body:
            return None
        framed = (
            "<system_note>\n"
            "Current working context (skills you can load, repo map) — reference "
            "material for your own planning, not a user message.  Do not echo it.\n\n"
            f"{body}\n"
            "</system_note>"
        )
        return Message(role=Role.USER, content=framed, ephemeral=True)

    def _get_substrate_cached(self) -> Any:
        """Return the cached :class:`preflight.SubstrateSummary` or ``None``.

        Phase 97.3: substrate detection (controllers, active cloud,
        MicroCloud presence) shells out to ``juju`` and ``snap``.  We
        compute it once on the first ``_build_system_prompt`` call and
        reuse the result for the agent's lifetime.  Probe failures are
        treated as "no substrate info" — the prompt section degrades
        cleanly when the summary is ``None`` or has no fields set.

        Callers wanting to force a refresh (e.g. after a fresh
        ``concierge`` run) clear ``self._substrate_cache`` directly.
        """
        if self._substrate_cache is not None:
            return self._substrate_cache or None
        try:
            from cantrip.agent.runtime.preflight import substrate_summary

            self._substrate_cache = substrate_summary()
        except Exception:  # noqa: BLE001 - never block the prompt on a probe error.
            log.debug("substrate_summary probe failed", exc_info=True)
            self._substrate_cache = False  # cache the failure so we don't retry
            return None
        # Mirror the active cloud onto AgentState so the autodeploy hook
        # (which only sees state, not the agent) can pick up the
        # OpenStack acceptance task.  Empty string = "unknown".
        self.state.active_cloud = self._substrate_cache.active_cloud or ""
        return self._substrate_cache

    @property
    def repo_map(self) -> RepoMap | None:
        """The repo-map for the active charm, if one is configured.

        Built lazily on first access; subsequent calls reuse the cache.
        Returns ``None`` when no charm path is set or the path doesn't
        exist on disk — slash commands and tests rely on this to skip
        the section gracefully.
        """
        return self._repo.get_repo_map()

    def refresh_repo_map(self) -> str:
        """Force a full rebuild of the repo-map.

        Used by ``/map-refresh``.  Returns the rendered map at the
        full configured budget, or the empty string when no charm is
        active.
        """
        return self._repo.refresh_repo_map()

    @property
    def code_intel(self) -> CodeIntel | None:
        """Phase 72b read-only code-intelligence index for the active charm.

        Built lazily — same pattern as :attr:`repo_map`.  Returns
        ``None`` when no charm path is set or the path doesn't exist
        on disk; tools handle ``None`` by returning a clear error
        rather than failing silently.
        """
        return self._repo.get_code_intel()

    def _code_intel_or_none(self) -> CodeIntel | None:
        """Bound getter handed to the codeintel tools.

        Lambdas would close over ``self`` just as well, but a named
        method gives the tool layer a stable hook to monkey-patch in
        tests and a tidier ``repr`` if a tool ever logs its
        provenance.
        """
        return self._repo.code_intel_or_none()

    def _render_repo_map(self) -> str | None:
        """Build (incremental) and render the repo-map for prompt injection.

        Returns ``None`` when there's nothing to inject so the Jinja
        ``{% if repo_map %}`` block stays out of the prompt entirely.
        Failures are swallowed: the repo-map is a navigation aid; it
        must never break the conversation loop.  Anything more
        targeted than a bare ``Exception`` would risk a future
        regression where a new error type slips through and kills
        every turn.
        """
        return self._repo.render_repo_map()

    # Phase 110: phase-aware tool curation.  Each :class:`WorkflowPhase`
    # gets a hand-curated ≤11-name set so an inference-snap provider's
    # 12-tool cap can still fit one MCP tool / extension on top.  The
    # active phase is derived from the work-queue task category (or the
    # ``CANTRIP_TOOL_PHASE`` override); see :meth:`workflow_phase`.
    # Names match LLM-facing entries — Juju leaves are bundled behind the
    # single ``juju`` tool, so the sets reference the bundle name; the
    # leaf still dispatches via the subcommand rewrite at the executor.
    _CORE_TOOLS_BY_PHASE: dict[WorkflowPhase, set[str]] = {
        WorkflowPhase.BUILD: {
            "read_file",
            "write_file",
            "edit_file",
            "list_directory",
            "charmcraft_init",
            "quick_pack",
            "charmcraft_pack",
            "charmlint",
            "plan_tasks",
            "run_charm_tests",
            "run_command",
        },
        WorkflowPhase.DEBUG: {
            "read_file",
            "edit_file",
            "list_directory",
            "juju",
            "charmlint",
            "juju_debug_log",
            "juju_status_render",
            "run_command",
            "plan_tasks",
            "run_charm_tests",
            "web_fetch",
        },
        WorkflowPhase.DEPLOY: {
            "juju",
            "concierge_prepare",
            "juju_status_render",
            "juju_debug_log",
            "wait_for",
            "relation_smoke_test",
            "charmcraft_pack",
            "run_command",
            "list_directory",
            "plan_tasks",
        },
        WorkflowPhase.RESEARCH: {
            "read_file",
            "list_directory",
            "web_fetch",
            "web_search",
            "analyse_framework",
            "code_definition",
            "code_references",
            "oracle_consult",
            "plan_tasks",
            "extract_design_decisions",
        },
        WorkflowPhase.DEMO: {
            "read_file",
            "write_file",
            "edit_file",
            "list_directory",
            "charmcraft_init",
            "quick_pack",
            "charmcraft_pack",
            "manage_tasks",
            "plan_tasks",
            "run_charm_tests",
            "run_command",
        },
    }

    #: ``CANTRIP_TOOL_PHASE={research|build|debug|deploy|demo}`` pins the
    #: curated tool slice regardless of work-queue state — useful for
    #: operators driving cantrip through an unusual flow (e.g. a
    #: documentation pass that wants research-tier tools throughout).
    _TOOL_PHASE_ENV = "CANTRIP_TOOL_PHASE"

    def _active_task_category(self) -> TaskCategory | None:
        """Category of the currently-running queue task, or ``None``.

        Falls back to the next ready task so an interactive turn between
        executor picks still gets a sensible scope.
        """
        active = next(
            (t for t in self._work_queue.all_tasks() if t.status == TaskStatus.ACTIVE),
            None,
        )
        if active is None:
            active = self._work_queue.next_ready()
        return active.category if active is not None else None

    @property
    def workflow_phase(self) -> WorkflowPhase:
        """Active workflow phase used to curate the LLM tool slice.

        ``CANTRIP_TOOL_PHASE`` wins if set to a recognised value;
        otherwise the active (or next-ready) work-queue task's category
        maps onto a phase, defaulting to :attr:`WorkflowPhase.BUILD`
        when the conversation is idle.
        """
        override = os.environ.get(self._TOOL_PHASE_ENV, "").strip().lower()
        if override:
            try:
                return WorkflowPhase(override)
            except ValueError:
                log.warning(
                    "%s=%r is not a valid workflow phase; ignoring",
                    self._TOOL_PHASE_ENV,
                    override,
                )
        return WorkflowPhase.from_category(self._active_task_category())

    def _curated_tool_names(self) -> set[str]:
        return self._tool_builder.curated_tool_names()

    def tool_phase_badge(self) -> str:
        """Short badge text for status surfaces, or ``""`` when uncurated.

        Returns e.g. ``"build · 11"`` when the LLM tool slice has been
        narrowed to the active phase's curated set; empty when the full
        toolset is offered (roomy providers), so the badge stays quiet in
        the common case.
        """
        full = len(self._tools)
        offered = len(self._tools_for_llm())
        return f"{self.workflow_phase.value} · {offered}" if offered < full else ""

    def _tools_for_llm(self) -> list[llm.Tool]:
        return self._tool_builder.tools_for_llm()

    async def _execute_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool by name.

        Forwards the per-edit lint flag (Phase 71.4) and the active
        charm directory so :func:`execute_tool` can append ruff /
        ty / charmlint diagnostics to file-edit results.  Subagent
        callers go through :mod:`cantrip.agent.subagent`, which
        uses ``execute_tool`` directly without these arguments.
        """
        from cantrip.agent.tools.base import execute_tool

        result = await execute_tool(
            self._tool_map,
            name,
            arguments,
            auto_lint=self.state.auto_lint,
            charm_path=self.state.charm_path,
        )
        # Phase 103.1: a successful ``read_file`` clears the resume
        # must-read directive — the model has now seen the on-disk
        # bytes, so the next edit doesn't need the prompt nudge.
        if name == "read_file" and result.success and self.state.was_resumed:
            self.state.was_resumed = False
        # Phase 103.4: tick the post-resume hallucination counter from
        # the structured signals the edit tools emit.  ``edit_miss_path``
        # increments the per-file count; ``edit_success_paths`` (or the
        # singular ``edit_success_path`` from ``edit_file``) decrements
        # for each file the agent successfully resolved.
        if name in ("edit_file", "multi_edit") and result.data:
            self._update_edit_string_misses(result.data)
        return result

    def _update_edit_string_misses(self, data: dict[str, Any]) -> None:
        """Apply the Phase 103.4 hallucination-counter signals from *data*."""
        miss_path = data.get("edit_miss_path")
        if isinstance(miss_path, str):
            current = self.state.edit_string_misses.get(miss_path, 0)
            self.state.edit_string_misses[miss_path] = current + 1

        success_path = data.get("edit_success_path")
        success_paths = data.get("edit_success_paths") or []
        candidates: list[str] = []
        if isinstance(success_path, str):
            candidates.append(success_path)
        if isinstance(success_paths, list):
            candidates.extend(p for p in success_paths if isinstance(p, str))
        for path in candidates:
            current = self.state.edit_string_misses.get(path, 0)
            if current <= 1:
                self.state.edit_string_misses.pop(path, None)
            else:
                self.state.edit_string_misses[path] = current - 1

    def _publish_activity(self, label: str) -> None:
        """Publish a status-bar activity update (e.g. "running: charmcraft_pack").

        Used by the main conversation loop so slow tools like
        ``charmcraft_pack`` and ``juju_deploy`` produce visible feedback
        between LLM rounds — without this the bar stuck on a single
        flavour label and the user had no idea a long-running command
        was in flight.
        """
        self._event_bus.publish(ui_events.status_bar_changed(task_label=label))

    def _publish_tool_invoked(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: ToolResult,
        *,
        source: str,
        duration_ms: int | None = None,
        tool_call_id: str | None = None,
    ) -> None:
        """Emit a ``TOOL_INVOKED`` event for the chat surfaces (Phase 75).

        Builds a caption via :func:`build_tool_caption` — the tool's
        own ``ToolResult.caption`` when present, a formulaic
        ``tool_name(key=value)`` fallback otherwise.  Published on the
        shared event bus; the TUI chat widget and the Web UI each
        render a compact tool block when they receive it.

        ``tool_call_id`` (Phase 82) round-trips with the matching
        :meth:`_publish_tool_invoked_pending` event so the renderers can
        update the existing block in place rather than appending a new
        line.  On a failed call the event also carries a ``detail``
        string (error summary + captured output) so the chat surfaces
        can offer a "what went wrong" drill-down.
        """
        from cantrip.agent.tools.base import build_tool_caption

        caption = build_tool_caption(tool_name, arguments, result)
        self._event_bus.publish(
            ui_events.tool_invoked(
                tool_name=tool_name,
                caption=caption,
                success=result.success,
                duration_ms=duration_ms,
                source=source,
                tool_call_id=tool_call_id,
                detail=core._tool_failure_detail(result),
            )
        )

    def _publish_tool_invoked_pending(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        source: str,
        tool_call_id: str,
    ) -> None:
        """Emit a ``TOOL_INVOKED_PENDING`` event before tool dispatch (Phase 82).

        Renders the chat-surface "running now" block immediately so
        slow tools (``charmcraft_pack``, ``juju_wait``, ``web_fetch``)
        produce visible feedback the moment they're dispatched rather
        than after they return.  The matching ``TOOL_INVOKED`` event,
        carrying the same ``tool_call_id``, replaces the pending block
        with the post-call caption when the tool finishes.
        """
        from cantrip.agent.tools.base import build_tool_intro_caption

        tool = self._tool_map.get(tool_name) if self._tool_map else None
        caption = build_tool_intro_caption(tool, tool_name, arguments)
        self._event_bus.publish(
            ui_events.tool_invoked_pending(
                tool_name=tool_name,
                caption=caption,
                tool_call_id=tool_call_id,
                source=source,
            )
        )

    def _capture_test_results(self, tool_name: str, result: ToolResult) -> None:
        """Update state with test results if the tool produced a test summary."""
        if tool_name not in core._TEST_RESULT_TOOLS:
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
