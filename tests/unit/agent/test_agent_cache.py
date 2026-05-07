"""Tests for ``CantripAgent`` cache cascade detection and metrics events."""

from cantrip.agent.core import CantripAgent
from cantrip.llm.base import Response, Role
from tests.conftest import FakeProvider


class TestCacheCascadeIntegration:
    """Phase 78.1: cascade detector fires log + UI event through the agent."""

    def _make_agent(self) -> CantripAgent:
        provider = FakeProvider([])
        return CantripAgent(provider=provider)

    def _read(self, n: int = 1000) -> dict[str, int]:
        return {
            "prompt_tokens": n,
            "completion_tokens": 10,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": n,
        }

    def _create(self, n: int = 1000) -> dict[str, int]:
        return {
            "prompt_tokens": n,
            "completion_tokens": 10,
            "cache_creation_input_tokens": n,
            "cache_read_input_tokens": 0,
        }

    def test_cascade_surfaces_as_system_message_and_ui_event(self, caplog) -> None:
        """The April 23 pattern logs, appends a SYSTEM message, and publishes."""
        import logging

        agent = self._make_agent()
        events: list = []
        agent.event_bus.subscribe(None, lambda e: events.append(e))

        with caplog.at_level(logging.WARNING, logger="cantrip.agent.core"):
            agent._record_usage(Response(content="", usage=self._read()))
            agent._record_usage(Response(content="", usage=self._create()))
            agent._record_usage(Response(content="", usage=self._create()))
            # Baseline: no warning yet.
            assert not any("cascade" in r.getMessage().lower() for r in caplog.records)
            system_before = [m for m in agent.state.messages if m.role == Role.SYSTEM]
            assert system_before == []

            # Third consecutive creation turn trips the detector.
            agent._record_usage(Response(content="", usage=self._create()))

        warnings = [r for r in caplog.records if "cascade" in r.getMessage().lower()]
        assert len(warnings) == 1

        system_msgs = [m for m in agent.state.messages if m.role == Role.SYSTEM]
        assert len(system_msgs) == 1
        assert "cascade" in system_msgs[0].content.lower()

        chat_events = [
            e for e in events if e.type.value == "chat_message" and e.payload["role"] == "system"
        ]
        assert len(chat_events) == 1
        assert "cascade" in chat_events[0].payload["content"].lower()

    def test_no_cascade_no_event(self, caplog) -> None:
        """A healthy session (all reads) never emits the warning."""
        import logging

        agent = self._make_agent()
        events: list = []
        agent.event_bus.subscribe(None, lambda e: events.append(e))

        with caplog.at_level(logging.WARNING, logger="cantrip.agent.core"):
            for _ in range(5):
                agent._record_usage(Response(content="", usage=self._read()))

        assert not any("cascade" in r.getMessage().lower() for r in caplog.records)
        assert [m for m in agent.state.messages if m.role == Role.SYSTEM] == []


class TestCacheMetricsEvent:
    """Phase 78.2: CACHE_METRICS_UPDATED fires from the shared event bus."""

    def _make_agent(self) -> CantripAgent:
        return CantripAgent(provider=FakeProvider([]))

    def test_cache_metrics_event_published_per_turn(self) -> None:
        """Every turn carrying cache fields fires one event."""
        from cantrip.ui.events import EventType

        agent = self._make_agent()
        events: list = []
        agent.event_bus.subscribe(EventType.CACHE_METRICS_UPDATED, lambda e: events.append(e))

        agent._record_usage(
            Response(
                content="",
                usage={
                    "prompt_tokens": 100,
                    "completion_tokens": 10,
                    "cache_creation_input_tokens": 80,
                    "cache_read_input_tokens": 0,
                },
            )
        )
        agent._record_usage(
            Response(
                content="",
                usage={
                    "prompt_tokens": 100,
                    "completion_tokens": 10,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 80,
                },
            )
        )

        assert len(events) == 2
        # Running totals — first turn: 80 created / 0 read.
        assert events[0].payload["cache_creation_tokens"] == 80
        assert events[0].payload["cache_read_tokens"] == 0
        assert events[0].payload["hit_pct"] == 0.0
        # Second turn: 80 created / 80 read totals → 50%.
        assert events[1].payload["cache_creation_tokens"] == 80
        assert events[1].payload["cache_read_tokens"] == 80
        assert events[1].payload["cache_total_tokens"] == 160
        assert events[1].payload["hit_pct"] == 50.0

    def test_cache_metrics_event_absent_without_cache_fields(self) -> None:
        """Providers with no cache fields (e.g. Gemini) don't emit the event."""
        from cantrip.ui.events import EventType

        agent = self._make_agent()
        events: list = []
        agent.event_bus.subscribe(EventType.CACHE_METRICS_UPDATED, lambda e: events.append(e))

        agent._record_usage(
            Response(
                content="",
                usage={"prompt_tokens": 100, "completion_tokens": 10},
            )
        )
        assert events == []
