"""Task planner — LLM-powered decomposition of user intent into agent tasks.

For the common "build a charm for X" flow, the research phase (Phase 1 + 2)
uses deterministic task templates — no LLM call needed.  LLM planning is
reserved for replanning (scope changes) and the build phase (which depends
on the approved design).
"""

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
    source_url: str | None = None


# ---------------------------------------------------------------------------
# Deterministic task templates
# ---------------------------------------------------------------------------

# Frameworks with well-understood 12-factor PaaS charm paths — skip research.
_FAST_PATH_FRAMEWORKS = frozenset(
    {
        "flask",
        "django",
        "fastapi",
        "go",
        "express",
        "spring-boot",
    }
)


def is_fast_path(context: PlanningContext) -> bool:
    """Return whether the context qualifies for the fast (no-research) path.

    Fast path applies when the framework is a known 12-factor type and
    no source URL needs deep analysis.
    """
    return (
        context.framework is not None
        and context.framework.lower() in _FAST_PATH_FRAMEWORKS
        and context.source_url is None
    )


def plan_fast_path(context: PlanningContext) -> list[AgentTask]:
    """Generate a compressed task list for well-known 12-factor frameworks.

    Skips the full research phase — produces a single synthesis task that
    generates a template-based design, then goes straight to confirm.
    """
    workload = context.charm_name or context.framework or "the workload"
    framework = context.framework or "unknown"

    return [
        AgentTask(
            id="fast-design",
            title=f"operational-discovery: design 12-factor charm for {workload}",
            category=TaskCategory.RESEARCH,
            description=(
                f"Generate a design proposal for a {framework} 12-factor PaaS charm. "
                f"This is a well-understood framework — use the paas-charm base with "
                f"the {framework}-framework profile. Include standard integrations "
                f"(ingress, database if applicable, COS). Search Charmhub briefly "
                f"to check for existing charms."
            ),
            dependencies=[],
        ),
        AgentTask(
            id="confirm-design",
            title="Confirm design with user",
            category=TaskCategory.CONFIRM,
            description="Present the design proposal for user approval.",
            dependencies=["fast-design"],
        ),
    ]


