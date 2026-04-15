"""Tests for the shared LLM retry logic."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from cantrip.agent.retry import TRANSIENT_BASE_DELAY, TRANSIENT_RETRIES, complete_with_retry
from cantrip.agent.subagent import ProviderThrottle
from cantrip.llm import base as llm


def _make_provider(side_effects: list) -> llm.LLMProvider:
    """Build a mock provider whose ``complete()`` returns *side_effects* in order."""
    provider = AsyncMock(spec=llm.LLMProvider)
    provider.name = "test-provider"
    provider.complete = AsyncMock(side_effect=side_effects)
    return provider


class TestCompleteWithRetry:
    """Tests for complete_with_retry."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """Returns immediately when the first call succeeds."""
        expected = llm.Response(content="ok")
        provider = _make_provider([expected])

        result = await complete_with_retry(
            provider,
            messages=[],
            tools=None,
            base_delay=0,
        )

        assert result is expected
        assert provider.complete.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_rate_limit(self):
        """Retries after a ProviderRateLimitError and succeeds."""
        expected = llm.Response(content="ok")
        provider = _make_provider(
            [
                llm.ProviderRateLimitError("slow down"),
                expected,
            ]
        )

        result = await complete_with_retry(
            provider,
            messages=[],
            tools=None,
            base_delay=0,
        )

        assert result is expected
        assert provider.complete.call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_overloaded(self):
        """Retries after a ProviderOverloadedError and succeeds."""
        expected = llm.Response(content="ok")
        provider = _make_provider(
            [
                llm.ProviderOverloadedError("busy"),
                expected,
            ]
        )

        result = await complete_with_retry(
            provider,
            messages=[],
            tools=None,
            base_delay=0,
        )

        assert result is expected
        assert provider.complete.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        """Raises after exhausting all retries."""
        provider = _make_provider(
            [
                llm.ProviderRateLimitError("slow down"),
                llm.ProviderRateLimitError("slow down"),
                llm.ProviderRateLimitError("slow down"),
            ]
        )

        with pytest.raises(llm.ProviderRateLimitError):
            await complete_with_retry(
                provider,
                messages=[],
                tools=None,
                max_retries=3,
                base_delay=0,
            )

        assert provider.complete.call_count == 3

    @pytest.mark.asyncio
    async def test_non_transient_error_not_retried(self):
        """Non-transient ProviderError is raised immediately."""
        provider = _make_provider(
            [
                llm.ProviderError("auth failed"),
            ]
        )

        with pytest.raises(llm.ProviderError, match="auth failed"):
            await complete_with_retry(
                provider,
                messages=[],
                tools=None,
                base_delay=0,
            )

        assert provider.complete.call_count == 1

    @pytest.mark.asyncio
    async def test_mixed_transient_errors(self):
        """Handles a mix of rate-limit and overloaded errors before success."""
        expected = llm.Response(content="finally")
        provider = _make_provider(
            [
                llm.ProviderRateLimitError("rate"),
                llm.ProviderOverloadedError("overloaded"),
                expected,
            ]
        )

        result = await complete_with_retry(
            provider,
            messages=[],
            tools=None,
            max_retries=3,
            base_delay=0,
        )

        assert result is expected
        assert provider.complete.call_count == 3

    @pytest.mark.asyncio
    async def test_default_retry_constants(self):
        """Verify the module-level retry defaults."""
        assert TRANSIENT_RETRIES == 3
        assert TRANSIENT_BASE_DELAY == 30

    @pytest.mark.asyncio
    async def test_custom_max_retries(self):
        """Custom max_retries is respected."""
        expected = llm.Response(content="ok")
        provider = _make_provider(
            [
                llm.ProviderRateLimitError("1"),
                llm.ProviderRateLimitError("2"),
                llm.ProviderRateLimitError("3"),
                llm.ProviderRateLimitError("4"),
                expected,
            ]
        )

        result = await complete_with_retry(
            provider,
            messages=[],
            tools=None,
            max_retries=5,
            base_delay=0,
        )

        assert result is expected
        assert provider.complete.call_count == 5

    @pytest.mark.asyncio
    async def test_passes_temperature_and_tools(self):
        """Temperature and tools are forwarded to the provider."""
        expected = llm.Response(content="ok")
        provider = _make_provider([expected])
        tools = [llm.Tool(name="t", description="d", parameters={})]
        messages = [llm.Message(role=llm.Role.USER, content="hi")]

        await complete_with_retry(
            provider,
            messages=messages,
            tools=tools,
            temperature=0.3,
            base_delay=0,
        )

        provider.complete.assert_called_once_with(
            messages=messages,
            tools=tools,
            temperature=0.3,
            max_tokens=None,
        )


class TestProviderThrottle:
    """Tests for the shared throttle coordinator."""

    @pytest.mark.asyncio
    async def test_no_throttle_when_no_signal(self):
        """wait_if_throttled returns immediately when no signal has been sent."""
        throttle = ProviderThrottle()
        # Should not hang or sleep.
        await asyncio.wait_for(throttle.wait_if_throttled("test"), timeout=1.0)

    @pytest.mark.asyncio
    async def test_signal_causes_wait(self):
        """After signalling, wait_if_throttled sleeps for the cooldown."""
        throttle = ProviderThrottle()
        throttle.signal_rate_limit("test", delay=0.1)

        # Should complete after ~0.1s.
        await asyncio.wait_for(throttle.wait_if_throttled("test"), timeout=2.0)

    @pytest.mark.asyncio
    async def test_longer_cooldown_wins(self):
        """If a longer cooldown is signalled, it takes precedence."""
        throttle = ProviderThrottle()
        throttle.signal_rate_limit("test", delay=0.05)
        throttle.signal_rate_limit("test", delay=0.2)

        # The 0.2s cooldown should be in effect.
        # We just verify it completes within a reasonable window.
        await asyncio.wait_for(throttle.wait_if_throttled("test"), timeout=2.0)

    @pytest.mark.asyncio
    async def test_shorter_cooldown_does_not_override(self):
        """A shorter signal does not reduce an existing longer cooldown."""
        throttle = ProviderThrottle()
        throttle.signal_rate_limit("test", delay=10.0)
        throttle.signal_rate_limit("test", delay=0.0)

        # The 10s cooldown should still be in effect — we check that the
        # deadline was not reduced by verifying a short timeout fails.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(throttle.wait_if_throttled("test"), timeout=0.05)

    @pytest.mark.asyncio
    async def test_different_providers_independent(self):
        """Throttles for different providers are independent."""
        throttle = ProviderThrottle()
        throttle.signal_rate_limit("provider_a", delay=10.0)

        # provider_b should not be throttled.
        await asyncio.wait_for(throttle.wait_if_throttled("provider_b"), timeout=0.5)

    @pytest.mark.asyncio
    async def test_throttle_with_complete_with_retry(self):
        """complete_with_retry integrates with the throttle."""
        throttle = ProviderThrottle()
        expected = llm.Response(content="ok")
        provider = _make_provider(
            [
                llm.ProviderRateLimitError("rate"),
                expected,
            ]
        )

        result = await complete_with_retry(
            provider,
            messages=[],
            tools=None,
            base_delay=0,
            throttle=throttle,
        )

        assert result is expected
