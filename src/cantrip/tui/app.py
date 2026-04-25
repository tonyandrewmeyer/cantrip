"""Main Cantrip TUI application."""

import asyncio
import contextlib
import datetime
import traceback
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Input
from textual.worker import Worker, WorkerState

from cantrip import __version__, diagnostics, notifications, update
from cantrip.agent import emotions, slash_commands
from cantrip.agent.core import CantripAgent
from cantrip.agent.design import DesignQuestion, parse_design_from_result
from cantrip.agent.git_branch import BOOTSTRAP_CONFIRM_PREFIX, PUSH_CONFIRM_PREFIX
from cantrip.agent.github_issues import TRIAGE_CONFIRM_PREFIX
from cantrip.agent.planner import IMPROVEMENT_CONFIRM_BASE
from cantrip.agent.preflight import DEFAULT_PRESET, CheckStatus, PreflightEvent
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.agent.race import RACE_CONFIRM_PREFIX
from cantrip.hooks import HookRunner
from cantrip.llm import LLMProvider, create_provider, pricing, resolve_light_provider
from cantrip.llm.base import ProviderError, ProviderOverloadedError, ProviderRateLimitError, Role
from cantrip.tui.widgets import chat as chat_widget
from cantrip.tui.widgets import filetree as filetree_widget
from cantrip.tui.widgets import modelbar as modelbar_widget
from cantrip.tui.widgets import status as status_widgets
from cantrip.tui.widgets import statusbar as statusbar_widget
from cantrip.tui.widgets import tasks as tasks_widget
from cantrip.ui import events as ui_events
from cantrip.ui import flavour

# Preflight check names shown during the eager prepare (full bootstrap).
_PREPARE_CHECKS = ["concierge", "prepare", "juju", "controller", "cos"]

# Preflight check names shown if a re-bootstrap is needed (different preset).
_BOOTSTRAP_CHECKS = ["bootstrap", "controller", "cos"]


