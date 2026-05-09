"""Tests for Phase 108.4 — ModelInfoBar default-collapsed.

The bar used to default to a two-line rich breakdown that always
took two rows of vertical space.  It now defaults to a single
compact line showing the glance-and-go signals
(``provider/model · NN% ctx · $X.XX``); F7 expands to the
existing rich form.  Line 2 stays populated even when collapsed
so a press of F7 reveals up-to-date data immediately, without
waiting for the next 5 s refresh tick.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.tui.app import CantripApp
from cantrip.tui.widgets.modelbar import ModelInfoBar

pytestmark = pytest.mark.tui


def _mock_agent() -> MagicMock:
    agent = MagicMock()
    agent.prepare = AsyncMock()
    agent.process_message = AsyncMock(return_value="ok")

    async def _stream(_msg: str):
        yield "ok"

    agent.process_message_streaming = _stream
    agent.state = MagicMock()
    agent.state.charm_type = None
    agent.state.test_results = None
    agent.state.messages = []
    agent.state.github_repo = None
    agent.state.charm_name = None
    agent.state.charm_path = None
    agent.state.dev_model = None
    agent.state.cos_model = None
    agent.preflight_result = MagicMock(fully_ready=True)
    agent.start_executor = MagicMock()
    agent.stop_executor = AsyncMock()
    agent.executor_running = False
    agent.watcher_running = False
    agent.issue_triage_running = False
    agent.work_queue = MagicMock(all_tasks=MagicMock(return_value=[]))
    agent.provider = MagicMock(
        name="gemini",
        model_name="gemini-3-flash-preview",
        context_window_tokens=1_048_576,
    )
    agent.context_manager = MagicMock()
    agent.context_manager.compaction_threshold = 0.80
    agent.context_manager.estimate_tokens = MagicMock(return_value=0)
    agent.store = None
    agent.load_state = MagicMock(return_value=False)
    agent.save_state = MagicMock()
    no_preview = MagicMock()
    no_preview.exists = False
    agent.preview_session = MagicMock(return_value=no_preview)
    agent.transcript_tail = MagicMock(return_value=[])
    agent.archive_session = MagicMock(return_value=None)
    agent.mcp_registry = MagicMock()
    agent.mcp_registry.configured = []
    agent.start_mcp = AsyncMock()
    agent.stop_mcp = AsyncMock()
    return agent


def _patch_app():
    return (
        patch("cantrip.tui.app.create_provider", return_value=MagicMock()),
        patch("cantrip.tui.app.CantripAgent", return_value=_mock_agent()),
    )


# ---------------------------------------------------------------------------
# Pure-builder tests (no Pilot needed)
# ---------------------------------------------------------------------------


def test_compact_line_shows_provider_model_ctx_cost():
    """All three glance signals appear in the compact line when populated.

    The cost segment is gated on actual session activity (prompt +
    completion tokens > 0) — the same gate the legacy expanded
    path uses — so this test populates the token counts as well as
    the cost itself.
    """
    bar = ModelInfoBar()
    bar.provider_name = "gemini"
    bar.model_name = "gemini-3-flash-preview"
    bar.context_used = 130_000
    bar.context_window = 1_000_000
    bar.session_prompt_tokens = 1_500
    bar.session_completion_tokens = 200
    bar.session_cost_usd = 0.04
    line = bar._build_line1_compact()
    assert "gemini/gemini-3-flash-preview" in line
    assert "13% ctx" in line
    assert "$0.04" in line
    # The model and the metrics are joined by the ``·`` separator —
    # one line, three segments.
    assert line.count("·") == 2


def test_compact_line_drops_cost_without_session_activity():
    """Cost segment vanishes when no LLM turns have happened yet."""
    bar = ModelInfoBar()
    bar.provider_name = "gemini"
    bar.model_name = "gemini-3-flash"
    bar.context_used = 100_000
    bar.context_window = 1_000_000
    bar.session_cost_usd = 0.04  # Set, but session_total still 0.
    line = bar._build_line1_compact()
    assert "$0.04" not in line
    assert "10% ctx" in line


def test_compact_line_drops_zero_segments():
    """A bar with no context window and zero cost shows only the model."""
    bar = ModelInfoBar()
    bar.provider_name = "gemini"
    bar.model_name = "gemini-3-flash"
    line = bar._build_line1_compact()
    assert line == "gemini/gemini-3-flash"
    assert "·" not in line


def test_compact_line_empty_when_nothing_populated():
    """Brand-new bar (no model wired up) renders an empty compact line."""
    bar = ModelInfoBar()
    assert bar._build_line1_compact() == ""


def test_expanded_line_keeps_full_breakdown():
    """The expanded path is unchanged from the legacy two-line form."""
    bar = ModelInfoBar()
    bar.provider_name = "gemini"
    bar.model_name = "gemini-3-flash"
    bar.thinking_mode = "extended"
    bar.light_model_name = "haiku"
    bar.github_repo = "owner/repo"
    line = bar._build_line1_expanded()
    assert "gemini/gemini-3-flash" in line
    assert "[extended]" in line
    assert "light: haiku" in line
    assert "gh: owner/repo" in line


# ---------------------------------------------------------------------------
# End-to-end: mounted under Pilot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bar_mounts_in_compact_state():
    """Default ``-compact`` class is set so line 2 is hidden."""
    p1, p2 = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            bar = pilot.app.query_one("#model-info", ModelInfoBar)
            assert bar.expanded is False
            assert bar.has_class("-compact")


@pytest.mark.asyncio
async def test_expanding_drops_compact_class():
    """Flipping ``expanded`` removes the class so CSS reveals line 2."""
    p1, p2 = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            bar = pilot.app.query_one("#model-info", ModelInfoBar)
            bar.expanded = True
            await pilot.pause()
            assert not bar.has_class("-compact")


@pytest.mark.asyncio
async def test_collapsing_re_adds_compact_class():
    """Round-trip toggle restores the ``-compact`` class."""
    p1, p2 = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            bar = pilot.app.query_one("#model-info", ModelInfoBar)
            bar.expanded = True
            await pilot.pause()
            bar.expanded = False
            await pilot.pause()
            assert bar.has_class("-compact")


@pytest.mark.asyncio
async def test_line_two_stays_populated_when_compact():
    """Line 2 content lives even while hidden so F7 reveal is instant.

    Without this, F7 would flash a blank line for a tick before the
    next 5 s ``_update_model_info`` refilled it.
    """
    p1, p2 = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            await pilot.pause()
            pilot.app._update_model_info()
            await pilot.pause()

            bar = pilot.app.query_one("#model-info", ModelInfoBar)
            line2 = pilot.app.query_one("#model-info-line2")
            # Compact mode hides line 2 visually; the underlying
            # Static still carries the full breakdown text.
            rendered = str(line2.render())
            assert bar.expanded is False
            assert "context:" in rendered
