"""Tests for the shared LLM retry logic."""

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from cantrip.agent.retry import (
    TRANSIENT_BASE_DELAY,
    TRANSIENT_RETRIES,
    RetryEvent,
    _resolve_base_delay,
    complete_with_retry,
    stream_with_retry,
)
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
            thinking_budget=None,
        )


class TestConnectionErrorRetry:
    """Phase 102.3: ``ProviderConnectionError`` is treated as transient."""

    @pytest.mark.asyncio
    async def test_retries_on_connection_error(self):
        """A mid-stream disconnect retries with backoff and recovers."""
        expected = llm.Response(content="ok")
        provider = _make_provider(
            [
                llm.ProviderConnectionError("server hung up"),
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
    async def test_connection_error_raises_after_max_retries(self):
        """Persistent ``ProviderConnectionError`` propagates once retries exhaust."""
        provider = _make_provider(
            [
                llm.ProviderConnectionError("drop 1"),
                llm.ProviderConnectionError("drop 2"),
                llm.ProviderConnectionError("drop 3"),
            ]
        )

        with pytest.raises(llm.ProviderConnectionError, match="drop 3"):
            await complete_with_retry(
                provider,
                messages=[],
                tools=None,
                max_retries=3,
                base_delay=0,
            )

        assert provider.complete.call_count == 3

    @pytest.mark.asyncio
    async def test_connection_error_uses_short_backoff(self, monkeypatch):
        """Connection drops use a shorter backoff than rate-limit retries.

        The retry layer's connection-drop path uses an exponential
        ``2/4/8s`` ladder rather than the rate-limit ``base_delay *
        attempt`` ladder so a slow snap can recover quickly without
        waiting for cloud-grade backoff windows.
        """
        sleeps: list[float] = []

        async def _capture_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr("cantrip.agent.retry.asyncio.sleep", _capture_sleep)

        provider = _make_provider(
            [
                llm.ProviderConnectionError("drop 1"),
                llm.ProviderConnectionError("drop 2"),
                llm.Response(content="ok"),
            ]
        )

        await complete_with_retry(
            provider,
            messages=[],
            tools=None,
            max_retries=3,
            # ``base_delay`` is the rate-limit ladder; connection drops
            # ignore it.  Pass a wildly different value so the test
            # would notice if the wrong ladder fired.
            base_delay=1000,
        )

        assert len(sleeps) == 2
        # First retry around 2s, second around 4s — both far below the
        # rate-limit ladder's 1000+ seconds.
        assert all(s < 10 for s in sleeps)
        assert sleeps[1] > sleeps[0]

    @pytest.mark.asyncio
    async def test_on_retry_invoked_for_connection_error(self):
        """The optional ``on_retry`` hook fires before each backoff sleep."""
        events: list[RetryEvent] = []
        provider = _make_provider(
            [
                llm.ProviderConnectionError("drop"),
                llm.Response(content="ok"),
            ]
        )

        await complete_with_retry(
            provider,
            messages=[],
            tools=None,
            base_delay=0,
            on_retry=events.append,
        )

        assert len(events) == 1
        event = events[0]
        assert event.provider_name == "test-provider"
        assert isinstance(event.exception, llm.ProviderConnectionError)
        assert event.attempt == 1
        assert event.delay > 0

    @pytest.mark.asyncio
    async def test_on_retry_invoked_for_rate_limit(self):
        """The hook also fires for rate-limit retries (Phase 102.4 banner)."""
        events: list[RetryEvent] = []
        provider = _make_provider(
            [
                llm.ProviderRateLimitError("slow"),
                llm.Response(content="ok"),
            ]
        )

        await complete_with_retry(
            provider,
            messages=[],
            tools=None,
            base_delay=0,
            on_retry=events.append,
        )

        assert len(events) == 1
        assert isinstance(events[0].exception, llm.ProviderRateLimitError)


class _ScriptedStreamProvider(llm.LLMProvider):
    """Test double whose ``stream()`` replays scripted attempts.

    Each attempt is either a list of ``Chunk`` objects (yielded in order)
    or an exception class to raise after yielding any prefix chunks.  The
    helper covers the cases the slow-path tests want to exercise:
    successful single-attempt streams, mid-stream connection drops with
    a successful retry, and exhausted-retry failures.
    """

    name = "scripted-stream"
    context_window_tokens = 200_000
    model_name = "scripted"

    def __init__(self, attempts: list[list[llm.Chunk] | BaseException]) -> None:
        self._attempts = list(attempts)
        self.stream_calls = 0

    async def complete(  # noqa: D401, ARG002 — abstract impl required.
        self,
        messages: list[llm.Message],
        tools: list[llm.Tool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
        response_schema: dict | None = None,
    ) -> llm.Response:
        raise AssertionError("complete() should not be called in streaming tests")

    async def stream(  # noqa: ARG002
        self,
        messages: list[llm.Message],
        tools: list[llm.Tool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
        response_schema: dict | None = None,
    ) -> AsyncIterator[llm.Chunk]:
        idx = self.stream_calls
        self.stream_calls += 1
        if idx >= len(self._attempts):
            raise AssertionError("stream() called more times than scripted attempts")
        attempt = self._attempts[idx]
        if isinstance(attempt, BaseException):
            raise attempt
        for chunk in attempt:
            yield chunk


class TestStreamWithRetry:
    """Phase 102.2: slow-path streaming with retry + partial writeback."""

    @pytest.mark.asyncio
    async def test_accumulates_chunks_into_response(self):
        """Concatenates content chunks and carries the final chunk's metadata."""
        provider = _ScriptedStreamProvider(
            [
                [
                    llm.Chunk(content="Hello, "),
                    llm.Chunk(content="world!"),
                    llm.Chunk(
                        is_final=True,
                        usage={"prompt_tokens": 5, "completion_tokens": 2},
                        metadata={"finish": "stop"},
                    ),
                ],
            ]
        )

        result = await stream_with_retry(
            provider,
            messages=[],
            tools=None,
            base_delay=0,
        )

        assert result.content == "Hello, world!"
        assert result.usage == {"prompt_tokens": 5, "completion_tokens": 2}
        assert result.metadata == {"finish": "stop"}

    @pytest.mark.asyncio
    async def test_carries_tool_calls_from_final_chunk(self):
        """Tool calls accumulated on the final chunk land on the response."""
        tc = llm.ToolCall(id="t1", name="read_file", arguments={"path": "x.py"})
        provider = _ScriptedStreamProvider(
            [
                [
                    llm.Chunk(content=""),
                    llm.Chunk(tool_calls=[tc], is_final=True),
                ],
            ]
        )

        result = await stream_with_retry(
            provider,
            messages=[],
            tools=None,
            base_delay=0,
        )

        assert result.tool_calls == [tc]

    @pytest.mark.asyncio
    async def test_retries_on_mid_stream_connection_drop(self):
        """A connection drop on the first attempt retries and succeeds."""
        provider = _ScriptedStreamProvider(
            [
                llm.ProviderConnectionError("server hung up"),
                [
                    llm.Chunk(content="recovered"),
                    llm.Chunk(is_final=True),
                ],
            ]
        )

        result = await stream_with_retry(
            provider,
            messages=[],
            tools=None,
            base_delay=0,
        )

        assert result.content == "recovered"
        assert provider.stream_calls == 2

    @pytest.mark.asyncio
    async def test_retries_on_rate_limit(self):
        """Rate-limit errors retry with backoff just like complete_with_retry."""
        provider = _ScriptedStreamProvider(
            [
                llm.ProviderRateLimitError("slow down"),
                [
                    llm.Chunk(content="ok"),
                    llm.Chunk(is_final=True),
                ],
            ]
        )

        result = await stream_with_retry(
            provider,
            messages=[],
            tools=None,
            base_delay=0,
        )

        assert result.content == "ok"

    @pytest.mark.asyncio
    async def test_non_transient_error_not_retried(self):
        """Non-transient ``ProviderError`` propagates immediately."""
        provider = _ScriptedStreamProvider(
            [
                llm.ProviderError("auth failed"),
            ]
        )

        with pytest.raises(llm.ProviderError, match="auth failed"):
            await stream_with_retry(
                provider,
                messages=[],
                tools=None,
                base_delay=0,
            )

        assert provider.stream_calls == 1

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        """Persistent connection drops propagate once retries exhaust."""
        provider = _ScriptedStreamProvider(
            [
                llm.ProviderConnectionError("drop 1"),
                llm.ProviderConnectionError("drop 2"),
                llm.ProviderConnectionError("drop 3"),
            ]
        )

        with pytest.raises(llm.ProviderConnectionError, match="drop 3"):
            await stream_with_retry(
                provider,
                messages=[],
                tools=None,
                max_retries=3,
                base_delay=0,
            )

        assert provider.stream_calls == 3

    @pytest.mark.asyncio
    async def test_on_partial_throttled_by_chunk_count(self):
        """``on_partial`` fires every ``partial_chunk_interval`` chunks plus a final flush."""
        partials: list[str] = []
        provider = _ScriptedStreamProvider(
            [
                [
                    llm.Chunk(content="a"),
                    llm.Chunk(content="b"),
                    llm.Chunk(content="c"),
                    llm.Chunk(content="d"),
                    llm.Chunk(is_final=True),
                ],
            ]
        )

        result = await stream_with_retry(
            provider,
            messages=[],
            tools=None,
            base_delay=0,
            on_partial=partials.append,
            partial_chunk_interval=2,
            partial_seconds_interval=10_000,  # disable the time-based trigger
        )

        # Two interval flushes (after chunks 2 and 4) + the trailing
        # final flush.  The last two see the same accumulated text but
        # the duplication is a deliberately cheap idempotent SQL update.
        assert partials == ["ab", "abcd", "abcd"]
        assert result.content == "abcd"

    @pytest.mark.asyncio
    async def test_on_partial_runs_even_when_only_final_flush_fires(self):
        """A short stream still gets a final-flush writeback so resume can recover."""
        partials: list[str] = []
        provider = _ScriptedStreamProvider(
            [
                [
                    llm.Chunk(content="hi"),
                    llm.Chunk(is_final=True),
                ],
            ]
        )

        await stream_with_retry(
            provider,
            messages=[],
            tools=None,
            base_delay=0,
            on_partial=partials.append,
            partial_chunk_interval=100,
            partial_seconds_interval=10_000,
        )

        assert partials == ["hi"]

    @pytest.mark.asyncio
    async def test_on_retry_invoked_for_connection_drop(self):
        """The Phase 102.4 reconnect hook fires on streaming retries too."""
        events: list[RetryEvent] = []
        provider = _ScriptedStreamProvider(
            [
                llm.ProviderConnectionError("drop"),
                [llm.Chunk(content="ok"), llm.Chunk(is_final=True)],
            ]
        )

        await stream_with_retry(
            provider,
            messages=[],
            tools=None,
            base_delay=0,
            on_retry=events.append,
        )

        assert len(events) == 1
        assert isinstance(events[0].exception, llm.ProviderConnectionError)
        assert events[0].provider_name == "scripted-stream"


class TestResolveBaseDelay:
    """Phase 41.9: Claude uses a shorter base delay than other providers."""

    def test_claude_uses_shorter_default(self):
        """Claude's default base delay is below the generic 30s."""
        provider = _make_provider([])
        provider.name = "claude"
        assert _resolve_base_delay(provider, None) == 15

    def test_unknown_provider_uses_generic_default(self):
        """Providers with no specific override fall back to TRANSIENT_BASE_DELAY."""
        provider = _make_provider([])
        provider.name = "some-other-provider"
        assert _resolve_base_delay(provider, None) == TRANSIENT_BASE_DELAY

    def test_explicit_override_wins(self):
        """An explicit base_delay argument is used regardless of provider."""
        provider = _make_provider([])
        provider.name = "claude"
        assert _resolve_base_delay(provider, 42) == 42

    def test_zero_override_respected(self):
        """Passing base_delay=0 (for fast tests) is respected rather than defaulting."""
        provider = _make_provider([])
        provider.name = "claude"
        assert _resolve_base_delay(provider, 0) == 0


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
