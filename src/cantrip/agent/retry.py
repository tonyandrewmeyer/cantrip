"""Shared retry logic for LLM provider calls.

Both the main conversation loop and subagent runners need to handle
transient errors (rate limits, overloaded) with linear backoff.  This
module provides a single implementation used by both.
"""

import asyncio
import logging
import random

from cantrip.llm import base as llm

log = logging.getLogger(__name__)

# Default retry settings for transient LLM errors.
TRANSIENT_RETRIES = 3
TRANSIENT_BASE_DELAY = 30  # seconds

# Anthropic's rate limits typically recover within 10–20 seconds, so a
# 30-second base delay over-waits on the first retry.  Keep the generic
# default for other providers — they recover on different schedules.
_PROVIDER_BASE_DELAY: dict[str, int] = {
    "claude": 15,
}


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
) -> llm.Response:
    """Call ``provider.complete()`` with linear-backoff retry for transient errors.

    When *throttle* is a ``ProviderThrottle`` instance, it is consulted
    before each attempt and signalled on rate-limit errors so concurrent
    callers back off together.
    """
    last_error: llm.ProviderRateLimitError | llm.ProviderOverloadedError | None = None
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
            await asyncio.sleep(delay)

    # Unreachable — the final attempt re-raises above.
    assert last_error is not None
    raise last_error
