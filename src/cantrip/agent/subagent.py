"""Subagent runner — isolated LLM context for autonomous task execution."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.llm import base as llm

log = logging.getLogger(__name__)

# Focused tasks need fewer rounds than the open-ended conversation loop.
MAX_SUBAGENT_ROUNDS = 12

_TRANSIENT_RETRIES = 3
_TRANSIENT_BASE_DELAY = 30  # seconds

# Action-oriented — slightly more deterministic than conversation (0.7).
_SUBAGENT_TEMPERATURE = 0.5

# Categories routed to the light (cheaper) model.
_LIGHT_CATEGORIES = frozenset({TaskCategory.RESEARCH, TaskCategory.INFRA})

# ---------------------------------------------------------------------------
# Tool allowlists per category
# ---------------------------------------------------------------------------

_CATEGORY_TOOLS: dict[TaskCategory, frozenset[str]] = {
    TaskCategory.RESEARCH: frozenset(
        {
            "web_fetch",
            "charmhub_search",
            "charmhub_info",
            "registry_search",
            "registry_image_info",
            "git_clone",
            "read_file",
            "write_file",
            "list_directory",
            "analyse_framework",
            "load_skill",
            "gh_issue_list",
            "virtual_file_read",
            "virtual_file_search",
        }
    ),
    TaskCategory.BUILD: frozenset(
        {
            "read_file",
            "write_file",
            "edit_file",
            "list_directory",
            "charmcraft_init",
            "charmcraft_fetch_libs",
            "rockcraft_init",
            "analyse_framework",
            "load_skill",
            "git_init",
            "git_status",
            "git_diff",
            "git_add",
            "git_commit",
            "git_log",
            "registry_search",
            "registry_image_info",
            "generate_readme",
            "virtual_file_read",
            "virtual_file_search",
        }
    ),
    TaskCategory.DEPLOY: frozenset(
        {
            "charmcraft_pack",
            "charmcraft_fetch_libs",
            "rockcraft_pack",
            "skopeo_registry_push",
            "juju_status",
            "juju_deploy",
            "juju_refresh",
            "juju_relate",
            "juju_add_model",
            "juju_offer",
            "juju_consume",
            "juju_config",
            "juju_wait",
            "charm_sync",
            "juju_dispatch",
            "charmcraft_upload",
            "charmcraft_release",
            "read_file",
            "list_directory",
            "virtual_file_read",
            "virtual_file_search",
        }
    ),
    TaskCategory.TEST: frozenset(
        {
            "run_charm_tests",
            "charm_validate",
            "charmcraft_pack",
            "juju_status",
            "juju_run_action",
            "juju_relate",
            "juju_wait",
            "read_file",
            "list_directory",
            "virtual_file_read",
            "virtual_file_search",
        }
    ),
    TaskCategory.DEBUG: frozenset(
        {
            "juju_debug_log",
            "tempo_query",
            "loki_query",
            "juju_status",
            "juju_ssh",
            "juju_config",
            "juju_dispatch",
            "charm_sync",
            "read_file",
            "edit_file",
            "list_directory",
            "git_diff",
            "git_status",
            "load_skill",
            "virtual_file_read",
            "virtual_file_search",
        }
    ),
    TaskCategory.INFRA: frozenset(
        {
            "concierge_prepare",
            "concierge_status",
            "juju_add_model",
            "juju_destroy_model",
            "gh_repo_create",
            "git_push",
            "git_init",
        }
    ),
    # CONFIRM tasks are handled by the conversation loop, not subagents.
}


@dataclass
class SubagentContext:
    """Everything a subagent needs — constructed by the executor before each run."""

    task: AgentTask
    charm_name: str | None = None
    charm_path: str | None = None
    charm_type: str | None = None
    framework: str | None = None
    dev_model: str | None = None
    cos_model: str | None = None
    decisions: list[dict[str, Any]] = field(default_factory=list)
    prior_results: dict[str, str] = field(default_factory=dict)
    design_content: str | None = None


# ---------------------------------------------------------------------------
# Category-specific guidance injected into the system prompt
# ---------------------------------------------------------------------------

_CATEGORY_GUIDANCE: dict[TaskCategory, str] = {
    TaskCategory.RESEARCH: (
        "### Research principles\n\n"
        "- **Cite sources**: include URLs, file paths, and version numbers for every claim.\n"
        "- **Structured output**: use Markdown with clear headings so downstream tasks "
        "can parse your findings.\n"
        "- **Flag gaps**: mark anything you could not determine as `[UNKNOWN]` rather than "
        "guessing.\n\n"
        "### Task-type guidance\n\n"
        "**source-analysis**: Clone the repository, read README, dependency files "
        "(requirements.txt, pyproject.toml, package.json, go.mod, pom.xml), "
        "Dockerfile/docker-compose.yml, configuration files, and entry points. "
        "Run `analyse_framework` to detect language and framework. "
        "Write findings into WORKLOAD.md at the charm root.\n\n"
        "**web-research**: Fetch external documentation, project website, PyPI/npm "
        "pages, and deployment guides. Focus on operational patterns: how the workload "
        "is deployed, configured, monitored, and scaled in production.\n\n"
        "**charmhub-survey**: Search Charmhub for existing charms covering this workload. "
        "Use `charmhub_search` and `charmhub_info` to evaluate candidates — check "
        "relations, config, storage, containers, and maintenance status.\n\n"
        "**operational-discovery**: Synthesise all research into a structured design "
        "proposal. Answer the operational story questions:\n"
        "- **Storage**: What data does the workload persist? File paths, databases, volumes?\n"
        "- **Clustering**: Does it support clustering, replication, or federation?\n"
        "- **Health**: What health/readiness endpoints or probes does it offer?\n"
        "- **Config**: What are the critical configuration knobs?\n"
        "- **Failure modes**: How does it fail? What recovery mechanisms exist?\n"
        "- **Integrations**: What external services does it connect to?\n"
        "- **Observability**: What metrics, logs, and traces does it emit?\n"
        "- **Scaling**: How does it scale — horizontally, vertically, or both?\n"
        "- **Backup**: What backup/restore procedures does it support?\n\n"
        "Format the output as DESIGN.md with clear headings for each section.\n\n"
        "**Important — structured questions**: The ## Questions section must use this "
        "exact format. Each question is a top-level bullet with a **bold key** prefix, "
        "followed by 2-3 indented sub-bullets as suggested answers:\n\n"
        "```\n"
        "## Questions\n"
        "- **Substrate**: Should this charm target Kubernetes or machine?\n"
        "  - Kubernetes (recommended — Dockerfile detected)\n"
        "  - Machine\n"
        "- **Database**: Which database backend should the charm support?\n"
        "  - PostgreSQL only\n"
        "  - PostgreSQL and MySQL\n"
        "  - SQLite (embedded, no relation needed)\n"
        "```\n\n"
        "The questions will be presented to the user one at a time with the suggestions "
        "as selectable options, so keep each question focused and self-contained."
    ),
    TaskCategory.BUILD: (
        "Write clean, well-structured code following ops framework conventions. "
        "Use Scenario for unit tests, include COS integration, and follow the "
        "charm type path (PaaS, custom, or infrastructure) as appropriate."
    ),
    TaskCategory.DEPLOY: (
        "Pack the charm and deploy it. Ensure all relations are established and "
        "the application reaches active/idle status. Use juju_wait to confirm "
        "readiness before reporting success."
    ),
    TaskCategory.TEST: (
        "Run the test suite and report results clearly. If tests fail, include "
        "the failure output so debug tasks can act on it. Validate the charm "
        "structure before packing."
    ),
    TaskCategory.DEBUG: (
        "Investigate failures methodically. Check logs, traces, and unit status. "
        "Apply targeted fixes and verify they resolve the issue. Report the root "
        "cause and what you changed."
    ),
    TaskCategory.INFRA: (
        "Set up infrastructure efficiently. Prepare the environment with Concierge, "
        "create models, and initialise repositories. Report the final state of each "
        "resource."
    ),
}


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def _select_provider(
    category: TaskCategory,
    provider: llm.LLMProvider,
    light_provider: llm.LLMProvider | None,
    task_title: str = "",
) -> llm.LLMProvider:
    """Return the light provider for research/infra categories, primary otherwise.

    Operational-discovery tasks are an exception: their output is
    user-facing (the design proposal), so they use the primary model.
    """
    if light_provider is not None and category in _LIGHT_CATEGORIES:
        # Route synthesis tasks to the primary model for quality.
        if "operational-discovery" in task_title or "synthesise" in task_title.lower():
            return provider
        return light_provider
    return provider


def _filter_tools(tools: list[Tool], category: TaskCategory) -> list[Tool]:
    """Filter agent tools to those allowed for *category*."""
    allowlist = _CATEGORY_TOOLS.get(category)
    if allowlist is None:
        return []
    return [t for t in tools if t.name in allowlist]


def _tools_for_llm(tools: list[Tool]) -> list[llm.Tool] | None:
    """Convert agent tools to LLM tool descriptors.

    Returns ``None`` when *tools* is empty, signalling no tool use.
    """
    if not tools:
        return None
    return [
        llm.Tool(name=t.name, description=t.description, parameters=t.parameters) for t in tools
    ]


def _task_instruction(task: AgentTask) -> str:
    """Format the initial USER message from the task title and description."""
    parts = [task.title]
    if task.description:
        parts.append(task.description)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------


def _build_subagent_prompt(context: SubagentContext) -> str:
    """Build a focused system prompt for the subagent."""
    task = context.task
    sections: list[str] = []

    # 1. Role preamble.
    sections.append(
        "You are an autonomous subagent of Cantrip, an AI agent that builds "
        "Juju charms. You have been assigned a single focused task. Complete "
        "it using the tools available to you, then respond with a clear "
        "summary of what you did and the outcome."
    )

    # 2. Task block.
    sections.append(
        f"## Task\n\n"
        f"- **Title:** {task.title}\n"
        f"- **Category:** {task.category.value}\n"
        f"- **Description:** {task.description or 'No additional details.'}"
    )

    # 3. Charm context (omit None values).
    context_lines: list[str] = []
    if context.charm_name:
        context_lines.append(f"- Charm name: {context.charm_name}")
    if context.charm_path:
        context_lines.append(f"- Charm path: {context.charm_path}")
    if context.charm_type:
        context_lines.append(f"- Charm type: {context.charm_type}")
    if context.framework:
        context_lines.append(f"- Framework: {context.framework}")
    if context.dev_model:
        context_lines.append(f"- Dev model: {context.dev_model}")
    if context.cos_model:
        context_lines.append(f"- COS model: {context.cos_model}")
    if context_lines:
        sections.append("## Charm context\n\n" + "\n".join(context_lines))

    # 4. Category-specific guidance.
    guidance = _CATEGORY_GUIDANCE.get(task.category)
    if guidance:
        sections.append(f"## Guidance\n\n{guidance}")

    # 5. Prior task results (dependency handoff).
    if context.prior_results:
        result_lines = []
        for dep_id, result in context.prior_results.items():
            result_lines.append(f"### {dep_id}\n\n{result}")
        sections.append(
            "## Prior task results\n\n"
            "Results from dependency tasks for context:\n\n" + "\n\n".join(result_lines)
        )

    # 6. Decisions already made.
    if context.decisions:
        decision_lines = []
        for d in context.decisions:
            line = f"- **{d.get('type', 'unknown')}:** {d.get('choice', '?')}"
            if d.get("reason"):
                line += f" — {d['reason']}"
            decision_lines.append(line)
        sections.append(
            "## Decisions\n\n"
            "These decisions have already been confirmed — do not re-ask:\n\n"
            + "\n".join(decision_lines)
        )

    # 7. Approved design (for build/deploy/test subagents).
    if context.design_content:
        sections.append(
            "## Approved design\n\n"
            "The user has approved the following design — implement according to it:\n\n"
            + context.design_content
        )

    # 8. Completion instruction.
    sections.append(
        "## Completion\n\n"
        "When you have finished, respond with a clear summary of what you "
        "accomplished and any important details for subsequent tasks."
    )

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Subagent class
# ---------------------------------------------------------------------------


class Subagent:
    """Run a single ``AgentTask`` in an isolated LLM context.

    The executor constructs a ``Subagent`` for each task, calls ``run()``,
    and records the returned summary as the task result.
    """

    def __init__(
        self,
        context: SubagentContext,
        tools: list[Tool],
        provider: llm.LLMProvider,
        light_provider: llm.LLMProvider | None = None,
    ) -> None:
        self._context = context
        self._provider = _select_provider(
            context.task.category,
            provider,
            light_provider,
            task_title=context.task.title,
        )
        self._tools = _filter_tools(tools, context.task.category)
        self._tool_map: dict[str, Tool] = {t.name: t for t in self._tools}

    async def run(self) -> str:
        """Execute the task and return a text summary of the outcome."""
        system_prompt = _build_subagent_prompt(self._context)
        user_instruction = _task_instruction(self._context.task)

        messages: list[llm.Message] = [
            llm.Message(role=llm.Role.SYSTEM, content=system_prompt),
            llm.Message(role=llm.Role.USER, content=user_instruction),
        ]

        llm_tools = _tools_for_llm(self._tools)
        response = await self._complete_with_retry(messages, llm_tools)

        rounds = 0
        while response.tool_calls and rounds < MAX_SUBAGENT_ROUNDS:
            rounds += 1

            # Record the assistant message with its tool calls.
            messages.append(
                llm.Message(
                    role=llm.Role.ASSISTANT,
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )

            # Execute each tool call and collect results.
            tool_results: list[llm.ToolResult] = []
            for tc in response.tool_calls:
                result = await self._execute_tool(tc.name, tc.arguments)
                content = result.output if result.success else (result.error or "Unknown error")
                tool_results.append(
                    llm.ToolResult(
                        tool_call_id=tc.id,
                        content=content,
                        is_error=not result.success,
                    )
                )

            messages.append(llm.Message(role=llm.Role.TOOL, content="", tool_results=tool_results))

            response = await self._complete_with_retry(messages, llm_tools)

        return response.content

    async def _complete_with_retry(
        self,
        messages: list[llm.Message],
        tools: list[llm.Tool] | None,
    ) -> llm.Response:
        """Call ``provider.complete()`` with linear-backoff retry for transient errors."""
        last_error: llm.ProviderRateLimitError | llm.ProviderOverloadedError | None = None
        for attempt in range(1, _TRANSIENT_RETRIES + 1):
            try:
                return await self._provider.complete(
                    messages=messages,
                    tools=tools,
                    temperature=_SUBAGENT_TEMPERATURE,
                )
            except (llm.ProviderRateLimitError, llm.ProviderOverloadedError) as exc:
                last_error = exc
                if attempt == _TRANSIENT_RETRIES:
                    raise
                delay = _TRANSIENT_BASE_DELAY * attempt
                log.warning(
                    "Subagent provider unavailable — retrying in %ds (attempt %d/%d): %s",
                    delay,
                    attempt,
                    _TRANSIENT_RETRIES,
                    exc,
                )
                await asyncio.sleep(delay)
        # Unreachable — the final attempt re-raises above.
        raise last_error  # type: ignore[misc]

    async def _execute_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Look up and execute a tool by name."""
        tool = self._tool_map.get(name)
        if not tool:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown tool: {name}",
            )
        try:
            return await tool.execute(**arguments)
        except TypeError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Invalid arguments for {name}: {exc}",
            )
