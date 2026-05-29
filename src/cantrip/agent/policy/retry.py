"""Shared retry logic for LLM provider calls.

Both the main conversation loop and subagent runners need to handle
transient errors (rate limits, overloaded, connection drops) with
linear backoff.  This module provides a single implementation used by
both.
"""

import asyncio
import logging
import random
import time
from collections.abc import Callable
from typing import Any

from cantrip.llm import base as llm

log = logging.getLogger(__name__)

# Default retry settings for transient LLM errors.
TRANSIENT_RETRIES = 3
TRANSIENT_BASE_DELAY = 30  # seconds

# Phase 102.3: connection drops on slow local snaps recover within a
# couple of seconds — a 30-second linear backoff would waste minutes on
# what is effectively a TCP-level retry.  Shorter base delay, smaller
# multiplier; the rate-limit / overloaded paths keep their existing
# longer backoff because cloud providers actually take that long.
_CONNECTION_BASE_DELAY = 2  # seconds

# Anthropic's rate limits typically recover within 10–20 seconds, so a
# 30-second base delay over-waits on the first retry.  Keep the generic
# default for other providers — they recover on different schedules.
_PROVIDER_BASE_DELAY: dict[str, int] = {
    "claude": 15,
}


# Optional listener invoked just before sleeping for a transient retry,
# so the UI can show a banner ("provider reconnecting…").  Phase 102.4
# wires the conversation loop into this hook.
type RetryNotifier = Callable[["RetryEvent"], None]


class RetryEvent:
    """Payload for the optional retry-listener callback.

    Carries enough context for a UI banner to render meaningfully
    without coupling the retry layer to any particular surface.
    """

    __slots__ = ("attempt", "delay", "exception", "max_retries", "provider_name")

    def __init__(
        self,
        *,
        provider_name: str,
        exception: BaseException,
        attempt: int,
        max_retries: int,
        delay: float,
    ) -> None:
        self.provider_name = provider_name
        self.exception = exception
        self.attempt = attempt
        self.max_retries = max_retries
        self.delay = delay


def _resolve_base_delay(provider: llm.LLMProvider, explicit: int | None) -> int:
    """Pick the per-provider base delay unless the caller gave one."""
    if explicit is not None:
        return explicit
    return _PROVIDER_BASE_DELAY.get(provider.name, TRANSIENT_BASE_DELAY)


async def complete_with_retry(
    provider: llm.LLMProvider,
    messages: list[llm.Message],
    tools: list[llm.Tool] | None,
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    thinking_budget: int | None = None,
    max_retries: int = TRANSIENT_RETRIES,
    base_delay: int | None = None,
    throttle: object | None = None,
    on_retry: RetryNotifier | None = None,
) -> llm.Response:
    """Call ``provider.complete()`` with linear-backoff retry for transient errors.

    When *throttle* is a ``ProviderThrottle`` instance, it is consulted
    before each attempt and signalled on rate-limit errors so concurrent
    callers back off together.

    Phase 102.3: ``ProviderConnectionError`` (a mid-stream disconnect or
    read timeout from a slow local snap) is also retried, with a
    shorter base delay because connection drops recover faster than rate
    limits.  ``on_retry`` (Phase 102.4) is invoked before each sleep so
    the UI can surface a "reconnecting" banner.
    """
    last_error: (
        llm.ProviderRateLimitError
        | llm.ProviderOverloadedError
        | llm.ProviderConnectionError
        | None
    ) = None
    effective_base_delay = _resolve_base_delay(provider, base_delay)

    for attempt in range(1, max_retries + 1):
        try:
            # Respect shared cooldown from other callers.
            if throttle is not None:
                await throttle.wait_if_throttled(provider.name)
            return await provider.complete(
                messages=messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                thinking_budget=thinking_budget,
            )
        except (llm.ProviderRateLimitError, llm.ProviderOverloadedError) as exc:
            last_error = exc
            if attempt == max_retries:
                raise
            # Jitter prevents thundering-herd retries from concurrent subagents.
            delay = effective_base_delay * attempt + random.uniform(0, effective_base_delay * 0.25)

            # Signal the shared throttle so other callers back off.
            if throttle is not None:
                throttle.signal_rate_limit(provider.name, delay)
            log.warning(
                "Provider unavailable — retrying in %ds (attempt %d/%d): %s",
                delay,
                attempt,
                max_retries,
                exc,
            )
            if on_retry is not None:
                on_retry(
                    RetryEvent(
                        provider_name=provider.name,
                        exception=exc,
                        attempt=attempt,
                        max_retries=max_retries,
                        delay=delay,
                    )
                )
            await asyncio.sleep(delay)
        except llm.ProviderConnectionError as exc:
            # Phase 102.3: transient TCP-level drop.  Retry with a
            # shorter (exponential) backoff than the rate-limit path —
            # local snaps recover quickly, so 2/4/8s is a sensible
            # ladder rather than 30/60/90.
            last_error = exc
            if attempt == max_retries:
                raise
            delay = _CONNECTION_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            log.warning(
                "Provider connection dropped — reconnecting in %.1fs (attempt %d/%d): %s",
                delay,
                attempt,
                max_retries,
                exc,
            )
            if on_retry is not None:
                on_retry(
                    RetryEvent(
                        provider_name=provider.name,
                        exception=exc,
                        attempt=attempt,
                        max_retries=max_retries,
                        delay=delay,
                    )
                )
            await asyncio.sleep(delay)

    # Unreachable — the final attempt re-raises above.
    assert last_error is not None
    raise last_error


