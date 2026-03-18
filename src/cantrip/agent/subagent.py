"""Subagent runner — isolated LLM context for autonomous task execution."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from cantrip.agent.queue import AgentTask, ModelHint, TaskCategory
from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.llm import base as llm

if TYPE_CHECKING:
    from cantrip.agent.store import SessionStore

# Called after each LLM completion with the response, for token tracking.
UsageCallback = Callable[[llm.Response], None] | None

log = logging.getLogger(__name__)

# Focused tasks need fewer rounds than the open-ended conversation loop.
# Kept tight to encourage batching tool calls rather than one-per-round chains.
MAX_SUBAGENT_ROUNDS = 8

_TRANSIENT_RETRIES = 3
_TRANSIENT_BASE_DELAY = 30  # seconds

# Action-oriented — slightly more deterministic than conversation (0.7).
_SUBAGENT_TEMPERATURE = 0.5

# Categories routed to the light (cheaper) model.
_LIGHT_CATEGORIES = frozenset({TaskCategory.RESEARCH, TaskCategory.INFRA})


class ProviderThrottle:
    """Shared rate-limit coordinator for concurrent subagents.

    When one subagent hits a rate limit, it signals the throttle with a
    cooldown duration.  Other subagents using the same provider call
    ``wait_if_throttled()`` before each LLM request and sleep until the
    cooldown expires, avoiding a thundering-herd of retries.

    Thread-safe for use across concurrent ``asyncio.Task`` instances
    (all on the same event loop).
    """

    def __init__(self) -> None:
        # Maps provider name → monotonic time when the cooldown ends.
        self._cooldowns: dict[str, float] = {}

    def signal_rate_limit(self, provider_name: str, delay: float) -> None:
        """Record that *provider_name* should be avoided for *delay* seconds.

        If an existing cooldown extends beyond the new one, keep the longer.
        """
        deadline = time.monotonic() + delay
        existing = self._cooldowns.get(provider_name, 0.0)
        if deadline > existing:
            self._cooldowns[provider_name] = deadline
            log.info(
                "Provider %s throttled for %.0fs (until %.1f)",
                provider_name,
                delay,
                deadline,
            )

    async def wait_if_throttled(self, provider_name: str) -> None:
        """Sleep until the cooldown for *provider_name* has elapsed."""
        deadline = self._cooldowns.get(provider_name, 0.0)
        remaining = deadline - time.monotonic()
        if remaining > 0:
            log.debug(
                "Waiting %.1fs for provider %s cooldown",
                remaining,
                provider_name,
            )
            await asyncio.sleep(remaining)


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
            "charm_audit",
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
            "charm_audit",
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
            "charm_validate",
            "run_charm_tests",
            "generate_terraform",
            "validate_terraform",
            "fuzz_charm",
            "juju_status",
            "juju_run_action",
            "juju_config",
            "juju_debug_log",
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
            "validate_terraform",
            "hook_benchmark",
            "fuzz_charm",
            "test_report",
            "chaos_test",
            "scaling_test",
            "upgrade_test",
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
            "git_add",
            "git_commit",
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
        "guessing.\n"
        "- **Batch fetches**: call `web_fetch` for multiple URLs in a single round. "
        "Similarly, read multiple files at once rather than one per round.\n"
        "- **Stop when sufficient**: 2-3 good sources per topic is enough. Do not "
        "chase every link — gather the key facts and summarise.\n\n"
        "### Task-type guidance\n\n"
        "**source-analysis**: Clone the repository, then in one round read README, "
        "dependency files (requirements.txt, pyproject.toml, package.json, go.mod, "
        "pom.xml), Dockerfile, and entry points simultaneously. "
        "Run `analyse_framework` in the same round if possible. "
        "Write findings into WORKLOAD.md at the charm root and finish.\n\n"
        "**web-research**: Fetch the project website, official docs, and one deployment "
        "guide in a single round. Extract operational patterns: deployment, config, "
        "monitoring, scaling. Summarise and finish — do not fetch more than 3-4 pages.\n\n"
        "**charmhub-survey**: Call `charmhub_search` once. If results exist, call "
        "`charmhub_info` for the top 1-2 candidates in one round. Summarise findings "
        "and finish.\n\n"
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
        "- **Backup**: What backup/restore procedures does it support?\n"
        "- **Security surface**: Does the workload handle authentication, credentials, "
        "access control, or sensitive data? If yes, list the security surface indicators "
        "and recommend OWASP event types to log.\n\n"
        "Format the output as DESIGN.md with clear headings for each section.\n\n"
        "Include a ## Security Surface section if the workload has authentication, "
        "credential management, access control, or data audit requirements. List the "
        "indicators and recommended event types (e.g. authn_login_success, authz_fail). "
        "Omit this section for workloads with no security surface.\n\n"
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
        "Include COS integration, and follow the charm type path (PaaS, custom, "
        "or infrastructure) as appropriate.\n\n"
        "**Red/green cycle**: follow an integration-tests-first approach.\n"
        "1. Read the design and any existing files (including integration tests if "
        "they already exist) in one round.\n"
        "2. If integration tests do not exist yet, write them first — derive test "
        "cases from the approved design: each relation endpoint gets a deploy+relate "
        "test, each action gets an execute test, each config option gets a set+verify "
        "test, and COS integration gets a relation test. Use Jubilant patterns. These "
        "tests define the external contract and are expected to fail initially (red).\n"
        "3. Write charm code (src/charm.py, Pebble layers, integrations, config) "
        "targeting the integration tests (green).\n"
        "4. Run `run_charm_tests` with `test_type='integration'` to check progress. "
        "Use the `pattern` parameter to target specific failing tests for faster "
        "iteration (e.g. `pattern='test_deploy'`).\n"
        "5. If tests fail, read the output, fix the code, and re-run. Iterate until "
        "integration tests pass or you exhaust your rounds.\n"
        "6. Write unit tests using Scenario (ops.testing) for edge cases and error "
        "paths that integration tests cannot easily cover: missing relations → "
        "BlockedStatus, invalid config → error handling, Pebble not ready → "
        "WaitingStatus.\n\n"
        "**Efficiency**: write multiple files in a single round when they are "
        "independent. Do not re-read files you just wrote.\n\n"
        "**Version control**: before finishing, use `git_add` to stage your changes "
        "and `git_commit` with a descriptive message summarising what was built. "
        "Every build task should leave a clean commit.\n\n"
        "**Self-check**: before finishing, run `charm_validate` to verify the charm "
        "packs and tests pass. If validation fails, attempt one fix and "
        "re-validate. Do not report success if validation fails.\n\n"
        "**Security event logging**: if the design identifies a security surface, "
        "generate a `src/log_security.py` helper that emits structured OWASP-format "
        "security events (JSON with datetime, appid, type, event, level, description). "
        "Call it from charm event handlers at the appropriate points (secret hooks, "
        "relation changes, action handlers). Never log sensitive data.\n\n"
        "**Tracing**: ops-tracing handles hook/Pebble/relation spans automatically. "
        "Only add manual spans for long-running workload operations (backups, "
        "migrations), external API calls, and decision logic with fallback paths. "
        "Do not span simple Pebble or relation handlers."
    ),
    TaskCategory.DEPLOY: (
        "Pack the charm and deploy it. Ensure all relations are established and "
        "the application reaches active/idle status. Use `juju_wait` to confirm "
        "readiness rather than polling `juju_status` repeatedly.\n\n"
        "**Efficiency**: chain pack → deploy → wait in as few rounds as possible. "
        "Establish all relations in a single round."
    ),
    TaskCategory.TEST: (
        "Run the test suite and report results clearly. If tests fail, include "
        "the failure output so debug tasks can act on it.\n\n"
        "**Combined validation**: run both unit tests and integration tests as a "
        "combined gate. Run unit tests first (faster feedback), then integration "
        "tests. Report pass/fail counts for each.\n\n"
        "**Efficiency**: run `run_charm_tests` for unit and integration in "
        "successive rounds (unit first, then integration). Report pass/fail counts "
        "and stop — do not attempt fixes (that is a debug task)."
    ),
    TaskCategory.DEBUG: (
        "Investigate failures methodically. Query logs, traces, and unit status "
        "in a single round to gather diagnostics. Then apply a targeted fix and "
        "verify it resolves the issue. Report the root cause and what you changed.\n\n"
        "**Efficiency**: fetch `juju_debug_log`, `loki_query`, and `juju_status` "
        "in one round. Apply the fix, then verify — aim for 2-3 rounds total.\n\n"
        "**Version control**: after applying a fix, use `git_add` to stage the "
        "changed files and `git_commit` with a message describing the fix and "
        "root cause. Every debug fix should be committed."
    ),
    TaskCategory.INFRA: (
        "Set up infrastructure efficiently. Prepare the environment with Concierge, "
        "create models, and initialise repositories. Report the final state of each "
        "resource.\n\n"
        "**Efficiency**: run independent setup steps in parallel (e.g. model creation "
        "and git init)."
    ),
}

# Task-specific guidance overlay for demo generation tasks.
_DEMO_GUIDANCE = (
    "### Demo generation\n\n"
    "You are generating demo artefacts for a deployed, tested charm. "
    "Capture real output from the live deployment.\n\n"
    "**Steps:**\n"
    "1. Read `charmcraft.yaml` to discover the charm's actions, config "
    "options, and relation endpoints.\n"
    "2. Read `WORKLOAD.md` and `DESIGN.md` (if they exist) for context.\n"
    "3. Run `juju_status` and save the output to `demo/juju-status.txt`.\n"
    "4. Run `juju_config` and save to `demo/config-reference.txt`.\n"
    "5. For each action in the charm, run `juju_run_action` with sensible "
    "defaults and save JSON results to `demo/actions/<name>.json`.\n"
    "6. Capture a `juju_debug_log` snippet (last 50 lines) to "
    "`demo/logs/event-log.txt`.\n"
    "7. Write `DEMO.md` — an annotated walk-through interleaving real "
    "command output with explanations. Structure: overview, deployment, "
    "relations, configuration, actions, observability.\n"
    "8. Write `demo.sh` — a self-contained bash script that reproduces "
    "the full deployment: deploy, relate, configure, verify. Include an "
    "optional `--cleanup` flag that destroys the model. Mark it executable.\n"
    "9. Write `TUTORIAL.md` — a step-by-step guide covering: "
    "prerequisites, deploying the charm, verifying the deployment, "
    "exercising features (config, actions, scaling), observability, "
    "and troubleshooting. Include copy-pasteable commands.\n"
    "10. Stage all files with `git_add` and commit with a descriptive "
    "message.\n\n"
    "**Important:** draw on WORKLOAD.md and DESIGN.md to explain *why* "
    "certain config options matter and what the actions do operationally "
    "— not just how to run commands."
)


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def _select_provider(
    category: TaskCategory,
    provider: llm.LLMProvider,
    light_provider: llm.LLMProvider | None,
    task_title: str = "",
    model_hint: ModelHint | None = None,
) -> llm.LLMProvider:
    """Choose the right model for a task.

    Priority order:
    1. Explicit ``model_hint`` on the task (PRIMARY or LIGHT).
    2. Category-based routing: RESEARCH and INFRA use light, others primary.
    3. Operational-discovery/synthesis research tasks use primary for quality.
    """
    # 1. Explicit per-task override.
    if model_hint is not None:
        if model_hint == ModelHint.LIGHT and light_provider is not None:
            return light_provider
        return provider

    # 2. Category-based routing.
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
        "summary of what you did and the outcome.\n\n"
        "### Efficiency rules\n\n"
        "- **Batch tool calls**: call multiple tools in a single round whenever "
        "possible. For example, fetch several URLs at once, or read multiple "
        "files in parallel, rather than one per round.\n"
        "- **Finish early**: once you have enough information to produce a good "
        "result, summarise and finish. Do not exhaustively explore every lead.\n"
        "- **Be direct**: execute the task, report the outcome. Skip preamble "
        "and unnecessary commentary."
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

    # 4b. Task-specific guidance overlay for demo generation.
    if "demo" in task.title.lower() and task.category == TaskCategory.BUILD:
        sections.append(f"## Demo guidance\n\n{_DEMO_GUIDANCE}")

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
        on_usage: UsageCallback = None,
        throttle: ProviderThrottle | None = None,
        store: SessionStore | None = None,
    ) -> None:
        self._context = context
        self._provider = _select_provider(
            context.task.category,
            provider,
            light_provider,
            task_title=context.task.title,
            model_hint=context.task.model_hint,
        )
        self._tools = _filter_tools(tools, context.task.category)
        self._tool_map: dict[str, Tool] = {t.name: t for t in self._tools}
        self._on_usage = on_usage
        self._throttle = throttle
        self._store = store

    async def run(self) -> str:
        """Execute the task and return a text summary of the outcome."""
        system_prompt = _build_subagent_prompt(self._context)
        user_instruction = _task_instruction(self._context.task)

        messages: list[llm.Message] = [
            llm.Message(role=llm.Role.SYSTEM, content=system_prompt),
            llm.Message(role=llm.Role.USER, content=user_instruction),
        ]

        # Track message indices for persistent recording.
        msg_idx = 0
        if self._store:
            task_id = self._context.task.id
            self._store.record_subagent_message(
                task_id,
                msg_idx,
                "system",
                system_prompt,
            )
            msg_idx += 1
            self._store.record_subagent_message(
                task_id,
                msg_idx,
                "user",
                user_instruction,
            )
            msg_idx += 1

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
                    metadata=response.metadata,
                )
            )

            if self._store:
                tc_data = [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in response.tool_calls
                ]
                self._store.record_subagent_message(
                    task_id,
                    msg_idx,
                    "assistant",
                    response.content,
                    tool_calls=tc_data,
                )
                msg_idx += 1

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

            messages.append(
                llm.Message(
                    role=llm.Role.TOOL,
                    content="",
                    tool_results=tool_results,
                )
            )

            if self._store:
                tr_data = [
                    {
                        "tool_call_id": tr.tool_call_id,
                        "content": tr.content,
                        "is_error": tr.is_error,
                    }
                    for tr in tool_results
                ]
                self._store.record_subagent_message(
                    task_id,
                    msg_idx,
                    "tool",
                    "",
                    tool_results=tr_data,
                )
                msg_idx += 1

            response = await self._complete_with_retry(messages, llm_tools)

        # Record the final assistant response.
        if self._store:
            self._store.record_subagent_message(
                task_id,
                msg_idx,
                "assistant",
                response.content,
            )

        return response.content

    async def _complete_with_retry(
        self,
        messages: list[llm.Message],
        tools: list[llm.Tool] | None,
    ) -> llm.Response:
        """Call ``provider.complete()`` with linear-backoff retry for transient errors.

        When a shared ``ProviderThrottle`` is set, waits for any existing
        cooldown before each attempt and signals the throttle on rate-limit
        errors so other subagents back off too.
        """
        last_error: llm.ProviderRateLimitError | llm.ProviderOverloadedError | None = None
        for attempt in range(1, _TRANSIENT_RETRIES + 1):
            try:
                # Respect shared cooldown from other subagents.
                if self._throttle is not None:
                    await self._throttle.wait_if_throttled(self._provider.name)
                response = await self._provider.complete(
                    messages=messages,
                    tools=tools,
                    temperature=_SUBAGENT_TEMPERATURE,
                )
                if self._on_usage:
                    self._on_usage(response)
                return response
            except (llm.ProviderRateLimitError, llm.ProviderOverloadedError) as exc:
                last_error = exc
                if attempt == _TRANSIENT_RETRIES:
                    raise
                delay = _TRANSIENT_BASE_DELAY * attempt
                # Signal the shared throttle so other subagents back off.
                if self._throttle is not None:
                    self._throttle.signal_rate_limit(self._provider.name, delay)
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
        except Exception as exc:
            log.warning("Tool %s raised %s: %s", name, type(exc).__name__, exc)
            return ToolResult(
                success=False,
                output="",
                error=f"Tool execution failed: {exc}",
            )
