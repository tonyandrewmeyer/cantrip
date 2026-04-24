"""Subagent runner — isolated LLM context for autonomous task execution."""

from __future__ import annotations

import asyncio
import datetime
import enum
import logging
import re as _re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import resources
from typing import TYPE_CHECKING, Any

from cantrip.agent.durability import (
    KIND_LLM_RESPONSE,
    KIND_TOOL_RESULT,
    CheckpointCtx,
    CheckpointStore,
    checkpoint,
    compute_input_hash,
    response_from_dict,
    response_to_dict,
    should_skip_resume,
    tool_result_from_dict,
    tool_result_to_dict,
)
from cantrip.agent.planner import SPRINT_BUILD_PREFIX
from cantrip.agent.queue import AgentTask, ModelHint, TaskCategory
from cantrip.agent.retry import complete_with_retry
from cantrip.agent.tools.base import Tool, ToolResult, execute_tool
from cantrip.hooks import HookEvent, HookRunner, final_arguments, first_veto
from cantrip.llm import base as llm
from cantrip.ui import flavour

if TYPE_CHECKING:
    from cantrip.agent.store import SessionStore

# Called after each LLM completion with the response, for token tracking.
UsageCallback = Callable[[llm.Response], None] | None

# Called whenever the subagent's transient phase (``subagent_phase`` /
# ``subagent_started_at``) changes so the UI can redraw.  The executor
# wires this to publish a ``TASK_UPDATED`` event on the shared bus.
PhaseChangeCallback = Callable[[AgentTask], None] | None

# Called after each subagent tool call so the UI can render an inline
# "tool block" in the chat (Phase 75).  Args: (tool_name, arguments,
# result, duration_ms).  The executor wires this to publish a
# ``TOOL_INVOKED`` event on the shared bus.
ToolInvokedCallback = Callable[[str, dict[str, Any], ToolResult, int], None] | None


# Tool-call "running" phases shorter than this threshold feel like flicker,
# so we always show at least this long before the phase updates again.  It's
# just a display heuristic — the underlying tool still runs to completion.
_PHASE_LABEL_TOOL_LIMIT = 3


# ---------------------------------------------------------------------------
# Structured exit contracts
# ---------------------------------------------------------------------------


class ExitState(enum.StrEnum):
    """Exit state reported by a subagent at the end of its run."""

    COMPLETED = "completed"  # Work done, state changed.
    BLOCKED = "blocked"  # Needs user input or missing dependency.
    FAILED = "failed"  # Error encountered, needs retry or escalation.
    NOOP = "noop"  # Nothing to do — task may already be satisfied.


@dataclass(frozen=True)
class SubagentResult:
    """Structured outcome of a subagent run."""

    exit_state: ExitState
    summary: str
    detail: str = ""

    @property
    def text(self) -> str:
        """Full text representation (for backwards compatibility with str results)."""
        return self.detail or self.summary


# Regex to extract an exit state tag from the LLM's final response.
# Matches patterns like "[EXIT: completed]" or "EXIT_STATE: blocked".
_EXIT_STATE_RE = _re.compile(
    r"\[?EXIT(?:_STATE)?:\s*(completed|blocked|failed|noop)\]?",
    _re.IGNORECASE,
)


def _parse_exit_state(text: str) -> ExitState:
    """Extract an exit state from a subagent's final response text.

    Falls back to COMPLETED if no explicit signal is found (the subagent
    finished without error, so we assume it completed).
    """
    match = _EXIT_STATE_RE.search(text)
    if match:
        return ExitState(match.group(1).lower())
    # Heuristic fallback: look for keywords indicating non-completion.
    lower = text.lower()
    if "blocked" in lower and ("need" in lower or "waiting" in lower or "cannot" in lower):
        return ExitState.BLOCKED
    if "nothing to do" in lower or "already" in lower and "no changes" in lower:
        return ExitState.NOOP
    return ExitState.COMPLETED


log = logging.getLogger(__name__)

