"""Confirmation-flow orchestration for the TUI.

Extracted from :class:`cantrip.tui.app.CantripApp` (Phase 113.6).  The app
hosts a dozen-plus confirmation flows — design questions, repo bootstrap, push,
PR creation, the maintenance loop, issue triage, race-cost approval, and
improvement approval — each a *present* step (show a prompt when a CONFIRM task
blocks) paired with a *handle* step (interpret the user's next reply).

:class:`ConfirmationCoordinator` owns the active-flow state
(``pending_confirm_id`` / ``pending_pr_branch`` / ``pending_maintenance``) and
the present/handle methods.  ``CantripApp`` keeps thin delegating wrappers and
property bridges so existing call sites and tests reach the same names; the bus
and input dispatch route through :meth:`present_for_blocked_task` and
:meth:`handle_pending_response`, which replace the former if/elif chains with a
prefix → presenter table and an ordered list of pending-reply handlers.

App-owned services (the agent, ``query_one``, ``push_screen``, ``run_worker``,
header/model refreshers, the one-shot ``_bootstrap_offered`` guard) are reached
through ``self._app``; all confirmation state lives here.
"""

from __future__ import annotations

import re
import typing

from cantrip.agent.design import DesignQuestion, parse_design_from_result
from cantrip.agent.git.git_branch import BOOTSTRAP_CONFIRM_PREFIX, PUSH_CONFIRM_PREFIX
from cantrip.agent.planner import IMPROVEMENT_CONFIRM_BASE
from cantrip.agent.queue import AgentTask, TaskStatus
from cantrip.agent.race.race import RACE_CONFIRM_PREFIX
from cantrip.agent.watcher.github_issues import TRIAGE_CONFIRM_PREFIX
from cantrip.tui.widgets import chat as chat_widget

if typing.TYPE_CHECKING:
    from cantrip.tui.app import CantripApp


