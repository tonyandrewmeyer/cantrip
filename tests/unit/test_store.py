"""Tests for the SQLite session store."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from cantrip.agent.state import AgentState
from cantrip.agent.store import SessionStore


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a temporary database path."""
    return tmp_path / ".cantrip"


@pytest.fixture
def store(db_path: Path) -> Iterator[SessionStore]:
    """Return an open SessionStore backed by a temporary file."""
    s = SessionStore(db_path)
    s.open()
    yield s
    s.close()


class TestOpenClose:
    """Tests for opening and closing the store."""

    def test_open_creates_database(self, db_path: Path) -> None:
        store = SessionStore(db_path)
        store.open()
        assert db_path.exists()
        store.close()

    def test_close_is_idempotent(self, store: SessionStore) -> None:
        store.close()
        store.close()

    def test_auto_opens_on_first_access(self, db_path: Path) -> None:
        """Store opens the database automatically when accessed without explicit open()."""
        store = SessionStore(db_path)
        assert store.load_session() is None
        assert db_path.exists()
        store.close()


class TestSessionCRUD:
    """Tests for saving and loading session state."""

    def test_load_empty_returns_none(self, store: SessionStore) -> None:
        assert store.load_session() is None

    def test_round_trip(self, store: SessionStore) -> None:
        state = AgentState(
            charm_name="my-charm",
            charm_path=Path("/tmp/my-charm"),
            charm_type="k8s",
            framework="flask",
            dev_model="dev",
            cos_model="cos",
        )
        state.add_decision("path", "12-factor", reason="Flask app")

        store.save_session(state)
        loaded = store.load_session()

        assert loaded is not None
        assert loaded.charm_name == "my-charm"
        assert loaded.charm_path == Path("/tmp/my-charm")
        assert loaded.charm_type == "k8s"
        assert loaded.framework == "flask"
        assert loaded.dev_model == "dev"
        assert loaded.cos_model == "cos"
        assert len(loaded.decisions) == 1
        assert loaded.decisions[0].type == "path"
        assert loaded.decisions[0].choice == "12-factor"
        assert loaded.decisions[0].reason == "Flask app"

    def test_save_upserts(self, store: SessionStore) -> None:
        """Saving twice updates rather than duplicating."""
        state = AgentState(charm_name="first")
        store.save_session(state)

        state.charm_name = "second"
        store.save_session(state)

        loaded = store.load_session()
        assert loaded is not None
        assert loaded.charm_name == "second"

    def test_save_replaces_decisions(self, store: SessionStore) -> None:
        state = AgentState()
        state.add_decision("a", "1")
        store.save_session(state)

        state.decisions.clear()
        state.add_decision("b", "2")
        store.save_session(state)

        loaded = store.load_session()
        assert loaded is not None
        assert len(loaded.decisions) == 1
        assert loaded.decisions[0].type == "b"

    def test_none_charm_path(self, store: SessionStore) -> None:
        state = AgentState(charm_name="no-path")
        store.save_session(state)
        loaded = store.load_session()
        assert loaded is not None
        assert loaded.charm_path is None