# Focused tasks need fewer rounds than the open-ended conversation loop.
# Kept tight to encourage batching tool calls rather than one-per-round chains.
MAX_SUBAGENT_ROUNDS = 8

# BUILD tasks benefit from extra rounds for complex multi-step operations.
MAX_BUILD_ROUNDS = 12

# Fraction of the context window that triggers message truncation.
_CONTEXT_WINDOW_THRESHOLD = 0.80

# Tool result content longer than this is eligible for truncation.
_TRUNCATION_CONTENT_THRESHOLD = 500

# How many characters to keep in the truncation summary.
_TRUNCATION_PREVIEW_LEN = 200

# Messages in the most recent N rounds are never truncated.
_PROTECTED_ROUNDS = 2

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
            "web_search",
            "charmhub_search",
            "charmhub_info",
            "registry_search",
            "registry_image_info",
            "git_clone",
            "read_file",
            "write_file",
            "list_directory",
            "grep",
            "glob",
            "analyse_framework",
            "charm_audit",
            "charmlint",
            "operational_readiness",
            "juju_list_secrets",
            "juju_show_secret",
            "juju_read_relation_data",
            "juju_get_app_config",
            "juju_list_offers",
            "juju_show_unit",
            "load_skill",
            "gh_issue_list",
            "gh_pr_list",
            "gh_pr_view",
            "virtual_file_read",
            "virtual_file_search",
        }
    ),
    TaskCategory.BUILD: frozenset(
        {
            "read_file",
            "write_file",
            "edit_file",
            "multi_edit",
            "list_directory",
            "grep",
            "glob",
            "run_command",
            "charmcraft_init",
            "charmcraft_pack",
            "charmcraft_fetch_libs",
            "rockcraft_init",
            "analyse_framework",
            "charm_audit",
            "charmlint",
            "operational_readiness",
            "load_skill",
            "git_init",
            "git_status",
            "git_diff",
            "git_add",
            "git_commit",
            "git_log",
            "git_branch",
            "git_checkout",
            "git_stash",
            "registry_search",
            "registry_image_info",
            "generate_readme",
            "generate_icon",
            "generate_docs",
            "generate_diagram",
            "generate_load_test",
            "generate_tests",
            "showboat",
            "rodney",
            "charm_validate",
            "run_charm_tests",
            "generate_terraform",
            "validate_terraform",
            "fuzz_charm",
            "juju_status",
            "juju_run_action",
            "juju_config",
            "juju_read_relation_data",
            "juju_get_app_config",
            "juju_debug_log",
            "tempo_query",
            "pr_review",
            "pr_review_reply",
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
            "juju_remove_application",
            "juju_show_unit",
            "charm_sync",
            "juju_dispatch",
            "charmcraft_upload",
            "charmcraft_release",
            "read_file",
            "list_directory",
            "grep",
            "glob",
            "virtual_file_read",
            "virtual_file_search",
        }
    ),
    TaskCategory.TEST: frozenset(
        {
            "run_command",
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
            "generate_load_test",
            "rodney",
            # Acceptance testing tools.
            "action_exerciser",
            "relation_smoke_test",
            "workload_endpoint_test",
            "config_variation_test",
            "config_under_load_test",
            "acceptance_report",
            # Juju operations needed for acceptance testing.
            "juju_status",
            "juju_run_action",
            "juju_relate",
            "juju_wait",
            "juju_deploy",
            "juju_config",
            "juju_remove_application",
            "juju_show_unit",
            "juju_read_relation_data",
            "juju_get_app_config",
            "juju_ssh",
            "read_file",
            "list_directory",
            "grep",
            "glob",
            "virtual_file_read",
            "virtual_file_search",
        }
    ),
    TaskCategory.DEBUG: frozenset(
        {
            "juju_debug_log",
            "juju_stream_logs",
            "tempo_query",
            "loki_query",
            "grafana_screenshot",
            "tempo_waterfall",
            "juju_status",
            "juju_status_render",
            "juju_ssh",
            "juju_config",
            "juju_dispatch",
            "juju_list_secrets",
            "juju_show_secret",
            "juju_read_relation_data",
            "juju_get_app_config",
            "juju_list_offers",
            "juju_show_unit",
            "juju_remove_application",
            "charm_sync",
            "read_file",
            "edit_file",
            "multi_edit",
            "list_directory",
            "grep",
            "glob",
            "run_command",
            "pr_review",
            "pr_review_reply",
            "git_diff",
            "git_status",
            "git_add",
            "git_commit",
            "git_branch",
            "git_checkout",
            "git_stash",
            "git_log",
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
            "gh_pr_create",
            "gh_pr_list",
            "gh_pr_view",
            "git_push",
            "git_init",
            "git_branch",
            "git_checkout",
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

# Guidance files live in prompts/subagent/ as plain markdown so they can be
# maintained and reused without touching Python code.
_PROMPTS_PKG = "cantrip.agent.prompts.subagent"


def _load_guidance(filename: str) -> str:
    """Load a guidance markdown file from the subagent prompts package."""
    return resources.files(_PROMPTS_PKG).joinpath(filename).read_text(encoding="utf-8").strip()


_CATEGORY_GUIDANCE: dict[TaskCategory, str] = {
    TaskCategory.RESEARCH: _load_guidance("research.md"),
    TaskCategory.BUILD: _load_guidance("build.md"),
    TaskCategory.DEPLOY: _load_guidance("deploy.md"),
    TaskCategory.TEST: _load_guidance("test.md"),
    TaskCategory.DEBUG: _load_guidance("debug.md"),
    TaskCategory.INFRA: _load_guidance("infra.md"),
}

_DEMO_GUIDANCE = _load_guidance("demo.md")

# Title prefix for acceptance test tasks — used to identify them in the
# subagent prompt builder and in autodeploy follow-up logic.
_ACCEPTANCE_PREFIX = "Acceptance test:"

_ACCEPTANCE_GUIDANCE = _load_guidance("acceptance.md")

# Title prefix for day-2 operations research tasks.
DAY2_PREFIX = "Day 2:"

_DAY2_GUIDANCE = _load_guidance("day2.md")


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
    """Filter agent tools to those allowed for *category*.

    MCP tools (names beginning ``mcp__``) bypass the per-category
    allowlist — the per-server ``allowed_tools`` config (Phase 45.2)
    is the gate for MCP exposure.  Operators who want category-scoped
    MCP access can drop unwanted servers from the YAML config.
    """
    allowlist = _CATEGORY_TOOLS.get(category)
    if allowlist is None:
        return []
    return [t for t in tools if t.name in allowlist or t.name.startswith("mcp__")]


def _tools_for_llm(tools: list[Tool]) -> list[llm.Tool] | None:
    """Convert agent tools to LLM tool descriptors.

    Returns ``None`` when *tools* is empty, signalling no tool use.
    """
    if not tools:
        return None
    return [
        llm.Tool(name=t.name, description=t.description, parameters=t.parameters) for t in tools
    ]


def _message_hash_repr(message: llm.Message) -> dict[str, Any]:
    """Return a canonical dict for an :class:`llm.Message` used in input-hash composition.

    Skips ``images`` and ``metadata`` — image bytes blow up the hash
    payload and metadata is stamped by the provider on responses, not
    inputs.  Tool calls and tool results are reduced to their
    identifier-bearing fields so the same prefix across runs produces
    the same digest.
    """
    return {
        "role": message.role.value,
        "content": message.content,
        "tool_calls": [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in message.tool_calls
        ],
        "tool_results": [
            {"id": tr.tool_call_id, "content": tr.content, "is_error": tr.is_error}
            for tr in message.tool_results
        ],
    }


def _tool_hash_repr(tool: llm.Tool) -> dict[str, Any]:
    """Return a canonical dict for an :class:`llm.Tool` schema."""
    return {"name": tool.name, "description": tool.description, "parameters": tool.parameters}


def _task_instruction(task: AgentTask) -> str:
    """Format the initial USER message from the task title and description."""
    parts = [task.title]
    if task.description:
        parts.append(task.description)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------


_ROLE_PREAMBLE = (
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
    "and unnecessary commentary.\n\n"
    "### Exit signalling\n\n"
    "Every response MUST end with an exit state tag on its own line:\n\n"
    "- `[EXIT: completed]` — work done, state changed\n"
    "- `[EXIT: blocked]` — cannot proceed; needs user input or a missing "
    "dependency\n"
    "- `[EXIT: failed]` — error encountered; explain what went wrong\n"
    "- `[EXIT: noop]` — nothing to do; the task is already satisfied\n\n"
    "Never produce a bare text response while work is pending. If you "
    "cannot make progress, signal `blocked` or `failed` — do not "
    "silently give up."
)

_SPRINT_GUIDANCE = (
    "## Guidance\n\n"
    "**Sprint mode — speed is everything.**\n\n"
    "Do NOT write tests. Do NOT run charm_validate. Do NOT add "
    "COS/observability. Do NOT rewrite the scaffolded charm code "
    "unless it will not pack.\n\n"
    "Steps:\n"
    "1. Run charmcraft_init — this scaffolds a working charm.\n"
    "2. Fix charmcraft.yaml: change base to ubuntu@24.04, "
    "change plugin from uv to charm, remove build-snaps.\n"
    "3. Overwrite requirements.txt with ONLY `ops>=3,<4` — remove "
    "ops-tracing or any other deps (they cause slow source builds).\n"
    "4. Run charmcraft_pack with destructive_mode=true for speed.\n"
    "5. git_init, git_add all files, git_commit.\n"
    "6. Done. Do not iterate or improve — just ship it.\n\n"
    "**Efficiency**: aim for 3-4 tool rounds total."
)

_COMPLETION_INSTRUCTION = (
    "## Completion\n\n"
    "When you have finished, respond with a clear summary of what you "
    "accomplished and any important details for subsequent tasks."
)


def _charm_context_section(context: SubagentContext) -> str | None:
    """Build the charm context section, or ``None`` if there is nothing to show."""
    lines: list[str] = []
    for label, value in (
        ("Charm name", context.charm_name),
        ("Charm path", context.charm_path),
        ("Charm type", context.charm_type),
        ("Framework", context.framework),
        ("Dev model", context.dev_model),
        ("COS model", context.cos_model),
    ):
        if value:
            lines.append(f"- {label}: {value}")
    return ("## Charm context\n\n" + "\n".join(lines)) if lines else None


def _guidance_sections(task: AgentTask) -> list[str]:
    """Build category and task-specific guidance sections."""
    sections: list[str] = []

    if task.title.startswith(SPRINT_BUILD_PREFIX) and task.category == TaskCategory.BUILD:
        sections.append(_SPRINT_GUIDANCE)
    else:
        guidance = _CATEGORY_GUIDANCE.get(task.category)
        if guidance:
            sections.append(f"## Guidance\n\n{guidance}")

    if "demo" in task.title.lower() and task.category == TaskCategory.BUILD:
        sections.append(f"## Demo guidance\n\n{_DEMO_GUIDANCE}")
    if task.title.startswith(_ACCEPTANCE_PREFIX) and task.category == TaskCategory.TEST:
        sections.append(f"## Acceptance testing guidance\n\n{_ACCEPTANCE_GUIDANCE}")
    if task.title.startswith(DAY2_PREFIX) and task.category == TaskCategory.RESEARCH:
        sections.append(f"## Day-2 operations guidance\n\n{_DAY2_GUIDANCE}")

    return sections


def _handoff_sections(context: SubagentContext) -> list[str]:
    """Build prior results, decisions, and design sections."""
    sections: list[str] = []

    if context.prior_results:
        result_lines = [
            f"### {dep_id}\n\n{result}" for dep_id, result in context.prior_results.items()
        ]
        sections.append(
            "## Prior task results\n\n"
            "Results from dependency tasks for context:\n\n" + "\n\n".join(result_lines)
        )

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

    if context.design_content:
        sections.append(
            "## Approved design\n\n"
            "The user has approved the following design — implement according to it:\n\n"
            + context.design_content
        )

    return sections


def _build_subagent_prompt(context: SubagentContext) -> str:
    """Build a focused system prompt for the subagent."""
    task = context.task
    sections: list[str] = [_ROLE_PREAMBLE]

    sections.append(
        f"## Task\n\n"
        f"- **Title:** {task.title}\n"
        f"- **Category:** {task.category.value}\n"
        f"- **Description:** {task.description or 'No additional details.'}"
    )

    charm_ctx = _charm_context_section(context)
    if charm_ctx:
        sections.append(charm_ctx)

    sections.extend(_guidance_sections(task))
    sections.extend(_handoff_sections(context))
    sections.append(_COMPLETION_INSTRUCTION)

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Context window management
# ---------------------------------------------------------------------------


def _truncate_messages(
    messages: list[llm.Message],
    context_window_tokens: int,
) -> None:
    """Truncate older tool results in-place when messages approach the context limit.

    Keeps the system message (index 0) and the most recent ``_PROTECTED_ROUNDS``
    rounds of messages intact.  For older tool result messages, any content
    longer than ``_TRUNCATION_CONTENT_THRESHOLD`` characters is replaced with
    a short preview.

    A "round" is an assistant message followed by a tool message (2 messages).
    """
    token_budget = int(context_window_tokens * _CONTEXT_WINDOW_THRESHOLD)
    estimated = llm.estimate_message_tokens(messages)
    if estimated <= token_budget:
        return

    # Work out where the protected tail begins.  Each round is an
    # assistant + tool pair, so protect the last (2 * _PROTECTED_ROUNDS)
    # non-system messages, plus the system message at index 0.
    protected_tail = len(messages) - (_PROTECTED_ROUNDS * 2)

    for idx in range(1, max(1, protected_tail)):
        msg = messages[idx]
        if msg.role != llm.Role.TOOL:
            continue
        for tr in msg.tool_results:
            if len(tr.content) > _TRUNCATION_CONTENT_THRESHOLD:
                original_len = len(tr.content)
                preview = tr.content[:_TRUNCATION_PREVIEW_LEN]
                tr.content = (
                    f"[Tool result truncated — was {original_len} chars. "
                    f"First {_TRUNCATION_PREVIEW_LEN} chars: {preview}...]"
                )

    log.debug(
        "Truncated messages: %d → %d estimated tokens",
        estimated,
        llm.estimate_message_tokens(messages),
    )


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
        max_rounds: int = MAX_SUBAGENT_ROUNDS,
        on_phase_change: PhaseChangeCallback = None,
        hook_runner: HookRunner | None = None,
        on_tool_invoked: ToolInvokedCallback = None,
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
        self._max_rounds = max_rounds
        self._on_phase_change = on_phase_change
        self._hook_runner = hook_runner if hook_runner is not None else HookRunner()
        self._on_tool_invoked = on_tool_invoked

    def _set_phase(self, phase: str) -> None:
        """Update the task's transient subagent phase and notify listeners."""
        task = self._context.task
        if task.subagent_phase == phase:
            return
        task.subagent_phase = phase
        if self._on_phase_change:
            self._on_phase_change(task)

    def _tool_phase_label(self, tool_names: list[str]) -> str:
        """Build a short "running: tool1, tool2" label, truncated gracefully."""
        if not tool_names:
            return "running"
        shown = tool_names[:_PHASE_LABEL_TOOL_LIMIT]
        extra = len(tool_names) - len(shown)
        suffix = f" (+{extra})" if extra > 0 else ""
        return f"running: {', '.join(shown)}{suffix}"

    async def run(self) -> SubagentResult:
        """Execute the task and return a structured outcome."""
        # Stamp the subagent start time so the TUI can show elapsed seconds;
        # use a single clock reading so phase-change events and elapsed
        # counters agree.
        self._context.task.subagent_started_at = datetime.datetime.now()
        self._set_phase(flavour.pick_activity_label())
        task = self._context.task
        pre_results = await self._hook_runner.fire(
            HookEvent.PRE_SUBAGENT,
            {
                "task_id": task.id,
                "title": task.title,
                "category": task.category.value,
            },
        )
        veto = first_veto(pre_results)
        if veto is not None:
            # A ``pre_subagent`` veto maps cleanly onto an
            # ``ExitState.BLOCKED`` result — the task didn't run, the
            # executor will treat it like any other blocked task, and
            # the ``post_subagent`` hook still fires so telemetry
            # hooks see every attempted subagent invocation.
            log.info(
                "Subagent for task %r blocked by %s",
                task.title,
                veto.veto_reason,
            )
            self._context.task.subagent_started_at = None
            self._set_phase("")
            blocked = SubagentResult(
                exit_state=ExitState.BLOCKED,
                summary=f"Blocked by {veto.veto_reason}",
                detail=veto.stderr.strip(),
            )
            await self._hook_runner.fire(
                HookEvent.POST_SUBAGENT,
                {
                    "task_id": task.id,
                    "title": task.title,
                    "category": task.category.value,
                    "exit_state": blocked.exit_state.value,
                    "vetoed_by": veto.name,
                },
            )
            return blocked
        result: SubagentResult | None = None
        try:
            result = await self._run_inner()
            return result
        finally:
            # Clear transient state so the task pane doesn't show a stale
            # phase on a DONE / FAILED / BLOCKED task.
            self._context.task.subagent_started_at = None
            self._set_phase("")
            await self._hook_runner.fire(
                HookEvent.POST_SUBAGENT,
                {
                    "task_id": task.id,
                    "title": task.title,
                    "category": task.category.value,
                    "exit_state": (result.exit_state.value if result is not None else "unknown"),
                },
            )

    async def _run_inner(self) -> SubagentResult:
        """Real body of ``run`` — phase stamping happens in the wrapper."""
        system_prompt = _build_subagent_prompt(self._context)
        user_instruction = _task_instruction(self._context.task)

        messages: list[llm.Message] = [
            llm.Message(role=llm.Role.SYSTEM, content=system_prompt),
            llm.Message(role=llm.Role.USER, content=user_instruction),
        ]

        # Checkpoint context tracks per-step ordinals for the replay
        # path (Phase 52.3).  Bound to the session store so a run that
        # rate-limits on turn 18 resumes from turn 18 instead of turn 1.
        # When the subagent runs without a store (unit tests, synthetic
        # harnesses), checkpointing is disabled — ``_llm_turn`` /
        # ``_execute_tool_with_checkpoint`` skip the wrapper entirely.
        # ``$CANTRIP_NO_RESUME`` (Phase 52.4) also disables the wrapper
        # so a debugging run can re-execute every step live without
        # tripping over a stale cached row.
        ctx: CheckpointCtx | None = None
        if self._store is not None and not should_skip_resume():
            store = CheckpointStore(self._store)
            ctx = CheckpointCtx(store=store, task_id=self._context.task.id)
            # Phase 52.4: surface a "resuming from step N" signal when
            # the store already has checkpoints for this task so the
            # user knows why token usage doesn't start at zero and
            # doesn't mistake the silence for a hang.
            prior_steps = store.count_for_task(self._context.task.id)
            if prior_steps:
                log.info(
                    "Subagent resuming task %r from step %d (%d checkpoint(s) cached)",
                    self._context.task.title,
                    prior_steps + 1,
                    prior_steps,
                )
                self._set_phase(f"resuming from step {prior_steps + 1}")
                self._store.record_event(
                    "subagent_resume",
                    {
                        "task_id": self._context.task.id,
                        "task_title": self._context.task.title,
                        "prior_steps": prior_steps,
                        "next_step": prior_steps + 1,
                    },
                )

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
        response = await self._llm_turn(ctx, messages, llm_tools)

        rounds = 0
        while response.tool_calls and rounds < self._max_rounds:
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

            # Execute tool calls concurrently — they are independent within
            # a single round.  asyncio.gather() preserves order.
            self._set_phase(self._tool_phase_label([tc.name for tc in response.tool_calls]))
            category_value = self._context.task.category.value
            # Fire pre-hooks sequentially and record a per-call veto
            # plus any mutated arguments (Phase 46.4b).  A vetoed tool
            # is replaced with a synthetic error result; the rest of
            # the batch still runs in parallel, each with whatever
            # arguments the pre-hook chain produced.
            call_vetoes: list[tuple[Any, ...] | None] = []
            call_arguments: list[dict[str, Any]] = []
            for tc in response.tool_calls:
                pre_results = await self._hook_runner.fire(
                    HookEvent.PRE_TOOL_CALL,
                    {
                        "tool": tc.name,
                        "arguments": tc.arguments,
                        "source": "subagent",
                        "task_category": category_value,
                    },
                )
                call_vetoes.append(first_veto(pre_results))
                call_arguments.append(final_arguments(pre_results) or tc.arguments)

            async def _tool_or_veto(
                tc: llm.ToolCall, veto: Any, arguments: dict[str, Any]
            ) -> tuple[ToolResult, int]:
                call_start = time.monotonic()
                if veto is not None:
                    log.info(
                        "Subagent tool call %r vetoed by %s",
                        tc.name,
                        veto.veto_reason,
                    )
                    result = ToolResult(
                        success=False,
                        output="",
                        error=f"Blocked by {veto.veto_reason}",
                    )
                else:
                    result = await self._execute_tool_with_checkpoint(ctx, tc.name, arguments)
                return result, int((time.monotonic() - call_start) * 1000)

            timed_results = await asyncio.gather(
                *(
                    _tool_or_veto(tc, veto, args)
                    for tc, veto, args in zip(
                        response.tool_calls,
                        call_vetoes,
                        call_arguments,
                        strict=True,
                    )
                )
            )
            raw_results = [r for r, _ in timed_results]
            raw_durations = [ms for _, ms in timed_results]
            # Only the un-vetoed calls actually fired; post_tool_call
            # fires for every call (vetoed or not) so observability
            # hooks see the full picture, with ``success`` reflecting
            # the veto as a failure the same way the LLM does.  The
            # ``arguments`` payload uses the mutated form so audit
            # hooks see what actually ran (or would have).
            for tc, tool_result, veto, args, duration_ms in zip(
                response.tool_calls,
                raw_results,
                call_vetoes,
                call_arguments,
                raw_durations,
                strict=True,
            ):
                payload = {
                    "tool": tc.name,
                    "arguments": args,
                    "success": tool_result.success,
                    "error": tool_result.error,
                    "source": "subagent",
                    "task_category": category_value,
                }
                if veto is not None:
                    payload["vetoed_by"] = veto.name
                await self._hook_runner.fire(HookEvent.POST_TOOL_CALL, payload)
                if self._on_tool_invoked is not None:
                    try:
                        self._on_tool_invoked(tc.name, args, tool_result, duration_ms)
                    except (  # noqa: PERF203
                        TypeError,
                        ValueError,
                        RuntimeError,
                        AttributeError,
                    ):
                        log.exception("on_tool_invoked callback raised for %s", tc.name)
            # Fresh flavour each time we return to the thinking phase so
            # a long turn that cycles through tools rolls a new label per
            # thinking leg rather than reading the same verb forever.
            self._set_phase(flavour.pick_activity_label())
            tool_results: list[llm.ToolResult] = [
                llm.ToolResult(
                    tool_call_id=tc.id,
                    content=(
                        result.output if result.success else (result.error or "Unknown error")
                    ),
                    is_error=not result.success,
                    images=list(result.images),
                )
                for tc, result in zip(response.tool_calls, raw_results, strict=True)
            ]

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

            # Trim older tool results if we are approaching the context limit.
            _truncate_messages(messages, self._provider.context_window_tokens)

            response = await self._llm_turn(ctx, messages, llm_tools)

        # Record the final assistant response.
        if self._store:
            self._store.record_subagent_message(
                task_id,
                msg_idx,
                "assistant",
                response.content,
            )

        exit_state = _parse_exit_state(response.content)

        # Record exit state in the session store.
        if self._store:
            self._store.record_event(
                "subagent_exit",
                {
                    "task_id": self._context.task.id,
                    "task_title": self._context.task.title,
                    "exit_state": exit_state.value,
                    "rounds": rounds,
                },
            )

        # Build a one-line summary from the first line of the response.
        first_line = response.content.split("\n", 1)[0].strip()
        summary = first_line[:200] if first_line else f"Task {exit_state.value}"

        return SubagentResult(
            exit_state=exit_state,
            summary=summary,
            detail=response.content,
        )

    async def _complete_with_retry(
        self,
        messages: list[llm.Message],
        tools: list[llm.Tool] | None,
        max_tokens: int | None = None,
    ) -> llm.Response:
        """Call ``provider.complete()`` with linear-backoff retry for transient errors."""
        response = await complete_with_retry(
            self._provider,
            messages,
            tools,
            temperature=_SUBAGENT_TEMPERATURE,
            max_tokens=max_tokens,
            throttle=self._throttle,
        )
        if self._on_usage:
            # Stamp the actual provider identity so the callback records
            # the correct model — the subagent may be using the light
            # provider, not the primary one the executor holds.  Also
            # stamp the task category so ``/cost`` can break cost down
            # by research / build / deploy / test / debug (Phase 31.4).
            response.metadata["_provider_name"] = self._provider.name
            response.metadata["_provider_model"] = self._provider.model_name
            response.metadata["_task_category"] = self._context.task.category.value
            self._on_usage(response)
        return response

    async def _execute_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Look up and execute a tool by name."""
        return await execute_tool(self._tool_map, name, arguments)

    async def _llm_turn(
        self,
        ctx: CheckpointCtx | None,
        messages: list[llm.Message],
        tools: list[llm.Tool] | None,
    ) -> llm.Response:
        """Run one provider turn, checkpointing the response when a store is wired.

        On checkpoint hit the LLM isn't called at all — the stored
        :class:`llm.Response` is returned verbatim.  On miss the real
        call fires, the response is serialised via :func:`response_to_dict`
        and persisted, then returned to the caller as a live
        :class:`llm.Response`.  The input hash spans provider name +
        model name + serialised messages + serialised tool schemas so a
        conversation that diverges from a prior run invalidates the
        stale row rather than silently serving it.
        """
        if ctx is None:
            return await self._complete_with_retry(messages, tools)

        async def run_turn() -> dict[str, Any]:
            response = await self._complete_with_retry(messages, tools)
            return response_to_dict(response)

        input_hash = compute_input_hash(
            self._provider.name,
            self._provider.model_name,
            [_message_hash_repr(m) for m in messages],
            [_tool_hash_repr(t) for t in tools] if tools else None,
        )
        data = await checkpoint(
            ctx,
            "llm_turn",
            run_turn,
            input_hash=input_hash,
            kind=KIND_LLM_RESPONSE,
        )
        return response_from_dict(data)

    async def _execute_tool_with_checkpoint(
        self,
        ctx: CheckpointCtx | None,
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        """Run one tool call, checkpointing the result when a store is wired.

        Failed tool calls are persisted as ``success=False`` rows —
        Phase 52.3 deliberately caches deterministic errors so a
        rate-limited task doesn't re-burn a broken tool on every
        resume.  A future session-level "retry failed steps" flag
        (Phase 52.4) can flip this behaviour.
        """
        if ctx is None:
            return await self._execute_tool(name, arguments)

        async def run_tool() -> dict[str, Any]:
            result = await self._execute_tool(name, arguments)
            return tool_result_to_dict(result)

        input_hash = compute_input_hash(name, arguments)
        data = await checkpoint(
            ctx,
            f"tool:{name}",
            run_tool,
            input_hash=input_hash,
            kind=KIND_TOOL_RESULT,
        )
        return tool_result_from_dict(data)
