"""Shared :class:`LLMProvider` doubles for unit and integration tests.

Several test modules used to define their own ``RecordingProvider``
subclass of :class:`tests.conftest.FakeProvider` to capture the
``messages`` / ``temperature`` / ``thinking_budget`` arguments handed
in.  This module centralises that pattern.

Use :class:`RecordingProvider` when you want to assert "the planner
sent these messages / this temperature / this thinking_budget" — every
:meth:`complete` call is captured in :attr:`messages_seen`,
:attr:`temperatures_seen`, and :attr:`thinking_budgets_seen`.

Use :class:`CallbackProvider` when the response needs to vary based
on what's in the message history — pass a ``callback(messages, tools)
→ Response`` and it runs on every :meth:`complete`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from cantrip.llm import base as llm
from tests.conftest import FakeProvider


class RecordingProvider(FakeProvider):
    """:class:`FakeProvider` that records every :meth:`complete` invocation.

    The provider always returns ``response`` (default: an empty
    :data:`~cantrip.llm.schemas.PLANNER_BRIEFING` payload — Phase 73.3
    moved planner calls onto
    :func:`~cantrip.llm.structured.complete_structured`, so the default
    reply must validate against the briefing schema or every
    recording-only test would burn the validation-retry budget).  Past
    invocations live in:

    * :attr:`messages_seen` — flattened list of every message handed in.
    * :attr:`temperatures_seen` — one entry per call.
    * :attr:`thinking_budgets_seen` — one entry per call (``None`` when
      the caller didn't pass a budget).

    The simpler shape suits planner / subagent assertions; reach for
    :class:`CallbackProvider` if the response needs to vary per call.
    """

    def __init__(self, response: llm.Response | None = None) -> None:
        super().__init__()
        self._response = (
            response if response is not None else llm.Response(content='{"tasks": []}')
        )
        self.messages_seen: list[llm.Message] = []
        self.temperatures_seen: list[float] = []
        self.thinking_budgets_seen: list[int | None] = []

    async def complete(
        self,
        messages: list[llm.Message],
        tools: list[llm.Tool] | None = None,  # noqa: ARG002
        temperature: float = 0.7,
        max_tokens: int | None = None,  # noqa: ARG002
        thinking_budget: int | None = None,
        response_schema: dict | None = None,
    ) -> llm.Response:
        self.last_response_schema = response_schema
        self._call_count += 1
        self.messages_seen.extend(messages)
        self.temperatures_seen.append(temperature)
        self.thinking_budgets_seen.append(thinking_budget)
        # Yield to the event loop so executor tests don't starve other coroutines.
        await asyncio.sleep(0)
        return self._response


class CallbackProvider(FakeProvider):
    """Provider that delegates to a callback for dynamic response logic.

    The callback receives the messages and tools and returns a
    :class:`llm.Response`.  Useful when tests need to inspect message
    content or vary behaviour per call.
    """

    def __init__(
        self,
        callback: Callable[[list[llm.Message], list[llm.Tool] | None], llm.Response],
    ) -> None:
        super().__init__()
        self._callback = callback

    async def complete(
        self,
        messages: list[llm.Message],
        tools: list[llm.Tool] | None = None,
        temperature: float = 0.7,  # noqa: ARG002
        max_tokens: int | None = None,  # noqa: ARG002
        thinking_budget: int | None = None,  # noqa: ARG002
        response_schema: dict | None = None,
    ) -> llm.Response:
        self.last_response_schema = response_schema
        self._call_count += 1
        # Yield to the event loop so executor tests don't starve other coroutines.
        await asyncio.sleep(0)
        return self._callback(messages, tools)


class MultiRoleProvider(FakeProvider):
    """Provider with separate response queues for planner vs subagent calls.

    Distinguishes by checking the system prompt for ``task planner``
    (planner) or ``autonomous subagent`` (subagent) keywords.
    """

    def __init__(
        self,
        planner_responses: list[llm.Response] | None = None,
        subagent_responses: list[llm.Response] | None = None,
    ) -> None:
        super().__init__()
        self._planner_responses = list(planner_responses or [])
        self._subagent_responses = list(subagent_responses or [])
        self._planner_call_count = 0
        self._subagent_call_count = 0

    async def complete(
        self,
        messages: list[llm.Message],
        tools: list[llm.Tool] | None = None,  # noqa: ARG002
        temperature: float = 0.7,  # noqa: ARG002
        max_tokens: int | None = None,  # noqa: ARG002
        thinking_budget: int | None = None,  # noqa: ARG002
        response_schema: dict | None = None,
    ) -> llm.Response:
        self.last_response_schema = response_schema
        self._call_count += 1

        # Determine role from system prompt content.
        system_text = ""
        for msg in messages:
            if msg.role == llm.Role.SYSTEM:
                system_text = msg.content.lower()
                break

        # Yield to the event loop so executor tests don't starve other coroutines.
        await asyncio.sleep(0)

        if "task planner" in system_text and (
            self._planner_call_count < len(self._planner_responses)
        ):
            resp = self._planner_responses[self._planner_call_count]
            self._planner_call_count += 1
            return resp

        if "autonomous subagent" in system_text and (
            self._subagent_call_count < len(self._subagent_responses)
        ):
            resp = self._subagent_responses[self._subagent_call_count]
            self._subagent_call_count += 1
            return resp

        return llm.Response(content="default response")
