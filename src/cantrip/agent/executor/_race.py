"""Best-of-N race orchestration for the background executor.

``RaceMixin`` carries the race dispatch gate, the per-candidate subagent
factory, winner-merge wiring, and event recording that
:class:`~cantrip.agent.executor.core.BackgroundExecutor` mixes in.  The
single-subagent execution path stays in ``core``; this module holds only
the racing concern.
"""

import dataclasses
import logging
import pathlib
import re

from cantrip.agent.git.worktree import WorktreeHandle
from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.agent.race import race
from cantrip.agent.subagent import MAX_BUILD_ROUNDS, ExitState, Subagent
from cantrip.llm import base as llm

log = logging.getLogger(__name__)


# Characters allowed in a filesystem-safe candidate id derived from a
# provider's model name.  Everything else collapses to a single hyphen.
_CANDIDATE_ID_RE = re.compile(r"[^a-z0-9-]+")


def _candidate_id_for(provider: llm.LLMProvider) -> str:
    """Build a short, filesystem-safe candidate id from *provider*.

    The id lands in both a git branch name and a worktree directory, so
    it needs to be lowercase, ASCII, and punctuation-light.  Falls back
    to the provider's short name when the model name is absent, and to
    the literal ``candidate`` when both are empty.
    """
    raw = getattr(provider, "model_name", None) or provider.name or ""
    safe = _CANDIDATE_ID_RE.sub("-", raw.lower()).strip("-")
    return safe or "candidate"


