"""LLM-driven task planning — replanning, design→build, day2→build.

Deterministic planning handles the common "build a charm for X" flow
without a model call (see ``deterministic``).  This module is the
fallback for cases where the plan depends on free-form user input:

- ``TaskPlanner.plan_from_design`` — generate build/deploy/test tasks
  from an approved design doc.
- ``TaskPlanner.plan_from_day2_findings`` — generate implementation
  tasks from a confirmed day-2 operations plan.
- ``TaskPlanner.replan`` — adapt existing tasks when the scope changes.

The guidance the LLM sees lives in Jinja2 templates under
``cantrip.agent.prompts.planning``; this module assembles context,
routes the call through :func:`cantrip.llm.structured.complete_structured`
against :data:`~cantrip.llm.schemas.PLANNER_BRIEFING`, and converts
the schema-validated briefing into :class:`~cantrip.agent.queue.AgentTask`
objects.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from cantrip.agent.planner.deterministic import (
    is_fast_path,
    is_improvement,
    is_sprint,
    plan_fast_path,
    plan_improvement_phase,
    plan_research_phase,
    plan_sprint_deploy,
)
from cantrip.agent.planner.prefetch import prefetch_symbol_block
from cantrip.agent.prompts import planning as planning_prompts
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.llm import base as llm
from cantrip.llm.schemas import PLANNER_BRIEFING
from cantrip.llm.structured import complete_structured

if TYPE_CHECKING:
    from cantrip.agent.planner.context import PlanningContext
    from cantrip.codeintel import CodeIntelQuery

log = logging.getLogger(__name__)

# Temperature used for planning calls — low to encourage structured output.
_PLANNING_TEMPERATURE = 0.3

# Extended-thinking budget for planner calls.  Task decomposition from a
# design doc benefits from structured reasoning; 4000 tokens is enough
# for the model to enumerate steps, dependencies, and tradeoffs without
# bloating latency or cost.  Providers that don't support extended
# thinking (inference-snap) ignore this parameter transparently.
_PLANNING_THINKING_BUDGET = 4000

# Valid task categories for validation.
_VALID_CATEGORIES = {c.value for c in TaskCategory}


class TaskPlanner:
    """Stateless planner that decomposes intent into ordered agent tasks.

    For fresh "build a charm" requests, uses deterministic templates for
    the research phase (no LLM call).  Falls back to the LLM for
    replanning and for generating build-phase tasks from an approved design.

    The optional ``code_intel`` argument enables Phase 72b.3 symbol
    prefetch: when a task title or the user's intent mentions a
    workspace symbol the indexer recognises, a compact definition
    block is appended to the matching task descriptions so the
    BUILD/DEBUG subagent does not burn a turn on navigation.  Pass
    ``None`` (or omit) to keep the planner unchanged.
    """

    def __init__(
        self,
        provider: llm.LLMProvider,
        code_intel: CodeIntelQuery | None = None,
    ) -> None:
        self._provider = provider
        self._code_intel = code_intel

    async def plan(self, context: PlanningContext) -> list[AgentTask]:
        """Decompose *context.intent* into an ordered list of tasks.

        Uses deterministic templates — no LLM call.  For well-known
        12-factor frameworks or explicit charm types, the sprint path
        goes straight to build + deploy.  For improvement requests,
        generates the audit → confirm flow.
        """
        if is_improvement(context):
            tasks = plan_improvement_phase(context)
        elif is_sprint(context):
            tasks = plan_sprint_deploy(context)
        elif is_fast_path(context):
            tasks = plan_fast_path(context)
        else:
            tasks = plan_research_phase(context)
        self._enrich_with_prefetch(tasks, context)
        return tasks

    async def plan_from_design(
        self,
        design_content: str,
        context: PlanningContext,
        overrides: str | None = None,
    ) -> list[AgentTask]:
        """Generate build/deploy/test tasks from an approved design.

        Called after the user confirms the design proposal.  Uses a
        dedicated prompt that focuses on the implementation phase.
        """
        prompt = _build_design_to_build_prompt(context)
        user_msg = f"## Approved design\n\n{design_content}"
        if overrides:
            user_msg += f"\n\n## User overrides\n\n{overrides}"
        messages = [
            llm.Message(role=llm.Role.SYSTEM, content=prompt),
            llm.Message(role=llm.Role.USER, content=user_msg),
        ]
        briefing = await complete_structured(
            self._provider,
            messages,
            PLANNER_BRIEFING,
            tools=None,
            temperature=_PLANNING_TEMPERATURE,
            thinking_budget=_PLANNING_THINKING_BUDGET,
        )
        tasks = _briefing_to_tasks(briefing)
        self._enrich_with_prefetch(tasks, context, design_content, overrides)
        return tasks

    async def replan(self, context: PlanningContext) -> list[AgentTask]:
        """Adapt existing tasks given new context or changed scope.

        Completed and active tasks are preserved; pending tasks are
        replaced by the new plan.
        """
        prompt = _build_replanning_prompt(context)
        messages = [
            llm.Message(role=llm.Role.SYSTEM, content=prompt),
            llm.Message(
                role=llm.Role.USER,
                content=context.new_context or context.intent,
            ),
        ]
        briefing = await complete_structured(
            self._provider,
            messages,
            PLANNER_BRIEFING,
            tools=None,
            temperature=_PLANNING_TEMPERATURE,
            thinking_budget=_PLANNING_THINKING_BUDGET,
        )
        new_tasks = _briefing_to_tasks(briefing)
        self._enrich_with_prefetch(new_tasks, context)
        return _merge_tasks(context.existing_tasks, new_tasks)

    async def plan_from_day2_findings(
        self,
        findings: str,
        context: PlanningContext,
        overrides: str | None = None,
    ) -> list[AgentTask]:
        """Generate implementation tasks from confirmed day-2 findings.

        Called after the user discusses and approves the day-2 operations
        plan.  Uses a dedicated prompt focused on adding operational
        features to an existing charm.
        """
        prompt = _build_day2_to_build_prompt(context)
        user_msg = f"## Approved day-2 operations plan\n\n{findings}"
        if overrides:
            user_msg += f"\n\n## User overrides\n\n{overrides}"
        messages = [
            llm.Message(role=llm.Role.SYSTEM, content=prompt),
            llm.Message(role=llm.Role.USER, content=user_msg),
        ]
        briefing = await complete_structured(
            self._provider,
            messages,
            PLANNER_BRIEFING,
            tools=None,
            temperature=_PLANNING_TEMPERATURE,
            thinking_budget=_PLANNING_THINKING_BUDGET,
        )
        tasks = _briefing_to_tasks(briefing)
        self._enrich_with_prefetch(tasks, context, findings, overrides)
        return tasks

    # -- prefetch -------------------------------------------------------

    def _enrich_with_prefetch(
        self,
        tasks: list[AgentTask],
        context: PlanningContext,
        *extra_signals: str | None,
    ) -> None:
        """Append a symbol-prefetch block to relevant task descriptions.

        Phase 72b.3.  No-op when a code-intelligence index is not
        configured.  Each task is enriched at most once; the block
        comes from the *task's own title and description*, falling
        back to the planner's user-side signals (intent / new context
        / extra signals like the design or day-2 findings) so a
        terse title like "fix bug" still picks up the symbol the
        user actually mentioned.
        """
        if self._code_intel is None or not tasks:
            return
        # The shared signals — intent, new_context, and any extras
        # (design content, day-2 findings, overrides) — let a task
        # whose own text is symbol-free still benefit from the
        # context the user provided up-stream.
        shared = [context.intent, context.new_context, *extra_signals]
        shared_text = "\n".join(s for s in shared if s)
        for task in tasks:
            task_text = "\n".join([task.title, task.description])
            block = prefetch_symbol_block(task_text, self._code_intel)
            if block is None and shared_text:
                block = prefetch_symbol_block(shared_text, self._code_intel)
            if block is None:
                continue
            if task.description:
                task.description = f"{task.description.rstrip()}\n\n{block}"
            else:
                task.description = block


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def _build_planning_prompt(context: PlanningContext) -> str:
    """Build the system prompt for a fresh planning call."""
    return planning_prompts.render_full(
        categories=", ".join(sorted(_VALID_CATEGORIES)),
        context_block=_format_context_block(context),
    )


def _build_design_to_build_prompt(context: PlanningContext) -> str:
    """Build the system prompt for generating build tasks from a design."""
    return planning_prompts.render_design_to_build(
        categories=", ".join(sorted(_VALID_CATEGORIES)),
        context_block=_format_context_block(context),
    )


def _build_replanning_prompt(context: PlanningContext) -> str:
    """Build the system prompt for a replanning call.

    Includes the existing task list so the LLM can see what has already
    been completed and what is still pending.
    """
    existing_json = json.dumps(
        [
            {
                "id": t.id,
                "title": t.title,
                "category": t.category.value,
                "status": t.status.value,
                "description": t.description,
            }
            for t in context.existing_tasks
        ],
        indent=2,
    )
    extra = (
        "\n\n### Existing tasks\n\n"
        "The following tasks already exist. Tasks with status 'done' or 'active' must "
        "NOT be replaced — only produce new tasks for work that is still pending. "
        "You may drop, reorder, or add pending tasks as needed.\n\n"
        f"```json\n{existing_json}\n```"
    )
    base = _build_planning_prompt(context)
    return base + extra


def _build_day2_to_build_prompt(context: PlanningContext) -> str:
    """Build the system prompt for generating tasks from day-2 findings."""
    return planning_prompts.render_day2_to_build(
        categories=", ".join(sorted(_VALID_CATEGORIES)),
        context_block=_format_context_block(context),
    )


def _format_context_block(context: PlanningContext) -> str:
    """Format the context variables section of the planning prompt."""
    lines: list[str] = []
    if context.charm_name:
        lines.append(f"- Charm name: {context.charm_name}")
    if context.charm_type:
        lines.append(f"- Charm type: {context.charm_type}")
    if context.framework:
        lines.append(f"- Framework: {context.framework}")
    if context.dev_model:
        lines.append(f"- Dev model: {context.dev_model}")
    if context.cos_model:
        lines.append(f"- COS model: {context.cos_model}")
    if context.source_url:
        lines.append(f"- Source URL: {context.source_url}")
    if context.environment_ready:
        lines.append("- Environment: ready")
    else:
        lines.append("- Environment: not yet provisioned")
    return "\n".join(lines) if lines else "No additional context."


# ---------------------------------------------------------------------------
# Briefing → AgentTask conversion
# ---------------------------------------------------------------------------


def _briefing_to_tasks(briefing: dict) -> list[AgentTask]:
    """Convert a schema-validated planner briefing into ``AgentTask`` objects.

    The :data:`~cantrip.llm.schemas.PLANNER_BRIEFING` schema guarantees the
    top-level shape (``{"tasks": [...]}``), required keys (``title``,
    ``category``), and the category enum.  This helper trusts those
    invariants and focuses on the conversion plus dependency-graph
    sanitisation that the schema does not cover.
    """
    items = briefing.get("tasks", [])
    tasks = [_briefing_item_to_task(item) for item in items]
    _validate_dependencies(tasks)
    return tasks


def _briefing_item_to_task(item: dict) -> AgentTask:
    """Build an ``AgentTask`` from a single PLANNER_BRIEFING ``tasks[]`` entry."""
    return AgentTask(
        id=str(item.get("id", "")),
        title=str(item["title"]),
        category=TaskCategory(item["category"]),
        description=str(item.get("description", "")),
        dependencies=[str(d) for d in item.get("dependencies", [])],
    )


def _validate_dependencies(tasks: list[AgentTask]) -> None:
    """Validate and sanitise task dependencies.

    Strips references to non-existent task IDs and detects cycles.
    Logs a warning for each invalid dependency rather than raising.
    """
    valid_ids = {t.id for t in tasks}

    # Strip references to tasks not in this plan.
    for task in tasks:
        invalid = [d for d in task.dependencies if d not in valid_ids]
        if invalid:
            log.warning(
                "Task %r references non-existent dependencies %s — stripping them",
                task.id,
                invalid,
            )
            task.dependencies = [d for d in task.dependencies if d in valid_ids]

    # Simple cycle detection via topological sort (Kahn's algorithm).
    in_degree: dict[str, int] = {t.id: 0 for t in tasks}
    for task in tasks:
        for dep in task.dependencies:
            if dep in in_degree:
                in_degree[dep] = in_degree[dep]  # dep exists — no-op, counted below

    # Recount properly: in_degree[x] = number of tasks that depend on x.
    # Actually, for cycle detection we need: in_degree[t] = len(t.dependencies).
    in_degree = {t.id: len(t.dependencies) for t in tasks}
    adjacency: dict[str, list[str]] = {t.id: [] for t in tasks}
    for task in tasks:
        for dep in task.dependencies:
            adjacency[dep].append(task.id)

    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for successor in adjacency[node]:
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                queue.append(successor)

    if visited < len(tasks):
        cycle_ids = [tid for tid, deg in in_degree.items() if deg > 0]
        log.warning(
            "Dependency cycle detected among tasks %s — stripping all dependencies in cycle",
            cycle_ids,
        )
        cycle_set = set(cycle_ids)
        for task in tasks:
            if task.id in cycle_set:
                task.dependencies = [d for d in task.dependencies if d not in cycle_set]


# ---------------------------------------------------------------------------
# Task merging (for replanning)
# ---------------------------------------------------------------------------


def _merge_tasks(
    existing: list[AgentTask],
    new: list[AgentTask],
) -> list[AgentTask]:
    """Merge new planned tasks with existing ones.

    - Completed and active tasks are preserved (appear first).
    - Pending tasks from the existing list are dropped.
    - New tasks are appended after preserved tasks.
    - If a new task ID collides with a completed/active task, the
      completed/active task wins and the duplicate is discarded.
    """
    preserved: list[AgentTask] = []
    preserved_ids: set[str] = set()

    for task in existing:
        if task.status in (TaskStatus.DONE, TaskStatus.ACTIVE):
            preserved.append(task)
            preserved_ids.add(task.id)

    merged = list(preserved)
    merged.extend(task for task in new if task.id not in preserved_ids)

    return merged