# Phase 102.2: callback for partial-token writeback during streaming.
# The slow-path conversation hands a closure that persists the partial
# assistant text to the session store so a mid-stream disconnect leaves
# a recoverable transcript instead of an empty turn.
type PartialWriteback = Callable[[str], None]


# Default throttle: at most one writeback per ``_PARTIAL_CHUNK_INTERVAL``
# chunks or per ``_PARTIAL_SECONDS_INTERVAL`` seconds, whichever first.
# Chunks are typically a few tokens each on the inference snap, so 8
# chunks is roughly a sentence's worth — frequent enough that resume
# keeps useful context, rare enough that SQLite isn't writing on every
# token.
_PARTIAL_CHUNK_INTERVAL = 8
_PARTIAL_SECONDS_INTERVAL = 2.0


async def stream_with_retry(
    provider: llm.LLMProvider,
    messages: list[llm.Message],
    tools: list[llm.Tool] | None,
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    thinking_budget: int | None = None,
    max_retries: int = TRANSIENT_RETRIES,
    base_delay: int | None = None,
    throttle: object | None = None,
    on_retry: RetryNotifier | None = None,
    on_partial: PartialWriteback | None = None,
    partial_chunk_interval: int = _PARTIAL_CHUNK_INTERVAL,
    partial_seconds_interval: float = _PARTIAL_SECONDS_INTERVAL,
) -> llm.Response:
    """Iterate ``provider.stream()`` with the same transient-error retry policy.

    Phase 102.2: the slow-path conversation loop routes through this
    helper instead of :func:`complete_with_retry` so partial-token
    decoding keeps a TCP-level heartbeat alive on connections that
    would otherwise trip the inference snap's keep-alive.  Chunks are
    accumulated into a single :class:`llm.Response` whose ``content``,
    ``tool_calls``, ``usage`` and ``metadata`` fields mirror what
    ``complete()`` would have returned.

    When *on_partial* is set, it fires periodically with the
    accumulated assistant text so a recoverable transcript lands on
    disk even when a generation never completes.  Throttled by
    *partial_chunk_interval* chunks or *partial_seconds_interval*
    seconds, whichever first.  Errors raised from the callback are
    not caught — callers should make their writeback resilient to
    transient backend errors.

    Retries on the same set of transient errors as
    :func:`complete_with_retry`: ``ProviderRateLimitError``,
    ``ProviderOverloadedError`` and ``ProviderConnectionError`` (a
    mid-stream disconnect or read timeout).  A successful retry starts
    streaming from scratch — the partial text already written via
    *on_partial* lands on disk for resume to find but is discarded
    from the in-memory accumulator so the returned ``Response`` is the
    full, single attempt that succeeded.
    """
    last_error: (
        llm.ProviderRateLimitError
        | llm.ProviderOverloadedError
        | llm.ProviderConnectionError
        | None
    ) = None
    effective_base_delay = _resolve_base_delay(provider, base_delay)

    for attempt in range(1, max_retries + 1):
        try:
            if throttle is not None:
                await throttle.wait_if_throttled(provider.name)
            return await _drain_stream(
                provider,
                messages,
                tools,
                temperature=temperature,
                max_tokens=max_tokens,
                thinking_budget=thinking_budget,
                on_partial=on_partial,
                partial_chunk_interval=partial_chunk_interval,
                partial_seconds_interval=partial_seconds_interval,
            )
        except (llm.ProviderRateLimitError, llm.ProviderOverloadedError) as exc:
            last_error = exc
            if attempt == max_retries:
                raise
            delay = effective_base_delay * attempt + random.uniform(0, effective_base_delay * 0.25)
            if throttle is not None:
                throttle.signal_rate_limit(provider.name, delay)
            log.warning(
                "Provider unavailable mid-stream — retrying in %ds (attempt %d/%d): %s",
                delay,
                attempt,
                max_retries,
                exc,
            )
            if on_retry is not None:
                on_retry(
                    RetryEvent(
                        provider_name=provider.name,
                        exception=exc,
                        attempt=attempt,
                        max_retries=max_retries,
                        delay=delay,
                    )
                )
            await asyncio.sleep(delay)
        except llm.ProviderConnectionError as exc:
            last_error = exc
            if attempt == max_retries:
                raise
            delay = _CONNECTION_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            log.warning(
                "Stream dropped — reconnecting in %.1fs (attempt %d/%d): %s",
                delay,
                attempt,
                max_retries,
                exc,
            )
            if on_retry is not None:
                on_retry(
                    RetryEvent(
                        provider_name=provider.name,
                        exception=exc,
                        attempt=attempt,
                        max_retries=max_retries,
                        delay=delay,
                    )
                )
            await asyncio.sleep(delay)

    assert last_error is not None
    raise last_error


