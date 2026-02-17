"""Task planner — LLM-powered decomposition of user intent into agent tasks."""

import json
import logging
import re
from dataclasses import dataclass, field

from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.llm import base as llm

log = logging.getLogger(__name__)

# Temperature used for planning calls — low to encourage structured output.
_PLANNING_TEMPERATURE = 0.3

# Valid task categories for validation.
_VALID_CATEGORIES = {c.value for c in TaskCategory}


@dataclass
class PlanningContext:
    """Bundles context for a planning or replanning call."""

    intent: str
    charm_name: str | None = None
    charm_type: str | None = None
    framework: str | None = None
    dev_model: str | None = None
    cos_model: str | None = None
    environment_ready: bool = False
    existing_tasks: list[AgentTask] = field(default_factory=list)
    new_context: str | None = None


class TaskPlanner:
    """Stateless planner that decomposes intent into ordered agent tasks.

    Takes an ``LLMProvider``, builds a planning prompt, calls the LLM,
    and parses the JSON response into ``AgentTask`` objects.
    """

    def __init__(self, provider: llm.LLMProvider) -> None:
        self._provider = provider

    async def plan(self, context: PlanningContext) -> list[AgentTask]:
        """Decompose *context.intent* into an ordered list of tasks."""
        prompt = _build_planning_prompt(context)
        messages = [
            llm.Message(role=llm.Role.SYSTEM, content=prompt),
            llm.Message(role=llm.Role.USER, content=context.intent),
        ]
        response = await self._provider.complete(
            messages=messages,
            tools=None,
            temperature=_PLANNING_TEMPERATURE,
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
        )
        new_tasks = _parse_task_list(response.content)
        return _merge_tasks(context.existing_tasks, new_tasks)


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

_PLANNING_PROMPT = """\
You are a task planner for Cantrip, an AI agent that builds Juju charms autonomously.

Given the user's intent, decompose it into a concrete, ordered list of tasks. Return
**only** a JSON array — no surrounding text or explanation.

Each task object must have:
- "id": short unique slug (e.g. "research-workload", "scaffold-charm")
- "title": concise imperative title (e.g. "Research the Redis workload")
- "category": one of {categories}
- "description": one or two sentences explaining what the task does
- "dependencies": list of task IDs that must complete before this one starts (may be empty)

### Category guide

- **research** — fetch documentation, explore source code, query Charmhub/registries
- **build** — scaffold, write charm code, write rockcraft.yaml, write tests
- **deploy** — pack, push images, deploy with Juju, refresh
- **test** — run unit tests, integration tests, validate the charm
- **debug** — investigate failures, query logs/traces, fix issues
- **infra** — set up the development environment, bootstrap controllers
- **confirm** — present a decision to the user and wait for approval

### Decomposition patterns

For a typical charm build:
1. Research the workload (clone source, analyse framework, check Charmhub)
2. Confirm the approach with the user (path, substrate, key decisions)
3. Scaffold the charm (charmcraft init, write charm code, add integrations)
4. Write unit tests
5. Pack and deploy
6. Run tests and validate
7. Commit and offer next steps

Adapt the pattern to the specific request — skip steps that do not apply, add steps
for complex requirements (e.g. multiple relations, custom actions, rock builds).

### Context
{context_block}

Return a JSON array of task objects. Example:
```json
[
  {{"id": "research", "title": "Research the workload", "category": "research", "description": "Clone and analyse the source repository.", "dependencies": []}},
  {{"id": "confirm-approach", "title": "Confirm approach with user", "category": "confirm", "description": "Present substrate and path choice for approval.", "dependencies": ["research"]}}
]
```
"""


def _build_planning_prompt(context: PlanningContext) -> str:
    """Build the system prompt for a fresh planning call."""
    return _PLANNING_PROMPT.format(
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
    """
    raw = _extract_json(content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse task list JSON: {exc}") from exc

    # Unwrap {"tasks": [...]} if present.
    if isinstance(data, dict):
        if "tasks" in data and isinstance(data["tasks"], list):
            data = data["tasks"]
        else:
            raise ValueError('Expected a JSON array of tasks or {"tasks": [...]}')

    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of tasks")

    return [_parse_single_task(item, idx) for idx, item in enumerate(data)]


def _parse_single_task(item: dict, index: int) -> AgentTask:
    """Validate and construct a single ``AgentTask`` from parsed JSON."""
    if not isinstance(item, dict):
        raise ValueError(f"Task at index {index} is not an object")

    title = item.get("title")
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
        title=title,
        category=TaskCategory(raw_category),
        description=str(item.get("description", "")),
        dependencies=[str(d) for d in dependencies],
    )


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
