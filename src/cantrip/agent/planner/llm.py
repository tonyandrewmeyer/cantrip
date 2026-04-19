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
``cantrip.agent.prompts.planning``; this module only assembles context,
invokes the provider, and parses the JSON response.
"""

from __future__ import annotations

import json
import logging
import re

from cantrip.agent.planner.context import PlanningContext
from cantrip.agent.planner.deterministic import (
    is_fast_path,
    is_improvement,
    is_sprint,
    plan_fast_path,
    plan_improvement_phase,
    plan_research_phase,
    plan_sprint_deploy,
)
from cantrip.agent.prompts import planning as planning_prompts
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.llm import base as llm

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
    """

    def __init__(self, provider: llm.LLMProvider) -> None:
        self._provider = provider

    async def plan(self, context: PlanningContext) -> list[AgentTask]:
        """Decompose *context.intent* into an ordered list of tasks.

        Uses deterministic templates — no LLM call.  For well-known
        12-factor frameworks or explicit charm types, the sprint path
        goes straight to build + deploy.  For improvement requests,
        generates the audit → confirm flow.
        """
        if is_improvement(context):
            return plan_improvement_phase(context)
        if is_sprint(context):
            return plan_sprint_deploy(context)
        if is_fast_path(context):
            return plan_fast_path(context)
        return plan_research_phase(context)

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
        response = await self._provider.complete(
            messages=messages,
            tools=None,
            temperature=_PLANNING_TEMPERATURE,
            thinking_budget=_PLANNING_THINKING_BUDGET,
        )
        return _parse_task_list(response.content)

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
        response = await self._provider.complete(
            messages=messages,
            tools=None,
            temperature=_PLANNING_TEMPERATURE,
            thinking_budget=_PLANNING_THINKING_BUDGET,
        )
        new_tasks = _parse_task_list(response.content)
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
        response = await self._provider.complete(
            messages=messages,
            tools=None,
            temperature=_PLANNING_TEMPERATURE,
            thinking_budget=_PLANNING_THINKING_BUDGET,
        )
        return _parse_task_list(response.content)


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
# JSON parsing
# ---------------------------------------------------------------------------


def _extract_json(content: str) -> str:
    """Strip markdown code fences from LLM output."""
    # Match ```json ... ``` or ``` ... ``` blocks.
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return content.strip()


def _parse_task_list(content: str) -> list[AgentTask]:
    """Parse the LLM response into a list of ``AgentTask`` objects.

    Handles:
    - Raw JSON arrays
    - JSON wrapped in markdown code fences
    - ``{"tasks": [...]}`` wrapper objects

    Individual malformed task items are logged and skipped rather than
    failing the whole batch — smaller LLMs (e.g. Gemini flash) occasionally
    emit an item with no title, and dropping it preserves the rest of the
    plan.  Raises only when the content isn't parseable JSON, the shape
    isn't an array, or every item fails to parse.
    """
    raw = _extract_json(content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("LLM returned unparseable planning JSON: %s", _truncate(content, 1000))
        raise ValueError(f"Failed to parse task list JSON: {exc}") from exc

    # Unwrap {"tasks": [...]} if present.
    if isinstance(data, dict):
        if "tasks" in data and isinstance(data["tasks"], list):
            data = data["tasks"]
        else:
            raise ValueError('Expected a JSON array of tasks or {"tasks": [...]}')

    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of tasks")

    tasks: list[AgentTask] = []
    for idx, item in enumerate(data):
        try:
            tasks.append(_parse_single_task(item, idx))
        except ValueError as exc:
            log.warning(
                "Skipping malformed task at index %d: %s — raw item: %r",
                idx,
                exc,
                item,
            )

    # Only fail hard when the LLM tried to produce tasks but we rejected them
    # all.  An empty list from the LLM (``[]``) is a deliberate "no tasks" and
    # is returned as-is — some replanning calls correctly produce no new tasks.
    if data and not tasks:
        log.warning("LLM planning response had no usable tasks: %s", _truncate(content, 1000))
        raise ValueError("No valid tasks in planning response")

    _validate_dependencies(tasks)
    return tasks


def _truncate(text: str, limit: int) -> str:
    """Return ``text`` truncated to ``limit`` characters with an ellipsis marker."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"… [truncated, total {len(text)} chars]"


# Alternate keys some models emit instead of "title".  Tried in order.
_TITLE_FALLBACK_KEYS = ("name", "task", "summary")


def _parse_single_task(item: dict, index: int) -> AgentTask:
    """Validate and construct a single ``AgentTask`` from parsed JSON.

    Accepts ``title`` or, as a fallback, any of ``name`` / ``task`` /
    ``summary`` — smaller models occasionally use these keys instead.
    Raises ``ValueError`` when none of them are present or usable.
    """
    if not isinstance(item, dict):
        raise ValueError(f"Task at index {index} is not an object")

    title = item.get("title")
    if not title:
        for key in _TITLE_FALLBACK_KEYS:
            candidate = item.get(key)
            if candidate:
                title = str(candidate)
                log.info(
                    "Task at index %d used %r instead of 'title'",
                    index,
                    key,
                )
                break
    if not title:
        raise ValueError(f"Task at index {index} is missing a title")

    raw_category = str(item.get("category", "build")).lower()
    if raw_category not in _VALID_CATEGORIES:
        log.warning("Unknown category %r in task %r — defaulting to 'build'", raw_category, title)
        raw_category = "build"

    dependencies = item.get("dependencies", [])
    if not isinstance(dependencies, list):
        dependencies = []

    return AgentTask(
        id=str(item.get("id", "")),
        title=str(title),
        category=TaskCategory(raw_category),
        description=str(item.get("description", "")),
        dependencies=[str(d) for d in dependencies],
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
    for task in new:
        if task.id not in preserved_ids:
            merged.append(task)

    return merged