async def _drain_stream(
    provider: llm.LLMProvider,
    messages: list[llm.Message],
    tools: list[llm.Tool] | None,
    *,
    temperature: float,
    max_tokens: int | None,
    thinking_budget: int | None,
    on_partial: PartialWriteback | None,
    partial_chunk_interval: int,
    partial_seconds_interval: float,
) -> llm.Response:
    """Iterate one streaming attempt and assemble the final :class:`Response`.

    Factored out of :func:`stream_with_retry` so the retry loop reads
    cleanly: the iteration body is the same on every attempt and the
    transient-error handling sits in a single ``try`` per attempt.
    """
    content_parts: list[str] = []
    tool_calls: list[llm.ToolCall] = []
    finish_reason = "stop"
    usage: dict[str, int] = {}
    metadata: dict[str, Any] = {}
    chunks_since_partial = 0
    last_partial_at = time.monotonic()

    async for chunk in provider.stream(
        messages=messages,
        tools=tools,
        temperature=temperature,
        max_tokens=max_tokens,
        thinking_budget=thinking_budget,
    ):
        if chunk.content:
            content_parts.append(chunk.content)
            chunks_since_partial += 1
        if chunk.is_final:
            if chunk.tool_calls:
                tool_calls = chunk.tool_calls
            if chunk.usage:
                usage = chunk.usage
            if chunk.metadata:
                metadata = chunk.metadata

        if on_partial is not None and content_parts:
            now = time.monotonic()
            if (
                chunks_since_partial >= partial_chunk_interval
                or now - last_partial_at >= partial_seconds_interval
            ):
                on_partial("".join(content_parts))
                chunks_since_partial = 0
                last_partial_at = now

    # Final flush so a successful generation lands its full text on
    # disk before the caller advances the conversation.
    if on_partial is not None and content_parts:
        on_partial("".join(content_parts))

    return llm.Response(
        content="".join(content_parts),
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        usage=usage,
        metadata=metadata,
    )