def plan_research_phase(context: PlanningContext) -> list[AgentTask]:
    """Generate the standard research → synthesis → confirm task sequence.

    These tasks are always the same structure for a "build a charm" request.
    Skips source-analysis if no source URL is provided.  Returns 4 or 5
    tasks depending on whether source analysis is needed.
    """
    workload = context.charm_name or "the workload"
    tasks: list[AgentTask] = []
    research_ids: list[str] = []

    if context.source_url:
        tasks.append(
            AgentTask(
                id="source-analysis",
                title=f"Analyse source repository for {workload}",
                category=TaskCategory.RESEARCH,
                description=(
                    f"Clone {context.source_url}, explore README, dependency files, "
                    "Dockerfiles, config files, and entry points. Run analyse_framework. "
                    "Write findings into WORKLOAD.md."
                ),
                dependencies=[],
            )
        )
        research_ids.append("source-analysis")

    tasks.append(
        AgentTask(
            id="web-research",
            title=f"Research {workload} documentation and operations",
            category=TaskCategory.RESEARCH,
            description=(
                f"Fetch official docs, project website, and deployment guides for {workload}. "
                "Focus on operational patterns: deployment, configuration, monitoring, scaling."
            ),
            dependencies=[],
        )
    )
    research_ids.append("web-research")

    tasks.append(
        AgentTask(
            id="charmhub-survey",
            title=f"Survey Charmhub for existing {workload} charms",
            category=TaskCategory.RESEARCH,
            description=(
                f"Search Charmhub for existing charms covering {workload}. "
                "Evaluate candidates: relations, config, storage, maintenance status."
            ),
            dependencies=[],
        )
    )
    research_ids.append("charmhub-survey")

    tasks.append(
        AgentTask(
            id="operational-discovery",
            title=f"operational-discovery: synthesise design for {workload}",
            category=TaskCategory.RESEARCH,
            description=(
                "Synthesise all research into a structured design proposal (DESIGN.md). "
                "Cover: substrate, charm path, Charmhub recommendation, integrations, "
                "config, actions, scaling, operational patterns, and open questions."
            ),
            dependencies=list(research_ids),
        )
    )

    tasks.append(
        AgentTask(
            id="confirm-design",
            title="Confirm design with user",
            category=TaskCategory.CONFIRM,
            description="Present the design proposal for user approval.",
            dependencies=["operational-discovery"],
        )
    )

    return tasks


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
        12-factor frameworks, the fast path skips research entirely.
        """
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
- "id": short unique slug (e.g. "source-analysis", "scaffold-charm")
- "title": concise imperative title (e.g. "Analyse the source repository")
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

### Research-first decomposition

For a typical charm build, always follow a **research → synthesis → confirm → build** \
pattern. Do NOT generate build tasks upfront — they are created after the user approves \
the design.

**Phase 1 — Research** (multiple parallel tasks, category: research):

- **source-analysis**: Clone the source repository, explore README, dependency files, \
Dockerfiles, configuration files, and entry points. Run `analyse_framework` to detect \
language and framework. Write findings into WORKLOAD.md.

- **web-research**: Fetch external documentation, project website, PyPI/npm pages, and \
deployment guides. Gather operational patterns: how the workload is typically deployed, \
configured, monitored, and scaled.

- **charmhub-survey**: Search Charmhub for existing charms that cover this workload. \
Use `charmhub_search` and `charmhub_info` to evaluate candidates — check relations, \
config, storage, containers, and maintenance status.

These three tasks have no dependencies on each other and can run in parallel.

**Phase 2 — Synthesis** (two tasks):

- **operational-discovery** (category: research, depends on all Phase 1 tasks): \
Synthesise the research findings into a structured design proposal. Cover: substrate \
choice (K8s vs machine) with reasoning, charm path (12-factor / custom / infrastructure), \
Charmhub recommendation (use existing / fork / build new), integrations, config options, \
actions, scaling strategy, operational patterns, and open questions for the user. \
Format the output as a DESIGN.md.

- **confirm-design** (category: confirm, depends on operational-discovery): \
Present the design proposal to the user for approval.

**Phase 3 — Build** is NOT generated at this stage. Build, deploy, and test tasks are \
created dynamically after the user confirms the design.

Adapt the pattern to the specific request — skip research tasks that do not apply (e.g. \
skip source-analysis if no source URL is given, skip charmhub-survey for a clearly novel \
workload). Always include operational-discovery and confirm-design.

### Context
{context_block}

Return a JSON array of task objects. Example:
```json
[
  {{"id": "source-analysis", "title": "Analyse the source repository", "category": \
"research", "description": "Clone the repo and explore the codebase structure, \
dependencies, and framework.", "dependencies": []}},
  {{"id": "web-research", "title": "Research workload documentation", "category": \
"research", "description": "Fetch external docs, deployment guides, and operational \
patterns.", "dependencies": []}},
  {{"id": "charmhub-survey", "title": "Survey Charmhub for existing charms", "category": \
"research", "description": "Search Charmhub and evaluate existing charms for this \
workload.", "dependencies": []}},
  {{"id": "operational-discovery", "title": "Synthesise design proposal", "category": \
"research", "description": "Combine all research into a structured design proposal \
(DESIGN.md).", "dependencies": ["source-analysis", "web-research", "charmhub-survey"]}},
  {{"id": "confirm-design", "title": "Confirm design with user", "category": "confirm", \
"description": "Present the design proposal for user approval.", "dependencies": \
["operational-discovery"]}}
]
```
"""

_DESIGN_TO_BUILD_PROMPT = """\
You are a task planner for Cantrip, an AI agent that builds Juju charms autonomously.

The user has approved a design proposal. Generate the **build, deploy, and test** tasks \
needed to implement it. Return **only** a JSON array — no surrounding text.

Each task object must have:
- "id": short unique slug (e.g. "scaffold-charm", "write-tests")
- "title": concise imperative title
- "category": one of {categories}
- "description": one or two sentences explaining what the task does
- "dependencies": list of task IDs that must complete before this one starts

### Typical build sequence

1. Scaffold the charm (charmcraft init, write metadata)
2. Write charm code (src/charm.py, Pebble layers, integrations)
3. Write unit tests (Scenario-based)
4. Pack and deploy
5. Run tests and validate
6. Commit and offer next steps

Adapt for the design — add rock-building steps for 12-factor charms, add integration \
wiring for complex workloads, skip steps that do not apply. Honour any user overrides.

### Context
{context_block}
"""


def _build_planning_prompt(context: PlanningContext) -> str:
    """Build the system prompt for a fresh planning call."""
    return _PLANNING_PROMPT.format(
        categories=", ".join(sorted(_VALID_CATEGORIES)),
        context_block=_format_context_block(context),
    )


def _build_design_to_build_prompt(context: PlanningContext) -> str:
    """Build the system prompt for generating build tasks from a design."""
    return _DESIGN_TO_BUILD_PROMPT.format(
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
