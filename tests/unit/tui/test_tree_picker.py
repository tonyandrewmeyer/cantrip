"""Behaviour tests for :class:`TreePickerScreen` (Phase 93.1 backfill).

The session-tree picker had no test exercising ``compose`` or the
selection / cancel paths — only the slash-command layer that builds the
``TreeNode`` list was covered.  These tests mount the modal in a minimal
host app and drive it with ``Pilot``.
"""

from __future__ import annotations

import types
from unittest.mock import patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from cantrip.agent.commands.session import TreeNode
from cantrip.tui.screens.tree import TreePickerScreen

pytestmark = pytest.mark.tui

_TERMINAL = (100, 40)


class _Host(App):
    def compose(self) -> ComposeResult:  # pragma: no cover - trivial
        yield from ()


def _node(node_id: int, *, depth: int = 0, active: bool = False, ts: str = "") -> TreeNode:
    return TreeNode(
        depth=depth,
        id=node_id,
        role="user",
        label=f"turn {node_id}",
        timestamp=ts,
        on_active_branch=active,
    )


class TestOptionRendering:
    def test_option_for_includes_marker_indent_and_timestamp(self) -> None:
        opt = TreePickerScreen._option_for(
            _node(7, depth=2, active=True, ts="2026-05-10T12:30:00.123456")
        )
        assert opt.id == "7"
        assert opt.prompt.startswith("    * [7] user: turn 7")
        assert "(2026-05-10T12:30:00)" in opt.prompt

    def test_option_for_without_timestamp_omits_parenthetical(self) -> None:
        opt = TreePickerScreen._option_for(_node(3))
        assert opt.prompt == "  [3] user: turn 3"


class TestComposeStates:
    @pytest.mark.asyncio
    async def test_empty_nodes_shows_placeholder(self) -> None:
        async with _Host().run_test(size=_TERMINAL) as pilot:
            screen = TreePickerScreen([])
            await pilot.app.push_screen(screen)
            await pilot.pause()
            empty = screen.query_one("#tree-empty", Static)
            assert "No turns yet" in str(empty.render())
            assert not screen.query("#tree-options")

    @pytest.mark.asyncio
    async def test_nodes_render_an_option_list(self) -> None:
        async with _Host().run_test(size=_TERMINAL) as pilot:
            screen = TreePickerScreen([_node(1, active=True), _node(2, depth=1)])
            await pilot.app.push_screen(screen)
            await pilot.pause()
            options = screen.query_one("#tree-options", OptionList)
            assert options.option_count == 2


class TestSelectionAndCancel:
    @pytest.mark.asyncio
    async def test_selecting_a_node_dismisses_with_turn_id(self) -> None:
        result: dict[str, int | None] = {}

        async with _Host().run_test(size=_TERMINAL) as pilot:
            screen = TreePickerScreen([_node(11), _node(12)])
            await pilot.app.push_screen(screen, callback=lambda v: result.__setitem__("v", v))
            await pilot.pause()
            options = screen.query_one("#tree-options", OptionList)
            options.highlighted = 1
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert result["v"] == 12

    @pytest.mark.parametrize("bad_id", [None, "not-a-number"])
    @pytest.mark.asyncio
    async def test_unusable_option_id_dismisses_with_none(self, bad_id: str | None) -> None:
        """Defensive branches: a missing or non-numeric option id → ``None``.

        Real options always carry a numeric id, so drive the handler
        directly with a synthetic ``OptionSelected`` event.
        """
        async with _Host().run_test(size=_TERMINAL) as pilot:
            screen = TreePickerScreen([_node(1)])
            await pilot.app.push_screen(screen)
            await pilot.pause()
            event = types.SimpleNamespace(option=Option("x", id=bad_id))
            with patch.object(screen, "dismiss") as dismiss:
                screen.on_option_list_option_selected(event)  # type: ignore[arg-type]
            dismiss.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_escape_cancels_with_none(self) -> None:
        result: dict[str, int | None] = {}

        async with _Host().run_test(size=_TERMINAL) as pilot:
            screen = TreePickerScreen([_node(1)])
            await pilot.app.push_screen(screen, callback=lambda v: result.__setitem__("v", v))
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert result["v"] is None
            assert not isinstance(pilot.app.screen, TreePickerScreen)
