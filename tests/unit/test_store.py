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
    """Tests for compaction safety counter persistence (Phase 40.2)."""

    def test_default_counters_are_zero(self, store: SessionStore) -> None:
        state = AgentState(charm_name="x")
        store.save_session(state)
        assert store.load_compaction_counters() == (0, 0)

    def test_save_and_load_counters(self, store: SessionStore) -> None:
        state = AgentState(charm_name="x")
        store.save_session(state)
        store.save_compaction_counters(compactions_attempted=7, emergencies_attempted=3)
        assert store.load_compaction_counters() == (7, 3)

    def test_counters_independent_of_session_save(self, store: SessionStore) -> None:
        """save_session() must not reset counters that save_compaction_counters set."""
        state = AgentState(charm_name="x")
        store.save_session(state)
        store.save_compaction_counters(5, 2)
        # Subsequent save_session (e.g. charm_path change) should not zero
        # the counters.
        state.charm_name = "y"
        store.save_session(state)
        assert store.load_compaction_counters() == (5, 2)

    def test_load_on_empty_store_returns_zero(self, store: SessionStore) -> None:
        """No session row yet → counters default to (0, 0)."""
        assert store.load_compaction_counters() == (0, 0)


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