def _alltime_cost(rows: list[dict]) -> float:
    """Sum per-model cost across all-time usage rows from the store.

    Cache tokens aren't tracked separately in the store, so the all-time
    figure uses fresh prompt/completion rates only — it slightly
    over-counts Claude sessions that benefited from prompt caching,
    which is acceptable for a ballpark display.
    """
    cost = 0.0
    for row in rows:
        cost += pricing.estimate_cost(
            str(row.get("model", "")),
            prompt_tokens=int(row.get("prompt_tokens") or 0),
            completion_tokens=int(row.get("completion_tokens") or 0),
        )
    return cost


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
        Binding("ctrl+f", "search_chat", "Search", priority=True),
        Binding("ctrl+c", "cancel_agent", "Cancel", show=False),
        Binding("escape", "cancel_agent", "Cancel", show=False),
    ]

    def __init__(
        self,
        provider: str = "gemini",
        model: str | None = None,
        charm_path: Path | None = None,
        light_model: str | None = None,
        max_concurrency: int | None = None,
        snap_name: str = "gemma3",
        light_snap_name: str | None = None,
        light_provider_name: str | None = None,
        improve_path: Path | None = None,
        theme_name: str | None = None,
        base_url: str | None = None,
        max_iterations: int | None = None,
        max_tokens: int | None = None,
        no_snapshots: bool = False,
        yolo: bool = False,
        no_auto_lint: bool = False,
        architect: bool = False,
        editor_provider: str | None = None,
        editor_model: str | None = None,
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
        self._base_url = base_url
        self._max_iterations = max_iterations
        self._max_tokens = max_tokens
        self._no_snapshots = no_snapshots
        self._yolo = yolo
        self._no_auto_lint = no_auto_lint
        self._architect = architect
        self._editor_provider = editor_provider
        self._editor_model = editor_model
        self._agent: CantripAgent | None = None
        self._prepare_group_idx: int | None = None
        self._bootstrap_group_idx: int | None = None
        self._bootstrap_started = False
        self._watcher_retry_timer: object | None = None
        self._session_start = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S")
        self._pending_confirm_id: str | None = None
        self._pending_pr_branch: str | None = None
        self._bootstrap_offered: bool = False
        self._pending_maintenance: dict | None = None  # {"pr_url": ..., "issue": ...}
        self._streaming_widget: chat_widget.MessageWidget | None = None
        # Populated by the background PyPI version-check worker.  Read
        # from :func:`cantrip.main._run` after ``app.run()`` returns so
        # the Rich panel prints once the Textual screen has torn down.
        self.pending_update_info: update.UpdateInfo | None = None

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

        Also persists the traceback to the diagnostics log
        (``$XDG_STATE_HOME/cantrip/diagnostics.log``) so a developer
        can read the underlying cause after the user has hit a UI
        crash — Textual's terminal-restoration tears the screen down
        before most users can copy the traceback by hand.
        """
        self.bell()
        formatted = traceback.format_exc()
        self._exit_renderables.append(formatted)
        # Also capture to the diagnostics log.  ``sys.exc_info`` may
        # not have a live exception by the time this runs in some
        # Textual paths, so guard accordingly and fall back to writing
        # the formatted text directly.
        import sys

        exc = sys.exc_info()[1]
        if exc is not None:
            with contextlib.suppress(Exception):
                diagnostics.report_internal_error("textual_fatal", exc)
        else:
            log_path = diagnostics.log_path()
            with contextlib.suppress(OSError):
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(
                        f"\n{'=' * 72}\n"
                        f"{datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds')}"
                        f"  textual_fatal (no live exception object)\n"
                        f"{'-' * 72}\n"
                        f"{formatted}"
                    )
        self._close_messages_no_wait()

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        yield Header()
        yield Horizontal(
            Vertical(
                modelbar_widget.ModelInfoBar(id="model-info"),
                chat_widget.ChatWidget(id="chat"),
                chat_widget.SlashCommandSuggestions(
                    self._build_command_catalogue(),
                    id="slash-suggestions",
                ),
                chat_widget.ChatInput(placeholder="Type your message...", id="chat-input"),
                id="left-panel",
            ),
            Vertical(
                tasks_widget.TaskChecklistWidget(id="task-checklist"),
                filetree_widget.CharmTreeWidget(self.charm_path, id="charm-files"),
                status_widgets.MultiModelStatusWidget(id="juju-status"),
                id="right-panel",
            ),
            id="main-container",
        )
        yield statusbar_widget.StatusBar(id="status-bar")

    @staticmethod
    def _build_command_catalogue() -> tuple[slash_commands.CommandInfo, ...]:
        """Return the catalogue used by the slash-suggestion popup.

        Starts from the shared :data:`slash_commands.COMMAND_CATALOGUE`
        and appends TUI-native verbs (currently ``/feelings``) so the
        popup can surface them alongside the cross-surface commands.
        """
        return (
            *slash_commands.COMMAND_CATALOGUE,
            slash_commands.CommandInfo("/feelings", "Convene the inner parliament"),
        )

    def on_mount(self) -> None:
        """Handle app mount."""
        chat_input = self.query_one("#chat-input", chat_widget.ChatInput)
        chat_input.focus()
        chat_input.bind_suggestions(
            self.query_one("#slash-suggestions", chat_widget.SlashCommandSuggestions)
        )
        # The right panel is visible by default (charm file tree is useful
        # from the start).  Task checklist and Juju status appear as needed.
        self._init_agent()
        # Route every cross-thread bus publish back onto the UI loop so
        # bus subscribers always run on the UI thread (matches cli.py
        # and web/server.py).  Without this, the watcher's in-loop
        # publish delivered synchronously on the UI thread, the
        # ``call_from_thread`` guard fired a RuntimeError, and the
        # exception was swallowed by the bus — leaving the Dev / COS
        # panes stuck on "Not connected" / "Not deployed".
        if self._agent is not None:
            self._agent.event_bus.bind_loop(asyncio.get_running_loop())
            notifications.install(self._agent.event_bus)
        # Issue triage adds tasks to the work queue for any actionable
        # GitHub issue.  It must run *after* ``_resume_session`` has
        # finished loading the persisted queue — otherwise the
        # background triage worker can register an ``triage-issue-N``
        # task before ``load_state`` gets to load the persisted copy
        # of the same task, and the deferred load then crashes on a
        # duplicate ID.  ``_resume_session`` calls ``_start_issue_triage``
        # itself once the resume modal resolves (or immediately when no
        # prior session exists and the modal is skipped).
        self._resume_session()
        self._start_prepare()
        self._start_executor()
        self._start_mcp()
        self._update_header_subtitle()
        self._update_model_info()
        # Refresh model info periodically to pick up subagent token usage.
        self.set_interval(5.0, self._update_model_info)
        self._subscribe_watcher_events()
        self._start_watcher()
        self._start_update_check()

    def _start_update_check(self) -> None:
        """Kick off the PyPI update check as a background worker.

        The result is stashed on :attr:`pending_update_info` and
        printed by :func:`cantrip.main._run` after the Textual screen
        tears down, matching ``toad``'s exit-time prompt so the notice
        never interrupts mid-session.
        """
        self.run_worker(
            self._run_update_check(),
            name="update_check",
            exclusive=False,
        )

    async def _run_update_check(self) -> None:
        """Worker body — swallow any surprise and stash the result."""
        try:
            self.pending_update_info = await update.check_for_update()
        except (OSError, RuntimeError, ValueError):
            self.pending_update_info = None

    def _start_mcp(self) -> None:
        """Connect any configured MCP servers in the background.

        Runs as a worker so a slow-launching server never blocks the UI.
        Failures are captured in the registry's per-server status —
        ``/mcp`` shows them — so this fire-and-forget pattern is safe.
        """
        if not self._agent:
            return
        if not self._agent.mcp_registry.configured:
            return
        self.run_worker(
            self._agent.start_mcp(),
            name="mcp_start",
            exclusive=False,
        )

    def _init_agent(self) -> None:
        """Initialise the LLM provider and agent."""
        try:
            llm_provider = create_provider(
                self.provider_name,
                self.model_name,
                snap_name=self._snap_name,
                base_url=self._base_url,
            )

            # Resolve light provider for internal tasks (e.g. compaction).
            light_provider = self._resolve_light_provider(llm_provider)

            self._agent = CantripAgent(
                provider=llm_provider,
                charm_path=self.charm_path,
                light_provider=light_provider,
                hook_runner=HookRunner.from_disk(repo_root=self.charm_path),
            )

            # Phase 55.3: stamp the per-goal budget from CLI flags + env vars.
            from cantrip.agent.goal_budget import from_cli_args

            self._agent.state.goal_budget = from_cli_args(
                max_iterations=self._max_iterations,
                max_tokens=self._max_tokens,
            )

            # Phase 68.1: opt out of per-turn working-tree snapshots.
            from cantrip.agent.snapshots import snapshots_enabled

            self._agent.state.snapshot_enabled = snapshots_enabled(
                no_snapshots_flag=self._no_snapshots,
            )

            # Phase 69.2: opt into unattended mode before the executor
            # starts so the first subagent sees ``ask`` decisions as
            # auto-approvals from the first dispatch.  ``start_executor``
            # syncs the flag onto the freshly-built PermissionManager.
            if self._yolo:
                self._agent.state.yolo_mode = True

            # Phase 71.4: per-edit lint feedback opt-out.  Inverted
            # because the CLI flag is ``--no-auto-lint`` while the
            # default state is ``True``.
            if self._no_auto_lint:
                self._agent.state.auto_lint = False

            # Phase 71.2: architect/editor split (CLI flag → state).
            if self._architect:
                self._agent.state.architect_mode = True
                self._agent.state.editor_provider = self._editor_provider
                self._agent.state.editor_model = self._editor_model

            # Set improvement mode if --improve was passed.
            if self._improve_path is not None:
                self._agent.state.mode = "improve"
                self._agent.state.charm_path = self._improve_path
        except (ValueError, ProviderError) as e:
            chat = self.query_one("#chat", chat_widget.ChatWidget)
            chat.add_system_message(f"Failed to initialise provider: {e}")

    def _resume_session(self) -> None:
        """Offer a Resume / Fresh / Transcript choice when prior state exists.

        Phase 31.3: replaces the old silent-load behaviour with an
        explicit prompt.  No ``load_state`` happens here — the modal's
        callback is responsible for loading (on Resume) or archiving
        (on Fresh), so a user picking Fresh doesn't end up with a
        polluted ``state`` that was populated before they decided.

        After the modal resolves (or immediately when no prior
        session exists), :meth:`_start_issue_triage` kicks off the
        background GitHub-issue scan.  Triage *must* run after
        ``load_state`` so the persisted queue takes priority over a
        fresh triage that happens to find the same issue —
        otherwise the deferred load crashes on a duplicate task ID.
        """
        if not self._agent:
            return
        preview = self._agent.preview_session()
        if not preview.exists:
            # No persisted state — no resume modal needed; triage can
            # start immediately.
            self._start_issue_triage()
            return
        from cantrip.tui.screens import resume as resume_screen

        transcript = self._agent.transcript_tail(limit=20)
        screen = resume_screen.ResumePromptScreen(preview, transcript=transcript)

        def _on_choice(choice: str | None) -> None:
            if choice == "fresh":
                backup = self._agent.archive_session() if self._agent else None
                chat = self.query_one("#chat", chat_widget.ChatWidget)
                if backup is not None:
                    chat.add_system_message(
                        f"Starting fresh — prior session archived to {backup.name}."
                    )
                self._start_issue_triage()
                return
            # Default path (resume or dismissed): load state and show summary.
            if self._agent and self._agent.load_state():
                summary = self._agent.build_resume_summary()
                if summary:
                    chat = self.query_one("#chat", chat_widget.ChatWidget)
                    chat.add_system_message(summary)
            self._start_issue_triage()

        self.push_screen(screen, _on_choice)

    def _start_issue_triage(self) -> None:
        """Kick off background GitHub-issue triage, if a remote was detected."""
        if self._agent and self._agent.state.github_repo:
            self._agent.start_issue_triage()

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
            if state.github_repo:
                parts.append(f"[gh:{state.github_repo}]")
        if self._light_model_name:
            parts.append(f"[light: {self._light_model_name}]")
        parts.append("[F1 Help]")
        self.sub_title = " ".join(parts)

    def _update_model_info(self) -> None:
        """Refresh the model info bar from current agent state."""
        bar = self.query_one("#model-info", modelbar_widget.ModelInfoBar)
        if not self._agent:
            return

        provider = self._agent.provider
        bar.provider_name = provider.name
        bar.model_name = provider.model_name
        bar.context_window = provider.context_window_tokens
        bar.compact_threshold = self._agent.context_manager.compaction_threshold

        if self._light_model_name:
            bar.light_model_name = self._light_model_name

        # Thinking mode — Gemini 3 and Claude models support extended thinking.
        if provider.model_name.startswith(("gemini-3", "claude-sonnet-4", "claude-opus-4")):
            bar.thinking_mode = "thinking"
        else:
            bar.thinking_mode = ""

        # Context usage from current conversation.
        bar.context_used = self._agent.context_manager.estimate_tokens(self._agent.state.messages)

        # Token usage from the store.
        store = self._agent.store
        if store:
            # Current session usage (since this TUI launched).
            session = store.get_usage_since(self._session_start)
            bar.session_prompt_tokens = session.get("prompt_tokens", 0)
            bar.session_completion_tokens = session.get("completion_tokens", 0)
            bar.session_request_count = session.get("request_count", 0)

            # All-time usage for this charm.
            alltime = store.get_total_usage()
            bar.alltime_prompt_tokens = alltime.get("prompt_tokens", 0)
            bar.alltime_completion_tokens = alltime.get("completion_tokens", 0)

            by_model = store.get_usage_by_model()
            total_requests = 0
            for r in by_model:
                count = r.get("request_count", 0)
                if isinstance(count, int):
                    total_requests += count
            bar.alltime_request_count = total_requests

            # Cost estimates.  Session cost applies Claude's per-model cache
            # rates to the session accumulators; all-time cost sums fresh
            # prompt/completion rates per model (historical cache splits are
            # not preserved in the store, so cache discounts are ignored
            # for the lifetime figure).
            bar.session_cost_usd = self._session_cost(store)
            bar.alltime_cost_usd = _alltime_cost(by_model)

        # Session-level cache stats (Claude prompt caching).
        bar.cache_creation_tokens = self._agent.cache_creation_tokens
        bar.cache_read_tokens = self._agent.cache_read_tokens

        # GitHub remote.
        bar.github_repo = self._agent.state.github_repo or ""

    def _session_cost(self, store) -> float:
        """Estimate total USD cost for the current session.

        Applies each per-model row from the store's since-filtered query
        at that model's price, then adds Claude cache contributions from
        the agent's session accumulators.  The cache portion is
        attributed to the current provider's model since the agent
        aggregates cache tokens without per-model granularity — a minor
        inaccuracy in the rare case a user switches Claude variants
        mid-session.
        """
        assert self._agent is not None
        session_rows = store.get_usage_by_model_since(self._session_start)
        cost = 0.0
        for row in session_rows:
            cost += pricing.estimate_cost(
                str(row["model"]),
                prompt_tokens=int(row["prompt_tokens"] or 0),
                completion_tokens=int(row["completion_tokens"] or 0),
            )
        cache_read = self._agent.cache_read_tokens
        cache_write = self._agent.cache_creation_tokens
        if cache_read or cache_write:
            cost += pricing.estimate_cost(
                self._agent.provider.model_name,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
            )
        return cost

    def action_toggle_model_info(self) -> None:
        """Toggle model info bar visibility."""
        bar = self.query_one("#model-info", modelbar_widget.ModelInfoBar)
        bar.display = not bar.display

    # -- Preflight integration ------------------------------------------------

    def _start_prepare(self) -> None:
        """Eagerly start a full environment preparation in a background worker.

        Uses the default preset (k8s) so the environment is ready by the
        time the user finishes describing their charm.
        """
        if not self._agent:
            return
        checklist = self.query_one("#task-checklist", tasks_widget.TaskChecklistWidget)
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
            checklist = self.query_one("#task-checklist", tasks_widget.TaskChecklistWidget)
            checklist.update_preflight(self._prepare_group_idx, idx, event.status)
        if event.check_name == "cos" and event.status == CheckStatus.PASSED:
            status_bar = self.query_one("#status-bar", statusbar_widget.StatusBar)
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
        checklist = self.query_one("#task-checklist", tasks_widget.TaskChecklistWidget)
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
            checklist = self.query_one("#task-checklist", tasks_widget.TaskChecklistWidget)
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
        # Subscribe to memory write/recall events so the user can see when
        # the agent durably remembers something or pulls up an old lesson.
        self._agent.event_bus.subscribe(
            ui_events.EventType.MEMORY_WRITTEN, self._on_bus_memory_written
        )
        self._agent.event_bus.subscribe(
            ui_events.EventType.MEMORY_RECALLED, self._on_bus_memory_recalled
        )
        # Surface main-agent tool activity in the status bar — slow tools
        # like charmcraft_pack and juju_deploy publish "running: <name>"
        # between LLM rounds so the UI isn't frozen on a single flavour
        # label.
        self._agent.event_bus.subscribe(
            ui_events.EventType.STATUS_BAR_CHANGED, self._on_bus_status_bar
        )
        # Phase 75: inline tool blocks in the chat so the trailing-colon
        # preambles ("Let me check the file:") stop reading as broken
        # speech — the next thing the user sees is the tool block that
        # explains what the agent actually did.
        self._agent.event_bus.subscribe(
            ui_events.EventType.TOOL_INVOKED, self._on_bus_tool_invoked
        )
        # Phase 78.2: update the modelbar cache indicator reactively on
        # every turn with cache activity, matching the same signal the
        # Web UI's header badge uses.  The 5-second polling timer in
        # ``_update_model_info`` still covers the initial render and
        # subagent-only turns where the main agent never fires a usage
        # event.
        self._agent.event_bus.subscribe(
            ui_events.EventType.CACHE_METRICS_UPDATED, self._on_bus_cache_metrics
        )

        self._agent.start_executor(max_concurrency=self._max_concurrency)

        # Prime the display with any tasks restored from a previous session.
        checklist = self.query_one("#task-checklist", tasks_widget.TaskChecklistWidget)
        existing = self._agent.work_queue.all_tasks()
        if existing:
            checklist.notify_changed(existing)

    def _on_bus_task_updated(self, event: ui_events.Event) -> None:
        """Handle a task-updated event from the bus.

        Subscribers run on the UI thread because the bus is bound to the
        app's loop in :meth:`on_mount`, so widget access is safe.
        """
        if not self._agent:
            return

        checklist = self.query_one("#task-checklist", tasks_widget.TaskChecklistWidget)
        checklist.notify_changed(self._agent.work_queue.all_tasks())
        self._refresh_subagent_status_bar()

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
            if task_id.startswith(PUSH_CONFIRM_PREFIX):
                self._present_push_confirmation(task)
            elif task_id.startswith(TRIAGE_CONFIRM_PREFIX):
                self._present_triage_confirmation(task)
            elif task_id.startswith(IMPROVEMENT_CONFIRM_BASE):
                self._present_improvement_confirmation(task)
            elif task_id.startswith(RACE_CONFIRM_PREFIX):
                self._present_race_confirmation(task)
            elif task_id.startswith(BOOTSTRAP_CONFIRM_PREFIX):
                self._present_bootstrap_confirmation(task)
            else:
                self._present_design_questions(task)

    def _on_bus_memory_written(self, event: ui_events.Event) -> None:
        """Render an inline 'Wrote memory: …' system message in chat."""
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        payload = event.payload
        scope = payload.get("scope", "?")
        kind = payload.get("kind", "?")
        title = payload.get("title", "?")
        chat.add_system_message(f"Wrote {kind} memory: {title} ({scope})")

    def _on_bus_memory_recalled(self, event: ui_events.Event) -> None:
        """Render an inline 'Recalled memory: …' system message in chat."""
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        payload = event.payload
        scope = payload.get("scope", "?")
        title = payload.get("title", "?")
        chat.add_system_message(f"Recalled memory: {title} ({scope})")

    def _on_bus_tool_invoked(self, event: ui_events.Event) -> None:
        """Render an inline tool-invocation block in the chat (Phase 75)."""
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        payload = event.payload
        caption = payload.get("caption") or payload.get("tool_name", "?")
        success = bool(payload.get("success", False))
        duration_ms = payload.get("duration_ms")
        chat.add_tool_block(
            caption,
            success=success,
            duration_ms=duration_ms if isinstance(duration_ms, int) else None,
        )

    def _on_bus_status_bar(self, event: ui_events.Event) -> None:
        """Apply a STATUS_BAR_CHANGED event to the status bar reactives."""
        status_bar = self.query_one("#status-bar", statusbar_widget.StatusBar)
        payload = event.payload
        if "task_label" in payload:
            status_bar.task_label = payload["task_label"]
        if "cos_health" in payload:
            status_bar.cos_health = payload["cos_health"]
        if "test_summary" in payload:
            status_bar.test_summary = payload["test_summary"]
        if "watcher_status" in payload:
            status_bar.watcher_status = payload["watcher_status"]
        if "mode" in payload:
            # Phase 68.4: ``/plan`` and ``/build`` publish
            # ``mode=plan|build`` so the bar tints distinctly while
            # the read-only gate is active.
            status_bar.mode = payload["mode"]

    def _on_bus_cache_metrics(self, event: ui_events.Event) -> None:
        """Apply a CACHE_METRICS_UPDATED event to the modelbar (Phase 78.2).

        The 5-second polling timer already keeps the bar close to the
        agent's state; this subscription removes the up-to-5s lag so
        the cache-hit readout moves in lockstep with the Web badge.
        """
        from textual.css.query import NoMatches

        try:
            bar = self.query_one("#model-info", modelbar_widget.ModelInfoBar)
        except NoMatches:
            return
        payload = event.payload
        bar.cache_creation_tokens = int(payload.get("cache_creation_tokens", 0) or 0)
        bar.cache_read_tokens = int(payload.get("cache_read_tokens", 0) or 0)

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
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        chat.add_system_message(proposal.format_for_chat())

        # Push the interactive questions screen.
        from cantrip.tui.screens import questions as questions_screen

        self.push_screen(
            questions_screen.DesignQuestionsScreen(questions),
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
        chat = self.query_one("#chat", chat_widget.ChatWidget)
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

        chat = self.query_one("#chat", chat_widget.ChatWidget)
        if build_tasks:
            titles = "\n".join(f"- {t.title}" for t in build_tasks)
            chat.add_system_message(f"Build plan created:\n{titles}")
        else:
            chat.add_system_message("No build tasks generated — check the design output.")

    # -- Improvement confirmation flow ----------------------------------------

    def _offer_repo_bootstrap(self) -> None:
        """Offer to create a GitHub repo by queuing a CONFIRM task.

        The CONFIRM task surfaces in the task panel and — via the
        shared CONFIRM+BLOCKED routing in :meth:`_on_bus_task_status_changed`
        — shows a framed confirmation prompt rather than an inline
        system message that blurs with other chat output.
        """
        if self._bootstrap_offered or not self._agent:
            return
        if not self._agent.should_offer_bootstrap():
            return

        self._bootstrap_offered = True
        task = self._agent.build_repo_bootstrap_confirm_task()
        self._agent.work_queue.add_task(task)

    def _present_bootstrap_confirmation(self, task: AgentTask) -> None:
        """Show the repo-bootstrap CONFIRM prompt in chat.

        Mirrors :meth:`_present_triage_confirmation` — the task stays
        blocked, and the user's next message is matched against the
        approve / skip / ``name=… public org=… desc=…`` tokens by
        :meth:`_handle_bootstrap_response`.
        """
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        chat.add_system_message(f"**Repo bootstrap:**\n\n{task.description}")

    def _handle_bootstrap_response(self, message: str) -> bool:
        """Handle approve / skip / customised reply for the bootstrap CONFIRM.

        Returns ``True`` if the message was consumed.  The default
        repo name comes from the CONFIRM task's ID suffix; callers
        override it with ``name=foo`` inside the reply.
        """
        if not self._agent or not self._pending_confirm_id:
            return False
        confirm_id = self._pending_confirm_id
        if not confirm_id.startswith(BOOTSTRAP_CONFIRM_PREFIX):
            return False

        lower = message.strip().lower()
        chat = self.query_one("#chat", chat_widget.ChatWidget)

        if lower in ("skip", "no", "n", "dismiss"):
            self._pending_confirm_id = None
            self._agent.work_queue.set_done(confirm_id, "Skipped by user")
            chat.add_system_message("Repository creation skipped.")
            return True

        if not lower.startswith(("approve", "yes", "y", "ok", "public", "private")):
            # Unrecognised — pass through to the LLM.
            return False

        self._pending_confirm_id = None
        self._agent.work_queue.set_done(confirm_id, "Approved by user")

        # ``public`` anywhere in the reply flips visibility; otherwise private.
        private = "public" not in lower

        # Extract ``name=`` / ``org=`` / ``desc=`` from the reply.  The
        # suggested name is encoded in the task ID so a bare "approve"
        # (without ``name=``) picks up ``<workload>-operator``.
        default_name = confirm_id.removeprefix(BOOTSTRAP_CONFIRM_PREFIX)
        import re

        name_match = re.search(r"name=(\S+)", message)
        repo_name = name_match.group(1) if name_match else default_name

        org = ""
        org_match = re.search(r"org=(\S+)", message)
        if org_match:
            org = org_match.group(1)

        description = ""
        desc_match = re.search(r"desc=(.+?)(?:\s+(?:org|name)=|$)", message)
        if desc_match:
            description = desc_match.group(1).strip()

        chat.add_system_message(
            f"Creating {'private' if private else 'public'} repository **{repo_name}**..."
        )
        result = self._agent.handle_repo_bootstrap(
            repo_name,
            private=private,
            description=description,
            org=org,
        )
        chat.add_system_message(result)

        if self._agent.state.github_repo:
            self._update_header_subtitle()
            self._update_model_info()
        return True

    def _handle_pr_response(self, message: str) -> bool:
        """Handle pr/draft/skip response after a successful push.

        Returns ``True`` if the message was handled, ``False`` otherwise.
        """
        if not self._agent or not self._pending_pr_branch:
            return False

        lower = message.strip().lower()
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        branch = self._pending_pr_branch

        if lower in ("pr", "yes", "y", "ok", "draft"):
            draft = lower == "draft"
            self._pending_pr_branch = None
            result = self._agent.handle_pr_creation(branch, draft=draft)
            chat.add_system_message(result)
            # Trigger maintenance loop: offer to comment + re-triage.
            self._offer_maintenance_continuation(branch, result)
            return True

        if lower in ("skip", "no", "n"):
            self._pending_pr_branch = None
            chat.add_system_message("PR creation skipped.")
            # Still offer re-triage even if PR was skipped.
            self._offer_retriage()
            return True

        return False

    def _offer_maintenance_continuation(self, branch: str, pr_result: str) -> None:
        """After PR creation, offer to comment on the issue and re-triage."""
        if not self._agent:
            return

        import re

        # Extract issue number from branch name.
        m = re.search(r"issue-(\d+)", branch)
        issue_number = int(m.group(1)) if m else None

        # Extract PR URL from result.
        pr_url = ""
        url_match = re.search(r"(https://github\.com/\S+/pull/\d+)", pr_result)
        if url_match:
            pr_url = url_match.group(1)

        chat = self.query_one("#chat", chat_widget.ChatWidget)

        # Extract PR number from URL.
        pr_number: int | None = None
        pr_num_match = re.search(r"/pull/(\d+)", pr_url)
        if pr_num_match:
            pr_number = int(pr_num_match.group(1))

        if issue_number and pr_url:
            self._pending_maintenance = {
                "issue_number": issue_number,
                "pr_url": pr_url,
                "pr_number": pr_number,
                "branch": branch,
            }
            chat.add_system_message(
                f"Reply **comment** to post a note on issue #{issue_number}, "
                f"**review** to check for PR feedback, "
                f"**next** to check for more issues, or **done** to stop."
            )
        elif pr_number:
            self._pending_maintenance = {
                "pr_url": pr_url,
                "pr_number": pr_number,
                "branch": branch,
            }
            chat.add_system_message(
                "Reply **review** to check for PR feedback, "
                "**next** to check for more issues, or **done** to stop."
            )
        else:
            self._offer_retriage()

    def _offer_retriage(self) -> None:
        """Offer to check for more issues."""
        if not self._agent or not self._agent.state.github_repo:
            return
        # Check for upstream divergence first.
        warning = self._agent.check_upstream()
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        if warning:
            chat.add_system_message(warning)
        chat.add_system_message("Reply **next** to check for more issues, or **done** to stop.")
        self._pending_maintenance = {"retriage_only": True}

    def _handle_maintenance_response(self, message: str) -> bool:
        """Handle comment/next/done response in the maintenance loop.

        Returns ``True`` if the message was handled.
        """
        if not self._agent or not self._pending_maintenance:
            return False

        lower = message.strip().lower()
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        ctx = self._pending_maintenance

        if lower == "comment" and "issue_number" in ctx:
            result = self._agent.comment_on_issue(ctx["issue_number"], ctx.get("pr_url", ""))
            chat.add_system_message(result)
            # After commenting, offer re-triage or review.
            self._pending_maintenance = {k: v for k, v in ctx.items() if k != "issue_number"}
            if "pr_number" in ctx:
                chat.add_system_message(
                    "Reply **review** to check for PR feedback, "
                    "**next** for more issues, or **done** to stop."
                )
            else:
                self._pending_maintenance = {"retriage_only": True}
                chat.add_system_message(
                    "Reply **next** to check for more issues, or **done** to stop."
                )
            return True

        if lower == "review" and "pr_number" in ctx:
            pr_number = ctx["pr_number"]
            branch = ctx.get("branch", "")
            feedback = self._agent.check_pr_feedback(pr_number)
            if feedback is None:
                chat.add_system_message(f"Could not fetch feedback for PR #{pr_number}.")
            elif feedback.is_approved:
                chat.add_system_message(f"PR #{pr_number} is **approved**. No changes needed.")
                self._pending_maintenance = {"retriage_only": True}
            elif feedback.needs_changes and feedback.comments:
                chat.add_system_message(feedback.format_for_chat())
                chat.add_system_message(
                    "Reply **fix** to address the review feedback, or **skip** to handle it manually."
                )
                self._pending_maintenance = {
                    "awaiting_fix": True,
                    "pr_number": pr_number,
                    "branch": branch,
                    "feedback": feedback,
                }
            elif feedback.comments:
                chat.add_system_message(feedback.format_for_chat())
                self._pending_maintenance = {"retriage_only": True}
            else:
                chat.add_system_message(f"PR #{pr_number} has no review comments yet.")
                self._pending_maintenance = {"retriage_only": True}
            return True

        if lower == "fix" and ctx.get("awaiting_fix"):
            feedback = ctx.get("feedback")
            branch = ctx.get("branch", "")
            if feedback and self._agent:
                fix_tasks = self._agent.create_pr_fix_tasks(feedback, branch)
                if fix_tasks:
                    titles = "\n".join(f"- {t.title}" for t in fix_tasks)
                    chat.add_system_message(f"Addressing review feedback:\n{titles}")
                else:
                    chat.add_system_message("Could not create fix tasks.")
            self._pending_maintenance = None
            return True

        if lower in ("next", "more"):
            self._pending_maintenance = None
            started = self._agent.retriage_issues()
            if started:
                chat.add_system_message("Checking for new issues...")
            else:
                chat.add_system_message("No new issues to check.")
            return True

        if lower in ("done", "stop", "skip", "no", "n"):
            self._pending_maintenance = None
            chat.add_system_message("Maintenance loop stopped.")
            return True

        return False

    def _handle_push_response(self, message: str) -> bool:
        """Handle approve/skip response for a push-confirm CONFIRM task.

        Returns ``True`` if the message was handled, ``False`` otherwise.
        """
        if not self._agent or not self._pending_confirm_id:
            return False

        lower = message.strip().lower()
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        confirm_id = self._pending_confirm_id

        if lower in ("approve", "yes", "y", "push", "ok"):
            self._pending_confirm_id = None
            self._agent.work_queue.set_done(confirm_id, "Push approved by user")
            result = self._agent.handle_push_confirmation(confirm_id, approved=True)
            chat.add_system_message(result)
            # If push succeeded, offer PR creation.
            if "Reply **pr**" in result:
                branch = confirm_id.removeprefix(PUSH_CONFIRM_PREFIX)
                self._pending_pr_branch = branch
            return True

        if lower in ("skip", "no", "n", "dismiss", "local"):
            self._pending_confirm_id = None
            self._agent.work_queue.set_done(confirm_id, "Push declined — branch left local")
            result = self._agent.handle_push_confirmation(confirm_id, approved=False)
            chat.add_system_message(result)
            return True

        return False

    def _present_push_confirmation(self, task: AgentTask) -> None:
        """Show a push confirmation prompt in chat.

        Called when a push-branch-* CONFIRM task becomes blocked.
        """
        if not self._agent:
            return

        chat = self.query_one("#chat", chat_widget.ChatWidget)
        chat.add_system_message(
            f"{task.description}\n\nReply **push** to push, or **skip** to leave the branch local."
        )

    def _present_race_confirmation(self, task: AgentTask) -> None:
        """Show a race-cost confirmation prompt in chat.

        Called when a ``race-confirm-*`` CONFIRM task becomes blocked.
        """
        if not self._agent:
            return
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        chat.add_system_message(task.description)

    def _handle_race_response(self, message: str) -> bool:
        """Handle approve/decline response for a race-cost CONFIRM task.

        Returns ``True`` if the message was handled (approved or declined),
        ``False`` if it should be passed through to the LLM.  Yes / no and
        common synonyms are accepted; anything else falls through so the
        user can ask clarifying questions.
        """
        if not self._agent or not self._pending_confirm_id:
            return False

        confirm_id = self._pending_confirm_id
        if not confirm_id.startswith(RACE_CONFIRM_PREFIX):
            return False

        lower = message.strip().lower()
        chat = self.query_one("#chat", chat_widget.ChatWidget)

        if lower in ("yes", "y", "approve", "race", "ok"):
            self._pending_confirm_id = None
            result = self._agent.handle_race_confirmation(confirm_id, approved=True)
            chat.add_system_message(result)
            return True

        if lower in ("no", "n", "decline", "single", "skip"):
            self._pending_confirm_id = None
            result = self._agent.handle_race_confirmation(confirm_id, approved=False)
            chat.add_system_message(result)
            return True

        return False

    def _handle_triage_response(self, message: str) -> bool:
        """Handle approve/skip response for a triage CONFIRM task.

        Returns ``True`` if the message was handled, ``False`` if it should
        be passed to the LLM instead.
        """
        if not self._agent or not self._pending_confirm_id:
            return False

        lower = message.strip().lower()
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        confirm_id = self._pending_confirm_id

        if lower in ("approve", "yes", "y", "ok"):
            self._pending_confirm_id = None
            self._agent.work_queue.set_done(confirm_id, "Approved by user")
            work_tasks = self._agent.handle_triage_confirmation(confirm_id)
            if work_tasks:
                titles = "\n".join(f"- {t.title}" for t in work_tasks)
                chat.add_system_message(f"Working on the issue:\n{titles}")
            else:
                chat.add_system_message("Could not generate work tasks for this issue.")
            return True

        if lower in ("skip", "no", "n", "dismiss"):
            self._pending_confirm_id = None
            self._agent.work_queue.set_done(confirm_id, "Skipped by user")
            chat.add_system_message("Issue skipped.")
            return True

        # Unrecognised response — don't consume it.
        return False

    def _present_triage_confirmation(self, task: AgentTask) -> None:
        """Show a GitHub issue summary in chat for user approval.

        Called when a triage-issue-* CONFIRM task becomes blocked.
        Shows the issue details and asks the user to approve or skip.
        """
        if not self._agent:
            return

        chat = self.query_one("#chat", chat_widget.ChatWidget)
        chat.add_system_message(
            f"**Issue triage:**\n\n{task.description}\n\n"
            f"Reply **approve** to work on this issue, or **skip** to dismiss."
        )
        # The confirm task stays blocked; the user's next message in
        # _on_agent_response_done or the chat handler will match
        # "approve"/"skip" and resolve the pending confirm.

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

        chat = self.query_one("#chat", chat_widget.ChatWidget)
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

        chat = self.query_one("#chat", chat_widget.ChatWidget)
        if fix_tasks:
            titles = "\n".join(f"- {t.title}" for t in fix_tasks)
            chat.add_system_message(f"Improvement plan created:\n{titles}")
        else:
            chat.add_system_message(
                "No improvement tasks generated — the charm may already be up to standard."
            )

    # -- Watcher integration --------------------------------------------------

    def _subscribe_watcher_events(self) -> None:
        """Subscribe to watcher events so the panes update even if the
        watcher starts later (e.g. once the agent provisions a model).
        """
        if not self._agent:
            return
        self._agent.event_bus.subscribe(
            ui_events.EventType.WATCHER_EVENT, self._on_bus_watcher_event
        )
        self._agent.event_bus.subscribe(
            ui_events.EventType.JUJU_STATUS_CHANGED, self._on_bus_juju_status
        )

    def _start_watcher(self) -> None:
        """Try to start the event watcher.

        If no Juju model is available yet, schedule a periodic retry so
        the watcher starts as soon as the agent provisions one.  Events
        are automatically routed to the task queue by the agent's
        ``start_watcher`` method.
        """
        if not self._agent or self._agent.watcher_running:
            return
        started = self._agent.start_watcher()
        if started:
            self._update_status_bar_watcher()
            if self._watcher_retry_timer is not None:
                self._watcher_retry_timer.stop()
                self._watcher_retry_timer = None
        elif self._watcher_retry_timer is None:
            self._watcher_retry_timer = self.set_interval(5.0, self._start_watcher)

    async def _stop_watcher(self) -> None:
        """Stop the event watcher."""
        if not self._agent:
            return
        await self._agent.stop_watcher()
        self._update_status_bar_watcher()

    def _refresh_model_panes(self) -> None:
        """Push the watcher's latest status snapshots into the model widget."""
        if not (self._agent and self._agent._watcher):
            return
        status_widget = self.query_one("#juju-status", status_widgets.MultiModelStatusWidget)
        latest = self._agent._watcher.latest_status
        if latest is not None:
            status_widget.dev_status = latest
        latest_cos = self._agent._watcher.latest_cos_status
        if latest_cos is not None:
            status_widget.cos_status = latest_cos

    def _on_bus_watcher_event(self, event: ui_events.Event) -> None:
        """Handle a watcher event from the bus."""
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        chat.add_system_message(f"[Watcher] {event.payload.get('summary', '')}")
        self._refresh_model_panes()

    def _on_bus_juju_status(self, _event: ui_events.Event) -> None:
        """Handle a periodic status-poll tick from the watcher."""
        self._refresh_model_panes()

    def _update_status_bar_watcher(self) -> None:
        """Update the status bar watcher indicator."""
        status_bar = self.query_one("#status-bar", statusbar_widget.StatusBar)
        if self._agent and self._agent.watcher_running:
            status_bar.watcher_status = "👁 Watching"
        else:
            status_bar.watcher_status = ""

    def _refresh_subagent_status_bar(self) -> None:
        """Mirror the currently-active subagent phase into the status bar.

        Picks the first ACTIVE task with a live ``subagent_phase`` so
        research/build activity is visible without having to expand the
        task pane.  Cleared when no subagent is running.
        """
        if not self._agent:
            return
        status_bar = self.query_one("#status-bar", statusbar_widget.StatusBar)
        for task in self._agent.work_queue.all_tasks():
            if task.status == TaskStatus.ACTIVE and task.subagent_phase:
                status_bar.subagent_label = f"⟳ {task.title} · {task.subagent_phase}"
                return
        status_bar.subagent_label = ""

    def action_toggle_watcher(self) -> None:
        """Toggle the event watcher on or off."""
        if not self._agent:
            return
        if self._agent.watcher_running:
            self.run_worker(self._stop_watcher(), name="stop_watcher", exclusive=False)
            chat = self.query_one("#chat", chat_widget.ChatWidget)
            chat.add_system_message("Watcher stopped.")
        else:
            self._start_watcher()

    # -- Chat -----------------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        """Drive the slash-suggestion popup from chat input changes."""
        from textual.css.query import NoMatches

        if event.input.id != "chat-input":
            return
        try:
            suggestions = self.query_one("#slash-suggestions", chat_widget.SlashCommandSuggestions)
        except NoMatches:
            return
        suggestions.update_from_value(event.value)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle chat input submission."""
        from textual.css.query import NoMatches

        message = event.value.strip()
        if not message:
            return

        event.input.value = ""
        with contextlib.suppress(NoMatches):
            self.query_one("#slash-suggestions", chat_widget.SlashCommandSuggestions).hide()

        chat = self.query_one("#chat", chat_widget.ChatWidget)
        chat.add_user_message(message)

        if not self._agent:
            chat.add_system_message("No LLM provider configured. Check your API key.")
            return

        # Handle pending confirmations before sending to the LLM.
        if self._pending_maintenance:
            handled = self._handle_maintenance_response(message)
            if handled:
                return
        if self._pending_pr_branch:
            handled = self._handle_pr_response(message)
            if handled:
                return
        if self._pending_confirm_id and self._pending_confirm_id.startswith(PUSH_CONFIRM_PREFIX):
            handled = self._handle_push_response(message)
            if handled:
                return
        if self._pending_confirm_id and self._pending_confirm_id.startswith(TRIAGE_CONFIRM_PREFIX):
            handled = self._handle_triage_response(message)
            if handled:
                return
        if self._pending_confirm_id and self._pending_confirm_id.startswith(RACE_CONFIRM_PREFIX):
            handled = self._handle_race_response(message)
            if handled:
                return
        if self._pending_confirm_id and self._pending_confirm_id.startswith(
            BOOTSTRAP_CONFIRM_PREFIX
        ):
            handled = self._handle_bootstrap_response(message)
            if handled:
                return

        if message.split(" ", 1)[0] == "/feelings":
            self._handle_feelings_command(message, chat)
            return

        if message.split(" ", 1)[0] == "/tree":
            self._handle_tree_command(chat)
            return

        # Blind A/B arena is pending — capture A/B/tie/skip picks before
        # anything else so a one-letter reply doesn't get forwarded to
        # the LLM or a slash dispatcher.
        if self._agent and self._agent.active_arena is not None:
            reveal = self._agent.handle_arena_pick(message)
            if reveal is not None:
                chat.add_system_message(reveal)
                return

        if self._handle_shared_slash_commands(message, chat):
            return

        # Disable input and show thinking indicator while processing.
        input_widget = self.query_one("#chat-input", Input)
        input_widget.disabled = True
        input_widget.placeholder = "Waiting for response..."
        chat.show_thinking()
        self.query_one(
            "#status-bar", statusbar_widget.StatusBar
        ).task_label = f"⟳ {flavour.pick_activity_label()}..."
        # Surface a transient "Planning tasks…" row so the task pane
        # isn't just the preflight group while the agent decides what
        # to do.  Cleared once real tasks appear or the turn finishes.
        checklist = self.query_one("#task-checklist", tasks_widget.TaskChecklistWidget)
        checklist.set_agent_activity("Planning tasks…")

        # Run agent processing in a background worker. ``exit_on_error=False``
        # keeps the Textual app alive when the provider raises (e.g. a 429
        # rate-limit error) — the ERROR branch of ``_on_agent_response_done``
        # renders a chat message instead of the app exiting with a traceback.
        self._streaming_widget = None
        self.run_worker(
            self._process_agent_message(message),
            name="agent_response",
            exclusive=True,
            exit_on_error=False,
        )

    async def _process_agent_message(self, message: str) -> None:
        """Stream a message through the agent, appending chunks as they arrive.

        The first non-empty chunk replaces the flavoured activity
        indicator (``⟳ Conjuring...`` etc.) with a new assistant
        message; subsequent chunks are appended to
        that same widget.  The worker returns ``None`` — success is
        observed via the chat widget, not the worker result.
        """
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        status_bar = self.query_one("#status-bar", statusbar_widget.StatusBar)

        async for chunk in self._agent.process_message_streaming(message):
            if not chunk:
                continue
            if self._streaming_widget is None:
                chat.hide_thinking()
                self._streaming_widget = chat.add_assistant_message("")
                status_bar.task_label = "⟳ Streaming..."
            chat.append_streaming_chunk(self._streaming_widget, chunk)

        # Reasoning (Claude extended thinking, Kimi K2 ``reasoning_content``)
        # is accumulated alongside the text stream and attached after
        # the stream completes so the user can see when their turn
        # spent reasoning tokens rather than answer tokens.
        reasoning = self._trailing_reasoning()
        if reasoning:
            if self._streaming_widget is None:
                chat.hide_thinking()
                self._streaming_widget = chat.add_assistant_message("", reasoning=reasoning)
            else:
                chat.set_reasoning(self._streaming_widget, reasoning)

    def _trailing_reasoning(self) -> str:
        """Return the reasoning text on the most recent assistant message."""
        for msg in reversed(self._agent.state.messages):
            if msg.role == Role.ASSISTANT:
                return str(msg.metadata.get("_thinking_content", ""))
        return ""

    def _handle_tree_command(self, chat: chat_widget.ChatWidget) -> None:
        """Phase 67.1: open the tree picker and fork from the chosen turn.

        The shared ``handle_tree`` produces the markdown text used by
        CLI / Web; the TUI overrides with an interactive modal so the
        user can pick a node directly.  The selection round-trips
        through ``handle_branch`` so the activate / rebuild logic
        stays in one place.
        """
        from cantrip.tui.screens.tree import TreePickerScreen

        if self._agent is None or self._agent.store is None:
            chat.add_system_message(
                "_No session store available — `/tree` needs a saved session._"
            )
            return
        store = self._agent.store
        messages = store.load_messages()
        if not messages:
            chat.add_system_message(
                "_No turns yet — `/tree` will populate after the first message._"
            )
            return
        active_ids = {m["id"] for m in store.load_active_branch()}
        nodes = slash_commands.build_tree_nodes(messages, active_ids)

        def _on_picked(turn_id: int | None) -> None:
            if turn_id is None:
                return
            text = slash_commands.handle_branch(self._agent, str(turn_id))
            chat.add_system_message(text)

        self.push_screen(TreePickerScreen(nodes), _on_picked)

    def _handle_feelings_command(self, message: str, chat: chat_widget.ChatWidget) -> None:
        """Dispatch a parliament run from a ``/feelings [emotions...]`` message.

        Experimental: runs the enabled emotion subagents in parallel and
        posts a markdown report back to the chat. Does not touch the
        main agent's conversation state.
        """
        tokens = message.split()[1:]
        unknown = [t for t in tokens if t.lower() not in emotions.available_emotions()]
        if unknown:
            known = ", ".join(emotions.available_emotions())
            chat.add_system_message(
                f"Unknown emotion(s): {', '.join(unknown)}. Known emotions: {known}."
            )
            return

        enabled = [t.lower() for t in tokens] or list(emotions.DEFAULT_ENABLED)
        chat.add_system_message(f"Convening the inner parliament: {', '.join(enabled)}...")
        self.run_worker(
            self._run_feelings(enabled),
            name="feelings",
            exclusive=False,
        )

    async def _run_feelings(self, enabled: list[str]) -> str:
        """Run the parliament and return the formatted markdown report."""
        result = await self._agent.run_parliament(enabled)
        return emotions.format_report(result, enabled=enabled)

    def _handle_shared_slash_commands(self, message: str, chat: chat_widget.ChatWidget) -> bool:
        """Dispatch the shared slash commands via :mod:`slash_commands`.

        Returns ``True`` when the message was handled (so the caller
        does not also send it to the LLM).  Async follow-ups (e.g.
        ``/mcp marketplace``) run in a Textual worker so the UI stays
        responsive; the result lands as a system message via
        :meth:`_on_mcp_marketplace_done`.
        """
        if not self._agent:
            return False
        result = slash_commands.dispatch(self._agent, message)
        if result is None:
            return False
        chat.add_system_message(result.text, markdown=result.markdown)
        if result.clipboard_text is not None:
            # Textual's App.copy_to_clipboard owns OSC 52 negotiation
            # against the host terminal -- preferred over writing the
            # escape ourselves because Textual already understands the
            # tmux passthrough wrap.
            self.copy_to_clipboard(result.clipboard_text)
        if result.followup is not None:
            self.run_worker(result.followup, name="mcp_marketplace", exclusive=False)
        if result.quit:
            # Schedule the exit after the current tick so the goodbye
            # message has a chance to render before the app tears down.
            self.call_after_refresh(self.exit)
        return True

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker state changes to update the UI."""
        if event.worker.name == "agent_response":
            self._on_agent_response_done(event)
        elif event.worker.name == "feelings":
            self._on_feelings_done(event)
        elif event.worker.name == "mcp_marketplace":
            self._on_mcp_marketplace_done(event)
        # Preflight workers don't need special handling on completion.

    def _on_mcp_marketplace_done(self, event: Worker.StateChanged) -> None:
        """Render the marketplace listing when the worker finishes."""
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            return
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        if event.state == WorkerState.SUCCESS:
            output = event.worker.result
            if output:
                chat.add_system_message(str(output))
        elif event.state == WorkerState.CANCELLED:
            chat.add_system_message("Marketplace lookup cancelled.")
        elif event.state == WorkerState.ERROR:
            chat.add_system_message(f"Marketplace lookup failed: {event.worker.error}")

    def _on_feelings_done(self, event: Worker.StateChanged) -> None:
        """Post the parliament report (or an error) when the feelings worker finishes."""
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            return
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        if event.state == WorkerState.SUCCESS:
            report = event.worker.result
            if report:
                chat.add_system_message(str(report), markdown=True)
        elif event.state == WorkerState.CANCELLED:
            chat.add_system_message("Parliament adjourned (cancelled).")
        elif event.state == WorkerState.ERROR:
            chat.add_system_message(f"Parliament failed: {event.worker.error}")

    def _on_agent_response_done(self, event: Worker.StateChanged) -> None:
        """Handle agent response worker completion."""
        # Only act on terminal states — not PENDING or RUNNING.
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            return

        chat = self.query_one("#chat", chat_widget.ChatWidget)
        input_widget = self.query_one("#chat-input", Input)

        # Remove the thinking indicator and reset status bar.  The
        # indicator may still be up if the stream yielded nothing.
        chat.hide_thinking()
        self.query_one("#status-bar", statusbar_widget.StatusBar).task_label = ""
        self.query_one("#task-checklist", tasks_widget.TaskChecklistWidget).set_agent_activity(
            None
        )
        streamed_content = self._streaming_widget.message.content if self._streaming_widget else ""
        self._streaming_widget = None

        if event.state == WorkerState.SUCCESS:
            # If the model produced no text at all (unusual, but possible
            # when a turn ends on a tool error), show a placeholder so the
            # user sees that the turn completed.
            if not streamed_content:
                chat.add_assistant_message("(no response)")
            input_widget.disabled = False
            input_widget.placeholder = "Type your message..."
            input_widget.focus()
            # Persist session state and check for new charm type.
            self._agent.save_state()
            self._start_bootstrap()
            self._update_header_subtitle()
            self._update_model_info()
            self._update_test_summary()
            # Offer repo bootstrap if conditions are met.
            if not self._bootstrap_offered and self._agent.state.charm_name:
                self._offer_repo_bootstrap()

        elif event.state == WorkerState.CANCELLED:
            chat.add_system_message("Operation cancelled.")
            input_widget.disabled = False
            input_widget.placeholder = "Type your message..."
            input_widget.focus()

        elif event.state == WorkerState.ERROR:
            error = event.worker.error
            if isinstance(error, ProviderRateLimitError | ProviderOverloadedError):
                chat.add_system_message(f"Provider unavailable: {error}")
            else:
                chat.add_system_message(f"Error: {error}")
            input_widget.disabled = False
            input_widget.placeholder = "Type your message..."
            input_widget.focus()

    def _update_test_summary(self) -> None:
        """Update the status bar test summary from agent state."""
        if not self._agent or not self._agent.state.test_results:
            return
        status_bar = self.query_one("#status-bar", statusbar_widget.StatusBar)
        status_bar.test_summary = self._agent.state.test_results.format_summary()

    def action_help(self) -> None:
        """Show help screen."""
        from cantrip.tui.screens import help as help_screen

        self.push_screen(help_screen.HelpScreen())

    def action_debug(self) -> None:
        """Show trace/debug screen."""
        from cantrip.agent import cos_endpoints
        from cantrip.tui.screens import traces as traces_screen

        cos_model = self._agent.state.cos_model if self._agent else None
        status = (
            self._agent._watcher.latest_cos_status
            if self._agent and self._agent._watcher
            else None
        )
        endpoints = cos_endpoints.derive_endpoints(status)
        self.push_screen(traces_screen.TraceScreen(cos_model=cos_model, endpoints=endpoints))

    def on_relation_line_selected(self, event: status_widgets.RelationLine.Selected) -> None:
        """Open the relation detail screen when a relation line is clicked."""
        from cantrip.tui.screens import relation as relation_screen

        dev_model = self._agent.state.dev_model if self._agent else None
        self.push_screen(
            relation_screen.RelationDetailScreen(
                unit_name=event.unit_name,
                endpoint=event.endpoint,
                related_app=event.related_app,
                model=dev_model,
            )
        )

    def on_juju_status_widget_status_available(self) -> None:
        """Show the status panel when status data first arrives."""
        self.query_one("#right-panel").display = True

    def action_toggle_status(self) -> None:
        """Toggle status panel visibility."""
        right_panel = self.query_one("#right-panel")
        right_panel.display = not right_panel.display

    def action_toggle_files(self) -> None:
        """Toggle charm file tree visibility."""
        tree = self.query_one("#charm-files", filetree_widget.CharmTreeWidget)
        tree.display = not tree.display

    def action_logs(self) -> None:
        """Show log viewer screen."""
        from cantrip.tui.screens import logs as logs_screen

        dev_model = self._agent.state.dev_model if self._agent else None
        cos_model = self._agent.state.cos_model if self._agent else None
        self.push_screen(logs_screen.LogScreen(dev_model=dev_model, cos_model=cos_model))

    def action_graph(self) -> None:
        """Show integration graph screen."""
        from cantrip.tui.screens import graph as graph_screen

        status_widget = self.query_one("#juju-status", status_widgets.MultiModelStatusWidget)
        current_app = self._agent.state.charm_name if self._agent else None
        dev_model = self._agent.state.dev_model if self._agent else None
        self.push_screen(
            graph_screen.GraphScreen(
                status=status_widget.dev_status,
                current_app=current_app,
                model=dev_model,
            )
        )

    def action_transcript(self) -> None:
        """Show session transcript screen."""
        import pathlib

        from cantrip.tui.screens import transcript as transcript_screen

        db_path: pathlib.Path | None = None
        if self._agent and self._agent.state.charm_path:
            candidate = self._agent.state.charm_path / ".cantrip"
            if candidate.exists():
                db_path = candidate
        self.push_screen(transcript_screen.TranscriptScreen(db_path=db_path))

    async def action_quit(self) -> None:
        """Stop background services and quit."""
        if self._agent:
            if self._agent.executor_running:
                await self._agent.stop_executor()
            if self._agent.watcher_running:
                await self._agent.stop_watcher()
            if self._agent.issue_triage_running:
                await self._agent.stop_issue_triage()
        self.exit()

    def action_clear_chat(self) -> None:
        """Clear chat history."""
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        chat.clear()

    def action_search_chat(self) -> None:
        """Open the chat search bar."""
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        chat.open_search()

    def on_chat_widget_search_closed(self, event: chat_widget.ChatWidget.SearchClosed) -> None:
        """Return focus to the chat input when the search bar closes."""
        from textual.css.query import NoMatches

        event.stop()
        with contextlib.suppress(NoMatches):
            self.query_one("#chat-input", Input).focus()

    def action_cancel_agent(self) -> None:
        """Cancel the running agent response worker."""
        for worker in self.workers:
            if worker.name == "agent_response" and worker.is_running:
                worker.cancel()
                self.query_one(
                    "#status-bar", statusbar_widget.StatusBar
                ).task_label = "⏹ Cancelling..."
                return