class ConfirmationCoordinator:
    """Owns the TUI's confirmation-flow state and present/handle routing."""

    def __init__(self, app: CantripApp) -> None:
        self._app = app
        # Active-flow state.  ``pending_confirm_id`` tracks a blocked CONFIRM
        # task awaiting an approve/skip reply; ``pending_pr_branch`` a
        # post-push PR offer; ``pending_maintenance`` the comment/review/next
        # maintenance loop after a PR lands.
        self.pending_confirm_id: str | None = None
        self.pending_pr_branch: str | None = None
        self.pending_maintenance: dict | None = None

    # -- Bus + input routing --------------------------------------------------

    def present_for_blocked_task(self, task: AgentTask) -> None:
        """Route a freshly-blocked CONFIRM task to its presenter.

        Records the task as the pending confirmation and dispatches by ID
        prefix; design confirmations (no recognised prefix) fall through to
        the interactive questions flow.
        """
        task_id = task.id
        self.pending_confirm_id = task_id
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

    def handle_pending_response(self, message: str) -> bool:
        """Offer *message* to whichever confirmation flow is active.

        Returns ``True`` if a flow consumed the reply.  Order matters: the
        maintenance loop and PR offer are keyed on their own state, the
        prefix-keyed CONFIRM handlers on ``pending_confirm_id``.
        """
        if self.pending_maintenance and self._handle_maintenance_response(message):
            return True
        if self.pending_pr_branch and self._handle_pr_response(message):
            return True
        confirm_id = self.pending_confirm_id
        if not confirm_id:
            return False
        # Prefix → pending-reply handler for the active CONFIRM task.
        for prefix, handler in (
            (PUSH_CONFIRM_PREFIX, self._handle_push_response),
            (TRIAGE_CONFIRM_PREFIX, self._handle_triage_response),
            (RACE_CONFIRM_PREFIX, self._handle_race_response),
            (BOOTSTRAP_CONFIRM_PREFIX, self._handle_bootstrap_response),
        ):
            if confirm_id.startswith(prefix):
                return handler(message)
        return False

    # -- Design questions flow ------------------------------------------------

    def _present_design_questions(self, task: AgentTask) -> None:
        """Extract the design proposal and show interactive questions.

        Called from the executor callback (via ``call_from_thread``) when a
        confirm-design task becomes blocked.  Walks the task's dependencies
        to find the synthesis result, parses it for structured questions,
        and either pushes the interactive questions screen or falls back to
        showing everything in chat for the LLM to handle.
        """
        if not self._app._agent:
            return

        # Find the synthesis result from the confirm task's dependencies.
        design_text = ""
        for dep_id in task.dependencies:
            dep = self._app._agent.work_queue.get_task(dep_id)
            if dep is not None and dep.result:
                design_text = dep.result
                break

        if not design_text:
            # No design found — let the conversation LLM handle it.
            self.pending_confirm_id = None
            return

        proposal = parse_design_from_result(design_text)
        questions = proposal.questions_for_user

        if not questions:
            # No structured questions — let the conversation LLM handle it.
            self.pending_confirm_id = None
            return

        # Show the design summary in chat (without questions).
        chat = self._app.query_one("#chat", chat_widget.ChatWidget)
        chat.add_system_message(proposal.format_for_chat())

        # Push the interactive questions screen.
        from cantrip.tui.screens import questions as questions_screen

        self._app.push_screen(
            questions_screen.DesignQuestionsScreen(questions),
            callback=self._on_questions_answered,
        )

    def _on_questions_answered(self, questions: list[DesignQuestion] | None) -> None:
        """Handle completed design questions and trigger design confirmation."""
        confirm_id = self.pending_confirm_id
        self.pending_confirm_id = None

        if not self._app._agent or not confirm_id:
            return

        # Build an overrides string from the answered questions.
        answered = [q for q in (questions or []) if q.answer]
        if answered:
            lines = [f"- **{q.key}**: {q.answer}" for q in answered]
            overrides = "User answers:\n" + "\n".join(lines)
        else:
            overrides = None

        # Show answers in chat.
        chat = self._app.query_one("#chat", chat_widget.ChatWidget)
        if answered:
            answer_text = "\n".join(f"**{q.key}**: {q.answer}" for q in answered)
            chat.add_user_message(answer_text)
        chat.add_system_message("Design approved. Generating build tasks...")

        # Approve the confirm task and generate build tasks.
        self._app.run_worker(
            self._complete_design_confirmation(confirm_id, overrides),
            name="design_confirmation",
            exclusive=False,
        )

    async def _complete_design_confirmation(self, confirm_id: str, overrides: str | None) -> None:
        """Approve the confirm task and generate build tasks from the design."""
        if not self._app._agent:
            return

        # Approve (unblock → done).
        self._app._agent.work_queue.set_done(confirm_id, "Approved by user")

        # Generate build tasks.
        build_tasks = await self._app._agent.handle_design_confirmation(
            confirm_id,
            overrides=overrides,
        )

        chat = self._app.query_one("#chat", chat_widget.ChatWidget)
        if build_tasks:
            titles = "\n".join(f"- {t.title}" for t in build_tasks)
            chat.add_system_message(f"Build plan created:\n{titles}")
        else:
            chat.add_system_message("No build tasks generated — check the design output.")

    # -- Repo bootstrap flow --------------------------------------------------

    def _offer_repo_bootstrap(self) -> None:
        """Offer to create a GitHub repo by queuing a CONFIRM task.

        The CONFIRM task surfaces in the task panel and — via the
        shared CONFIRM+BLOCKED routing in :meth:`present_for_blocked_task`
        — shows a framed confirmation prompt rather than an inline
        system message that blurs with other chat output.
        """
        if self._app._bootstrap_offered or not self._app._agent:
            return
        if not self._app._agent.should_offer_bootstrap():
            return

        self._app._bootstrap_offered = True
        task = self._app._agent.build_repo_bootstrap_confirm_task()
        self._app._agent.work_queue.add_task(task)

    def _present_bootstrap_confirmation(self, task: AgentTask) -> None:
        """Show the repo-bootstrap CONFIRM prompt in chat.

        Mirrors :meth:`_present_triage_confirmation` — the task stays
        blocked, and the user's next message is matched against the
        approve / skip / ``name=… public org=… desc=…`` tokens by
        :meth:`_handle_bootstrap_response`.
        """
        chat = self._app.query_one("#chat", chat_widget.ChatWidget)
        chat.add_system_message(f"**Repo bootstrap:**\n\n{task.description}", markdown=True)

    def _handle_bootstrap_response(self, message: str) -> bool:
        """Handle approve / skip / customised reply for the bootstrap CONFIRM.

        Returns ``True`` if the message was consumed.  The default
        repo name comes from the CONFIRM task's ID suffix; callers
        override it with ``name=foo`` inside the reply.
        """
        if not self._app._agent or not self.pending_confirm_id:
            return False
        confirm_id = self.pending_confirm_id
        if not confirm_id.startswith(BOOTSTRAP_CONFIRM_PREFIX):
            return False

        lower = message.strip().lower()
        chat = self._app.query_one("#chat", chat_widget.ChatWidget)

        if lower in ("skip", "no", "n", "dismiss"):
            self.pending_confirm_id = None
            self._app._agent.work_queue.set_done(confirm_id, "Skipped by user")
            chat.add_system_message("Repository creation skipped.")
            return True

        if not lower.startswith(("approve", "yes", "y", "ok", "public", "private")):
            # Unrecognised — pass through to the LLM.
            return False

        self.pending_confirm_id = None
        self._app._agent.work_queue.set_done(confirm_id, "Approved by user")

        # ``public`` anywhere in the reply flips visibility; otherwise private.
        private = "public" not in lower

        # Extract ``name=`` / ``org=`` / ``desc=`` from the reply.  The
        # suggested name is encoded in the task ID so a bare "approve"
        # (without ``name=``) picks up ``<workload>-operator``.
        default_name = confirm_id.removeprefix(BOOTSTRAP_CONFIRM_PREFIX)

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
            f"Creating {'private' if private else 'public'} repository **{repo_name}**...",
            markdown=True,
        )
        result = self._app._agent.handle_repo_bootstrap(
            repo_name,
            private=private,
            description=description,
            org=org,
        )
        chat.add_system_message(result, markdown=True)

        if self._app._agent.state.github_repo:
            self._app._update_header_subtitle()
            self._app._update_model_info()
        return True

    # -- PR creation + maintenance loop ---------------------------------------

    def _handle_pr_response(self, message: str) -> bool:
        """Handle pr/draft/skip response after a successful push.

        Returns ``True`` if the message was handled, ``False`` otherwise.
        """
        if not self._app._agent or not self.pending_pr_branch:
            return False

        lower = message.strip().lower()
        chat = self._app.query_one("#chat", chat_widget.ChatWidget)
        branch = self.pending_pr_branch

        if lower in ("pr", "yes", "y", "ok", "draft"):
            draft = lower == "draft"
            self.pending_pr_branch = None
            result = self._app._agent.handle_pr_creation(branch, draft=draft)
            chat.add_system_message(result)
            # Trigger maintenance loop: offer to comment + re-triage.
            self._offer_maintenance_continuation(branch, result)
            return True

        if lower in ("skip", "no", "n"):
            self.pending_pr_branch = None
            chat.add_system_message("PR creation skipped.")
            # Still offer re-triage even if PR was skipped.
            self._offer_retriage()
            return True

        return False

    def _offer_maintenance_continuation(self, branch: str, pr_result: str) -> None:
        """After PR creation, offer to comment on the issue and re-triage."""
        if not self._app._agent:
            return

        # Extract issue number from branch name.
        m = re.search(r"issue-(\d+)", branch)
        issue_number = int(m.group(1)) if m else None

        # Extract PR URL from result.
        pr_url = ""
        url_match = re.search(r"(https://github\.com/\S+/pull/\d+)", pr_result)
        if url_match:
            pr_url = url_match.group(1)

        chat = self._app.query_one("#chat", chat_widget.ChatWidget)

        # Extract PR number from URL.
        pr_number: int | None = None
        pr_num_match = re.search(r"/pull/(\d+)", pr_url)
        if pr_num_match:
            pr_number = int(pr_num_match.group(1))

        if issue_number and pr_url:
            self.pending_maintenance = {
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
            self.pending_maintenance = {
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
        if not self._app._agent or not self._app._agent.state.github_repo:
            return
        # Check for upstream divergence first.
        warning = self._app._agent.check_upstream()
        chat = self._app.query_one("#chat", chat_widget.ChatWidget)
        if warning:
            chat.add_system_message(warning)
        chat.add_system_message("Reply **next** to check for more issues, or **done** to stop.")
        self.pending_maintenance = {"retriage_only": True}

    def _handle_maintenance_response(self, message: str) -> bool:
        """Handle comment/next/done response in the maintenance loop.

        Returns ``True`` if the message was handled.
        """
        if not self._app._agent or not self.pending_maintenance:
            return False

        lower = message.strip().lower()
        chat = self._app.query_one("#chat", chat_widget.ChatWidget)
        ctx = self.pending_maintenance

        if lower == "comment" and "issue_number" in ctx:
            result = self._app._agent.comment_on_issue(ctx["issue_number"], ctx.get("pr_url", ""))
            chat.add_system_message(result)
            # After commenting, offer re-triage or review.
            self.pending_maintenance = {k: v for k, v in ctx.items() if k != "issue_number"}
            if "pr_number" in ctx:
                chat.add_system_message(
                    "Reply **review** to check for PR feedback, "
                    "**next** for more issues, or **done** to stop."
                )
            else:
                self.pending_maintenance = {"retriage_only": True}
                chat.add_system_message(
                    "Reply **next** to check for more issues, or **done** to stop."
                )
            return True

        if lower == "review" and "pr_number" in ctx:
            pr_number = ctx["pr_number"]
            branch = ctx.get("branch", "")
            feedback = self._app._agent.check_pr_feedback(pr_number)
            if feedback is None:
                chat.add_system_message(f"Could not fetch feedback for PR #{pr_number}.")
            elif feedback.is_approved:
                chat.add_system_message(f"PR #{pr_number} is **approved**. No changes needed.")
                self.pending_maintenance = {"retriage_only": True}
            elif feedback.needs_changes and feedback.comments:
                chat.add_system_message(feedback.format_for_chat())
                chat.add_system_message(
                    "Reply **fix** to address the review feedback, or **skip** to handle it manually."
                )
                self.pending_maintenance = {
                    "awaiting_fix": True,
                    "pr_number": pr_number,
                    "branch": branch,
                    "feedback": feedback,
                }
            elif feedback.comments:
                chat.add_system_message(feedback.format_for_chat())
                self.pending_maintenance = {"retriage_only": True}
            else:
                chat.add_system_message(f"PR #{pr_number} has no review comments yet.")
                self.pending_maintenance = {"retriage_only": True}
            return True

        if lower == "fix" and ctx.get("awaiting_fix"):
            feedback = ctx.get("feedback")
            branch = ctx.get("branch", "")
            if feedback and self._app._agent:
                fix_tasks = self._app._agent.create_pr_fix_tasks(feedback, branch)
                if fix_tasks:
                    titles = "\n".join(f"- {t.title}" for t in fix_tasks)
                    chat.add_system_message(f"Addressing review feedback:\n{titles}")
                else:
                    chat.add_system_message("Could not create fix tasks.")
            self.pending_maintenance = None
            return True

        if lower in ("next", "more"):
            self.pending_maintenance = None
            started = self._app._agent.retriage_issues()
            if started:
                chat.add_system_message("Checking for new issues...")
            else:
                chat.add_system_message("No new issues to check.")
            return True

        if lower in ("done", "stop", "skip", "no", "n"):
            self.pending_maintenance = None
            chat.add_system_message("Maintenance loop stopped.")
            return True

        return False

    # -- Push confirmation ----------------------------------------------------

    def _handle_push_response(self, message: str) -> bool:
        """Handle approve/skip response for a push-confirm CONFIRM task.

        Returns ``True`` if the message was handled, ``False`` otherwise.
        """
        if not self._app._agent or not self.pending_confirm_id:
            return False

        lower = message.strip().lower()
        chat = self._app.query_one("#chat", chat_widget.ChatWidget)
        confirm_id = self.pending_confirm_id

        if lower in ("approve", "yes", "y", "push", "ok"):
            self.pending_confirm_id = None
            self._app._agent.work_queue.set_done(confirm_id, "Push approved by user")
            result = self._app._agent.handle_push_confirmation(confirm_id, approved=True)
            chat.add_system_message(result)
            # If push succeeded, offer PR creation.
            if "Reply **pr**" in result:
                branch = confirm_id.removeprefix(PUSH_CONFIRM_PREFIX)
                self.pending_pr_branch = branch
            return True

        if lower in ("skip", "no", "n", "dismiss", "local"):
            self.pending_confirm_id = None
            self._app._agent.work_queue.set_done(confirm_id, "Push declined — branch left local")
            result = self._app._agent.handle_push_confirmation(confirm_id, approved=False)
            chat.add_system_message(result)
            return True

        return False

    def _present_push_confirmation(self, task: AgentTask) -> None:
        """Show a push confirmation prompt in chat.

        Called when a push-branch-* CONFIRM task becomes blocked.
        """
        if not self._app._agent:
            return

        chat = self._app.query_one("#chat", chat_widget.ChatWidget)
        chat.add_system_message(
            f"{task.description}\n\nReply **push** to push, or **skip** to leave the branch local."
        )

    # -- Race-cost confirmation -----------------------------------------------

    def _present_race_confirmation(self, task: AgentTask) -> None:
        """Show a race-cost confirmation prompt in chat.

        Called when a ``race-confirm-*`` CONFIRM task becomes blocked.
        """
        if not self._app._agent:
            return
        chat = self._app.query_one("#chat", chat_widget.ChatWidget)
        chat.add_system_message(task.description)

    def _handle_race_response(self, message: str) -> bool:
        """Handle approve/decline response for a race-cost CONFIRM task.

        Returns ``True`` if the message was handled (approved or declined),
        ``False`` if it should be passed through to the LLM.  Yes / no and
        common synonyms are accepted; anything else falls through so the
        user can ask clarifying questions.
        """
        if not self._app._agent or not self.pending_confirm_id:
            return False

        confirm_id = self.pending_confirm_id
        if not confirm_id.startswith(RACE_CONFIRM_PREFIX):
            return False

        lower = message.strip().lower()
        chat = self._app.query_one("#chat", chat_widget.ChatWidget)

        if lower in ("yes", "y", "approve", "race", "ok"):
            self.pending_confirm_id = None
            result = self._app._agent.handle_race_confirmation(confirm_id, approved=True)
            chat.add_system_message(result)
            return True

        if lower in ("no", "n", "decline", "single", "skip"):
            self.pending_confirm_id = None
            result = self._app._agent.handle_race_confirmation(confirm_id, approved=False)
            chat.add_system_message(result)
            return True

        return False

    # -- Issue triage ---------------------------------------------------------

    def _handle_triage_response(self, message: str) -> bool:
        """Handle approve/skip response for a triage CONFIRM task.

        Returns ``True`` if the message was handled, ``False`` if it should
        be passed to the LLM instead.
        """
        if not self._app._agent or not self.pending_confirm_id:
            return False

        lower = message.strip().lower()
        chat = self._app.query_one("#chat", chat_widget.ChatWidget)
        confirm_id = self.pending_confirm_id

        if lower in ("approve", "yes", "y", "ok"):
            self.pending_confirm_id = None
            self._app._agent.work_queue.set_done(confirm_id, "Approved by user")
            work_tasks = self._app._agent.handle_triage_confirmation(confirm_id)
            if work_tasks:
                titles = "\n".join(f"- {t.title}" for t in work_tasks)
                chat.add_system_message(f"Working on the issue:\n{titles}")
            else:
                chat.add_system_message("Could not generate work tasks for this issue.")
            self._present_next_pending_triage()
            return True

        if lower in ("skip", "no", "n", "dismiss"):
            self.pending_confirm_id = None
            self._app._agent.work_queue.set_done(confirm_id, "Skipped by user")
            chat.add_system_message("Issue skipped.")
            self._present_next_pending_triage()
            return True

        # Unrecognised response — don't consume it.
        return False

    def _present_next_pending_triage(self) -> None:
        """If another triage CONFIRM is already BLOCKED, present it now.

        The executor blocks every PENDING triage CONFIRM in successive
        polling ticks, so by the time the user answers the first one the
        next two are already in ``BLOCKED`` state — no new
        ``task_changed`` event will fire for them, and they'd otherwise
        sit unanswered in the task pane.  Manually pick the next one and
        run it through the same presenter the bus would have invoked.
        """
        if not self._app._agent:
            return
        for task in self._app._agent.work_queue.all_tasks():
            if task.id.startswith(TRIAGE_CONFIRM_PREFIX) and task.status == TaskStatus.BLOCKED:
                self.pending_confirm_id = task.id
                self._present_triage_confirmation(task)
                return

    def _present_triage_confirmation(self, task: AgentTask) -> None:
        """Show a GitHub issue summary in chat for user approval.

        Called when a triage-issue-* CONFIRM task becomes blocked.
        Shows the issue details and asks the user to approve or skip.
        """
        if not self._app._agent:
            return

        # The triage task description carries embedded GitHub issue
        # markup (headings, bullet points, fenced code blocks).  Render
        # as Markdown so the user sees formatting instead of literal
        # ``##`` and ``-`` characters in the chat.
        chat = self._app.query_one("#chat", chat_widget.ChatWidget)
        chat.add_system_message(
            f"**Issue triage:**\n\n{task.description}\n\n"
            f"Reply **approve** to work on this issue, or **skip** to dismiss.",
            markdown=True,
        )
        # The confirm task stays blocked; the user's next message in
        # _on_agent_response_done or the chat handler will match
        # "approve"/"skip" and resolve the pending confirm.

    # -- Improvement confirmation ---------------------------------------------

    def _present_improvement_confirmation(self, task: AgentTask) -> None:
        """Show audit findings in chat and auto-approve all gaps.

        Called when the ``confirm-improvements`` task becomes blocked.
        Presents the audit report to the user, then immediately triggers
        fix task generation for all detected gaps.
        """
        if not self._app._agent:
            return

        # Find the audit result from the confirm task's dependencies.
        audit_report = ""
        for dep_id in task.dependencies:
            dep = self._app._agent.work_queue.get_task(dep_id)
            if dep is not None and dep.result:
                audit_report = dep.result
                # The audit tool stores structured gaps in task data, but
                # the subagent result is plain text.  Re-extract gaps from
                # the audit report heuristically, or approve all.
                break

        chat = self._app.query_one("#chat", chat_widget.ChatWidget)
        if audit_report:
            # Truncate long reports for the chat display.
            preview = audit_report[:2000]
            if len(audit_report) > 2000:
                preview += "\n\n*(truncated — full report in task result)*"
            chat.add_system_message(f"**Audit complete:**\n\n{preview}")

        chat.add_system_message("Approving all improvements. Generating fix tasks...")

        self._app.run_worker(
            self._complete_improvement_confirmation(task.id),
            name="improvement_confirmation",
            exclusive=False,
        )

    async def _complete_improvement_confirmation(self, confirm_id: str) -> None:
        """Approve the improvement confirm task and generate fix tasks."""
        if not self._app._agent:
            return

        self._app._agent.work_queue.set_done(confirm_id, "Approved by user")
        self.pending_confirm_id = None

        fix_tasks = await self._app._agent.handle_improvement_confirmation(confirm_id)

        chat = self._app.query_one("#chat", chat_widget.ChatWidget)
        if fix_tasks:
            titles = "\n".join(f"- {t.title}" for t in fix_tasks)
            chat.add_system_message(f"Improvement plan created:\n{titles}")
        else:
            chat.add_system_message(
                "No improvement tasks generated — the charm may already be up to standard."
            )
