"""Shared retry logic for LLM provider calls.

Both the main conversation loop and subagent runners need to handle
transient errors (rate limits, overloaded, connection drops) with
linear backoff.  This module provides a single implementation used by
both.
"""

import asyncio
import logging
import random
from collections.abc import Callable

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
