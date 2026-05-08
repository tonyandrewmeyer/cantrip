"""Tests for the SQLite session store."""

import json
import pathlib
from collections.abc import Iterator

import pytest

from cantrip.agent.goal_budget import GoalBudget
from cantrip.agent.state import (
    AgentState,
    Decision,
    append_shared_decision,
    shared_decisions_path,
)
from cantrip.agent.store import SessionStore


@pytest.fixture
def db_path(tmp_path: pathlib.Path) -> pathlib.Path:
    """Return a temporary database path."""
    return tmp_path / ".cantrip"


@pytest.fixture
def store(db_path: pathlib.Path) -> Iterator[SessionStore]:
    """Return an open SessionStore backed by a temporary file."""
    s = SessionStore(db_path)
    s.open()
    yield s
    s.close()


class TestOpenClose:
    """Tests for opening and closing the store."""

    def test_open_creates_database(self, db_path: pathlib.Path) -> None:
        store = SessionStore(db_path)
        store.open()
        assert db_path.exists()
        store.close()

    def test_close_is_idempotent(self, store: SessionStore) -> None:
        store.close()
        store.close()

    def test_auto_opens_on_first_access(self, db_path: pathlib.Path) -> None:
        """Store opens the database automatically when accessed without explicit open()."""
        store = SessionStore(db_path)
        assert store.load_session() is None
        assert db_path.exists()
        store.close()

    def test_open_creates_query_indexes(self, store: SessionStore) -> None:
        """Indexes for the routinely-queried columns must exist after open().

        Without ``ix_subagent_messages_task``, ``ix_events_event_type``,
        and ``ix_events_timestamp``, the WHERE clauses in
        ``load_subagent_messages``, ``load_events``, and
        ``get_replay_savings`` degenerate to full-table scans as the
        session grows.
        """
        rows = store._db.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
        names = {r["name"] for r in rows}
        assert {
            "ix_subagent_messages_task",
            "ix_events_event_type",
            "ix_events_timestamp",
        }.issubset(names)


