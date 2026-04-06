"""Main Cantrip TUI application."""

import datetime
import traceback
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Input
from textual.worker import Worker, WorkerState

from cantrip import __version__
from cantrip.agent.core import CantripAgent
from cantrip.agent.design import DesignQuestion, parse_design_from_result
from cantrip.agent.preflight import DEFAULT_PRESET, CheckStatus, PreflightEvent
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.llm import LLMProvider, create_provider, resolve_light_provider
from cantrip.llm.base import ProviderError, ProviderOverloadedError, ProviderRateLimitError
from cantrip.tui.screens.graph import GraphScreen
from cantrip.tui.screens.help import HelpScreen
from cantrip.tui.screens.logs import LogScreen
from cantrip.tui.screens.questions import DesignQuestionsScreen
from cantrip.tui.screens.traces import TraceScreen
from cantrip.tui.screens.transcript import TranscriptScreen
from cantrip.tui.widgets.chat import ChatWidget
from cantrip.tui.widgets.filetree import CharmTreeWidget
from cantrip.tui.widgets.modelbar import ModelInfoBar
from cantrip.tui.widgets.status import MultiModelStatusWidget
from cantrip.tui.widgets.statusbar import StatusBar
from cantrip.tui.widgets.tasks import TaskChecklistWidget
from cantrip.ui import events as ui_events

# Preflight check names shown during the eager prepare (full bootstrap).
_PREPARE_CHECKS = ["concierge", "prepare", "juju", "controller", "cos"]

# Preflight check names shown if a re-bootstrap is needed (different preset).
_BOOTSTRAP_CHECKS = ["bootstrap", "controller", "cos"]