class TestTokenUsage:
    """Tests for token usage recording and aggregation."""

    def test_record_and_get_total(self, store: SessionStore) -> None:
        store.record_usage("gemini", "gemini-2.0-flash", 100, 50)
        store.record_usage("gemini", "gemini-2.0-flash", 200, 100)

        total = store.get_total_usage()
        assert total["prompt_tokens"] == 300
        assert total["completion_tokens"] == 150

    def test_empty_usage(self, store: SessionStore) -> None:
        total = store.get_total_usage()
        assert total["prompt_tokens"] == 0
        assert total["completion_tokens"] == 0

    def test_usage_by_model(self, store: SessionStore) -> None:
        store.record_usage("gemini", "gemini-2.0-flash", 100, 50)
        store.record_usage("claude", "claude-sonnet", 200, 100)
        store.record_usage("gemini", "gemini-2.0-flash", 50, 25)

        by_model = store.get_usage_by_model()
        assert len(by_model) == 2

        # Sorted by provider, model.
        assert by_model[0]["provider"] == "claude"
        assert by_model[0]["model"] == "claude-sonnet"
        assert by_model[0]["prompt_tokens"] == 200
        assert by_model[0]["completion_tokens"] == 100
        assert by_model[0]["request_count"] == 1

        assert by_model[1]["provider"] == "gemini"
        assert by_model[1]["prompt_tokens"] == 150
        assert by_model[1]["completion_tokens"] == 75
        assert by_model[1]["request_count"] == 2

    def test_record_with_category(self, store: SessionStore) -> None:
        """``category`` is persisted so ``/cost`` can break cost down (Phase 31.4)."""
        store.record_usage("claude", "claude-opus", 100, 50, category="build")
        store.record_usage("claude", "claude-opus", 200, 100, category="test")
        store.record_usage("claude", "claude-haiku", 50, 25)  # NULL category

        # Total ignores category — historical rows still add up.
        total = store.get_total_usage()
        assert total["prompt_tokens"] == 350
        assert total["completion_tokens"] == 175

    def test_usage_by_category_groups_null_under_conversation(self, store: SessionStore) -> None:
        """Legacy rows with NULL category aggregate under ``"conversation"``."""
        store.record_usage("claude", "claude-opus", 100, 50, category="build")
        store.record_usage("claude", "claude-opus", 400, 100, category="build")
        store.record_usage("claude", "claude-opus", 200, 75, category="test")
        store.record_usage("claude", "claude-haiku", 50, 25)  # NULL → conversation

        by_cat = store.get_usage_by_category()
        bucket = {r["category"]: r for r in by_cat}
        assert bucket["build"]["prompt_tokens"] == 500
        assert bucket["build"]["completion_tokens"] == 150
        assert bucket["build"]["request_count"] == 2
        assert bucket["test"]["prompt_tokens"] == 200
        assert bucket["conversation"]["prompt_tokens"] == 50

    def test_usage_by_category_since_filters_by_timestamp(self, store: SessionStore) -> None:
        store.record_usage("claude", "claude-opus", 100, 50, category="build")
        assert store.get_usage_by_category(since="9999-01-01 00:00:00") == []
        past = store.get_usage_by_category(since="2000-01-01 00:00:00")
        assert len(past) == 1
        assert past[0]["category"] == "build"

    def test_usage_by_model_since(self, store: SessionStore) -> None:
        """get_usage_by_model_since filters rows by timestamp.

        The column uses SQLite's ``datetime('now')`` default (seconds
        precision, UTC, no ``T`` separator) so the boundary string must
        be in the same format.  A future-dated boundary must exclude
        every row; a past-dated boundary must include them all.
        """
        store.record_usage("gemini", "gemini-2.0-flash", 100, 50)
        store.record_usage("claude", "claude-sonnet-4-6", 500, 200)

        # A timestamp far in the past — every row qualifies.
        past_rows = store.get_usage_by_model_since("2000-01-01 00:00:00")
        by_past = {(r["provider"], r["model"]): r for r in past_rows}
        assert by_past[("gemini", "gemini-2.0-flash")]["prompt_tokens"] == 100
        assert by_past[("claude", "claude-sonnet-4-6")]["prompt_tokens"] == 500

        # A timestamp far in the future — no rows qualify.
        future_rows = store.get_usage_by_model_since("9999-01-01 00:00:00")
        assert future_rows == []


