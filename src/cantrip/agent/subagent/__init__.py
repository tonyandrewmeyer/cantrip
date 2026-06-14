"""Subagent runtime — the worker that executes a single queued task.

``core`` holds the ``Subagent`` runner, its result/context dataclasses, the
provider-throttle, and the prompt/policy helpers; ``allowlists`` holds the
per-category tool allowlists and light-model routing data.
"""

# Re-exported so ``subagent.asyncio`` stays the patch target the throttle /
# retry tests reach for (asyncio is a shared module object).
import asyncio  # noqa: F401

from cantrip.agent.subagent.allowlists import _CATEGORY_TOOLS, _LIGHT_CATEGORIES
from cantrip.agent.subagent.core import (
    _ACCEPTANCE_PREFIX,
    _CATEGORY_GUIDANCE,
    _PROTECTED_ROUNDS,
    _TRUNCATION_CONTENT_THRESHOLD,
    _TRUNCATION_PREVIEW_LEN,
    MAX_BUILD_ROUNDS,
    MAX_SUBAGENT_ROUNDS,
    ExitState,
    ProviderThrottle,
    Subagent,
    SubagentContext,
    SubagentResult,
    ToolInvokedCallback,
    ToolInvokedPendingCallback,
    _build_policy_enforcer,
    _build_subagent_prompt,
    _filter_tools,
    _parse_exit_state,
    _select_provider,
    _task_instruction,
    _tools_for_llm,
    _truncate_messages,
)

__all__ = [
    "Subagent",
    "SubagentContext",
    "SubagentResult",
    "ExitState",
    "ProviderThrottle",
    "MAX_BUILD_ROUNDS",
    "MAX_SUBAGENT_ROUNDS",
    "ToolInvokedCallback",
    "ToolInvokedPendingCallback",
    "_CATEGORY_TOOLS",
    "_LIGHT_CATEGORIES",
    "_ACCEPTANCE_PREFIX",
    "_CATEGORY_GUIDANCE",
    "_PROTECTED_ROUNDS",
    "_TRUNCATION_CONTENT_THRESHOLD",
    "_TRUNCATION_PREVIEW_LEN",
    "_build_policy_enforcer",
    "_build_subagent_prompt",
    "_filter_tools",
    "_parse_exit_state",
    "_select_provider",
    "_task_instruction",
    "_tools_for_llm",
    "_truncate_messages",
]
