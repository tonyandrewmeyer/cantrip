"""Shared retry logic for LLM provider calls.

Both the main conversation loop and subagent runners need to handle
transient errors (rate limits, overloaded) with linear backoff.  This
module provides a single implementation used by both.
"""

import asyncio
import logging

from cantrip.llm import base as llm

log = logging.getLogger(__name__)

# Default retry settings for transient LLM errors.
TRANSIENT_RETRIES = 3
TRANSIENT_BASE_DELAY = 30  # seconds


async def complete_with_retry(
    provider: llm.LLMProvider,
    messages: list[llm.Message],
    tools: list[llm.Tool] | None,
    *,
    temperature: float = 0.7,
    max_retries: int = TRANSIENT_RETRIES,
    base_delay: int = TRANSIENT_BASE_DELAY,
    throttle: object | None = None,
) -> llm.Response:
    """Call ``provider.complete()`` with linear-backoff retry for transient errors.

    When *throttle* is a ``ProviderThrottle`` instance, it is consulted
    before each attempt and signalled on rate-limit errors so concurrent
    callers back off together.
    """
    last_error: llm.ProviderRateLimitError | llm.ProviderOverloadedError | None = None

    for attempt in range(1, max_retries + 1):
        try:
            # Respect shared cooldown from other callers.
            if throttle is not None:
                await throttle.wait_if_throttled(provider.name)
            return await provider.complete(
                messages=messages,
                tools=tools,
                temperature=temperature,
            )
        except (llm.ProviderRateLimitError, llm.ProviderOverloadedError) as exc:
            last_error = exc
            if attempt == max_retries:
                raise
            delay = base_delay * attempt

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
    raise last_error  # type: ignore[misc]
