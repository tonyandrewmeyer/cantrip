"""Tests for the Inner Parliament emotion subagents."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from cantrip.agent import emotions
from cantrip.llm.base import Response
from tests.conftest import FakeProvider

if TYPE_CHECKING:
    import pathlib


class TestResolveEnabled:
    """``resolve_enabled`` picks the run list from user input."""

    def test_none_falls_back_to_defaults(self) -> None:
        assert emotions.resolve_enabled(None) == list(emotions.DEFAULT_ENABLED)

    def test_empty_list_runs_nothing(self) -> None:
        assert emotions.resolve_enabled([]) == []

    def test_preserves_order_and_case_folds(self) -> None:
        assert emotions.resolve_enabled(["Fear", "JOY"]) == ["fear", "joy"]

    def test_deduplicates(self) -> None:
        assert emotions.resolve_enabled(["joy", "joy", "fear"]) == ["joy", "fear"]

    def test_drops_unknown_names(self) -> None:
        assert emotions.resolve_enabled(["joy", "smugness", "fear"]) == ["joy", "fear"]


class TestParseSuggestions:
    """Extracting structured suggestions from a raw LLM response."""

    def test_parses_valid_json_array(self) -> None:
        text = json.dumps(
            [
                {
                    "severity": "high",
                    "title": "Add a backup action",
                    "rationale": "Operators need a one-shot way to snapshot.",
                    "suggested_change": "Implement a `backup` action that calls BGSAVE.",
                }
            ]
        )
        result = emotions.parse_suggestions("joy", text)
        assert len(result) == 1
        assert result[0].emotion == "joy"
        assert result[0].severity == "high"
        assert result[0].title == "Add a backup action"

    def test_strips_prose_around_json(self) -> None:
        text = (
            "Here are my thoughts:\n\n"
            '[{"severity": "low", "title": "Ship it", '
            '"rationale": "Why not", "suggested_change": "Nothing"}]\n\n'
            "Hope that helps!"
        )
        result = emotions.parse_suggestions("joy", text)
        assert len(result) == 1
        assert result[0].title == "Ship it"

    def test_caps_at_three_suggestions(self) -> None:
        items = [
            {
                "severity": "low",
                "title": f"Idea {i}",
                "rationale": "x",
                "suggested_change": "y",
            }
            for i in range(10)
        ]
        result = emotions.parse_suggestions("joy", json.dumps(items))
        assert len(result) == 3

    def test_skips_entries_without_a_title(self) -> None:
        text = json.dumps(
            [
                {"severity": "low", "rationale": "x", "suggested_change": "y"},
                {
                    "severity": "low",
                    "title": "Real one",
                    "rationale": "x",
                    "suggested_change": "y",
                },
            ]
        )
        result = emotions.parse_suggestions("joy", text)
        assert len(result) == 1
        assert result[0].title == "Real one"

    def test_defaults_missing_severity_to_medium(self) -> None:
        text = json.dumps([{"title": "Untriaged"}])
        result = emotions.parse_suggestions("joy", text)
        assert result[0].severity == "medium"

    def test_empty_array_is_valid(self) -> None:
        assert emotions.parse_suggestions("joy", "[]") == []

    def test_raises_when_no_array_found(self) -> None:
        with pytest.raises(ValueError, match="no JSON array"):
            emotions.parse_suggestions("joy", "I have no opinions today.")

    def test_raises_on_invalid_json(self) -> None:
        with pytest.raises(ValueError, match="not valid JSON"):
            emotions.parse_suggestions("joy", "[this is not json]")


class TestBuildContextMessage:
    """The user message assembled for each emotion."""

    def test_includes_charm_identity(self) -> None:
        msg = emotions.build_context_message(
            charm_name="redis-k8s",
            charm_type="k8s",
            framework="paas",
            charm_path=None,
            decisions=[],
        )
        assert "redis-k8s" in msg
        assert "k8s" in msg
        assert "paas" in msg

    def test_includes_recent_decisions(self) -> None:
        decisions = [
            {"type": "substrate", "choice": "k8s", "reason": "no state"},
            {"type": "framework", "choice": "paas"},
        ]
        msg = emotions.build_context_message(
            charm_name="x",
            charm_type=None,
            framework=None,
            charm_path=None,
            decisions=decisions,
        )
        assert "substrate: k8s — no state" in msg
        assert "framework: paas" in msg

    def test_inlines_sampled_files(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text("type: charm\nname: demo\n")
        (tmp_path / "README.md").write_text("# Demo\n")
        msg = emotions.build_context_message(
            charm_name="demo",
            charm_type=None,
            framework=None,
            charm_path=tmp_path,
            decisions=[],
        )
        assert "charmcraft.yaml" in msg
        assert "type: charm" in msg
        assert "README.md" in msg

    def test_oversized_files_are_skipped(self, tmp_path: pathlib.Path) -> None:
        big = "x" * 10_000
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "charm.py").write_text(big)
        msg = emotions.build_context_message(
            charm_name="demo",
            charm_type=None,
            framework=None,
            charm_path=tmp_path,
            decisions=[],
        )
        assert "above the inline limit" in msg
        assert big not in msg

    def test_placeholder_when_nothing_to_show(self) -> None:
        msg = emotions.build_context_message(
            charm_name=None,
            charm_type=None,
            framework=None,
            charm_path=None,
            decisions=[],
        )
        assert "No charm has been created yet" in msg


class TestFormatReport:
    """Rendering a parliament result as markdown."""

    def test_groups_by_emotion_in_requested_order(self) -> None:
        result = emotions.ParliamentResult(
            suggestions=[
                emotions.Suggestion("fear", "high", "Lock it down", "risk", "use TLS"),
                emotions.Suggestion("joy", "low", "Add icon", "nice", "draw one"),
            ],
            failed_emotions=[],
        )
        report = emotions.format_report(result, enabled=["joy", "fear"])
        joy_at = report.index("## Joy")
        fear_at = report.index("## Fear")
        assert joy_at < fear_at
        assert "Add icon" in report
        assert "Lock it down" in report

    def test_notes_failed_emotions(self) -> None:
        result = emotions.ParliamentResult(
            suggestions=[],
            failed_emotions=["disgust"],
        )
        report = emotions.format_report(result, enabled=["disgust"])
        assert "disgust" in report
        assert "not produce a parseable response" in report

    def test_empty_result_yields_placeholder(self) -> None:
        result = emotions.ParliamentResult(suggestions=[], failed_emotions=[])
        report = emotions.format_report(result, enabled=[])
        assert "no opinions" in report

    def test_shows_severity_and_suggested_change(self) -> None:
        result = emotions.ParliamentResult(
            suggestions=[
                emotions.Suggestion("joy", "medium", "Add emoji", "delight", "use unicode hearts")
            ],
            failed_emotions=[],
        )
        report = emotions.format_report(result, enabled=["joy"])
        assert "medium" in report
        assert "use unicode hearts" in report


class TestRunParliament:
    """End-to-end: parallel emotion runs with a fake provider."""

    @pytest.mark.asyncio
    async def test_aggregates_suggestions_from_each_emotion(self) -> None:
        # One canned response per emotion call; fake returns them in order.
        joy_resp = Response(
            content=json.dumps(
                [
                    {
                        "severity": "low",
                        "title": "Joy pick",
                        "rationale": "r",
                        "suggested_change": "c",
                    }
                ]
            )
        )
        fear_resp = Response(
            content=json.dumps(
                [
                    {
                        "severity": "high",
                        "title": "Fear pick",
                        "rationale": "r",
                        "suggested_change": "c",
                    }
                ]
            )
        )
        provider = FakeProvider(responses=[joy_resp, fear_resp])

        result = await emotions.run_parliament(
            enabled=["joy", "fear"],
            provider=provider,
            charm_name="demo",
        )

        assert len(result.suggestions) == 2
        titles = {s.title for s in result.suggestions}
        assert titles == {"Joy pick", "Fear pick"}
        assert result.failed_emotions == []

    @pytest.mark.asyncio
    async def test_unparseable_response_marks_emotion_failed(self) -> None:
        bad = Response(content="I don't feel like emitting JSON today.")
        good = Response(
            content=json.dumps(
                [{"severity": "low", "title": "OK", "rationale": "r", "suggested_change": "c"}]
            )
        )
        # Parallel gather order isn't guaranteed, so queue two identical
        # fallbacks and check the aggregate shape rather than ordering.
        provider = FakeProvider(responses=[bad, good])

        result = await emotions.run_parliament(
            enabled=["joy", "fear"],
            provider=provider,
            charm_name="demo",
        )

        assert len(result.failed_emotions) == 1
        assert len(result.suggestions) == 1

    @pytest.mark.asyncio
    async def test_empty_enabled_list_returns_empty_result(self) -> None:
        provider = FakeProvider()
        result = await emotions.run_parliament(enabled=[], provider=provider)
        assert result.suggestions == []
        assert result.failed_emotions == []
