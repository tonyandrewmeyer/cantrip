"""Outward subsystem-integration and session-lifecycle surface for the agent.

``IntegrationMixin`` collects the methods the CLI / TUI call to drive the
agent's long-running subsystems — the event watcher, issue triage, the PR
feedback loop, the blind A/B arena, the background executor, MCP, repo
bootstrap — together with the session save / load / preview / preflight
lifecycle.  Most are thin delegations to the controllers and services the
agent composes; the bodies live here rather than in the ``CantripAgent``
class so ``core.py`` stays navigable.  All state and controllers are
reached through ``self``.

``create_branch`` and ``gh_pr_view`` are reached through the ``core``
module object at call time so ``patch("cantrip.agent.core.<name>")`` tests
keep taking effect.
"""

from __future__ import annotations

import logging
import pathlib
import typing
from collections.abc import Callable
from typing import Any

from cantrip.agent.git.git_branch import PUSH_CONFIRM_PREFIX, PrFeedback
from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.agent.runtime.preflight import (
    DEFAULT_PRESET,
    PreflightCallback,
    PreflightResult,
    PreflightRunner,
)
from cantrip.agent.safety.permissions import PermissionDecision
from cantrip.agent.session_preview import SessionPreview
from cantrip.agent.tools import ToolResult
from cantrip.agent.watcher.watcher import WatcherConfig, WatcherEvent
from cantrip.llm.base import Message

if typing.TYPE_CHECKING:
    from cantrip.mcp import MarketplaceLoader, MarketplaceSource, MCPRegistry

log = logging.getLogger("cantrip.agent.core")


