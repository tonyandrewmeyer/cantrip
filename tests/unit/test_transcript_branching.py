"""Tests for session-tree rewind / branch (Phase 67.1).

The store now persists a parent pointer on every message and a
single "active head" pointer on the session.  ``record_message``
advances the head; ``delete_messages_from`` rewinds it; ``/branch``
overrides it.  These tests pin down the round-trip so /undo, resume,
and exports keep agreeing on what the active conversation is.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from cantrip.agent.store import SCHEMA_VERSION, SessionStore


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a temporary database path."""
    return tmp_path / ".cantrip"


@pytest.fixture
def store(db_path: Path) -> Iterator[SessionStore]:
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


class TestV12Migration:
    """A pre-v12 .cantrip file gains the parent chain on first open."""

    def test_existing_messages_get_chained(self, db_path: Path) -> None:
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