class CantripApp(App):
    """Cantrip TUI application."""

    TITLE = f"Cantrip v{__version__}"
    CSS_PATH = "cantrip.tcss"

    BINDINGS = [
        Binding("f1", "help", "Help"),
        Binding("f2", "toggle_status", "Toggle Status"),
        Binding("f3", "logs", "Logs"),
        Binding("f4", "debug", "Debug"),
        Binding("f5", "toggle_watcher", "Watcher"),
        Binding("f6", "toggle_files", "Files"),
        Binding("f7", "toggle_model_info", "Model"),
        Binding("f8", "graph", "Graph"),
        Binding("f9", "transcript", "Transcript"),
        Binding("q", "quit", "Quit"),
        Binding("ctrl+l", "clear_chat", "Clear"),
    ]

    def __init__(
        self,
        provider: str = "gemini",
        model: str | None = None,
        charm_path: Path | None = None,
        light_model: str | None = None,
        watcher: bool = False,
        max_concurrency: int | None = None,
        snap_name: str = "gemma3",
        light_snap_name: str | None = None,
        light_provider_name: str | None = None,
        improve_path: Path | None = None,
        theme_name: str | None = None,
    ):
        """Initialise the app."""
        super().__init__()
        self.provider_name = provider
        self.model_name = model
        self.charm_path = charm_path or Path.cwd()
        self._light_model_override = light_model
        self._snap_name = snap_name
        self._light_snap_name = light_snap_name
        self._light_provider_name = light_provider_name
        self._light_model_name: str | None = None
        self._max_concurrency = max_concurrency
        self._improve_path = improve_path
        self._theme_name = theme_name
        self._agent: CantripAgent | None = None
        self._prepare_group_idx: int | None = None
        self._bootstrap_group_idx: int | None = None
        self._bootstrap_started = False
        self._watcher_autostart = watcher
        self._session_start = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S")
        self._pending_confirm_id: str | None = None

        # Register bundled and user themes.
        from cantrip.tui.themes import register_themes

        register_themes(self)
        if self._theme_name:
            self.theme = self._theme_name

    def _fatal_error(self) -> None:
        """Print a plain traceback instead of Rich's decorated version.

        The default Textual implementation uses ``rich.traceback.Traceback``
        with ``show_locals=True``, which produces very long output that is
        hard to copy-paste into bug reports.
        """
        self.bell()
        self._exit_renderables.append(traceback.format_exc())
        self._close_messages_no_wait()

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        yield Header()
        yield Horizontal(
            Vertical(
                ModelInfoBar(id="model-info"),
                ChatWidget(id="chat"),
                Input(placeholder="Type your message...", id="chat-input"),
                id="left-panel",
            ),
            Vertical(
                TaskChecklistWidget(id="task-checklist"),
                CharmTreeWidget(self.charm_path, id="charm-files"),
                MultiModelStatusWidget(id="juju-status"),
                id="right-panel",
            ),
            id="main-container",
        )
        yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        """Handle app mount."""
        self.query_one("#chat-input", Input).focus()
        # The right panel is visible by default (charm file tree is useful
        # from the start).  Task checklist and Juju status appear as needed.
        self._init_agent()
        self._resume_session()
        self._start_prepare()
        self._start_executor()
        self._update_header_subtitle()
        self._update_model_info()
        # Refresh model info periodically to pick up subagent token usage.
        self.set_interval(5.0, self._update_model_info)
        if self._watcher_autostart:
            self._start_watcher()

    def _init_agent(self) -> None:
        """Initialise the LLM provider and agent."""
        try:
            llm_provider = create_provider(
                self.provider_name, self.model_name, snap_name=self._snap_name
            )

            # Resolve light provider for internal tasks (e.g. compaction).
            light_provider = self._resolve_light_provider(llm_provider)

            self._agent = CantripAgent(
                provider=llm_provider,
                charm_path=self.charm_path,
                light_provider=light_provider,
            )

            # Set improvement mode if --improve was passed.
            if self._improve_path is not None:
                self._agent.state.mode = "improve"
                self._agent.state.charm_path = self._improve_path
        except (ValueError, ProviderError) as e:
            chat = self.query_one("#chat", ChatWidget)
            chat.add_system_message(f"Failed to initialise provider: {e}")

    def _resume_session(self) -> None:
        """Load prior session state and show a resume summary if available."""
        if not self._agent:
            return
        if self._agent.load_state():
            summary = self._agent.build_resume_summary()
            if summary:
                chat = self.query_one("#chat", ChatWidget)
                chat.add_system_message(summary)

    def _resolve_light_provider(self, main_provider: LLMProvider) -> LLMProvider | None:
        """Build a light provider for cheap internal tasks."""
        light, name = resolve_light_provider(
            main_provider,
            self.provider_name,
            light_provider_name=self._light_provider_name,
            light_model_override=self._light_model_override,
            snap_name=self._snap_name,
            light_snap_name=self._light_snap_name,
        )
        if name:
            self._light_model_name = name
        return light

    def _update_header_subtitle(self) -> None:
        """Rebuild the header subtitle from agent state."""
        parts: list[str] = []
        if self._agent:
            state = self._agent.state
            if state.dev_model:
                substrate = "lxd" if state.charm_type == "machine" else "k8s"
                parts.append(f"[{state.dev_model}:{substrate}]")
            if state.cos_model:
                parts.append(f"[{state.cos_model}:k8s]")
        if self._light_model_name:
            parts.append(f"[light: {self._light_model_name}]")
        parts.append("[F1 Help]")
        self.sub_title = " ".join(parts)

    def _update_model_info(self) -> None:
        """Refresh the model info bar from current agent state."""
        bar = self.query_one("#model-info", ModelInfoBar)
        if not self._agent:
            return

        provider = self._agent.provider
        bar.provider_name = provider.name
        bar.model_name = provider.model_name
        bar.context_window = provider.context_window_tokens
        bar.compact_threshold = self._agent.context_manager._compaction_threshold

        if self._light_model_name:
            bar.light_model_name = self._light_model_name

        # Thinking mode — Gemini 3 models use thinking by default.
        if provider.model_name.startswith("gemini-3"):
            bar.thinking_mode = "thinking"
        else:
            bar.thinking_mode = ""

        # Context usage from current conversation.
        bar.context_used = self._agent.context_manager.estimate_tokens(self._agent.state.messages)

        # Token usage from the store.
        self._agent._ensure_store()
        if self._agent._store:
            # Current session usage (since this TUI launched).
            session = self._agent._store.get_usage_since(self._session_start)
            bar.session_prompt_tokens = session.get("prompt_tokens", 0)
            bar.session_completion_tokens = session.get("completion_tokens", 0)
            bar.session_request_count = session.get("request_count", 0)

            # All-time usage for this charm.
            alltime = self._agent._store.get_total_usage()
            bar.alltime_prompt_tokens = alltime.get("prompt_tokens", 0)
            bar.alltime_completion_tokens = alltime.get("completion_tokens", 0)

            by_model = self._agent._store.get_usage_by_model()
            total_requests = 0
            for r in by_model:
                count = r.get("request_count", 0)
                if isinstance(count, int):
                    total_requests += count
            bar.alltime_request_count = total_requests

    def action_toggle_model_info(self) -> None:
        """Toggle model info bar visibility."""
        bar = self.query_one("#model-info", ModelInfoBar)
        bar.display = not bar.display

    # -- Preflight integration ------------------------------------------------

    def _start_prepare(self) -> None:
        """Eagerly start a full environment preparation in a background worker.

        Uses the default preset (k8s) so the environment is ready by the
        time the user finishes describing their charm.
        """
        if not self._agent:
            return
        checklist = self.query_one("#task-checklist", TaskChecklistWidget)
        self._prepare_group_idx = checklist.add_preflight_group(
            "Preparing environment",
            ["Concierge", "Environment", "Juju CLI", "Controller", "COS"],
        )
        self.run_worker(
            self._agent.prepare(
                preset=DEFAULT_PRESET,
                callback=self._on_prepare_event,
            ),
            name="preflight_prepare",
            exclusive=False,
        )

    def _on_prepare_event(self, event: PreflightEvent) -> None:
        """Handle an eager-prepare preflight event — update the task pane."""
        if self._prepare_group_idx is None:
            return
        if event.check_name in _PREPARE_CHECKS:
            idx = _PREPARE_CHECKS.index(event.check_name)
            checklist = self.query_one("#task-checklist", TaskChecklistWidget)
            checklist.update_preflight(self._prepare_group_idx, idx, event.status)
        if event.check_name == "cos" and event.status == CheckStatus.PASSED:
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.cos_health = "● COS healthy"
            self._update_header_subtitle()

    def _start_bootstrap(self) -> None:
        """Re-bootstrap if the user picked a different preset than the default.

        If the eager prepare already completed with the same preset (or the
        user hasn't specified a charm type yet), this is a no-op.
        """
        if not self._agent or self._bootstrap_started:
            return
        preset = self._agent.state.charm_type
        if not preset:
            return
        # Skip if the eager prepare already used the right preset.
        if preset == DEFAULT_PRESET and self._agent.preflight_result.fully_ready:
            self._bootstrap_started = True
            return
        self._bootstrap_started = True
        checklist = self.query_one("#task-checklist", TaskChecklistWidget)
        self._bootstrap_group_idx = checklist.add_preflight_group(
            f"Re-bootstrapping ({preset})",
            ["Controller", "Controller check", "COS"],
        )
        self.run_worker(
            self._agent.bootstrap_environment(
                preset=preset,
                callback=self._on_bootstrap_event,
            ),
            name="preflight_bootstrap",
            exclusive=False,
        )

    def _on_bootstrap_event(self, event: PreflightEvent) -> None:
        """Handle a re-bootstrap preflight event — update the task pane."""
        if self._bootstrap_group_idx is None:
            return
        if event.check_name in _BOOTSTRAP_CHECKS:
            idx = _BOOTSTRAP_CHECKS.index(event.check_name)
            checklist = self.query_one("#task-checklist", TaskChecklistWidget)
            checklist.update_preflight(self._bootstrap_group_idx, idx, event.status)

    # -- Executor integration -------------------------------------------------

    def _start_executor(self) -> None:
        """Start the background executor and wire task-change notifications."""
        if not self._agent:
            return

        # Subscribe to task updates via the shared event bus.
        self._agent.event_bus.subscribe(
            ui_events.EventType.TASK_UPDATED, self._on_bus_task_updated
        )

        self._agent.start_executor(max_concurrency=self._max_concurrency)

        # Prime the display with any tasks restored from a previous session.
        checklist = self.query_one("#task-checklist", TaskChecklistWidget)
        existing = self._agent.work_queue.all_tasks()
        if existing:
            checklist.notify_changed(existing)

    def _on_bus_task_updated(self, event: ui_events.Event) -> None:
        """Handle a task-updated event from the bus."""
        if not self._agent:
            return

        def _update() -> None:
            checklist = self.query_one("#task-checklist", TaskChecklistWidget)
            checklist.notify_changed(self._agent.work_queue.all_tasks())

            # Detect when a confirm task becomes blocked.
            payload = event.payload
            if (
                payload.get("category") == TaskCategory.CONFIRM.value
                and payload.get("status") == TaskStatus.BLOCKED.value
                and self._pending_confirm_id is None
            ):
                task_id = payload["id"]
                self._pending_confirm_id = task_id
                task = self._agent.work_queue.get_task(task_id)
                if task is None:
                    return
                if task_id == "confirm-improvements":
                    self._present_improvement_confirmation(task)
                else:
                    self._present_design_questions(task)

        self.call_from_thread(_update)

    def on_task_checklist_widget_tasks_available(self) -> None:
        """Show the status panel when tasks first appear."""
        self.query_one("#right-panel").display = True

    # -- Design questions flow ------------------------------------------------

    def _present_design_questions(self, task: AgentTask) -> None:
        """Extract the design proposal and show interactive questions.

        Called from the executor callback (via ``call_from_thread``) when a
        confirm-design task becomes blocked.  Walks the task's dependencies
        to find the synthesis result, parses it for structured questions,
        and either pushes the interactive questions screen or falls back to
        showing everything in chat for the LLM to handle.
        """
        if not self._agent:
            return

        # Find the synthesis result from the confirm task's dependencies.
        design_text = ""
        for dep_id in task.dependencies:
            dep = self._agent.work_queue.get_task(dep_id)
            if dep is not None and dep.result:
                design_text = dep.result
                break

        if not design_text:
            # No design found — let the conversation LLM handle it.
            self._pending_confirm_id = None
            return

        proposal = parse_design_from_result(design_text)
        questions = proposal.questions_for_user

        if not questions:
            # No structured questions — let the conversation LLM handle it.
            self._pending_confirm_id = None
            return

        # Show the design summary in chat (without questions).
        chat = self.query_one("#chat", ChatWidget)
        chat.add_system_message(proposal.format_for_chat())

        # Push the interactive questions screen.
        self.push_screen(
            DesignQuestionsScreen(questions),
            callback=self._on_questions_answered,
        )

    def _on_questions_answered(self, questions: list[DesignQuestion] | None) -> None:
        """Handle completed design questions and trigger design confirmation."""
        confirm_id = self._pending_confirm_id
        self._pending_confirm_id = None

        if not self._agent or not confirm_id:
            return

        # Build an overrides string from the answered questions.
        answered = [q for q in (questions or []) if q.answer]
        if answered:
            lines = [f"- **{q.key}**: {q.answer}" for q in answered]
            overrides = "User answers:\n" + "\n".join(lines)
        else:
            overrides = None

        # Show answers in chat.
        chat = self.query_one("#chat", ChatWidget)
        if answered:
            answer_text = "\n".join(f"**{q.key}**: {q.answer}" for q in answered)
            chat.add_user_message(answer_text)
        chat.add_system_message("Design approved. Generating build tasks...")

        # Approve the confirm task and generate build tasks.
        self.run_worker(
            self._complete_design_confirmation(confirm_id, overrides),
            name="design_confirmation",
            exclusive=False,
        )

    async def _complete_design_confirmation(self, confirm_id: str, overrides: str | None) -> None:
        """Approve the confirm task and generate build tasks from the design."""
        if not self._agent:
            return

        # Approve (unblock → done).
        self._agent.work_queue.set_done(confirm_id, "Approved by user")

        # Generate build tasks.
        build_tasks = await self._agent.handle_design_confirmation(
            confirm_id,
            overrides=overrides,
        )

        chat = self.query_one("#chat", ChatWidget)
        if build_tasks:
            titles = "\n".join(f"- {t.title}" for t in build_tasks)
            chat.add_system_message(f"Build plan created:\n{titles}")
        else:
            chat.add_system_message("No build tasks generated — check the design output.")

    # -- Improvement confirmation flow ----------------------------------------

    def _present_improvement_confirmation(self, task: AgentTask) -> None:
        """Show audit findings in chat and auto-approve all gaps.

        Called when the ``confirm-improvements`` task becomes blocked.
        Presents the audit report to the user, then immediately triggers
        fix task generation for all detected gaps.
        """
        if not self._agent:
            return

        # Find the audit result from the confirm task's dependencies.
        audit_report = ""
        for dep_id in task.dependencies:
            dep = self._agent.work_queue.get_task(dep_id)
            if dep is not None and dep.result:
                audit_report = dep.result
                # The audit tool stores structured gaps in task data, but
                # the subagent result is plain text.  Re-extract gaps from
                # the audit report heuristically, or approve all.
                break

        chat = self.query_one("#chat", ChatWidget)
        if audit_report:
            # Truncate long reports for the chat display.
            preview = audit_report[:2000]
            if len(audit_report) > 2000:
                preview += "\n\n*(truncated — full report in task result)*"
            chat.add_system_message(f"**Audit complete:**\n\n{preview}")

        chat.add_system_message("Approving all improvements. Generating fix tasks...")

        self.run_worker(
            self._complete_improvement_confirmation(task.id),
            name="improvement_confirmation",
            exclusive=False,
        )

    async def _complete_improvement_confirmation(self, confirm_id: str) -> None:
        """Approve the improvement confirm task and generate fix tasks."""
        if not self._agent:
            return

        self._agent.work_queue.set_done(confirm_id, "Approved by user")
        self._pending_confirm_id = None

        fix_tasks = await self._agent.handle_improvement_confirmation(confirm_id)

        chat = self.query_one("#chat", ChatWidget)
        if fix_tasks:
            titles = "\n".join(f"- {t.title}" for t in fix_tasks)
            chat.add_system_message(f"Improvement plan created:\n{titles}")
        else:
            chat.add_system_message(
                "No improvement tasks generated — the charm may already be up to standard."
            )

    # -- Watcher integration --------------------------------------------------

    def _start_watcher(self) -> None:
        """Start the event watcher if possible.

        Events are automatically routed to the task queue by the agent's
        ``start_watcher`` method.  The TUI subscribes to ``WATCHER_EVENT``
        on the bus to display chat notifications.
        """
        if not self._agent:
            return
        chat = self.query_one("#chat", ChatWidget)
        if not self._agent.state.dev_model:
            chat.add_system_message(
                "Cannot start watcher: no development model is set. "
                "Deploy a charm first, then press F5 to start watching."
            )
            return

        # Subscribe to watcher events via the bus.
        self._agent.event_bus.subscribe(
            ui_events.EventType.WATCHER_EVENT, self._on_bus_watcher_event
        )

        started = self._agent.start_watcher()
        if started:
            self._update_status_bar_watcher()
            chat.add_system_message("Watcher started — monitoring development model for events.")
        else:
            chat.add_system_message("Failed to start watcher.")

    async def _stop_watcher(self) -> None:
        """Stop the event watcher."""
        if not self._agent:
            return
        await self._agent.stop_watcher()
        self._update_status_bar_watcher()

    def _on_bus_watcher_event(self, event: ui_events.Event) -> None:
        """Handle a watcher event from the bus."""

        def _update() -> None:
            chat = self.query_one("#chat", ChatWidget)
            chat.add_system_message(f"[Watcher] {event.payload.get('summary', '')}")

            # Feed the latest status snapshot into the multi-model widget.
            if self._agent and self._agent._watcher:
                latest = self._agent._watcher.latest_status
                if latest is not None:
                    status_widget = self.query_one("#juju-status", MultiModelStatusWidget)
                    status_widget.dev_status = latest

        self.call_from_thread(_update)

    def _update_status_bar_watcher(self) -> None:
        """Update the status bar watcher indicator."""
        status_bar = self.query_one("#status-bar", StatusBar)
        if self._agent and self._agent.watcher_running:
            status_bar.watcher_status = "👁 Watching"
        else:
            status_bar.watcher_status = ""

    def action_toggle_watcher(self) -> None:
        """Toggle the event watcher on or off."""
        if not self._agent:
            return
        if self._agent.watcher_running:
            self.run_worker(self._stop_watcher(), name="stop_watcher", exclusive=False)
            chat = self.query_one("#chat", ChatWidget)
            chat.add_system_message("Watcher stopped.")
        else:
            self._start_watcher()

    # -- Chat -----------------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle chat input submission."""
        message = event.value.strip()
        if not message:
            return

        event.input.value = ""

        chat = self.query_one("#chat", ChatWidget)
        chat.add_user_message(message)

        if not self._agent:
            chat.add_system_message("No LLM provider configured. Check your API key.")
            return

        # Disable input and show thinking indicator while processing.
        input_widget = self.query_one("#chat-input", Input)
        input_widget.disabled = True
        input_widget.placeholder = "Waiting for response..."
        chat.show_thinking()
        self.query_one("#status-bar", StatusBar).task_label = "⟳ Thinking..."

        # Run agent processing in a background worker.
        self.run_worker(
            self._process_agent_message(message),
            name="agent_response",
            exclusive=True,
        )

    async def _process_agent_message(self, message: str) -> str:
        """Process a message through the agent. Runs in a worker."""
        return await self._agent.process_message(message)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker state changes to update the UI."""
        if event.worker.name == "agent_response":
            self._on_agent_response_done(event)
        # Preflight workers don't need special handling on completion.

    def _on_agent_response_done(self, event: Worker.StateChanged) -> None:
        """Handle agent response worker completion."""
        # Only act on terminal states — not PENDING or RUNNING.
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            return

        chat = self.query_one("#chat", ChatWidget)
        input_widget = self.query_one("#chat-input", Input)

        # Remove the thinking indicator and reset status bar.
        chat.hide_thinking()
        self.query_one("#status-bar", StatusBar).task_label = ""

        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if result:
                chat.add_assistant_message(str(result))
            input_widget.disabled = False
            input_widget.placeholder = "Type your message..."
            input_widget.focus()
            # Persist session state and check for new charm type.
            self._agent.save_state()
            self._start_bootstrap()
            self._update_header_subtitle()
            self._update_model_info()
            self._update_test_summary()

        elif event.state == WorkerState.ERROR:
            error = event.worker.error
            if isinstance(error, ProviderRateLimitError | ProviderOverloadedError):
                chat.add_system_message(
                    "Provider temporarily unavailable — please wait a moment and try again."
                )
            else:
                chat.add_system_message(f"Error: {error}")
            input_widget.disabled = False
            input_widget.placeholder = "Type your message..."
            input_widget.focus()

    def _update_test_summary(self) -> None:
        """Update the status bar test summary from agent state."""
        if not self._agent or not self._agent.state.test_results:
            return
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.test_summary = self._agent.state.test_results.format_summary()

    def action_help(self) -> None:
        """Show help screen."""
        self.push_screen(HelpScreen())

    def action_debug(self) -> None:
        """Show trace/debug screen."""
        cos_model = self._agent.state.cos_model if self._agent else None
        self.push_screen(TraceScreen(cos_model=cos_model))

    def on_juju_status_widget_status_available(self) -> None:
        """Show the status panel when status data first arrives."""
        self.query_one("#right-panel").display = True

    def action_toggle_status(self) -> None:
        """Toggle status panel visibility."""
        right_panel = self.query_one("#right-panel")
        right_panel.display = not right_panel.display

    def action_toggle_files(self) -> None:
        """Toggle charm file tree visibility."""
        tree = self.query_one("#charm-files", CharmTreeWidget)
        tree.display = not tree.display

    def action_logs(self) -> None:
        """Show log viewer screen."""
        dev_model = self._agent.state.dev_model if self._agent else None
        self.push_screen(LogScreen(model=dev_model))

    def action_graph(self) -> None:
        """Show integration graph screen."""
        status_widget = self.query_one("#juju-status", MultiModelStatusWidget)
        current_app = self._agent.state.charm_name if self._agent else None
        self.push_screen(GraphScreen(status=status_widget.dev_status, current_app=current_app))

    def action_transcript(self) -> None:
        """Show session transcript screen."""
        import pathlib

        db_path: pathlib.Path | None = None
        if self._agent and self._agent.state.charm_path:
            candidate = self._agent.state.charm_path / ".cantrip"
            if candidate.exists():
                db_path = candidate
        self.push_screen(TranscriptScreen(db_path=db_path))

    async def action_quit(self) -> None:
        """Stop background services and quit."""
        if self._agent:
            if self._agent.executor_running:
                await self._agent.stop_executor()
            if self._agent.watcher_running:
                await self._agent.stop_watcher()
        self.exit()

    def action_clear_chat(self) -> None:
        """Clear chat history."""
        chat = self.query_one("#chat", ChatWidget)
        chat.clear()