class IntegrationMixin:
    """Subsystem-integration and session-lifecycle delegations."""

    # -- Watcher integration ---------------------------------------------------

    @property
    def watcher_running(self) -> bool:
        """Whether the event watcher is currently running."""
        return self._watcher_ctl.running

    def start_watcher(
        self,
        config: WatcherConfig | None = None,
        on_event: Callable | None = None,
    ) -> bool:
        """Create and start the event watcher."""
        return self._watcher_ctl.start(config=config, on_event=on_event)

    async def stop_watcher(self) -> None:
        """Stop the event watcher if it is running."""
        await self._watcher_ctl.stop()

    @property
    def watcher_reacting(self) -> bool:
        """Whether watcher events are routed to the work queue.

        When ``False`` the watcher keeps observing (status panes and
        ``[Watcher]`` chat notices still update) but detected events do
        not become tasks, so the agent stops reacting autonomously.
        """
        return self.state.watcher_reacting

    def toggle_watcher_reacting(self) -> bool:
        """Flip whether watcher events queue tasks; return the new value."""
        self.state.watcher_reacting = not self.state.watcher_reacting
        return self.state.watcher_reacting

    def route_watcher_event(self, event: WatcherEvent) -> AgentTask | None:
        """Convert a watcher event into a task and add it to the work queue."""
        return self._watcher_ctl.route_event(event)

    async def process_watcher_event(self) -> str | None:
        """Dequeue one watcher event and route it to the task queue."""
        return await self._watcher_ctl.process_event()

    # -- Issue triage integration -----------------------------------------------

    @property
    def issue_triage_running(self) -> bool:
        """Whether the GitHub issue triage worker is active."""
        return self._triage_ctl.running

    def start_issue_triage(self) -> bool:
        """Start the background issue triage worker."""
        return self._triage_ctl.start()

    async def stop_issue_triage(self) -> None:
        """Stop the issue triage worker if running."""
        await self._triage_ctl.stop()

    def retriage_issues(self) -> bool:
        """Re-run issue triage to check for new issues."""
        return self._triage_ctl.retriage()

    def comment_on_issue(self, issue_number: int, pr_url: str) -> str:
        """Post a comment on a resolved GitHub issue."""
        return self._triage_ctl.comment_on_issue(issue_number, pr_url)

    def check_upstream(self) -> str | None:
        """Check if the default branch has diverged from the remote."""
        return self._triage_ctl.check_upstream()

    # -- PR feedback loop (Phase 42.7) ----------------------------------------

    def check_pr_feedback(self, pr_number: int) -> PrFeedback | None:
        """Fetch review feedback for a pull request.

        Returns structured feedback or ``None`` if unavailable.
        """
        from cantrip.agent import core

        repo = self.state.github_repo
        if not repo:
            return None
        return core.gh_pr_view(repo, pr_number)

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
        from cantrip.agent import core

        if not self.state.github_repo or not self.state.charm_path:
            return None
        branch = core.create_branch(str(self.state.charm_path), description)
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

    # ── Blind A/B arena (Phase 47.5) ────────────────────────────────────

    @property
    def active_arena(self) -> object | None:
        """The pending blind A/B arena, or ``None`` when idle."""
        return self._arena_ctl.active

    async def begin_arena(self, prompt: str) -> str:
        """Run a blind A/B arena for *prompt* and return the formatted output."""
        return await self._arena_ctl.begin(prompt)

    def handle_arena_pick(self, message: str) -> str | None:
        """Resolve a pending arena pick from a raw user reply."""
        return self._arena_ctl.handle_pick(message)

    def handle_race_confirmation(self, confirm_task_id: str, *, approved: bool) -> str:
        """Resolve a race-cost CONFIRM task and unblock the parent."""
        return self._confirmations.handle_race(confirm_task_id, approved=approved)

    def handle_push_confirmation(self, confirm_task_id: str, *, approved: bool) -> str:
        """Handle an approved or skipped push-confirm task."""
        return self._confirmations.handle_push(confirm_task_id, approved=approved)

    def handle_pr_creation(self, branch_name: str, *, draft: bool = False) -> str:
        """Create a pull request for *branch_name*."""
        return self._confirmations.handle_pr_creation(branch_name, draft=draft)

    def should_offer_bootstrap(self) -> bool:
        """Return ``True`` if repo bootstrap should be offered to the user."""
        return self._confirmations.should_offer_bootstrap()

    def build_repo_bootstrap_confirm_task(self) -> AgentTask:
        """Build the CONFIRM task that offers to create a GitHub repo."""
        return self._confirmations.build_repo_bootstrap_confirm_task()

    def handle_repo_bootstrap(
        self, name: str, *, private: bool = True, description: str = "", org: str = ""
    ) -> str:
        """Create a GitHub repository and push the initial commit."""
        return self._confirmations.handle_repo_bootstrap(
            name, private=private, description=description, org=org
        )

    def handle_triage_confirmation(self, confirm_task_id: str) -> list[AgentTask]:
        """Process an approved triage-confirm task and generate work tasks."""
        return self._confirmations.handle_triage(confirm_task_id)

    # -- Executor integration -------------------------------------------------

    @property
    def _executor(self):
        """Backward-compatible access to the live background executor."""
        return self._executor_ctl._executor

    @property
    def executor_running(self) -> bool:
        """Whether the background executor is currently running."""
        return self._executor_ctl.running

    def start_executor(
        self,
        max_concurrency: int | None = None,
    ) -> None:
        """Create and start the background executor."""
        self._executor_ctl.start(
            queue=self._work_queue,
            tools=self._tools,
            provider=self.provider,
            store=self._store,
            light_provider=self._light_provider,
            hook_runner=self._hook_runner,
            ensure_store=self._ensure_store,
            max_concurrency=max_concurrency,
        )
        # Phase 73.2: wire MCP App iframe tool calls through the same
        # permission gate and audit writer the executor uses.  Done
        # after start so ``self._executor`` exists; the controller
        # silently rejects iframe calls until this fires (defensive —
        # the Web UI doesn't render any iframes before tool dispatch
        # has happened anyway).
        self._wire_mcp_app_dispatcher()

    def _wire_mcp_app_dispatcher(self) -> None:
        """Register the MCP-App permission + dispatch hooks on the controller.

        Permission evaluation reads the *current* executor ruleset on
        every call so a runtime ``/plan`` / ``/build`` mode flip is
        picked up without re-registering.  Dispatch routes through the
        same :func:`execute_tool` helper the agent's tool loop uses,
        so MCP-App calls share validation, error shaping, and post-edit
        lint hooks with agent-initiated calls.  Audit writes land in
        the same ``.cantrip-audit.jsonl`` the rest of the dispatch path
        appends to.
        """
        from cantrip.agent.audit import AUDIT_FILENAME, AuditWriter
        from cantrip.agent.safety.permissions import evaluate as evaluate_permissions
        from cantrip.agent.tools.base import execute_tool as base_execute_tool

        executor = self._executor
        if executor is None:
            return

        def _evaluate(name: str, arguments: dict[str, Any]) -> PermissionDecision:
            return evaluate_permissions(
                executor.permissions,
                name,
                arguments,
                agent_name="mcp-app",
            )

        async def _dispatch(name: str, arguments: dict[str, Any]) -> ToolResult:
            return await base_execute_tool(self._tool_map, name, arguments)

        audit_writer: AuditWriter | None = None
        if self.state.charm_path is not None:
            audit_writer = AuditWriter(pathlib.Path(self.state.charm_path) / AUDIT_FILENAME)

        self._mcp.register_app_dispatcher(
            evaluate_permission=_evaluate,
            dispatch_tool=_dispatch,
            permission_manager=executor.permission_manager,
            audit_writer=audit_writer,
        )

    async def stop_executor(self) -> None:
        """Stop the background executor if it is running."""
        await self._executor_ctl.stop()

    # -- MCP integration ------------------------------------------------------

    @property
    def mcp_registry(self) -> MCPRegistry:
        """Lazy registry of configured MCP servers — see :class:`MCPController`."""
        return self._mcp.registry

    @property
    def mcp_marketplace_sources(self) -> list[MarketplaceSource]:
        """Marketplace sources declared in user + repo MCP configs."""
        return self._mcp.marketplace_sources

    @property
    def mcp_marketplace_loader(self) -> MarketplaceLoader:
        """Lazy :class:`MarketplaceLoader` shared across slash-command calls."""
        return self._mcp.marketplace_loader

    async def start_mcp(self) -> None:
        """Open every configured MCP connection.  Idempotent."""
        await self._mcp.start()

    def _on_mcp_elicitation(self, request: object) -> None:
        """Forward an MCP elicitation request to the UI event bus."""
        self._mcp.handle_elicitation(request)

    def complete_mcp_elicitation(
        self,
        request_id: str,
        action: str,
        content: dict[str, Any] | None = None,
    ) -> bool:
        """UI entry point — answer a parked MCP elicitation by id."""
        return self._mcp.complete_elicitation(request_id, action, content)

    async def stop_mcp(self) -> None:
        """Tear down every MCP connection.  Best-effort, never raises."""
        await self._mcp.stop()

    def save_state(self) -> None:
        """Save agent state to the session store."""
        self._persistence.save_state()

    def preview_session(self) -> SessionPreview:
        """Peek at the persisted session without mutating agent state."""
        return self._persistence.preview_session()

    def transcript_tail(self, limit: int = 20) -> list[Message]:
        """Return the last ``limit`` persisted messages, for "review" mode."""
        return self._persistence.transcript_tail(limit)

    def archive_session(self) -> pathlib.Path | None:
        """Rename the current ``.cantrip`` file aside so a fresh session can start."""
        return self._persistence.archive_session()

    def load_state(self) -> bool:
        """Load agent state from the session store."""
        return self._persistence.load_state()

    def build_resume_summary(self) -> str | None:
        """Build a structured summary of prior session work."""
        return self._persistence.build_resume_summary()

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
