"""Tests for session-tree rewind / branch (Phase 67.1).

The store now persists a parent pointer on every message and a
single "active head" pointer on the session.  ``record_message``
advances the head; ``delete_messages_from`` rewinds it; ``/branch``
overrides it.  These tests pin down the round-trip so /undo, resume,
and exports keep agreeing on what the active conversation is.
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.agent.slash_commands import build_tree_nodes, handle_branch, handle_tree
from cantrip.agent.store import SCHEMA_VERSION, SessionStore
from cantrip.llm.base import Role
from tests.conftest import FakeProvider


@pytest.fixture
def db_path(tmp_path: pathlib.Path) -> pathlib.Path:
    """Return a temporary database path."""
    return tmp_path / ".cantrip"


@pytest.fixture
def store(db_path: pathlib.Path) -> Iterator[SessionStore]:
    """Yield an open store backed by a temp .cantrip file."""
    s = SessionStore(db_path)
    s.open()
    yield s
    s.close()


class TestActiveHeadAdvance:
    """``record_message`` advances the head; the chain stays correct."""

    def test_first_message_is_root(self, store: SessionStore) -> None:
        msg_id = store.record_message(role="user", content="hello")
        assert store.get_active_head() == msg_id
        rows = store.load_messages()
        assert rows[0]["parent_turn_id"] is None

    def test_second_message_chains_to_first(self, store: SessionStore) -> None:
        first = store.record_message(role="user", content="hello")
        second = store.record_message(role="assistant", content="hi")
        rows = {r["id"]: r for r in store.load_messages()}
        assert rows[first]["parent_turn_id"] is None
        assert rows[second]["parent_turn_id"] == first
        assert store.get_active_head() == second

    def test_active_branch_walks_in_order(self, store: SessionStore) -> None:
        ids = [
            store.record_message(role="user", content="a"),
            store.record_message(role="assistant", content="b"),
            store.record_message(role="user", content="c"),
        ]
        branch = store.load_active_branch()
        assert [m["id"] for m in branch] == ids
        assert [m["content"] for m in branch] == ["a", "b", "c"]


class TestBranchAndRewind:
    """``set_active_head`` lets /branch and /undo rewind without dropping rows."""

    def test_branch_off_earlier_turn(self, store: SessionStore) -> None:
        a = store.record_message(role="user", content="a")
        b = store.record_message(role="assistant", content="b")
        c = store.record_message(role="user", content="c")
        # Rewind to b — c is now off-branch but still in the DB.
        store.set_active_head(b)
        active = store.load_active_branch()
        assert [m["id"] for m in active] == [a, b]
        # The original branch is reachable through load_messages.
        all_messages = {m["id"] for m in store.load_messages()}
        assert c in all_messages
        # A new message after rewinding chains off b, not c.
        d = store.record_message(role="user", content="d")
        rows = {m["id"]: m for m in store.load_messages()}
        assert rows[d]["parent_turn_id"] == b
        assert store.get_active_head() == d

    def test_delete_rewinds_active_head(self, store: SessionStore) -> None:
        a = store.record_message(role="user", content="a")
        b = store.record_message(role="assistant", content="b")
        c = store.record_message(role="user", content="c")
        deleted = store.delete_messages_from(b)
        assert deleted == 2
        # Head must point at the row that survived (a) — leaving it
        # at b would orphan the next record_message call.
        assert store.get_active_head() == a
        assert {m["id"] for m in store.load_messages()} == {a}
        # Recording onto the rewound chain keeps the parent pointer
        # consistent with the surviving leaf.
        d = store.record_message(role="user", content="d")
        rows = {m["id"]: m for m in store.load_messages()}
        assert rows[d]["parent_turn_id"] == a
        # We didn't pre-set the c row — it's gone.  No reference here.
        assert c not in rows

    def test_delete_root_clears_head(self, store: SessionStore) -> None:
        a = store.record_message(role="user", content="a")
        store.delete_messages_from(a)
        assert store.get_active_head() is None
        assert store.load_active_branch() == []


class TestActiveBranchEdgeCases:
    """Failure modes on the resume path must not crash the agent."""

    def test_empty_session(self, store: SessionStore) -> None:
        assert store.get_active_head() is None
        assert store.load_active_branch() == []

    def test_dangling_head_is_warned_not_raised(self, store: SessionStore) -> None:
        a = store.record_message(role="user", content="a")
        # Hand-edit the DB to point at a nonexistent row.
        store._db.execute("UPDATE session SET active_head_message_id = 9999 WHERE id = 1")
        store._db.commit()
        # load_active_branch tolerates the dangling pointer rather
        # than raising — resume runs through this code path.
        assert store.load_active_branch() == []
        # Sanity check: the row that does exist is still there.
        assert {m["id"] for m in store.load_messages()} == {a}


class TestBranchSlashCommand:
    """``/branch`` moves the head and rebuilds ``state.messages``."""

    def _seed_agent(self, tmp_path: pathlib.Path) -> tuple[CantripAgent, list[int]]:
        """Build an agent with three persisted user/assistant turns."""
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        agent._ensure_store()
        store = agent.store
        assert store is not None
        ids = [
            store.record_message(role="user", content="first ask"),
            store.record_message(role="assistant", content="first reply"),
            store.record_message(role="user", content="bad steering"),
            store.record_message(role="assistant", content="off-target"),
        ]
        agent._rebuild_messages_from_active_branch()
        return agent, ids

    def test_branch_with_explicit_turn_id(self, tmp_path: pathlib.Path) -> None:
        agent, ids = self._seed_agent(tmp_path)
        first_user, first_reply, _bad_user, _off = ids
        result = handle_branch(agent, str(first_reply))
        assert "Forked at turn" in result
        # State now reflects the rewound branch — only the first
        # ask + reply remain in memory.
        assert [m.content for m in agent.state.messages] == ["first ask", "first reply"]
        # The store still has every row, including the off-branch ones.
        assert agent.store is not None
        all_ids = {m["id"] for m in agent.store.load_messages()}
        assert all_ids == set(ids)
        # The active head is at first_reply.
        assert agent.store.get_active_head() == first_reply
        # User-message metadata still carries the db_message_id so /undo
        # would still see it.
        user_msgs = [m for m in agent.state.messages if m.role == Role.USER]
        assert user_msgs[0].metadata.get("db_message_id") == first_user

    def test_branch_with_no_arg_forks_before_last_user(self, tmp_path: pathlib.Path) -> None:
        agent, ids = self._seed_agent(tmp_path)
        _first_user, first_reply, _bad_user, _off = ids
        result = handle_branch(agent, "")
        assert "Forked at turn" in result
        # The bad user turn is the leaf user; the parent of that user
        # is the assistant reply, so the forked branch ends there.
        assert agent.store is not None
        assert agent.store.get_active_head() == first_reply
        assert [m.content for m in agent.state.messages] == ["first ask", "first reply"]

    def test_branch_with_invalid_turn_id_returns_error(self, tmp_path: pathlib.Path) -> None:
        agent, _ids = self._seed_agent(tmp_path)
        result = handle_branch(agent, "not-an-int")
        assert "expected an integer" in result
        # State unchanged.
        assert len(agent.state.messages) == 4

    def test_branch_with_unknown_turn_returns_error(self, tmp_path: pathlib.Path) -> None:
        agent, _ids = self._seed_agent(tmp_path)
        result = handle_branch(agent, "9999")
        assert "not found" in result
        assert len(agent.state.messages) == 4

    def test_branch_no_user_turns_returns_error(self, tmp_path: pathlib.Path) -> None:
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        agent._ensure_store()
        store = agent.store
        assert store is not None
        store.record_message(role="assistant", content="orphan reply")
        agent._rebuild_messages_from_active_branch()
        result = handle_branch(agent, "")
        assert "no user turns" in result.lower()


class TestResumeFollowsBranch:
    """A /branch made before quitting carries through to the next resume."""

    def test_resume_loads_active_branch_only(self, tmp_path: pathlib.Path) -> None:
        # Seed messages, then rewind via /branch, then close and reopen.
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        agent._ensure_store()
        store = agent.store
        assert store is not None
        a = store.record_message(role="user", content="a")
        store.record_message(role="assistant", content="b")
        store.record_message(role="user", content="c")
        store.record_message(role="assistant", content="d")
        agent._rebuild_messages_from_active_branch()
        handle_branch(agent, str(a))
        # Close and reopen.
        store.close()

        agent2 = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        loaded = agent2.load_state()
        assert loaded is True
        assert [m.content for m in agent2.state.messages] == ["a"]


class TestTreeBuilder:
    """``build_tree_nodes`` produces a DFS traversal with depth markers."""

    def test_linear_history_renders_as_flat(self) -> None:
        msgs = [
            {"id": 1, "role": "user", "content": "a", "parent_turn_id": None, "timestamp": "t1"},
            {"id": 2, "role": "assistant", "content": "b", "parent_turn_id": 1, "timestamp": "t2"},
            {"id": 3, "role": "user", "content": "c", "parent_turn_id": 2, "timestamp": "t3"},
        ]
        nodes = build_tree_nodes(msgs, active_branch_ids={1, 2, 3})
        assert [(n.id, n.depth) for n in nodes] == [(1, 0), (2, 1), (3, 2)]
        assert all(n.on_active_branch for n in nodes)

    def test_fork_gets_indented_under_parent(self) -> None:
        # 1 → 2 → 3 (the original branch) and 2 → 4 (fork).
        msgs = [
            {"id": 1, "role": "user", "content": "a", "parent_turn_id": None, "timestamp": "t1"},
            {"id": 2, "role": "assistant", "content": "b", "parent_turn_id": 1, "timestamp": "t2"},
            {"id": 3, "role": "user", "content": "c", "parent_turn_id": 2, "timestamp": "t3"},
            {"id": 4, "role": "user", "content": "fork", "parent_turn_id": 2, "timestamp": "t4"},
        ]
        nodes = build_tree_nodes(msgs, active_branch_ids={1, 2, 4})
        # Children visited in id order: 3 before 4.
        assert [(n.id, n.depth) for n in nodes] == [(1, 0), (2, 1), (3, 2), (4, 2)]
        actives = {n.id: n.on_active_branch for n in nodes}
        assert actives == {1: True, 2: True, 3: False, 4: True}

    def test_long_content_truncated(self) -> None:
        long = "x" * 200
        msgs = [
            {"id": 1, "role": "user", "content": long, "parent_turn_id": None, "timestamp": "t"},
        ]
        nodes = build_tree_nodes(msgs, active_branch_ids={1})
        assert len(nodes[0].label) <= 80
        assert nodes[0].label.endswith("…")


class TestTreeSlashCommand:
    """``/tree`` produces a markdown summary with branch markers."""

    def test_empty_session_returns_friendly_message(self, tmp_path: pathlib.Path) -> None:
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        agent._ensure_store()
        result = handle_tree(agent, "")
        assert "No turns yet" in result

    def test_lists_active_branch_with_marker(self, tmp_path: pathlib.Path) -> None:
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        agent._ensure_store()
        store = agent.store
        assert store is not None
        a = store.record_message(role="user", content="first ask")
        store.record_message(role="assistant", content="first reply")
        store.record_message(role="user", content="off-branch")
        store.set_active_head(a)
        result = handle_tree(agent, "")
        # Active branch row gets `*`; off-branch row is unmarked.
        assert "first ask" in result
        assert "off-branch" in result
        active_lines = [line for line in result.splitlines() if "first ask" in line]
        assert active_lines and "*" in active_lines[0]
        off_lines = [line for line in result.splitlines() if "off-branch" in line]
        # The marker column should be a space (not `*`) for off-branch
        # rows — be tolerant of indentation by checking for the row id.
        assert off_lines and "*" not in off_lines[0].split("`", 1)[0]


class TestTreePickerScreen:
    """Smoke-check the TUI modal renders nodes with stable option ids."""

    def test_option_ids_match_turn_ids(self) -> None:
        from cantrip.agent.slash_commands import TreeNode
        from cantrip.tui.screens.tree import TreePickerScreen

        nodes = [
            TreeNode(
                depth=0,
                id=42,
                role="user",
                label="hello",
                timestamp="2026-04-26T10:00:00",
                on_active_branch=True,
            ),
            TreeNode(
                depth=1,
                id=43,
                role="assistant",
                label="world",
                timestamp="2026-04-26T10:00:01",
                on_active_branch=True,
            ),
        ]
        screen = TreePickerScreen(nodes)
        # The screen builds options at compose time; spot-check the
        # option-builder shared with compose so we don't require a
        # running Textual app to verify ids round-trip.
        for node in nodes:
            option = TreePickerScreen._option_for(node)
            assert option.id == str(node.id)
            assert str(node.id) in str(option.prompt)
            assert node.label in str(option.prompt)
        assert screen._nodes == nodes


class TestExportFollowsBranch:
    """``load_transcript`` defaults to the active branch and respects --branch."""

    def test_default_export_excludes_off_branch_messages(self, tmp_path: pathlib.Path) -> None:
        from cantrip.transcript.export import load_transcript

        db_path = tmp_path / ".cantrip"
        s = SessionStore(db_path)
        s.open()
        try:
            a = s.record_message(role="user", content="a")
            s.record_message(role="assistant", content="b")
            s.record_message(role="user", content="c-bad")
            s.record_message(role="assistant", content="d-bad")
            # Rewind to a so b/c/d become off-branch.
            s.set_active_head(a)
        finally:
            s.close()

        data = load_transcript(db_path)
        assert [m["content"] for m in data.messages] == ["a"]

    def test_explicit_branch_id_walks_that_path(self, tmp_path: pathlib.Path) -> None:
        from cantrip.transcript.export import load_transcript

        db_path = tmp_path / ".cantrip"
        s = SessionStore(db_path)
        s.open()
        try:
            a = s.record_message(role="user", content="a")
            s.record_message(role="assistant", content="b")
            c = s.record_message(role="user", content="c")
            s.record_message(role="assistant", content="d")
            # Active head stays at d.  --branch=c should yield a→b→c.
            assert s.get_active_head() != c
            assert a is not None
        finally:
            s.close()

        data = load_transcript(db_path, branch=c)
        assert [m["content"] for m in data.messages] == ["a", "b", "c"]


class TestV12Migration:
    """A pre-v12 .cantrip file gains the parent chain on first open."""

    def test_existing_messages_get_chained(self, db_path: pathlib.Path) -> None:
        # Hand-craft a v11 database: add three rows without parent
        # pointers, then bump the schema_version row backwards.
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            CREATE TABLE session (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                charm_name TEXT,
                charm_path TEXT,
                charm_type TEXT,
                framework TEXT,
                dev_model TEXT,
                cos_model TEXT,
                design_proposal TEXT,
                message_count INTEGER DEFAULT 0,
                compactions_attempted INTEGER NOT NULL DEFAULT 0,
                emergencies_attempted INTEGER NOT NULL DEFAULT 0,
                cycle_detected INTEGER NOT NULL DEFAULT 0,
                budget_exhausted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                tool_calls TEXT,
                tool_results TEXT,
                metadata TEXT,
                token_usage_id INTEGER,
                timestamp TEXT NOT NULL DEFAULT (datetime('now'))
            );
            INSERT INTO schema_version (version) VALUES (11);
            INSERT INTO session (id) VALUES (1);
            INSERT INTO messages (role, content) VALUES ('user', 'a');
            INSERT INTO messages (role, content) VALUES ('assistant', 'b');
            INSERT INTO messages (role, content) VALUES ('user', 'c');
            """
        )
        conn.commit()
        conn.close()

        # Open via SessionStore — the v12 migration runs.
        s = SessionStore(db_path)
        s.open()
        try:
            # Schema version bumped to current.
            row = s._db.execute("SELECT version FROM schema_version").fetchone()
            assert row[0] == SCHEMA_VERSION
            # Active head landed at the highest existing message id.
            ids_sorted = sorted(m["id"] for m in s.load_messages())
            assert s.get_active_head() == ids_sorted[-1]
            # Backfill chained the rows in id order.
            chain = s.load_active_branch()
            assert [m["content"] for m in chain] == ["a", "b", "c"]
            # Recording onto the migrated session still works.
            new_id = s.record_message(role="assistant", content="d")
            rows = {m["id"]: m for m in s.load_messages()}
            assert rows[new_id]["parent_turn_id"] == ids_sorted[-1]
        finally:
            s.close()
