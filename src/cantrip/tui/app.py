"""Main Cantrip TUI application."""

import asyncio
import contextlib
import datetime
import logging
import pathlib
import sqlite3
import traceback

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Input
from textual.worker import Worker, WorkerState

from cantrip import diagnostics, notifications, update
from cantrip.agent import emotions
from cantrip.agent.commands import session as session_commands
from cantrip.agent.commands import slash as slash_commands
from cantrip.agent.context import context_providers
from cantrip.agent.core import CantripAgent
from cantrip.agent.git import git_branch
from cantrip.agent.queue import TaskCategory, TaskStatus
from cantrip.agent.runtime.preflight import DEFAULT_PRESET, CheckStatus, PreflightEvent
from cantrip.hooks import HookRunner
from cantrip.llm import LLMProvider, create_provider, pricing, resolve_light_provider
from cantrip.llm.base import ProviderError, ProviderOverloadedError, ProviderRateLimitError, Role
from cantrip.tui import confirmations
from cantrip.tui.actions import chat as chat_actions
from cantrip.tui.actions import screens as screens_actions
from cantrip.tui.actions import status as status_actions
from cantrip.tui.actions import watcher as watcher_actions
from cantrip.tui.widgets import chat as chat_widget
from cantrip.tui.widgets import filetree as filetree_widget
from cantrip.tui.widgets import header as header_widget
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


log = logging.getLogger(__name__)


