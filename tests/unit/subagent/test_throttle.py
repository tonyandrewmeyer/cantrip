"""Subagent tests: throttle."""

from unittest.mock import AsyncMock

import pytest

from cantrip.agent.subagent import (
    ProviderThrottle,
    Subagent,
)
from cantrip.llm.base import ProviderRateLimitError, Response
from tests.conftest import FakeProvider
from tests.unit.subagent.conftest import _make_context

# ===================================================================
# TestProviderThrottle
# ===================================================================


class TestProviderThrottle:
    """Tests for the shared rate-limit throttle."""

    @pytest.mark.asyncio
    async def test_no_throttle_no_wait(self) -> None:
        """Without signalling, wait_if_throttled returns immediately."""
        throttle = ProviderThrottle()
        # Should not block or raise.
        await throttle.wait_if_throttled("gemini")

    @pytest.mark.asyncio
    async def test_signal_then_wait(self) -> None:
        """After signalling, wait_if_throttled sleeps until the cooldown expires."""
        import cantrip.agent.subagent as subagent_mod

        throttle = ProviderThrottle()
        throttle.signal_rate_limit("gemini", 5.0)

        original_sleep = subagent_mod.asyncio.sleep
        slept: list[float] = []

        async def fake_sleep(duration: float) -> None:
            slept.append(duration)

        subagent_mod.asyncio.sleep = fake_sleep  # type: ignore[assignment]
        try:
            await throttle.wait_if_throttled("gemini")
        finally:
            subagent_mod.asyncio.sleep = original_sleep  # type: ignore[assignment]

        assert len(slept) == 1
        assert slept[0] > 0

    @pytest.mark.asyncio
    async def test_different_providers_independent(self) -> None:
        """Throttling one provider does not affect another."""
        throttle = ProviderThrottle()
        throttle.signal_rate_limit("gemini", 60.0)
        # Claude should not be throttled.
        await throttle.wait_if_throttled("claude")

    def test_longer_cooldown_preserved(self) -> None:
        """If an existing cooldown is longer, it is kept."""
        throttle = ProviderThrottle()
        throttle.signal_rate_limit("gemini", 60.0)
        first_deadline = throttle._cooldowns["gemini"]
        throttle.signal_rate_limit("gemini", 1.0)
        assert throttle._cooldowns["gemini"] == first_deadline

    @pytest.mark.asyncio
    async def test_throttle_passed_to_subagent(self) -> None:
        """Subagent calls wait_if_throttled before each LLM request."""
        waited = []

        class TrackingThrottle(ProviderThrottle):
            async def wait_if_throttled(self, provider_name: str) -> None:
                waited.append(provider_name)

        provider = FakeProvider(responses=[Response(content="done")])
        ctx = _make_context()
        throttle = TrackingThrottle()
        subagent = Subagent(ctx, tools=[], provider=provider, throttle=throttle)

        await subagent.run()

        assert len(waited) == 1
        assert waited[0] == provider.name

    @pytest.mark.asyncio
    async def test_throttle_signalled_on_rate_limit(self) -> None:
        """When a rate limit occurs, the throttle is signalled."""
        call_count = 0

        class FlakeyProvider(FakeProvider):
            async def complete(
                self,
                messages,
                tools=None,
                temperature=0.7,
                max_tokens=None,
                thinking_budget=None,  # noqa: ARG002
            ):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise ProviderRateLimitError("rate limited")
                return Response(content="recovered")

        throttle = ProviderThrottle()
        provider = FlakeyProvider()
        ctx = _make_context()
        subagent = Subagent(ctx, tools=[], provider=provider, throttle=throttle)

        import cantrip.agent.subagent as subagent_mod

        original_sleep = subagent_mod.asyncio.sleep
        subagent_mod.asyncio.sleep = AsyncMock()  # type: ignore[assignment]
        try:
            result = await subagent.run()
        finally:
            subagent_mod.asyncio.sleep = original_sleep  # type: ignore[assignment]

        assert result.text == "recovered"
        # The throttle should have recorded a cooldown for the provider.
        assert provider.name in throttle._cooldowns