class TestSessionCRUD:
    """Tests for saving and loading session state."""

    def test_load_empty_returns_none(self, store: SessionStore) -> None:
        assert store.load_session() is None

    def test_round_trip(self, store: SessionStore) -> None:
        state = AgentState(
            charm_name="my-charm",
            charm_path=pathlib.Path("/tmp/my-charm"),
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
        assert loaded.charm_path == pathlib.Path("/tmp/my-charm")
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

    def test_role_column_groups_legacy_under_chat(self, store: SessionStore) -> None:
        """Phase 72.3: ``get_usage_by_role`` rolls NULL legacy rows into ``"chat"``."""
        store.record_usage("claude", "claude-opus", 100, 50)  # legacy NULL role
        store.record_usage("claude", "claude-opus", 200, 100, role="chat")
        store.record_usage("voyage", "voyage-3", 30, 0, role="embed")
        store.record_usage("voyage", "rerank-2", 20, 0, role="rerank")

        by_role = store.get_usage_by_role()
        bucket = {r["role"]: r for r in by_role}
        # NULL + explicit "chat" both fall into the chat bucket.
        assert bucket["chat"]["prompt_tokens"] == 300
        assert bucket["chat"]["request_count"] == 2
        assert bucket["embed"]["prompt_tokens"] == 30
        assert bucket["embed"]["completion_tokens"] == 0
        assert bucket["rerank"]["prompt_tokens"] == 20

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

    def test_v14_adds_source_column_to_existing_decisions(self, tmp_path: pathlib.Path) -> None:
        """A pre-v14 database gains the decisions ``source`` column on open.

        Legacy rows have NULL source — ``load_session`` reads them as
        ``"local"`` so existing decisions retain their original meaning
        (Phase 51b.2).
        """
        import sqlite3

        db_path = tmp_path / ".cantrip"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""\
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (13);
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
                active_head_message_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                choice TEXT NOT NULL,
                reason TEXT,
                timestamp TEXT NOT NULL
            );
            INSERT INTO session (id, charm_name) VALUES (1, 'legacy');
            INSERT INTO decisions (type, choice, reason, timestamp)
            VALUES ('substrate', 'K8s', 'old', '2025-01-01T00:00:00');
        """)
        conn.commit()
        conn.close()

        store = SessionStore(db_path)
        store.open()
        try:
            cols = {r[1] for r in store._db.execute("PRAGMA table_info(decisions)").fetchall()}
            assert "source" in cols
            loaded = store.load_session()
            assert loaded is not None
            assert len(loaded.decisions) == 1
            # Pre-v14 row had NULL source — surfaces as "local".
            assert loaded.decisions[0].source == "local"
            assert loaded.decisions[0].choice == "K8s"
        finally:
            store.close()

    def test_v9_adds_category_column_to_existing_token_usage(self, tmp_path: pathlib.Path) -> None:
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

    def test_migrate_from_json(self, tmp_path: pathlib.Path) -> None:
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
            assert loaded.charm_path == pathlib.Path("/tmp/migrated-charm")
            assert loaded.charm_type == "machine"
            assert loaded.framework is None
            assert loaded.dev_model == "dev-model"
            assert loaded.cos_model is None
            assert len(loaded.decisions) == 1
            assert loaded.decisions[0].choice == "custom"
        finally:
            store.close()

    def test_migrate_empty_json(self, tmp_path: pathlib.Path) -> None:
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

    def test_migrate_corrupt_json_raises_value_error(self, tmp_path: pathlib.Path) -> None:
        """Corrupt session.json must raise ``ValueError``, never crash startup.

        Regression: ``json.loads`` raises ``JSONDecodeError`` (a
        ``ValueError`` subclass) and ``read_text`` raises
        ``UnicodeDecodeError`` (also a ``ValueError``); the migration now
        re-raises both as a clean ``ValueError`` so ``CantripAgent._init_store``
        can fall back instead of taking down the agent.
        """
        json_path = tmp_path / "session.json"
        json_path.write_text("{not valid json")
        db_path = tmp_path / ".cantrip"
        with pytest.raises(ValueError, match="not valid JSON"):
            SessionStore.migrate_from_json(json_path, db_path)

    def test_migrate_non_utf8_json_does_not_unicode_crash(self, tmp_path: pathlib.Path) -> None:
        """Non-UTF-8 bytes in session.json must surface as ``ValueError``."""
        json_path = tmp_path / "session.json"
        # ``\xff`` is not valid UTF-8; ``read_text`` would raise
        # ``UnicodeDecodeError`` under strict decoding.
        json_path.write_bytes(b'{"charm_name": "\xff\xff"}')
        db_path = tmp_path / ".cantrip"
        # ``errors="replace"`` lets the read succeed; the decoded payload is
        # then valid JSON, so this particular fixture round-trips.  The
        # behaviour we actually rely on is "no UnicodeDecodeError".
        SessionStore.migrate_from_json(json_path, db_path)
        store = SessionStore(db_path)
        store.open()
        try:
            loaded = store.load_session()
            assert loaded is not None
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


class TestGoalBudgetPersistence:
    """Phase 99.2: ``goal_budget`` round-trips through save / load.

    Without this the ``/budget`` caps the operator set in one session
    would silently vanish on ``cantrip resume`` and they'd have to
    re-specify them every time.
    """

    def test_no_budget_round_trips_as_none(self, store: SessionStore) -> None:
        """A session without a goal_budget loads back with goal_budget=None."""
        state = AgentState(charm_name="x")
        store.save_session(state)
        loaded = store.load_session()
        assert loaded is not None
        assert loaded.goal_budget is None

    def test_budget_round_trips(self, store: SessionStore) -> None:
        """Every cap and the started_at timestamp survive save/load."""
        state = AgentState(charm_name="x")
        state.goal_budget = GoalBudget(
            max_iterations=42,
            max_prompt_tokens=10_000,
            max_completion_tokens=5_000,
            started_at="2026-05-08 12:34:56",
        )
        store.save_session(state)
        loaded = store.load_session()
        assert loaded is not None
        assert loaded.goal_budget is not None
        assert loaded.goal_budget.max_iterations == 42
        assert loaded.goal_budget.max_prompt_tokens == 10_000
        assert loaded.goal_budget.max_completion_tokens == 5_000
        # ``started_at`` must round-trip exactly — ``measure_usage``
        # uses string comparison against ``token_usage.timestamp`` so
        # any drift would silently change the spend window.
        assert loaded.goal_budget.started_at == "2026-05-08 12:34:56"

    def test_uncapped_axes_round_trip_as_none(self, store: SessionStore) -> None:
        """An "iterations only" budget survives without zeroing the token caps.

        The dataclass exposes ``None`` for "no cap on this axis"; persistence
        must distinguish that from "cap == 0" so a partially-capped budget
        doesn't mutate into an everything-capped one across resume.
        """
        state = AgentState(charm_name="x")
        state.goal_budget = GoalBudget(max_iterations=10)
        store.save_session(state)
        loaded = store.load_session()
        assert loaded is not None
        assert loaded.goal_budget is not None
        assert loaded.goal_budget.max_iterations == 10
        assert loaded.goal_budget.max_prompt_tokens is None
        assert loaded.goal_budget.max_completion_tokens is None

    def test_clear_after_set_round_trips_as_none(self, store: SessionStore) -> None:
        """Setting then clearing the budget must zero the persisted columns.

        Without the upsert covering goal_budget on the unset path, a
        ``/budget --clear`` would leave the previous caps in the database
        and the next resume would silently re-establish them.
        """
        state = AgentState(charm_name="x")
        state.goal_budget = GoalBudget(max_iterations=5)
        store.save_session(state)
        state.goal_budget = None
        store.save_session(state)
        loaded = store.load_session()
        assert loaded is not None
        assert loaded.goal_budget is None

    def test_pre_v15_database_loads_with_no_budget(self, db_path: pathlib.Path) -> None:
        """Sessions persisted before the v15 migration load cleanly.

        Simulates the migration path by stamping schema_version=14 on a
        store with the v15 columns missing, then re-opening — the v15
        migration must add the columns, populate them as NULL, and the
        subsequent ``load_session`` must report ``goal_budget is None``
        rather than raising.  This is the backwards-compat exit
        criterion for Phase 99.2.
        """
        # Open and seed at v14, dropping the v15 columns to mimic the
        # on-disk shape of a session written before the migration.
        first = SessionStore(db_path)
        first.open()
        try:
            state = AgentState(
                charm_name="legacy",
                charm_path=pathlib.Path("/tmp/legacy"),
                charm_type="k8s",
            )
            first.save_session(state)
            # Force the schema back to v14 so the next open replays the
            # v15 migration against an existing populated row.
            first._db.execute("UPDATE schema_version SET version = 14")
            for column in (
                "goal_budget_max_iterations",
                "goal_budget_max_prompt_tokens",
                "goal_budget_max_completion_tokens",
                "goal_budget_started_at",
            ):
                first._db.execute(f"ALTER TABLE session DROP COLUMN {column}")
            first._db.commit()
        finally:
            first.close()

        # Reopen — the v15 migration runs and the row reads cleanly.
        second = SessionStore(db_path)
        second.open()
        try:
            loaded = second.load_session()
            assert loaded is not None
            assert loaded.charm_name == "legacy"
            assert loaded.goal_budget is None
        finally:
            second.close()


class TestObjectivePersistence:
    """Phase 99.3: free-text user-prose objective round-trips through save / load."""

    def test_no_objective_round_trips_as_none(self, store: SessionStore) -> None:
        state = AgentState(charm_name="x")
        store.save_session(state)
        loaded = store.load_session()
        assert loaded is not None
        assert loaded.objective is None

    def test_objective_round_trips(self, store: SessionStore) -> None:
        state = AgentState(charm_name="x")
        state.objective = "build a Postgres charm with COS plus Pebble notices"
        store.save_session(state)
        loaded = store.load_session()
        assert loaded is not None
        assert loaded.objective == "build a Postgres charm with COS plus Pebble notices"

    def test_clear_after_set_round_trips_as_none(self, store: SessionStore) -> None:
        """Without the upsert covering ``objective`` on the unset path, a
        ``/goal clear`` would leave the previous text in the database."""
        state = AgentState(charm_name="x")
        state.objective = "first goal"
        store.save_session(state)
        state.objective = None
        store.save_session(state)
        loaded = store.load_session()
        assert loaded is not None
        assert loaded.objective is None

    def test_pre_v16_database_loads_with_no_objective(self, db_path: pathlib.Path) -> None:
        """Sessions persisted before the v16 migration load cleanly.

        Forces schema_version back to 15 with the v16 column dropped to
        mimic an on-disk shape from before Phase 99.3, then re-opens
        and asserts that the migration backfills the column as NULL and
        ``load_session`` reads the row without crashing.
        """
        first = SessionStore(db_path)
        first.open()
        try:
            state = AgentState(charm_name="legacy", charm_path=pathlib.Path("/tmp/legacy"))
            first.save_session(state)
            first._db.execute("UPDATE schema_version SET version = 15")
            first._db.execute("ALTER TABLE session DROP COLUMN objective")
            first._db.commit()
        finally:
            first.close()

        second = SessionStore(db_path)
        second.open()
        try:
            loaded = second.load_session()
            assert loaded is not None
            assert loaded.charm_name == "legacy"
            assert loaded.objective is None
        finally:
            second.close()


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


class TestSharedDecisionsMerge:
    """Phase 51b.2: load_session merges the shared JSONL log; save skips shared rows."""

    def test_save_persists_decision_source(
        self, store: SessionStore, tmp_path: pathlib.Path
    ) -> None:
        state = AgentState(charm_path=tmp_path)
        state.decisions.append(Decision(type="t", choice="c", source="local"))
        store.save_session(state)
        loaded = store.load_session()
        assert loaded is not None
        assert len(loaded.decisions) == 1
        assert loaded.decisions[0].source == "local"

    def test_save_skips_shared_rows(self, store: SessionStore, tmp_path: pathlib.Path) -> None:
        """A shared decision in state must not get written into SQLite.

        Shared decisions live in the JSONL file; persisting them to SQLite
        too would duplicate them on every load.
        """
        state = AgentState(charm_path=tmp_path)
        state.decisions.append(Decision(type="local", choice="L"))
        state.decisions.append(Decision(type="shared", choice="S", source="shared"))
        store.save_session(state)
        rows = store._db.execute("SELECT type FROM decisions").fetchall()
        assert [r[0] for r in rows] == ["local"]

    def test_load_merges_shared_log(self, store: SessionStore, tmp_path: pathlib.Path) -> None:
        # Seed both stores: one local SQLite decision and one shared JSONL.
        state = AgentState(charm_path=tmp_path)
        state.decisions.append(Decision(type="t1", choice="local-choice"))
        store.save_session(state)
        append_shared_decision(
            tmp_path, Decision(type="t2", choice="team-choice", reason="from teammate")
        )
        loaded = store.load_session()
        assert loaded is not None
        sources = [(d.type, d.choice, d.source) for d in loaded.decisions]
        assert ("t1", "local-choice", "local") in sources
        assert ("t2", "team-choice", "shared") in sources

    def test_load_with_no_charm_path_skips_shared_log(
        self, store: SessionStore, tmp_path: pathlib.Path
    ) -> None:
        # charm_path stays None — the shared JSONL is not consulted.
        state = AgentState(charm_name="no-path", charm_path=None)
        state.decisions.append(Decision(type="t", choice="local"))
        store.save_session(state)
        # Even if a JSONL exists at some path, no charm_path means no merge.
        append_shared_decision(tmp_path, Decision(type="ignored", choice="x"))
        loaded = store.load_session()
        assert loaded is not None
        assert [d.type for d in loaded.decisions] == ["t"]

    def test_round_trip_does_not_duplicate_shared(
        self, store: SessionStore, tmp_path: pathlib.Path
    ) -> None:
        """save → load → save → load must leave the shared log alone."""
        append_shared_decision(tmp_path, Decision(type="t", choice="s"))
        state = AgentState(charm_path=tmp_path)
        store.save_session(state)
        loaded = store.load_session()
        assert loaded is not None
        # First load picks up the shared row.
        assert any(d.source == "shared" for d in loaded.decisions)
        # Second save must NOT write that shared row to SQLite.
        store.save_session(loaded)
        sql_count = store._db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        assert sql_count == 0
        # And the JSONL file is still the canonical record (one entry).
        jsonl_lines = shared_decisions_path(tmp_path).read_text(encoding="utf-8").splitlines()
        assert len(jsonl_lines) == 1

    def test_load_merges_shared_and_local_in_chronological_order(
        self, store: SessionStore, tmp_path: pathlib.Path
    ) -> None:
        """``load_session`` must order merged decisions by ``timestamp``.

        Regression: ``load_session`` previously read every local decision
        from SQLite, then *appended* shared decisions from the JSONL log.
        A teammate's earlier decision (e.g. recorded at 10:00 and pulled
        into your tree at 11:00) ended up *after* your own later
        decisions in ``state.decisions``.  ``/decisions``, the resume
        preview, and the prompt-injected decisions block all render the
        list in order, so the audit trail looked time-shuffled.  The fix
        merges by ``Decision.timestamp`` before returning.
        """
        import datetime as dt

        # A teammate recorded a decision yesterday and you pulled it
        # into ``.cantrip-shared/decisions.jsonl``.
        teammate_old = Decision(
            type="path",
            choice="12-factor",
            reason="teammate's call",
            timestamp=dt.datetime(2026, 1, 1, 10, 0, 0),
        )
        append_shared_decision(tmp_path, teammate_old)

        # You then record a local decision today, after the pull.
        state = AgentState(charm_path=tmp_path)
        local_new = Decision(
            type="model",
            choice="claude-sonnet",
            reason="my call",
            timestamp=dt.datetime(2026, 1, 2, 10, 0, 0),
        )
        state.decisions.append(local_new)
        store.save_session(state)

        loaded = store.load_session()
        assert loaded is not None
        ordered = [(d.type, d.source) for d in loaded.decisions]
        # Older shared decision must precede the newer local one.
        assert ordered == [("path", "shared"), ("model", "local")]
