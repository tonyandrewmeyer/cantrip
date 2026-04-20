"""Tests for the RelationDetailScreen.

Unit tests cover the pure ``_fetch_data_blocking`` helper; Pilot tests
drive the screen through its mount / worker / render lifecycle with
``subprocess.run`` mocked.
"""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets import RichLog

from cantrip.tui.screens.relation import RelationDetailScreen

pytestmark = pytest.mark.tui


def _rendered(screen: RelationDetailScreen) -> str:
    """Return the concatenated rendered text of the relation output log."""
    output = screen.query_one("#relation-output", RichLog)
    return " ".join(line.text for line in output.lines)


class _Host(App):
    """Minimal app used to push a RelationDetailScreen."""

    def compose(self) -> ComposeResult:  # pragma: no cover - trivial
        yield from ()


class TestFetchDataBlocking:
    """Tests for the synchronous ``_fetch_data_blocking`` classmethod."""

    def test_missing_juju_cli(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            result = RelationDetailScreen._fetch_data_blocking("app/0", "dev")
        assert json.loads(result)["error"].startswith("juju CLI")

    def test_timeout(self) -> None:
        err = subprocess.TimeoutExpired(cmd=["juju"], timeout=15)
        with patch("subprocess.run", side_effect=err):
            result = RelationDetailScreen._fetch_data_blocking("app/0", "dev")
        assert "Timed out" in json.loads(result)["error"]

    def test_nonzero_returncode(self) -> None:
        mock_result = MagicMock(returncode=1, stderr="boom", stdout="")
        with patch("subprocess.run", return_value=mock_result):
            result = RelationDetailScreen._fetch_data_blocking("app/0", "dev")
        assert json.loads(result)["error"] == "boom"

    def test_nonzero_returncode_empty_stderr_uses_fallback(self) -> None:
        mock_result = MagicMock(returncode=2, stderr="", stdout="")
        with patch("subprocess.run", return_value=mock_result):
            result = RelationDetailScreen._fetch_data_blocking("app/0", "dev")
        assert json.loads(result)["error"] == "unknown error"

    def test_success_passes_stdout_through(self) -> None:
        mock_result = MagicMock(returncode=0, stdout='{"foo": 1}', stderr="")
        with patch("subprocess.run", return_value=mock_result):
            result = RelationDetailScreen._fetch_data_blocking("app/0", "dev")
        assert json.loads(result) == {"foo": 1}


class TestRelationScreenInit:
    """Constructor stores all the relation identifiers it's given."""

    def test_stores_arguments(self) -> None:
        screen = RelationDetailScreen("charm/0", "db", "postgresql", model="dev")
        assert screen._unit_name == "charm/0"
        assert screen._endpoint == "db"
        assert screen._related_app == "postgresql"
        assert screen._model == "dev"

    def test_model_defaults_to_none(self) -> None:
        screen = RelationDetailScreen("charm/0", "db", "postgresql")
        assert screen._model is None


class TestRelationScreenPilot:
    """Pilot tests for the mount → fetch → render pipeline."""

    @pytest.mark.asyncio
    async def test_no_model_shows_notice(self) -> None:
        """Without a model, ``_fetch_data`` writes a short notice and stops."""
        async with _Host().run_test() as pilot:
            screen = RelationDetailScreen("app/0", "db", "postgresql", model=None)
            await pilot.app.push_screen(screen)
            await pilot.pause()
            assert "No development model connected." in _rendered(screen)

    @pytest.mark.asyncio
    async def test_matching_relation_rendered(self) -> None:
        """Full render path: databags, headers, asymmetry section."""
        payload = json.dumps(
            {
                "app/0": {
                    "relation-info": [
                        {
                            "endpoint": "db",
                            "relation-id": 7,
                            "application-data": {"user": "tony", "only_local": "1"},
                            "related-units": {
                                "postgresql/0": {
                                    "data": {"user": "tony", "only_remote": "x"},
                                },
                            },
                        }
                    ]
                }
            }
        )
        result = MagicMock(returncode=0, stdout=payload, stderr="")
        with patch("subprocess.run", return_value=result):
            async with _Host().run_test() as pilot:
                screen = RelationDetailScreen("app/0", "db", "postgresql", model="dev")
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.4)

                text = _rendered(screen)
                assert "Endpoint:" in text
                assert "Relation ID:" in text
                assert "app (local)" in text
                assert "postgresql (remote)" in text
                assert "only_local" in text
                assert "only_remote" in text
                assert "Asymmetries" in text
                assert "Only in local:" in text
                assert "Only in remote:" in text

    @pytest.mark.asyncio
    async def test_no_matching_endpoint(self) -> None:
        """If the endpoint isn't found we write the 'no relation data' line."""
        payload = json.dumps(
            {
                "app/0": {
                    "relation-info": [
                        {"endpoint": "other", "application-data": {}, "related-units": {}}
                    ]
                }
            }
        )
        result = MagicMock(returncode=0, stdout=payload, stderr="")
        with patch("subprocess.run", return_value=result):
            async with _Host().run_test() as pilot:
                screen = RelationDetailScreen("app/0", "db", "postgresql", model="dev")
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.4)
                assert "No relation data found for endpoint" in _rendered(screen)

    @pytest.mark.asyncio
    async def test_symmetric_relation_has_no_asymmetry_section(self) -> None:
        """With identical databags there's no Asymmetries header."""
        payload = json.dumps(
            {
                "app/0": {
                    "relation-info": [
                        {
                            "endpoint": "db",
                            "relation-id": 1,
                            "application-data": {"shared": "v"},
                            "related-units": {
                                "postgresql/0": {"data": {"shared": "v"}},
                            },
                        }
                    ]
                }
            }
        )
        result = MagicMock(returncode=0, stdout=payload, stderr="")
        with patch("subprocess.run", return_value=result):
            async with _Host().run_test() as pilot:
                screen = RelationDetailScreen("app/0", "db", "postgresql", model="dev")
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.4)
                assert "Asymmetries" not in _rendered(screen)

    @pytest.mark.asyncio
    async def test_subprocess_error_surfaces(self) -> None:
        """A non-zero return code becomes an ``Error: ...`` line."""
        result = MagicMock(returncode=1, stdout="", stderr="juju exploded")
        with patch("subprocess.run", return_value=result):
            async with _Host().run_test() as pilot:
                screen = RelationDetailScreen("app/0", "db", "postgresql", model="dev")
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.4)
                assert "Error: juju exploded" in _rendered(screen)

    @pytest.mark.asyncio
    async def test_unparseable_output(self) -> None:
        """Non-JSON stdout hits the ``Could not parse`` branch."""
        result = MagicMock(returncode=0, stdout="not even close to JSON", stderr="")
        with patch("subprocess.run", return_value=result):
            async with _Host().run_test() as pilot:
                screen = RelationDetailScreen("app/0", "db", "postgresql", model="dev")
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.4)
                assert "Could not parse" in _rendered(screen)

    @pytest.mark.asyncio
    async def test_refresh_action_reissues_fetch(self) -> None:
        """Calling ``action_refresh`` runs the subprocess again."""
        payload = json.dumps({"app/0": {"relation-info": []}})
        mock_result = MagicMock(returncode=0, stdout=payload, stderr="")
        with patch("subprocess.run", return_value=mock_result) as run:
            async with _Host().run_test() as pilot:
                screen = RelationDetailScreen("app/0", "db", "postgresql", model="dev")
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.4)
                calls_before = run.call_count
                screen.action_refresh()
                await pilot.pause(delay=0.4)
                assert run.call_count > calls_before
