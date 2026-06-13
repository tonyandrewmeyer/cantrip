"""Token-usage / cost accounting and tool-failure-streak tracking.

This module hosts :class:`UsageTracker`, a service composed onto
:class:`~cantrip.agent.core.CantripAgent`. It accumulates token counts and cost
from API responses, watches for the prompt-cache cascade, and tracks
consecutive tool failures so the agent can warn before, and ultimately enforce,
the failure cap. All instance state stays on the agent; the service reads and
writes it through ``self._agent``.
"""

from __future__ import annotations

import json
import logging
import typing

from cantrip.llm.base import LLMProvider, Message, Response, Role
from cantrip.ui import events as ui_events

if typing.TYPE_CHECKING:
    from typing import Any

    from cantrip.agent.core import CantripAgent

log = logging.getLogger("cantrip.agent.core")


class UsageTracker:
    """Usage, cost, and tool-failure-streak tracking for the agent."""

    def __init__(self, agent: CantripAgent) -> None:
        self._agent = agent

    def record_usage(
        self,
        response: Response,
        provider: LLMProvider | None = None,
    ) -> int | None:
        """Record token usage from a provider response if a store is active.

        ``provider`` defaults to ``self._agent.provider`` so existing call
        sites stay unchanged; Phase 71.2 architect/editor passes pass
        the specific pass's provider so ``/cost`` can break costs out
        per-model.
        """
        attribution = provider or self._agent.provider
        if response.usage:
            created = response.usage.get("cache_creation_input_tokens", 0) or 0
            read = response.usage.get("cache_read_input_tokens", 0) or 0
            self._agent.cache_creation_tokens += created
            self._agent.cache_read_tokens += read
            self._agent._check_cache_cascade(response.usage)
            # Phase 78.2: publish on every turn where the provider
            # reports cache fields so the Web status element and the
            # TUI modelbar stay in lockstep off a single signal.
            if (
                "cache_creation_input_tokens" in response.usage
                or "cache_read_input_tokens" in response.usage
            ):
                self._agent._event_bus.publish(
                    ui_events.cache_metrics_updated(
                        cache_creation_tokens=self._agent.cache_creation_tokens,
                        cache_read_tokens=self._agent.cache_read_tokens,
                    )
                )
        self._agent._ensure_store()
        if self._agent._store and response.usage:
            return self._agent._store.record_usage(
                provider=attribution.name,
                model=attribution.model_name,
                prompt_tokens=response.usage.get("prompt_tokens", 0),
                completion_tokens=response.usage.get("completion_tokens", 0),
                cache_read_tokens=response.usage.get("cache_read_input_tokens", 0) or 0,
                cache_creation_tokens=response.usage.get("cache_creation_input_tokens", 0) or 0,
            )
        return None

    def check_cache_cascade(self, usage: dict[str, int]) -> None:
        """Feed per-turn usage into the cache cascade detector.

        Surfaces the warning as a WARNING log, a SYSTEM conversation
        message (so it rides along with the transcript), and a UI
        chat event so the TUI and Web chat show it in-band — the
        April 23 lesson is that passive metrics aren't enough.
        """
        warning = self._agent._cache_monitor.observe(usage)
        if warning is None:
            return
        log.warning("Cache cascade detected: %s", warning)
        self._agent.state.messages.append(Message(role=Role.SYSTEM, content=warning))
        self._agent._event_bus.publish(ui_events.chat_message(role="system", content=warning))

    def track_tool_failure_streak(
        self, tool_name: str, arguments: dict[str, Any], success: bool
    ) -> None:
        """Update the consecutive same-(tool, args) failure counter.

        Resets to zero on a successful call.  The streak only compounds
        when the *same* ``(tool name, serialised arguments)`` signature
        fails again; any different signature resets it to one — so a
        model can legitimately retry one ``edit_file`` after fixing its
        ``old_string`` without tripping the cap.  Once the streak hits
        two it also publishes a "tool retrying (n/cap)" status update.
        """
        if success:
            self._agent.state.consecutive_tool_failures = 0
            self._agent.state.last_failed_tool_signature = None
            self._agent.state.last_failed_tool_name = None
            return
        try:
            args_repr = json.dumps(arguments, sort_keys=True, default=str)[:200]
        except (TypeError, ValueError):
            args_repr = "<unserialisable>"
        signature = f"{tool_name}:{args_repr}"
        if signature == self._agent.state.last_failed_tool_signature:
            self._agent.state.consecutive_tool_failures += 1
        else:
            self._agent.state.consecutive_tool_failures = 1
            self._agent.state.last_failed_tool_signature = signature
        self._agent.state.last_failed_tool_name = tool_name
        n = self._agent.state.consecutive_tool_failures
        if n >= 3:
            log.warning(
                "Tool %s has now failed %d consecutive times "
                "(cap is %d; tune via CANTRIP_TOOL_FAILURE_CAP)",
                signature,
                n,
                self._agent.state.tool_failure_cap,
            )
        if n >= 2:
            # Phase 107.4: surface the streak on the status bar so the
            # TUI/Web show a "tool retrying (3/5)" badge while the loop
            # is grinding, not just afterwards in the logs.
            self._agent._publish_activity(
                f"⟳ tool retrying ({n}/{self._agent.state.tool_failure_cap})"
            )

    def maybe_warn_before_failure_cap(self) -> None:
        """One turn before the cap fires, tell the model to change tack.

        Phase 107.3: a model that keeps re-emitting the same failing
        tool call gets one explicit, in-conversation chance to split a
        large payload, switch tools, fix the arguments, or bail — before
        cantrip force-blocks the task.  Fires only on the exact turn the
        streak reaches ``cap - 1`` so the warning lands while there is
        still a round left to act on it; a cap below 2 leaves no room
        for the warning and is silently skipped.
        """
        cap = self._agent.state.tool_failure_cap
        n = self._agent.state.consecutive_tool_failures
        if cap < 2 or n != cap - 1:
            return
        tool = self._agent.state.last_failed_tool_name or "that tool"
        warning = (
            f"You have called {tool} {n} times in a row with the same arguments "
            "and it has failed every time. One more identical failure and this "
            "task will be marked BLOCKED and the run will stop. Do something "
            "different now: split a large payload into smaller writes, use a "
            "different tool, correct the arguments — or, if you genuinely cannot "
            "make progress, say so plainly instead of retrying."
        )
        self._agent.state.messages.append(Message(role=Role.SYSTEM, content=warning))
        self._agent._event_bus.publish(ui_events.chat_message(role="system", content=warning))
        log.warning(
            "Phase 107: injected pre-cap warning after %d consecutive %s failures",
            n,
            tool,
        )

    def consecutive_failure_cap_exceeded(self) -> str | None:
        """Return a blocked-reason string when the cap has been hit.

        ``None`` means "still within tolerance, keep looping".  The
        reason string is operator-facing — it goes into the
        ``blocked_reason`` on the work-queue task and into stderr.
        """
        if self._agent.state.consecutive_tool_failures < self._agent.state.tool_failure_cap:
            return None
        sig = self._agent.state.last_failed_tool_signature or "<unknown>"
        return f"Tool {sig} failed {self._agent.state.consecutive_tool_failures} consecutive times"
