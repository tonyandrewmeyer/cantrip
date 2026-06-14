"""Planning-confirmation handlers for the agent.

``PlanningConfirmationsMixin`` carries the three approve-and-generate
flows — design, day-2 operations, and improvement — that turn an
approved CONFIRM task's synthesis result into a batch of build / impl /
fix tasks on the work queue.  It is mixed into
:class:`~cantrip.agent.core.CantripAgent`; all instance state and the
sibling helpers (``_create_feature_branch``, ``_build_push_confirm_task``,
``_ensure_store``) are reached through ``self``.

The planner entry points that tests patch on :mod:`cantrip.agent.core`
(``parse_design_from_result``, ``TaskPlanner``, the one-shot / day-2
planners, ``_infer_gaps_from_audit``) are reached through the ``core``
module object at call time so those patches keep taking effect.
"""

from __future__ import annotations

import logging

from cantrip.agent.planner import PlanningContext, plan_improvement_fixes
from cantrip.agent.queue import AgentTask

log = logging.getLogger("cantrip.agent.core")


class PlanningConfirmationsMixin:
    """Design / day-2 / improvement approve-and-generate handlers."""

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
        from cantrip.agent import core

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
        proposal = core.parse_design_from_result(design_text)
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
        if core.is_one_shot_build(context) and not overrides:
            build_tasks = core.plan_one_shot_build(context, design_md)
        else:
            planner = core.TaskPlanner(self.provider, code_intel=self.code_intel)
            build_tasks = await planner.plan_from_design(
                design_content=design_md,
                context=context,
                overrides=overrides,
            )
        self._work_queue.add_tasks(build_tasks)

        # Append day-2 operations research phase after the build/deploy tasks.
        anchor = core.find_day2_anchor(build_tasks)
        if anchor:
            day2_tasks = core.plan_day2_ops_phase(context, depends_on=anchor)
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
        from cantrip.agent import core

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

        planner = core.TaskPlanner(self.provider, code_intel=self.code_intel)
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
        from cantrip.agent import core

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
        gaps = core._infer_gaps_from_audit(audit_text)

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
