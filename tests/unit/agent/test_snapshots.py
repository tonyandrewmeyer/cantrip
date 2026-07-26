"""Phase 68.1: snapshot manager and ``/undo`` / ``/redo`` slash commands."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from cantrip.agent.commands.slash import handle_redo, handle_undo
from cantrip.agent.core import CantripAgent
from cantrip.agent.snapshots import (
    ENV_SNAPSHOTS,
    SnapshotManager,
    snapshots_enabled,
)
from cantrip.llm.base import Message, Role
from cantrip.ui.events import EventBus, EventType
from tests.conftest import FakeProvider

if TYPE_CHECKING:
    import pathlib

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git is required for snapshot tests",
)


@pytest.fixture
def charm(tmp_path: pathlib.Path) -> pathlib.Path:
    """A bare charm root with one starter file."""
    charm_dir = tmp_path / "charm"
    charm_dir.mkdir()
    (charm_dir / "src.py").write_text("v1\n")
    (charm_dir / ".gitignore").write_text("ignored.txt\n")
    return charm_dir


@pytest.fixture
def state_root(tmp_path: pathlib.Path) -> pathlib.Path:
    """Snapshot repo lives outside the charm tree, per design."""
    return tmp_path / "state"


@pytest.fixture
def manager(charm: pathlib.Path, state_root: pathlib.Path) -> SnapshotManager:
    return SnapshotManager(charm, state_root=state_root)


class TestSnapshotsEnabled:
    """The ``snapshots_enabled`` helper resolves CLI + env into a bool."""

    def test_default_is_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(ENV_SNAPSHOTS, raising=False)
        assert snapshots_enabled() is True

    def test_cli_flag_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(ENV_SNAPSHOTS, raising=False)
        assert snapshots_enabled(no_snapshots_flag=True) is False

    def test_env_falsy_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_SNAPSHOTS, "false")
        assert snapshots_enabled() is False
        monkeypatch.setenv(ENV_SNAPSHOTS, "0")
        assert snapshots_enabled() is False

    def test_env_truthy_keeps_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_SNAPSHOTS, "true")
        assert snapshots_enabled() is True

    def test_cli_flag_overrides_truthy_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_SNAPSHOTS, "true")
        assert snapshots_enabled(no_snapshots_flag=True) is False


class TestSnapshotCapture:
    """``snapshot_turn`` commits a working-tree snapshot."""

    def test_first_snapshot_returns_sha(self, manager: SnapshotManager) -> None:
        sha = manager.snapshot_turn("1")
        assert sha is not None
        assert len(sha) == 40  # full git sha

    def test_snapshot_publishes_event(self, charm: pathlib.Path, state_root: pathlib.Path) -> None:
        bus = EventBus()
        seen: list[dict[str, object]] = []
        bus.subscribe(EventType.SNAPSHOT_CREATED, lambda e: seen.append(dict(e.payload)))
        mgr = SnapshotManager(charm, event_bus=bus, state_root=state_root)
        sha = mgr.snapshot_turn("1")
        assert seen == [{"turn_id": "1", "sha": sha}]

    def test_repo_lives_outside_charm(
        self, manager: SnapshotManager, charm: pathlib.Path, state_root: pathlib.Path
    ) -> None:
        manager.snapshot_turn("1")
        # The state_root passed to the manager is used as the parent
        # directory for the per-charm snapshot repo.
        assert any(state_root.iterdir())
        # Snapshot repo never appears inside the user's tree.
        assert not (charm / ".cantrip-snapshots").exists()
        assert not list(charm.glob(".git*"))[1:]  # only the user's own .git, if any


class TestRestoreRoundTrip:
    """Restore returns the working tree to a prior snapshot."""

    def test_undo_restores_modification(
        self, manager: SnapshotManager, charm: pathlib.Path
    ) -> None:
        sha_v1 = manager.snapshot_turn("1")
        assert sha_v1 is not None
        (charm / "src.py").write_text("v2\n")
        manager.snapshot_turn("2")  # capture v2 so reset removes nothing surprising
        manager.restore(sha_v1, direction="undo")
        assert (charm / "src.py").read_text() == "v1\n"

    def test_undo_restores_deletion(self, manager: SnapshotManager, charm: pathlib.Path) -> None:
        (charm / "doomed.py").write_text("alive\n")
        sha = manager.snapshot_turn("1")
        assert sha is not None
        (charm / "doomed.py").unlink()
        manager.snapshot_turn("2")
        manager.restore(sha, direction="undo")
        assert (charm / "doomed.py").read_text() == "alive\n"

    def test_undo_removes_creation(self, manager: SnapshotManager, charm: pathlib.Path) -> None:
        sha_initial = manager.snapshot_turn("1")
        assert sha_initial is not None
        (charm / "new.py").write_text("hello\n")
        manager.snapshot_turn("2")  # tracks the new file
        manager.restore(sha_initial, direction="undo")
        assert not (charm / "new.py").exists()

    def test_restore_publishes_event(self, charm: pathlib.Path, state_root: pathlib.Path) -> None:
        bus = EventBus()
        seen: list[dict[str, object]] = []
        bus.subscribe(EventType.SNAPSHOT_RESTORED, lambda e: seen.append(dict(e.payload)))
        mgr = SnapshotManager(charm, event_bus=bus, state_root=state_root)
        sha = mgr.snapshot_turn("1")
        assert sha is not None
        (charm / "src.py").write_text("dirty\n")
        mgr.snapshot_turn("2")
        mgr.restore(sha, direction="undo")
        assert seen and seen[0]["direction"] == "undo"
        assert seen[0]["sha"] == sha

    def test_restore_cleans_unsnapshotted_dirt(
        self, manager: SnapshotManager, charm: pathlib.Path
    ) -> None:
        """A file the agent created mid-turn (not yet committed) is removed.

        ``/undo`` stages ``add -A`` before ``reset --hard`` so dirty
        adds get tracked and then wiped by the reset.
        """
        sha = manager.snapshot_turn("1")
        assert sha is not None
        (charm / "midturn.py").write_text("oops\n")
        # No second snapshot — the file is dirty and untracked.
        manager.restore(sha, direction="undo")
        assert not (charm / "midturn.py").exists()


class TestExclusions:
    """Cantrip-internal paths and gitignored files are not snapshotted."""

    def test_gitignored_path_not_in_snapshot(
        self, manager: SnapshotManager, charm: pathlib.Path
    ) -> None:
        (charm / "ignored.txt").write_text("secret\n")
        sha = manager.snapshot_turn("1")
        assert sha is not None
        # Restoring to a state before the file existed must not "delete"
        # ignored.txt because git never saw it.
        result = subprocess.run(
            ["git", f"--git-dir={manager._git_dir}", "ls-tree", "-r", sha, "--name-only"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert "ignored.txt" not in result.stdout

    def test_cantrip_dir_excluded(self, manager: SnapshotManager, charm: pathlib.Path) -> None:
        (charm / ".cantrip").mkdir()
        (charm / ".cantrip" / "session.db").write_text("binary-ish\n")
        sha = manager.snapshot_turn("1")
        assert sha is not None
        result = subprocess.run(
            ["git", f"--git-dir={manager._git_dir}", "ls-tree", "-r", sha, "--name-only"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert ".cantrip/session.db" not in result.stdout
        assert ".cantrip" not in result.stdout.split("\n")


class TestRedoStack:
    """Redo-stack lifecycle: push, pop, clear."""

    def test_pop_empty_returns_none(self, manager: SnapshotManager) -> None:
        assert manager.pop_undone() is None

    def test_push_pop_round_trip(self, manager: SnapshotManager) -> None:
        msg = Message(role=Role.USER, content="hi")
        manager.push_undone("abc123", [msg])
        assert manager.redo_depth == 1
        entry = manager.pop_undone()
        assert entry is not None
        assert entry.redo_sha == "abc123"
        assert entry.removed_messages == [msg]
        assert manager.redo_depth == 0

    def test_clear_redo_drops_all(self, manager: SnapshotManager) -> None:
        manager.push_undone("a", [])
        manager.push_undone("b", [])
        manager.clear_redo()
        assert manager.redo_depth == 0
        assert manager.pop_undone() is None


class TestSlashCommandsDisabled:
    """``/undo`` / ``/redo`` short-circuit when snapshots are off."""

    def test_undo_when_disabled(self, charm: pathlib.Path) -> None:
        agent = CantripAgent(provider=FakeProvider(), charm_path=charm)
        agent.state.snapshot_enabled = False
        result = handle_undo(agent)
        assert "disabled" in result.lower()

    def test_redo_when_disabled(self, charm: pathlib.Path) -> None:
        agent = CantripAgent(provider=FakeProvider(), charm_path=charm)
        agent.state.snapshot_enabled = False
        result = handle_redo(agent)
        assert "disabled" in result.lower()


class TestSlashCommandFlow:
    """Full ``/undo`` + ``/redo`` flow against a live agent.

    Patches the snapshot root so the test never touches the user's
    ``$XDG_STATE_HOME``.
    """

    @pytest.fixture
    def agent(self, charm: pathlib.Path, tmp_path: pathlib.Path) -> CantripAgent:
        os.environ.pop(ENV_SNAPSHOTS, None)
        with patch(
            "cantrip.agent.snapshots._snapshot_root",
            return_value=tmp_path / "snap-root",
        ):
            agent = CantripAgent(provider=FakeProvider(), charm_path=charm)
            # Touch the property so the cached manager uses our state root.
            assert agent.snapshot_manager is not None
            yield agent

    @pytest.mark.asyncio
    async def test_undo_walks_back_one_turn(
        self, agent: CantripAgent, charm: pathlib.Path
    ) -> None:
        # Simulate one user turn: the snapshot helper stamps SHA + DB id.
        user_msg = Message(role=Role.USER, content="add v2")
        agent._snapshot_before_user_turn(user_msg)
        agent.state.messages.append(user_msg)
        agent._record_message(user_msg)
        # Agent edits the file mid-turn.
        (charm / "src.py").write_text("v2\n")
        # Agent's reply lands.
        assistant = Message(role=Role.ASSISTANT, content="done")
        agent.state.messages.append(assistant)
        agent._record_message(assistant)

        out = handle_undo(agent)

        assert "Undid" in out
        assert (charm / "src.py").read_text() == "v1\n"
        assert agent.state.messages == []
        # Persisted history truncated alongside.
        assert agent.store is not None
        assert agent.store.load_messages() == []

    @pytest.mark.asyncio
    async def test_redo_round_trips(self, agent: CantripAgent, charm: pathlib.Path) -> None:
        user_msg = Message(role=Role.USER, content="bump")
        agent._snapshot_before_user_turn(user_msg)
        agent.state.messages.append(user_msg)
        agent._record_message(user_msg)
        (charm / "src.py").write_text("v2\n")
        assistant = Message(role=Role.ASSISTANT, content="ok")
        agent.state.messages.append(assistant)
        agent._record_message(assistant)

        handle_undo(agent)
        assert (charm / "src.py").read_text() == "v1\n"
        assert agent.state.messages == []

        out = handle_redo(agent)
        assert "Redid" in out
        assert (charm / "src.py").read_text() == "v2\n"
        # Both messages came back, and the user msg is once again first.
        assert len(agent.state.messages) == 2
        assert agent.state.messages[0].role == Role.USER
        assert agent.state.messages[1].role == Role.ASSISTANT

    @pytest.mark.asyncio
    async def test_redo_empty_when_no_undo(self, agent: CantripAgent) -> None:
        out = handle_redo(agent)
        assert "Nothing to redo" in out

    @pytest.mark.asyncio
    async def test_undo_with_no_user_turns(self, agent: CantripAgent) -> None:
        out = handle_undo(agent)
        assert "Nothing to undo" in out

    @pytest.mark.asyncio
    async def test_new_user_turn_clears_redo(
        self, agent: CantripAgent, charm: pathlib.Path
    ) -> None:
        # Turn 1
        user1 = Message(role=Role.USER, content="t1")
        agent._snapshot_before_user_turn(user1)
        agent.state.messages.append(user1)
        agent._record_message(user1)
        (charm / "src.py").write_text("v2\n")
        agent.state.messages.append(Message(role=Role.ASSISTANT, content="ok"))
        agent._record_message(agent.state.messages[-1])

        handle_undo(agent)
        assert agent.snapshot_manager is not None
        assert agent.snapshot_manager.redo_depth == 1

        # Turn 2 — the snapshot hook clears the redo stack.
        user2 = Message(role=Role.USER, content="t2")
        agent._snapshot_before_user_turn(user2)
        assert agent.snapshot_manager.redo_depth == 0
        out = handle_redo(agent)
        assert "Nothing to redo" in out
