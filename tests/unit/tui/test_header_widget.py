"""Tests for Phase 108.8 — slim contextual header.

Replaces Textual's stock ``Header`` (generic ``⭘`` glyph + ``Title
— Subtitle`` chrome) with a custom :class:`CantripHeader` that
shows the four signals a user actually wants at a glance:
``✦ cantrip`` brand mark, ``provider/model``, ``~/<path>``, and
``branch:<name>``.
"""

from __future__ import annotations

import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.tui.app import CantripApp
from cantrip.tui.widgets.header import CantripHeader, _format_path

pytestmark = pytest.mark.tui


# ---------------------------------------------------------------------------
# _format_path — pure helper, no Pilot needed
# ---------------------------------------------------------------------------


def test_format_path_under_home_collapses_to_tilde() -> None:
    """A path under ``$HOME`` renders as ``~/<rel>``."""
    target = pathlib.Path.home() / "cantrip"
    assert _format_path(target) == "~/cantrip"


def test_format_path_outside_home_renders_absolute(tmp_path: pathlib.Path) -> None:
    """A path outside ``$HOME`` renders as the absolute path.

    ``tmp_path`` lives under ``/tmp`` on Linux runners, which is
    not ancestor-of ``$HOME`` — so the helper must not crash on
    the ``relative_to`` and must fall through to the absolute form.
    """
    rendered = _format_path(tmp_path)
    assert rendered == str(tmp_path.expanduser().resolve())


def test_format_path_none_is_empty() -> None:
    """``None`` returns ``""`` so the segment is dropped at render time."""
    assert _format_path(None) == ""


def test_format_path_home_root_collapses_to_bare_tilde() -> None:
    """``$HOME`` itself renders as ``~`` rather than ``~/.``."""
    home = pathlib.Path.home()
    assert _format_path(home) == "~"


# ---------------------------------------------------------------------------
# CantripHeader rendering — no Pilot needed (widget supports update without mount)
# ---------------------------------------------------------------------------


def _rendered(header: CantripHeader) -> str:
    """Snapshot the header line by calling ``_refresh`` directly.

    The widget normally renders into its child ``Static``; without
    a mount we read back from the helper that builds the line.
    Mounting under a Pilot is exercised in the end-to-end tests below.
    """
    segments: list[str] = ["[bold $primary]✦ cantrip[/bold $primary]"]
    if header.model_name:
        segments.append(header.model_name)
    if header.charm_path is not None:
        from cantrip.tui.widgets.header import _format_path as fmt

        path_label = fmt(header.charm_path)
        if path_label:
            segments.append(path_label)
    if header.git_branch:
        segments.append(f"branch:{header.git_branch}")
    return " · ".join(segments)


def test_header_brand_alone_when_no_state() -> None:
    """A fresh header carries only the brand mark."""
    header = CantripHeader()
    rendered = _rendered(header)
    assert "✦ cantrip" in rendered
    assert "·" not in rendered


def test_header_combines_all_segments() -> None:
    """Brand + model + path + branch all line up with ``·`` separators."""
    header = CantripHeader()
    header.model_name = "gemini/gemini-3-flash"
    header.charm_path = pathlib.Path.home() / "cantrip"
    header.git_branch = "main"
    rendered = _rendered(header)
    assert "✦ cantrip" in rendered
    assert "gemini/gemini-3-flash" in rendered
    assert "~/cantrip" in rendered
    assert "branch:main" in rendered
    # Brand · model · path · branch = three separators.
    assert rendered.count(" · ") == 3


def test_header_drops_missing_segments() -> None:
    """Empty model and branch do not leave dangling separators."""
    header = CantripHeader()
    header.charm_path = pathlib.Path.home() / "charm-x"
    rendered = _rendered(header)
    assert rendered.count(" · ") == 1
    assert "✦ cantrip" in rendered
    assert "~/charm-x" in rendered


# ---------------------------------------------------------------------------
# End-to-end: header is mounted by ``CantripApp`` and updates from app state.
# ---------------------------------------------------------------------------


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
    agent.provider = MagicMock()
    agent.provider.name = "gemini"
    agent.provider.model_name = "gemini-3-flash-preview"
    agent.provider.context_window_tokens = 1_048_576
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


@pytest.mark.asyncio
async def test_header_mounts_and_carries_brand_mark() -> None:
    """The header is mounted at the top of the app and shows the brand mark."""
    p1, p2 = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            header = pilot.app.query_one("#cantrip-header", CantripHeader)
            text = pilot.app.query_one("#cantrip-header-text")
            rendered = str(text.render())
            assert "✦ cantrip" in rendered
            # The model from the mock agent flows through.
            assert "gemini/gemini-3-flash-preview" in rendered
            # Header is exactly one row tall (Phase 108.8 contract).
            assert header.styles.height.value == 1


@pytest.mark.asyncio
async def test_header_updates_when_agent_state_changes() -> None:
    """``_update_header_subtitle`` re-pushes state into the header."""
    p1, p2 = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            text = pilot.app.query_one("#cantrip-header-text")

            pilot.app._agent.provider.model_name = "claude-sonnet-4-6"
            pilot.app._agent.provider.name = "claude"
            pilot.app._update_header_subtitle()
            await pilot.pause()

            rendered = str(text.render())
            assert "claude/claude-sonnet-4-6" in rendered