class RaceMixin:
    """Best-of-N race orchestration mixed into ``BackgroundExecutor``.

    The methods here read executor state (``_provider``, ``_race_config``,
    ``_race_coordinator``, ``_queue``, …) and call back into the core
    execution helpers (``_merge_worktree``, ``_build_context``,
    ``_handle_result``, …) through ``self``; all of that state and those
    helpers live on :class:`BackgroundExecutor`.
    """

    def _race_candidate_specs(self) -> list[race.CandidateSpec]:
        """Build candidate specs for a race from the executor's providers.

        Always includes the primary provider.  The light provider (if
        configured) is added as a second candidate.  Any ``extra_providers``
        supplied to the constructor follow.  Duplicates by candidate id are
        filtered so the same model is never raced against itself.
        """
        seen: set[str] = set()
        specs: list[race.CandidateSpec] = []
        for provider in (self._provider, self._light_provider, *self._extra_providers):
            if provider is None:
                continue
            cid = _candidate_id_for(provider)
            if cid in seen:
                continue
            seen.add(cid)
            specs.append(
                race.CandidateSpec(
                    candidate_id=cid,
                    provider=provider,
                    light_provider=self._light_provider,
                )
            )
        return specs

    def _should_race(self, task: AgentTask, specs: list[race.CandidateSpec]) -> bool:
        """Return True when *task* should run via the race coordinator."""
        # Races need a charm path: the coordinator allocates per-candidate
        # worktrees, which fall back silently without one.
        if self._state.charm_path is None:
            return False
        return self._race_config.should_race(task.category, len(specs))

    def _dispatch_race_gate(
        self,
        task: AgentTask,
        specs: list[race.CandidateSpec],
    ) -> race.RaceGate:
        """Classify *task* against the race cost thresholds and act on it.

        A prior user decision stored on ``task.race_decision`` short-circuits
        the threshold check: an approved race runs silently, a declined race
        downgrades to a single-subagent run without re-prompting.  Otherwise
        the estimate is compared against the configured thresholds and the
        helper emits a CONFIRM task + blocks the parent when the soft
        threshold is crossed, or records a downgrade event when the hard
        budget is exceeded.
        """
        if task.race_decision == "approved":
            return race.RaceGate.RACE
        if task.race_decision == "declined":
            self._record_race_downgrade(task, specs, reason="user_declined")
            return race.RaceGate.DOWNGRADE

        estimate = race.estimate_race_tokens(
            baseline_tokens_per_run=self._race_config.baseline_tokens_per_run,
            candidate_count=len(specs),
        )
        gate = self._race_config.race_gate(estimate)

        if gate == race.RaceGate.DOWNGRADE:
            self._record_race_downgrade(task, specs, reason="over_budget", estimate=estimate)
        elif gate == race.RaceGate.CONFIRM:
            self._emit_race_confirm_task(task, specs, estimate)
        return gate

    def _emit_race_confirm_task(
        self,
        task: AgentTask,
        specs: list[race.CandidateSpec],
        estimate: int,
    ) -> None:
        """Add a CONFIRM task gating *task* on the user's approval.

        Idempotent: a pre-existing CONFIRM for the same parent is reused
        rather than re-created so a task that re-enters the executor (for
        any reason) does not flood the queue.  The parent task is moved
        to BLOCKED with a reason the TUI and Web surface pick up via the
        existing task-update bus.
        """
        confirm_id = f"{race.RACE_CONFIRM_PREFIX}{task.id}"
        candidate_names = ", ".join(s.candidate_id for s in specs)
        threshold = self._race_config.confirm_threshold_tokens
        description = (
            f"Racing **{len(specs)}** models ({candidate_names}) on "
            f"*{task.title}* is estimated to consume **~{estimate:,} tokens** — "
            f"above the configured race confirmation threshold of "
            f"**{threshold:,}**.\n\n"
            "Reply **yes** to proceed with the race, or **no** to run with a "
            "single model instead."
        )
        blocked_reason = (
            f"Awaiting race cost confirmation (~{estimate:,} tokens, {len(specs)} candidates)"
        )

        existing = self._queue.get_task(confirm_id)
        if existing is None:
            self._queue.add_task(
                AgentTask(
                    id=confirm_id,
                    title=f"Confirm race for '{task.title}'",
                    category=TaskCategory.CONFIRM,
                    description=description,
                    dependencies=[task.id],
                )
            )
        else:
            existing.description = description

        self._queue.set_blocked(task.id, blocked_reason)
        self._record_status_change(task, "blocked", error=blocked_reason)
        # Mark the confirm itself blocked so the TUI's task-updated
        # listener (which watches for CONFIRM+BLOCKED pairs) picks it up.
        self._queue.set_blocked(confirm_id, description)

        if self._state_service is not None:
            self._state_service.record_event(
                "race_confirm_requested",
                {
                    "task_id": task.id,
                    "task_title": task.title,
                    "confirm_task_id": confirm_id,
                    "estimate_tokens": str(estimate),
                    "threshold_tokens": str(threshold),
                    "candidates": candidate_names,
                },
            )

    def _record_race_downgrade(
        self,
        task: AgentTask,
        specs: list[race.CandidateSpec],
        *,
        reason: str,
        estimate: int | None = None,
    ) -> None:
        """Record that a would-be race ran as a single subagent instead."""
        log.info(
            "Race for task %s downgraded to single-subagent (%s, estimate=%s, candidates=%d)",
            task.id,
            reason,
            estimate,
            len(specs),
        )
        if self._state_service is None:
            return
        payload: dict[str, str] = {
            "task_id": task.id,
            "task_title": task.title,
            "reason": reason,
            "candidates": ",".join(s.candidate_id for s in specs),
        }
        if estimate is not None:
            payload["estimate_tokens"] = str(estimate)
            payload["budget_tokens"] = str(self._race_config.budget_tokens)
        self._state_service.record_event("race_downgraded", payload)

    def _build_race_subagent_factory(
        self,
        parent_task: AgentTask,
        monitor: race.RaceBudgetMonitor | None = None,
    ) -> race.SubagentFactory:
        """Return a factory that builds per-candidate subagents.

        Each candidate runs under a shadow task whose id is
        ``{parent_id}__{candidate_id}`` so the subagent's transcript
        records land in their own ``subagent_messages`` partition — every
        candidate's full tool-call trace is preserved for review, not
        just the winner's.

        *monitor* (Phase 47.4 follow-up) is the mid-flight budget
        monitor.  When supplied, each candidate's ``on_usage`` callback
        is wrapped so the monitor sees the per-round usage *before* the
        normal cost-recording path does.  Mid-flight cancellation kicks
        in through the watcher inside :class:`RaceCoordinator`.
        """

        async def factory(
            spec: race.CandidateSpec,
            work_path: pathlib.Path,
            _handle: WorktreeHandle | None,
        ) -> Subagent:
            shadow_task = dataclasses.replace(
                parent_task,
                id=f"{parent_task.id}__{spec.candidate_id}",
            )
            context = self._build_context(shadow_task, work_path)
            await self._attach_diagnostics_brief(context)
            # BUILD tasks get the extended round budget that non-race BUILD
            # subagents already enjoy; other categories use the default.
            extra: dict[str, int] = {}
            if parent_task.category == TaskCategory.BUILD:
                extra["max_rounds"] = MAX_BUILD_ROUNDS

            def on_usage(response: llm.Response) -> None:
                # Phase 47.4 follow-up: feed the mid-flight monitor
                # before the standard cost-recording path so the budget
                # trip races the next round, not the next call site.
                if monitor is not None:
                    monitor.record_candidate_usage(spec.candidate_id, response)
                self._record_usage(response)

            return Subagent(
                context,
                self._tools,
                spec.provider,
                light_provider=spec.light_provider or self._light_provider,
                on_usage=on_usage,
                throttle=self._throttle,
                store=self._store,
                on_phase_change=self._queue.notify_task,
                hook_runner=self._hook_runner,
                on_tool_invoked=self._on_tool_invoked,
                on_tool_invoked_pending=self._on_tool_invoked_pending,
                permissions=self._effective_permissions(),
                permission_manager=self._permission_manager,
                on_permission_decided=self._on_permission_decided,
                **extra,
            )

        return factory

    def _record_race_events(
        self,
        task: AgentTask,
        specs: list[race.CandidateSpec],
        result: race.RaceResult,
    ) -> None:
        """Write a ``race_finished`` event plus one per-candidate row.

        Each candidate's composite transcript id is recorded so a reviewer
        looking at ``subagent_messages`` can find the loser transcripts by
        joining on ``race_candidate.transcript_task_id``.
        """
        if self._state_service is None:
            return
        self._state_service.record_event(
            "race_finished",
            {
                "task_id": task.id,
                "task_title": task.title,
                "winner": result.winner.candidate_id if result.winner else "",
                "winner_score": f"{result.winner.total:.3f}" if result.winner else "",
                "candidates": ",".join(s.candidate_id for s in specs),
                "elapsed_s": f"{result.elapsed_seconds:.1f}",
            },
        )
        for candidate_score in result.all_scores:
            self._state_service.record_event(
                "race_candidate",
                {
                    "task_id": task.id,
                    "candidate_id": candidate_score.candidate_id,
                    "transcript_task_id": f"{task.id}__{candidate_score.candidate_id}",
                    "exit_state": candidate_score.exit_state.value,
                    "total": f"{candidate_score.total:.3f}",
                },
            )

    async def _release_race_worktree(
        self,
        task_id: str,
        candidate_id: str,
        *,
        keep_branch: bool,
    ) -> None:
        """Release a race candidate's composite-keyed worktree."""
        key = f"{task_id}__{candidate_id}"
        try:
            await self._worktrees.release(key, keep_branch=keep_branch)
        except (OSError, RuntimeError) as exc:
            log.warning("Worktree release failed for race key %s: %s", key, exc)

    async def _execute_race(
        self,
        task: AgentTask,
        specs: list[race.CandidateSpec],
    ) -> None:
        """Race *specs* against each other on *task* and apply the winner.

        The coordinator allocates its own worktrees, spawns every candidate
        concurrently, scores them, and releases losing worktrees.  This
        method merges the winner's worktree back into the main charm tree
        and sets the parent task's status.  Losing candidates' transcripts
        are preserved under composite task ids for post-hoc review.
        """
        base_path = self._state.charm_path
        assert base_path is not None  # _should_race guards this  # noqa: S101
        # Phase 47.4 follow-up: per-race budget monitor.  ``budget_tokens``
        # of zero disables the watcher entirely (matches the dispatch
        # gate's semantics for the same field).  The monitor's
        # ``cancel_event`` flips when the *actual* sum of per-round
        # usage across all candidates first crosses the hard cap —
        # giving us a mid-flight downgrade where the dispatch-time
        # ``estimate * candidate_count`` could only guess.
        monitor = race.RaceBudgetMonitor(budget_tokens=self._race_config.budget_tokens)
        build_subagent = self._build_race_subagent_factory(task, monitor=monitor)

        if self._state_service is not None:
            self._state_service.record_event(
                "race_started",
                {
                    "task_id": task.id,
                    "task_title": task.title,
                    "candidates": ",".join(s.candidate_id for s in specs),
                },
            )

        try:
            result = await self._race_coordinator.run(
                task_id=task.id,
                base_path=pathlib.Path(base_path),
                specs=specs,
                build_subagent=build_subagent,
                monitor=monitor,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            log.exception("Race for task %s failed: %s", task.id, exc)
            self._fail_task(task, f"Race coordinator error: {exc}", exc, snapshot=None)
            self._create_followups(task)
            self._persist()
            return

        self._record_race_events(task, specs, result)

        if result.cancelled_for_budget:
            # Phase 47.4 follow-up: mid-flight downgrade.  The race was
            # cancelled because the *actual* token usage crossed the
            # hard budget cap.  Decline the race for this task so the
            # next executor pass takes the single-subagent path,
            # record the downgrade event for visibility in ``/cost`` /
            # ``/diagnostics``, and reset the task to PENDING so the
            # main loop re-picks it up.
            self._record_race_downgrade(
                task,
                specs,
                reason="over_budget_midflight",
                estimate=result.total_tokens_at_cancel,
            )
            task.race_decision = "declined"
            self._queue.set_pending(task.id)
            self._persist()
            return

        if result.winner is None or result.winner_outcome is None:
            self._fail_task(task, "All race candidates failed", None, snapshot=None)
            self._create_followups(task)
            self._persist()
            return

        winner_outcome = result.winner_outcome
        winner_result = winner_outcome.result
        winner_handle = winner_outcome.handle
        # A viable winner always carries a result; the coordinator's scoring
        # layer forces a zero-total on ``result is None`` so pick_winner
        # cannot select it.
        assert winner_result is not None  # noqa: S101
        winner_candidate_id = winner_outcome.spec.candidate_id

        # Non-COMPLETED winners (BLOCKED / NOOP) skip the merge: we do not
        # want to land a half-finished change on main.  Defer to the shared
        # result handler to transition the parent task's status the same
        # way a single-subagent run would.
        if winner_result.exit_state != ExitState.COMPLETED:
            await self._release_race_worktree(
                task.id,
                winner_candidate_id,
                keep_branch=winner_result.exit_state == ExitState.BLOCKED,
            )
            self._handle_result(task, winner_result, fp_before="", effective_path=None)
            self._create_followups(task)
            self._persist()
            return

        merge_error: str | None = None
        if winner_handle is not None:
            try:
                merge_error = await self._merge_worktree(winner_handle, task)
            except (OSError, RuntimeError) as exc:
                log.exception("Race winner merge for %s failed: %s", task.id, exc)
                merge_error = f"merge failed: {exc}"

        if merge_error is not None:
            self._queue.set_blocked(task.id, merge_error)
            self._record_status_change(task, "blocked", error=merge_error)
            if self._on_task_failed:
                self._on_task_failed(task)
        else:
            self._queue.set_done(task.id, winner_result.text)
            self._record_status_change(task, "done")
            if task.category in (TaskCategory.BUILD, TaskCategory.DEBUG):
                self._check_uncommitted(task)
            if self._on_task_done:
                self._on_task_done(task)

        await self._release_race_worktree(
            task.id,
            winner_candidate_id,
            keep_branch=merge_error is not None,
        )
        self._create_followups(task)
        self._persist()