class CantripApp(App):
    """Cantrip TUI application.

    Phase 108.8: dropped Textual's stock ``Header``; the slim
    :class:`cantrip.tui.widgets.header.CantripHeader` carries
    brand + model + path + branch instead.  ``TITLE`` /
    ``sub_title`` are no longer wired to a visible surface.
    """

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
        charm_path: pathlib.Path | None = None,
        light_model: str | None = None,
        max_concurrency: int | None = None,
        snap_name: str = "gemma3",
        light_snap_name: str | None = None,
        light_provider_name: str | None = None,
        improve_path: pathlib.Path | None = None,
        theme_name: str | None = None,
        base_url: str | None = None,
        max_iterations: int | None = None,
        max_tokens: int | None = None,
        objective: str | None = None,
        no_snapshots: bool = False,
        yolo: bool = False,
        no_auto_lint: bool = False,
        architect: bool = False,
        editor_provider: str | None = None,
        editor_model: str | None = None,
        no_auto_commit: bool = False,
        embed_provider: str | None = None,
        embed_model: str | None = None,
        rerank_provider: str | None = None,
        rerank_model: str | None = None,
        short_session: str | None = None,
    ):
        """Initialise the app."""
        super().__init__()
        self.provider_name = provider
        self.model_name = model
        self.charm_path = charm_path or pathlib.Path.cwd()
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
        self._objective = objective
        self._no_snapshots = no_snapshots
        self._yolo = yolo
        self._no_auto_lint = no_auto_lint
        self._architect = architect
        self._editor_provider = editor_provider
        self._editor_model = editor_model
        self._no_auto_commit = no_auto_commit
        self._embed_provider = embed_provider
        self._embed_model = embed_model
        self._rerank_provider = rerank_provider
        self._rerank_model = rerank_model
        self._short_session = short_session
        self._agent: CantripAgent | None = None
        self._prepare_group_idx: int | None = None
        self._bootstrap_group_idx: int | None = None
        self._bootstrap_started = False
        self._watcher_retry_timer: object | None = None
        self._session_start = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S")
        self._bootstrap_offered: bool = False
        # All confirmation-flow state and present/handle routing lives on the
        # coordinator; the app keeps property bridges (below) so existing call
        # sites and tests still reach ``self._pending_*`` by name.
        self._confirmations = confirmations.ConfirmationCoordinator(self)
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

    # Bridges to the confirmation coordinator's state.  These let call sites
    # and tests read or set ``app._pending_*`` unchanged while the values
    # actually live on ``self._confirmations``.

    @property
    def _pending_confirm_id(self) -> str | None:
        return self._confirmations.pending_confirm_id

    @_pending_confirm_id.setter
    def _pending_confirm_id(self, value: str | None) -> None:
        self._confirmations.pending_confirm_id = value

    @property
    def _pending_pr_branch(self) -> str | None:
        return self._confirmations.pending_pr_branch

    @_pending_pr_branch.setter
    def _pending_pr_branch(self, value: str | None) -> None:
        self._confirmations.pending_pr_branch = value

    @property
    def _pending_maintenance(self) -> dict | None:
        return self._confirmations.pending_maintenance

    @_pending_maintenance.setter
    def _pending_maintenance(self, value: dict | None) -> None:
        self._confirmations.pending_maintenance = value

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
        yield header_widget.CantripHeader(id="cantrip-header")
        yield Horizontal(
            Vertical(
                modelbar_widget.ModelInfoBar(id="model-info"),
                chat_widget.ChatWidget(id="chat"),
                chat_widget.SlashCommandSuggestions(
                    self._build_command_catalogue(),
                    id="slash-suggestions",
                ),
                chat_widget.MentionSuggestions(
                    id="mention-suggestions",
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
        chat_input.bind_mentions(
            self.query_one("#mention-suggestions", chat_widget.MentionSuggestions)
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
            # Phase 72.2: seed the ``@``-mention popup catalogue from
            # the agent's registry so Tab-complete sees both baseline
            # and any third-party providers registered at startup.
            mentions = self.query_one("#mention-suggestions", chat_widget.MentionSuggestions)
            mentions.update_catalogue(self._agent.context_providers.catalogue())
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

            # Phase 72.3: build embed/rerank role router from CLI / env.
            from cantrip.llm.roles import build_role_router

            role_router = build_role_router(
                embed_provider=self._embed_provider,
                embed_model=self._embed_model,
                rerank_provider=self._rerank_provider,
                rerank_model=self._rerank_model,
            )

            self._agent = CantripAgent(
                provider=llm_provider,
                charm_path=self.charm_path,
                light_provider=light_provider,
                hook_runner=HookRunner.from_disk(repo_root=self.charm_path),
                role_router=role_router,
                short_session=self._short_session,
            )

            # Phase 55.3: stamp the per-goal budget from CLI flags + env vars.
            from cantrip.agent.runtime.goal_budget import from_cli_args

            self._agent.state.goal_budget = from_cli_args(
                max_iterations=self._max_iterations,
                max_tokens=self._max_tokens,
            )

            # Phase 99.3: stamp the user-prose objective from the CLI flag.
            if self._objective is not None and self._objective.strip():
                self._agent.state.objective = self._objective.strip()

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

            # Phase 71.3: auto-commit-per-turn opt-out.
            if self._no_auto_commit:
                self._agent.state.git_auto_commit = False

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
        """Push the latest brand / model / path / branch into the header.

        Phase 108.8: the legacy implementation built a long
        ``[dev:k8s] [cos:k8s] [gh:repo] [light:…] [F1 Help]``
        subtitle; the new :class:`CantripHeader` carries only the
        four signals that *change with what the user is doing*
        (model, path, branch).  Juju model state is already in the
        right-panel Juju status pane, F1 hints are on the welcome
        body and the bottom binding row, and the subtitle is no
        longer rendered to any visible surface — so this method
        is now a state-push into the custom header widget rather
        than a string assemble for ``self.sub_title``.

        The method name stays for the existing call sites.
        """
        from textual.css.query import NoMatches

        try:
            header = self.query_one("#cantrip-header", header_widget.CantripHeader)
        except NoMatches:
            return

        model_label = ""
        if self._agent and getattr(self._agent, "provider", None) is not None:
            provider = self._agent.provider
            model_name = getattr(provider, "model_name", "") or ""
            provider_name = getattr(provider, "name", "") or ""
            if model_name:
                model_label = f"{provider_name}/{model_name}" if provider_name else model_name
        header.model_name = model_label

        header.charm_path = self.charm_path

        branch = ""
        if self.charm_path is not None:
            with contextlib.suppress(OSError):
                branch = git_branch.current_branch(str(self.charm_path)) or ""
        header.git_branch = branch

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
        status_actions.toggle_model_info(self)

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
        # Phase 82: pre-call "running now" block.  Carries the same
        # tool_call_id as the matching TOOL_INVOKED so the chat widget
        # can update the same line in place when the tool returns —
        # one block per tool call, not two.
        self._agent.event_bus.subscribe(
            ui_events.EventType.TOOL_INVOKED_PENDING,
            self._on_bus_tool_invoked_pending,
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
        # Phase 73.2 — MCP Apps fallback.  The TUI cannot host the
        # sandboxed iframe the Web UI uses, so render a one-line
        # marker plus any text fallback the server attached so the
        # user knows an app was returned and can switch to the Web
        # UI if they want to interact with it.
        self._agent.event_bus.subscribe(
            ui_events.EventType.MCP_APP_RENDER, self._on_bus_mcp_app_render
        )

        self._agent.start_executor(max_concurrency=self._max_concurrency)

        # Prime the display with any tasks restored from a previous session.
        checklist = self.query_one("#task-checklist", tasks_widget.TaskChecklistWidget)
        existing = self._agent.work_queue.all_tasks()
        if existing:
            checklist.notify_changed(existing)
        # Phase 99.4: prime the lifecycle badge from restored state so a
        # session resumed mid-block doesn't render as ``running`` until
        # the first task event arrives.
        self._refresh_lifecycle_badge()
        # Phase 104: prime the [short-session] chip so it shows from the
        # start when a tight-context provider is in play.
        from textual.css.query import NoMatches

        with contextlib.suppress(NoMatches):
            status_bar = self.query_one("#status-bar", statusbar_widget.StatusBar)
            status_bar.short_session = (
                "[short-session]" if self._agent.context_manager.short_session_mode else ""
            )
            # Phase 110: prime the curated-tool-phase chip (quiet unless
            # the provider's tool slice is actually being trimmed).
            status_bar.tool_phase = self._agent.tool_phase_badge()

    def _on_bus_task_updated(self, event: ui_events.Event) -> None:
        """Handle a task-updated event from the bus.

        Subscribers run on the UI thread because the bus is bound to the
        app's loop in :meth:`on_mount`, so widget access is safe.
        """
        from textual.css.query import NoMatches

        if not self._agent:
            return

        # Late updates can arrive after the screen has been torn down
        # (e.g. shutdown after a 503 cancels in-flight subagents); the
        # checklist widget no longer exists, so swallow the lookup.
        try:
            checklist = self.query_one("#task-checklist", tasks_widget.TaskChecklistWidget)
        except NoMatches:
            return
        checklist.notify_changed(self._agent.work_queue.all_tasks())
        self._refresh_subagent_status_bar()
        # Phase 99.4: keep the lifecycle badge in sync with queue state.
        # A task moving to BLOCKED with a budget reason flips the badge
        # to BUDGET LIMITED on the next paint; a queue draining to empty
        # flips it to DONE without /pause needing to fire.
        self._refresh_lifecycle_badge()
        # Phase 110: a task transition (build → debug because a test
        # failed) reshapes the curated tool slice — keep the chip current.
        with contextlib.suppress(NoMatches):
            self.query_one(
                "#status-bar", statusbar_widget.StatusBar
            ).tool_phase = self._agent.tool_phase_badge()

        # Detect when a confirm task becomes blocked.
        payload = event.payload
        if (
            payload.get("category") == TaskCategory.CONFIRM.value
            and payload.get("status") == TaskStatus.BLOCKED.value
            and self._pending_confirm_id is None
        ):
            task_id = payload["id"]
            task = self._agent.work_queue.get_task(task_id)
            if task is None:
                self._pending_confirm_id = task_id
                return
            self._confirmations.present_for_blocked_task(task)

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
        """Render an inline tool-invocation block in the chat (Phase 75).

        When the matching pending block exists (Phase 82), the chat
        widget updates it in place rather than appending a fresh line.
        """
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        payload = event.payload
        caption = payload.get("caption") or payload.get("tool_name", "?")
        success = bool(payload.get("success", False))
        duration_ms = payload.get("duration_ms")
        tool_call_id = payload.get("tool_call_id")
        detail = payload.get("detail")
        chat.add_tool_block(
            caption,
            success=success,
            duration_ms=duration_ms if isinstance(duration_ms, int) else None,
            tool_call_id=tool_call_id if isinstance(tool_call_id, str) else None,
            detail=detail if isinstance(detail, str) and detail else None,
        )

    def on_message_widget_tool_error_requested(
        self, event: chat_widget.MessageWidget.ToolErrorRequested
    ) -> None:
        """Open the failure-detail modal when the user clicks a failed tool block."""
        event.stop()
        from cantrip.tui.screens.tool_error import ToolErrorScreen

        self.push_screen(ToolErrorScreen(event.caption, event.detail))

    def _on_bus_tool_invoked_pending(self, event: ui_events.Event) -> None:
        """Render the pre-call "running now" block (Phase 82).

        A pending event without a usable ``tool_call_id`` is dropped —
        without an id we have no way to match the matching final event
        and would leave a permanent spinner on the screen.
        """
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        payload = event.payload
        tool_call_id = payload.get("tool_call_id")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            return
        caption = payload.get("caption") or payload.get("tool_name", "?")
        chat.add_pending_tool_block(caption, tool_call_id=tool_call_id)

    def _on_bus_mcp_app_render(self, event: ui_events.Event) -> None:
        """Render the TUI fallback for an MCP App render (Phase 73.2).

        The TUI cannot host the Web UI's sandboxed iframe, so we
        surface the spec-mandated one-line marker plus any text-form
        fallback the server provided.  Users who need to interact
        with the app are nudged toward the Web UI.
        """
        chat = self.query_one("#chat", chat_widget.ChatWidget)
        payload = event.payload
        title = payload.get("title")
        if not isinstance(title, str) or not title:
            title = "MCP App"
        fallback = payload.get("fallback_text")
        chat.add_mcp_app_fallback(
            title=title,
            fallback_text=fallback if isinstance(fallback, str) else "",
            web_url=self._web_url_or_none(),
        )

    def _web_url_or_none(self) -> str | None:
        """Best-effort URL for the running Web UI surface (Phase 73.2)."""
        port = getattr(self, "_web_port", None)
        if isinstance(port, int) and port > 0:
            return f"http://localhost:{port}"
        return None

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
        if "short_session" in payload:
            # Phase 104: non-empty when the active provider runs the
            # tight-context short-session flow.
            status_bar.short_session = payload["short_session"]
        if "mode" in payload:
            # Phase 68.4: ``/plan`` and ``/build`` publish
            # ``mode=plan|build`` so the bar tints distinctly while
            # the read-only gate is active.
            status_bar.mode = payload["mode"]
        if "loop_state" in payload:
            # Phase 99.1: ``/pause`` and ``/resume`` publish
            # ``loop_state=paused|running`` so the bar surfaces a
            # PAUSED badge alongside whichever mode badge is active.
            status_bar.loop_state = payload["loop_state"]

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

    # -- Watcher integration --------------------------------------------------

    def _subscribe_watcher_events(self) -> None:
        """Subscribe to watcher events so the panes update even if the
        watcher starts later (e.g. once the agent provisions a model).
        """
        watcher_actions.subscribe_events(self)

    def _start_watcher(self) -> None:
        """Try to start the event watcher.

        If no Juju model is available yet, schedule a periodic retry so
        the watcher starts as soon as the agent provisions one.
        """
        watcher_actions.start_watcher(self)

    async def _stop_watcher(self) -> None:
        """Stop the event watcher."""
        await watcher_actions.stop_watcher(self)

    def _refresh_model_panes(self) -> None:
        """Push the watcher's latest status snapshots into the model widget."""
        watcher_actions.refresh_model_panes(self)

    def _on_bus_watcher_event(self, event: ui_events.Event) -> None:
        """Handle a watcher event from the bus."""
        watcher_actions.on_watcher_event(self, event)

    def _on_bus_juju_status(self, _event: ui_events.Event) -> None:
        """Handle a periodic status-poll tick from the watcher."""
        watcher_actions.on_juju_status(self)

    def _update_status_bar_watcher(self) -> None:
        """Update the status bar watcher indicator."""
        watcher_actions.update_status_bar(self)

    def _refresh_subagent_status_bar(self) -> None:
        """Mirror the currently-active subagent phase into the status bar."""
        watcher_actions.refresh_subagent_status_bar(self)

    def _refresh_lifecycle_badge(self) -> None:
        """Phase 99.4: pull the projected lifecycle label onto the status bar.

        Called after every queue change so the badge reflects current
        truth without relying on a slash command to publish.  Swallows
        ``NoMatches`` because the bar can be torn down before a late
        task-update event lands during shutdown.
        """
        from textual.css.query import NoMatches

        if self._agent is None:
            return
        try:
            status_bar = self.query_one("#status-bar", statusbar_widget.StatusBar)
        except NoMatches:
            return
        status_bar.loop_state = self._agent.lifecycle_label()

    def action_toggle_watcher(self) -> None:
        """Pause or resume the watcher's autonomous reactions."""
        watcher_actions.toggle_watcher(self)

    # -- Chat -----------------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        """Drive the slash and ``@``-mention suggestion popups from chat input changes."""
        from textual.css.query import NoMatches

        if event.input.id != "chat-input":
            return
        try:
            suggestions = self.query_one("#slash-suggestions", chat_widget.SlashCommandSuggestions)
        except NoMatches:
            return
        suggestions.update_from_value(event.value)
        try:
            mentions = self.query_one("#mention-suggestions", chat_widget.MentionSuggestions)
        except NoMatches:
            return
        mentions.update_from_input(event.value, event.input.cursor_position)

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

        # Phase 69.3: ``Ctrl-X`` shell mode runs the input as a
        # subprocess and never reaches the agent.  Dispatch before
        # ``add_user_message`` so the row appears as a ``$`` block,
        # not as a user message that would also be replayed to the
        # LLM on next turn.
        if isinstance(event.input, chat_widget.ChatInput) and event.input.shell_mode:
            await self._handle_shell_command(message, chat)
            return

        chat.add_user_message(message)

        if not self._agent:
            chat.add_system_message("No LLM provider configured. Check your API key.")
            return

        # Handle pending confirmations before sending to the LLM.
        if self._confirmations.handle_pending_response(message):
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

        # Phase 72.2: expand ``@`` mentions before the message reaches
        # the LLM.  Slash commands run first so ``/foo @bar`` doesn't
        # accidentally substitute provider output into a slash arg.
        expansion = await self._expand_mentions(message)
        agent_message = expansion.expanded
        if expansion.changed:
            chat.add_system_message(f"_Expanded mentions: {expansion.summary()}_")

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
            self._process_agent_message(agent_message),
            name="agent_response",
            exclusive=True,
            exit_on_error=False,
        )

    async def _expand_mentions(self, message: str) -> context_providers.ExpansionResult:
        """Expand any ``@<name>`` mentions in *message* via the agent's registry.

        Phase 72.2: returns the original text unchanged when no agent
        is attached or no mentions are present, so callers can keep
        the same code path regardless of whether expansion fired.
        """
        if self._agent is None:
            return context_providers.ExpansionResult(raw=message, expanded=message, blocks=())
        ctx = context_providers.ExpansionContext(
            charm_path=self._agent.state.charm_path,
            repo_root=self._agent.state.charm_path,
        )
        return await context_providers.expand_mentions(
            message,
            self._agent.context_providers,
            ctx,
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
        nodes = session_commands.build_tree_nodes(messages, active_ids)

        def _on_picked(turn_id: int | None) -> None:
            if turn_id is None:
                return
            text = session_commands.handle_branch(self._agent, str(turn_id))
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

    async def _handle_shell_command(
        self,
        raw: str,
        chat: chat_widget.ChatWidget,
    ) -> None:
        """Run *raw* as a Phase 69.3 shell-mode subprocess.

        The submission never reaches the LLM — the rendered row uses
        the ``SHELL`` chat role and persists with role ``"shell"``,
        which the agent's branch-rebuild path skips because ``"shell"``
        is not a member of :class:`cantrip.llm.base.Role`.
        """
        from cantrip.tui.actions import shell as shell_action

        parsed = shell_action.parse_shell_input(raw)
        if parsed.error is not None or not parsed.argv:
            chat.add_system_message(parsed.error or "Empty command.")
            return

        cwd = str(self.charm_path) if self.charm_path is not None else "."
        result = await asyncio.to_thread(
            shell_action.run_shell_command,
            parsed.argv,
            cwd=cwd,
        )
        chat.add_shell_message(
            list(result.argv),
            output=result.output,
            exit_code=result.exit_code,
            hidden_from_agent=parsed.hidden_from_agent,
        )

        if self._agent is not None and self._agent.store is not None:
            metadata = shell_action.metadata_for_persisted_row(
                result, hidden_from_agent=parsed.hidden_from_agent
            )
            content = " ".join(result.argv)
            try:
                self._agent.store.record_message(
                    role="shell",
                    content=content,
                    metadata=metadata,
                )
            except sqlite3.Error:
                # Persistence is best-effort here: the user already
                # saw the output in the chat, and a transient store
                # error must not break shell-mode dispatch.
                log.debug("Failed to persist shell-mode row", exc_info=True)

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
        # Phase 82: any pending tool block left over from a cancelled
        # or crashed turn would otherwise read as a spinner forever.
        # Scrub them as failed "cancelled" blocks so the chat never
        # leaves a dangling ⟳.
        chat.scrub_pending_tool_blocks()
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
                self._confirmations._offer_repo_bootstrap()

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
        screens_actions.show_help(self)

    def action_debug(self) -> None:
        """Show trace/debug screen."""
        screens_actions.show_debug(self)

    def on_relation_line_selected(self, event: status_widgets.RelationLine.Selected) -> None:
        """Open the relation detail screen when a relation line is clicked."""
        screens_actions.open_relation_detail(self, event)

    def on_app_node_selected(self, event: status_widgets.AppNode.Selected) -> None:
        """Open the F8 graph focused on the app picked in the sketch."""
        screens_actions.show_graph(self, focus_app=event.app_name)

    def on_juju_status_widget_status_available(self) -> None:
        """Show the status panel when status data first arrives."""
        status_actions.show_status_panel_when_data_arrives(self)

    def action_toggle_status(self) -> None:
        """Toggle status panel visibility."""
        status_actions.toggle_status(self)

    def action_toggle_files(self) -> None:
        """Toggle charm file tree visibility."""
        status_actions.toggle_files(self)

    def action_logs(self) -> None:
        """Show log viewer screen."""
        screens_actions.show_logs(self)

    def action_graph(self) -> None:
        """Show integration graph screen."""
        screens_actions.show_graph(self)

    def action_transcript(self) -> None:
        """Show session transcript screen."""
        screens_actions.show_transcript(self)

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
        chat_actions.clear_chat(self)

    def action_search_chat(self) -> None:
        """Open the chat search bar."""
        chat_actions.open_search(self)

    def on_chat_widget_search_closed(self, event: chat_widget.ChatWidget.SearchClosed) -> None:
        """Return focus to the chat input when the search bar closes."""
        chat_actions.search_closed(self, event)

    def action_cancel_agent(self) -> None:
        """Cancel the running agent response worker."""
        chat_actions.cancel_agent(self)