class TestSchemaMigrations:
    """Tests for incremental ``_apply_migrations`` paths (Phase 31.4 etc.)."""

    def test_v9_adds_category_column_to_existing_token_usage(self, tmp_path: Path) -> None:
        """A pre-v9 database gains the ``category`` column on open.

        Legacy rows without the column survive — ``get_total_usage``
        still totals them and ``get_usage_by_category`` surfaces them
        under ``"conversation"``.
        """
        import sqlite3

        db_path = tmp_path / ".cantrip"
        # Hand-roll a v8 database: create the old token_usage schema
        # (no category column) and pin schema_version=8.
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""\
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (8);
            CREATE TABLE token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL,
                completion_tokens INTEGER NOT NULL,
                timestamp TEXT NOT NULL DEFAULT (datetime('now'))
            );
            INSERT INTO token_usage (provider, model, prompt_tokens, completion_tokens)
            VALUES ('claude', 'claude-opus', 123, 45);
        """)
        conn.commit()
        conn.close()

        store = SessionStore(db_path)
        store.open()
        try:
            cols = {r[1] for r in store._db.execute("PRAGMA table_info(token_usage)").fetchall()}
            assert "category" in cols

            # Legacy row still counts in the total and aggregates under
            # the "conversation" bucket.
            total = store.get_total_usage()
            assert total["prompt_tokens"] == 123
            assert total["completion_tokens"] == 45

            by_cat = store.get_usage_by_category()
            assert len(by_cat) == 1
            assert by_cat[0]["category"] == "conversation"
            assert by_cat[0]["prompt_tokens"] == 123
        finally:
            store.close()


class TestMigration:
    """Tests for migrating from session.json to SQLite."""

    def test_migrate_from_json(self, tmp_path: Path) -> None:
        json_data = {
            "charm_name": "migrated-charm",
            "charm_path": "/tmp/migrated-charm",
            "charm_type": "machine",
            "framework": None,
            "dev_model": "dev-model",
            "cos_model": None,
            "decisions": [
                {"type": "path", "choice": "custom", "reason": "Complex app"},
            ],
            "message_count": 5,
        }
        json_path = tmp_path / "session.json"
        json_path.write_text(json.dumps(json_data))

        db_path = tmp_path / ".cantrip"
        SessionStore.migrate_from_json(json_path, db_path)

        store = SessionStore(db_path)
        store.open()
        try:
            loaded = store.load_session()
            assert loaded is not None
            assert loaded.charm_name == "migrated-charm"
            assert loaded.charm_path == Path("/tmp/migrated-charm")
            assert loaded.charm_type == "machine"
            assert loaded.framework is None
            assert loaded.dev_model == "dev-model"
            assert loaded.cos_model is None
            assert len(loaded.decisions) == 1
            assert loaded.decisions[0].choice == "custom"
        finally:
            store.close()

    def test_migrate_empty_json(self, tmp_path: Path) -> None:
        json_path = tmp_path / "session.json"
        json_path.write_text("{}")

        db_path = tmp_path / ".cantrip"
        SessionStore.migrate_from_json(json_path, db_path)

        store = SessionStore(db_path)
        store.open()
        try:
            loaded = store.load_session()
            assert loaded is not None
            assert loaded.charm_name is None
            assert loaded.decisions == []
        finally:
            store.close()


class TestCompactionCounters:
    """Tests for compaction safety counter persistence (Phase 40.2, 78.3)."""

    def test_default_counters_are_zero(self, store: SessionStore) -> None:
        state = AgentState(charm_name="x")
        store.save_session(state)
        assert store.load_compaction_counters() == (0, 0, False, False)

    def test_save_and_load_counters(self, store: SessionStore) -> None:
        state = AgentState(charm_name="x")
        store.save_session(state)
        store.save_compaction_counters(compactions_attempted=7, emergencies_attempted=3)
        assert store.load_compaction_counters() == (7, 3, False, False)

    def test_counters_independent_of_session_save(self, store: SessionStore) -> None:
        """save_session() must not reset counters that save_compaction_counters set."""
        state = AgentState(charm_name="x")
        store.save_session(state)
        store.save_compaction_counters(5, 2)
        # Subsequent save_session (e.g. charm_path change) should not zero
        # the counters.
        state.charm_name = "y"
        store.save_session(state)
        assert store.load_compaction_counters() == (5, 2, False, False)

    def test_load_on_empty_store_returns_zero(self, store: SessionStore) -> None:
        """No session row yet → counters default to (0, 0, False, False)."""
        assert store.load_compaction_counters() == (0, 0, False, False)

    def test_stop_flags_persist_across_save_load(self, store: SessionStore) -> None:
        """Phase 78.3: cycle_detected / budget_exhausted round-trip.

        Without this, a session that had already decided to stop
        compacting would silently re-arm on resume and the ineffective
        compaction loop could start again.
        """
        state = AgentState(charm_name="x")
        store.save_session(state)
        store.save_compaction_counters(
            compactions_attempted=3,
            emergencies_attempted=1,
            cycle_detected=True,
            budget_exhausted=True,
        )
        assert store.load_compaction_counters() == (3, 1, True, True)

    def test_stop_flags_default_false_when_unset(self, store: SessionStore) -> None:
        """Callers that only pass counters leave stop-flags False."""
        state = AgentState(charm_name="x")
        store.save_session(state)
        store.save_compaction_counters(4, 2)
        _, _, cycle, exhausted = store.load_compaction_counters()
        assert (cycle, exhausted) == (False, False)


class TestCorruptDataResilience:
    """Tests for handling corrupt data in the database."""

    def test_corrupt_event_detail_json(self, store: SessionStore) -> None:
        """Events with corrupt detail JSON are loaded with empty dict instead of crashing."""
        # Insert a row with invalid JSON directly.
        store._db.execute(
            "INSERT INTO events (event_type, detail) VALUES (?, ?)",
            ("test", "{invalid json}"),
        )
        store._db.commit()

        events = store.load_events()
        assert len(events) == 1
        assert events[0]["detail"] == {}

    def test_corrupt_subagent_tool_calls_json(self, store: SessionStore) -> None:
        """Subagent messages with corrupt tool_calls JSON load as None."""
        store._db.execute(
            "INSERT INTO subagent_messages "
            "(task_id, message_index, role, content, tool_calls) "
            "VALUES (?, ?, ?, ?, ?)",
            ("t1", 0, "assistant", "test", "{not valid json}"),
        )
        store._db.commit()

        msgs = store.load_subagent_messages("t1")
        assert len(msgs) == 1
        assert msgs[0]["tool_calls"] is None
