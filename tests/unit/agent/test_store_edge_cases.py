"""Tests for SessionStore edge cases: truncation, JSON safety, roundtrips."""

from cantrip.agent.design import DesignProposal
from cantrip.agent.queue import AgentTask, ModelHint, TaskCategory, TaskStatus
from cantrip.agent.state import AgentState
from cantrip.agent.store import (
    _MAX_CONTENT_BYTES,
    SCHEMA_VERSION,
    SessionStore,
    _safe_json_load,
    _truncate,
)


class TestSafeJsonLoad:
    """Tests for _safe_json_load."""

    def test_valid_json(self):
        assert _safe_json_load('{"key": "value"}') == {"key": "value"}

    def test_none_returns_fallback(self):
        assert _safe_json_load(None) is None
        assert _safe_json_load(None, fallback=[]) == []

    def test_empty_string_returns_fallback(self):
        assert _safe_json_load("") is None

    def test_corrupt_json_returns_fallback(self):
        assert _safe_json_load("{invalid") is None
        assert _safe_json_load("{invalid", fallback="default") == "default"

    def test_valid_array(self):
        assert _safe_json_load("[1, 2, 3]") == [1, 2, 3]


class TestTruncate:
    """Tests for content truncation."""

    def test_short_content_unchanged(self):
        text = "short text"
        assert _truncate(text) == text

    def test_content_at_limit_unchanged(self):
        text = "x" * _MAX_CONTENT_BYTES
        assert _truncate(text) == text

    def test_content_over_limit_truncated(self):
        text = "x" * (_MAX_CONTENT_BYTES + 1000)
        result = _truncate(text)
        assert len(result.encode("utf-8")) < len(text.encode("utf-8"))
        assert "[truncated" in result

    def test_truncation_marker_includes_total_length(self):
        text = "y" * (_MAX_CONTENT_BYTES + 500)
        result = _truncate(text)
        assert str(len(text)) in result

    def test_multibyte_chars_at_boundary(self):
        """UTF-8 multi-byte characters at the truncation boundary don't corrupt."""
        # Each emoji is 4 bytes in UTF-8.
        emojis = "\U0001f600" * (_MAX_CONTENT_BYTES // 4 + 100)
        result = _truncate(emojis)
        # Should be valid UTF-8.
        result.encode("utf-8")
        assert "[truncated" in result

    def test_custom_max_bytes(self):
        text = "hello world"
        result = _truncate(text, max_bytes=5)
        assert "[truncated" in result


class TestSessionStoreRoundtrip:
    """Tests for save/load cycles."""

    def test_save_and_load_session(self, tmp_path):
        """State roundtrips correctly through SQLite."""
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        state = AgentState()
        state.charm_name = "redis-k8s"
        state.charm_type = "kubernetes"
        state.framework = "custom"
        state.dev_model = "dev-model"
        state.cos_model = "cos-model"
        state.add_decision("substrate", "Kubernetes", "Best for containers")
        state.add_decision("charm_path", "Custom")
        store.save_session(state)

        loaded = store.load_session()
        assert loaded is not None
        assert loaded.charm_name == "redis-k8s"
        assert loaded.charm_type == "kubernetes"
        assert loaded.framework == "custom"
        assert loaded.dev_model == "dev-model"
        assert loaded.cos_model == "cos-model"
        assert len(loaded.decisions) == 2
        assert loaded.decisions[0].type == "substrate"
        assert loaded.decisions[0].choice == "Kubernetes"
        assert loaded.decisions[0].reason == "Best for containers"

        store.close()

    def test_design_proposal_roundtrip(self, tmp_path):
        """Design proposal survives a save/load cycle via raw Markdown."""
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        raw_md = "# Redis\n## Substrate\nKubernetes\n## Charm path\nCustom"
        state = AgentState()
        state.charm_name = "redis-k8s"
        state.design_proposal = DesignProposal(raw_design_md=raw_md)
        store.save_session(state)

        loaded = store.load_session()
        assert loaded is not None
        assert loaded.design_proposal is not None
        assert loaded.design_proposal.to_design_md() == raw_md
        assert loaded.design_proposal.workload_name == "Redis"
        assert loaded.charm_name == "redis-k8s"

        store.close()

    def test_design_proposal_none_roundtrip(self, tmp_path):
        """A session with no design proposal loads with design_proposal=None."""
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        state = AgentState()
        state.charm_name = "test"
        store.save_session(state)

        loaded = store.load_session()
        assert loaded is not None
        assert loaded.design_proposal is None

        store.close()

    def test_save_and_load_tasks(self, tmp_path):
        """Tasks roundtrip correctly including all fields."""
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        tasks = [
            AgentTask(
                id="t1",
                title="Research",
                category=TaskCategory.RESEARCH,
                status=TaskStatus.DONE,
                result="Research complete",
                dependencies=["dep1", "dep2"],
                model_hint=ModelHint.PRIMARY,
            ),
            AgentTask(
                id="t2",
                title="Build",
                category=TaskCategory.BUILD,
                status=TaskStatus.PENDING,
                blocked_reason=None,
            ),
        ]
        store.save_tasks(tasks)

        loaded = store.load_tasks()
        assert len(loaded) == 2
        assert loaded[0].id == "t1"
        assert loaded[0].status == TaskStatus.DONE
        assert loaded[0].result == "Research complete"
        assert loaded[0].dependencies == ["dep1", "dep2"]
        assert loaded[0].model_hint == ModelHint.PRIMARY
        assert loaded[1].id == "t2"
        assert loaded[1].noop_count == 0

        store.close()

    def test_noop_count_persisted(self, tmp_path):
        """noop_count survives a save/load roundtrip."""
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        task = AgentTask(
            id="noop1",
            title="Stubborn task",
            category=TaskCategory.BUILD,
            status=TaskStatus.ACTIVE,
            noop_count=3,
        )
        store.save_tasks([task])

        loaded = store.load_tasks()
        assert len(loaded) == 1
        assert loaded[0].noop_count == 3

        store.close()

    def test_save_tasks_upserts_and_removes_stale(self, tmp_path):
        """Upsert updates existing tasks, adds new ones, and prunes removed ones."""
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        # Seed two tasks.
        original = [
            AgentTask(
                id="t1",
                title="Research",
                category=TaskCategory.RESEARCH,
                status=TaskStatus.PENDING,
            ),
            AgentTask(
                id="t2",
                title="Build",
                category=TaskCategory.BUILD,
                status=TaskStatus.PENDING,
            ),
        ]
        store.save_tasks(original)
        assert len(store.load_tasks()) == 2

        # Second save: update t1 status, drop t2, add t3.
        updated = [
            AgentTask(
                id="t1",
                title="Research",
                category=TaskCategory.RESEARCH,
                status=TaskStatus.DONE,
                result="All done",
            ),
            AgentTask(
                id="t3",
                title="Deploy",
                category=TaskCategory.DEPLOY,
                status=TaskStatus.PENDING,
            ),
        ]
        store.save_tasks(updated)

        loaded = store.load_tasks()
        ids = {t.id for t in loaded}
        assert ids == {"t1", "t3"}, "t2 should be removed, t3 added"

        t1 = next(t for t in loaded if t.id == "t1")
        assert t1.status == TaskStatus.DONE
        assert t1.result == "All done"

        store.close()

    def test_save_tasks_preserves_created_at_on_upsert(self, tmp_path):
        """Upserting an existing task must not overwrite created_at."""
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        task = AgentTask(
            id="t1",
            title="Original",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.PENDING,
        )
        store.save_tasks([task])
        original_ts = store.load_tasks()[0].created_at

        # Update with a new AgentTask object (different created_at by default).
        updated = AgentTask(
            id="t1",
            title="Updated",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
        )
        store.save_tasks([updated])
        loaded_ts = store.load_tasks()[0].created_at

        # ON CONFLICT ... DO UPDATE deliberately omits created_at.
        assert loaded_ts == original_ts

        store.close()

    def test_load_session_when_empty(self, tmp_path):
        """Loading from an empty database returns None."""
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        loaded = store.load_session()
        assert loaded is None

        store.close()

    def test_load_tasks_when_empty(self, tmp_path):
        """Loading tasks from an empty database returns empty list."""
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        loaded = store.load_tasks()
        assert loaded == []

        store.close()

    def test_save_overwrites_previous(self, tmp_path):
        """Saving again overwrites all state and tasks."""
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        state1 = AgentState()
        state1.charm_name = "first"
        store.save_session(state1)

        state2 = AgentState()
        state2.charm_name = "second"
        store.save_session(state2)

        loaded = store.load_session()
        assert loaded.charm_name == "second"

        store.close()


class TestMessageRecording:
    """Tests for message persistence."""

    def test_record_and_load_message(self, tmp_path):
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        msg_id = store.record_message(
            role="user",
            content="Hello, world!",
            tool_calls=[],
            tool_results=[],
            metadata={"key": "value"},
        )
        assert isinstance(msg_id, int)

        messages = store.load_messages()
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello, world!"

        store.close()

    def test_record_message_with_tool_calls(self, tmp_path):
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        tool_calls = [{"id": "tc1", "name": "read_file", "arguments": {"path": "x"}}]
        store.record_message(
            role="assistant",
            content="",
            tool_calls=tool_calls,
            tool_results=[],
        )

        messages = store.load_messages()
        assert messages[0]["tool_calls"] == tool_calls

        store.close()

    def test_large_content_truncated(self, tmp_path):
        """Content exceeding _MAX_CONTENT_BYTES is truncated."""
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        big_content = "x" * (_MAX_CONTENT_BYTES + 10_000)
        store.record_message(role="user", content=big_content)

        messages = store.load_messages()
        assert "[truncated" in messages[0]["content"]

        store.close()


class TestSubagentMessages:
    """Tests for subagent message persistence."""

    def test_record_and_load_subagent_messages(self, tmp_path):
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        store.record_subagent_message(
            task_id="task-1",
            message_index=0,
            role="user",
            content="Do the task",
        )
        store.record_subagent_message(
            task_id="task-1",
            message_index=1,
            role="assistant",
            content="Done.",
        )
        store.record_subagent_message(
            task_id="task-2",
            message_index=0,
            role="user",
            content="Other task",
        )

        msgs_1 = store.load_subagent_messages("task-1")
        msgs_2 = store.load_subagent_messages("task-2")

        assert len(msgs_1) == 2
        assert len(msgs_2) == 1
        assert msgs_1[0]["content"] == "Do the task"
        assert msgs_1[1]["content"] == "Done."

        store.close()


class TestEventRecording:
    """Tests for event persistence and filtering."""

    def test_record_and_load_events(self, tmp_path):
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        eid = store.record_event("design_confirmed", {"workload": "redis"})
        assert isinstance(eid, int)

        events = store.load_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "design_confirmed"
        assert events[0]["detail"]["workload"] == "redis"

        store.close()

    def test_filter_by_event_type(self, tmp_path):
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        store.record_event("design_confirmed", {"a": 1})
        store.record_event("task_completed", {"b": 2})
        store.record_event("design_confirmed", {"c": 3})

        filtered = store.load_events(event_type="design_confirmed")
        assert len(filtered) == 2

        store.close()


class TestTokenUsage:
    """Tests for token usage tracking."""

    def test_record_and_get_total(self, tmp_path):
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        store.record_usage("gemini", "gemini-2.0-flash", 100, 50)
        store.record_usage("gemini", "gemini-2.0-flash", 200, 100)

        total = store.get_total_usage()
        assert total["prompt_tokens"] == 300
        assert total["completion_tokens"] == 150

        store.close()

    def test_usage_by_model(self, tmp_path):
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        store.record_usage("gemini", "flash", 100, 50)
        store.record_usage("claude", "sonnet", 200, 100)
        store.record_usage("gemini", "flash", 50, 25)

        by_model = store.get_usage_by_model()
        assert len(by_model) == 2
        gemini = next(m for m in by_model if m["provider"] == "gemini")
        assert gemini["prompt_tokens"] == 150
        assert gemini["request_count"] == 2

        store.close()

    def test_empty_usage(self, tmp_path):
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        total = store.get_total_usage()
        assert total["prompt_tokens"] == 0
        assert total["completion_tokens"] == 0

        store.close()


class TestSchemaVersion:
    """Tests for schema versioning."""

    def test_schema_version_set_on_creation(self, tmp_path):
        store = SessionStore(tmp_path / ".cantrip")
        store.open()

        # Verify schema version is current.
        assert store._conn is not None
        row = store._conn.execute("SELECT version FROM schema_version").fetchone()
        assert row[0] == SCHEMA_VERSION

        store.close()

    def test_reopen_same_version(self, tmp_path):
        """Reopening a database with current version works without migration."""
        db_path = tmp_path / ".cantrip"
        store = SessionStore(db_path)
        store.open()
        store.save_session(AgentState())
        store.close()

        store2 = SessionStore(db_path)
        store2.open()
        loaded = store2.load_session()
        assert loaded is not None
        store2.close()
