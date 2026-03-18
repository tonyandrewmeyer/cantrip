"""Tests for transcript recording in SessionStore."""

from pathlib import Path

import pytest

from cantrip.agent.store import SessionStore, _truncate


class TestMessageRecording:
    @pytest.fixture()
    def store(self, tmp_path: Path):
        s = SessionStore(tmp_path / ".cantrip")
        s.open()
        yield s
        s.close()

    def test_record_and_load_message(self, store):
        msg_id = store.record_message(role="user", content="Hello world")
        assert isinstance(msg_id, int)
        messages = store.load_messages()
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello world"

    def test_record_message_with_tool_calls(self, store):
        tc = [{"id": "tc1", "name": "read_file", "arguments": {"path": "foo.py"}}]
        store.record_message(role="assistant", content="", tool_calls=tc)
        messages = store.load_messages()
        assert messages[0]["tool_calls"] == tc

    def test_record_message_with_tool_results(self, store):
        tr = [{"tool_call_id": "tc1", "content": "file content", "is_error": False}]
        store.record_message(role="tool", content="", tool_results=tr)
        messages = store.load_messages()
        assert messages[0]["tool_results"] == tr

    def test_messages_ordered_by_id(self, store):
        store.record_message(role="user", content="first")
        store.record_message(role="assistant", content="second")
        store.record_message(role="user", content="third")
        messages = store.load_messages()
        assert [m["content"] for m in messages] == ["first", "second", "third"]

    def test_large_content_truncated(self, store):
        big = "x" * 60_000
        store.record_message(role="user", content=big)
        messages = store.load_messages()
        assert len(messages[0]["content"]) < 60_000
        assert "[truncated" in messages[0]["content"]


class TestSubagentMessageRecording:
    @pytest.fixture()
    def store(self, tmp_path: Path):
        s = SessionStore(tmp_path / ".cantrip")
        s.open()
        yield s
        s.close()

    def test_record_and_load_subagent_messages(self, store):
        store.record_subagent_message("task-1", 0, "system", "You are a subagent")
        store.record_subagent_message("task-1", 1, "user", "Do the thing")
        store.record_subagent_message("task-1", 2, "assistant", "Done")
        msgs = store.load_subagent_messages("task-1")
        assert len(msgs) == 3
        assert msgs[0]["role"] == "system"
        assert msgs[2]["content"] == "Done"

    def test_load_filters_by_task_id(self, store):
        store.record_subagent_message("task-1", 0, "user", "A")
        store.record_subagent_message("task-2", 0, "user", "B")
        assert len(store.load_subagent_messages("task-1")) == 1
        assert len(store.load_subagent_messages("task-2")) == 1


class TestEventRecording:
    @pytest.fixture()
    def store(self, tmp_path: Path):
        s = SessionStore(tmp_path / ".cantrip")
        s.open()
        yield s
        s.close()

    def test_record_and_load_event(self, store):
        eid = store.record_event("session_start", {"provider": "gemini"})
        assert isinstance(eid, int)
        events = store.load_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "session_start"
        assert events[0]["detail"]["provider"] == "gemini"

    def test_filter_by_event_type(self, store):
        store.record_event("session_start")
        store.record_event("task_status_change", {"task": "t1"})
        store.record_event("session_start")
        assert len(store.load_events(event_type="session_start")) == 2
        assert len(store.load_events(event_type="task_status_change")) == 1

    def test_record_event_no_detail(self, store):
        store.record_event("session_start")
        events = store.load_events()
        assert events[0]["detail"] == {}


class TestTruncation:
    def test_short_text_unchanged(self):
        assert _truncate("hello") == "hello"

    def test_long_text_truncated(self):
        big = "x" * 60_000
        result = _truncate(big)
        assert len(result) < 60_000
        assert "[truncated" in result

    def test_custom_limit(self):
        result = _truncate("hello world", max_bytes=5)
        assert "[truncated" in result


class TestRecordUsageReturnsId:
    @pytest.fixture()
    def store(self, tmp_path: Path):
        s = SessionStore(tmp_path / ".cantrip")
        s.open()
        yield s
        s.close()

    def test_returns_row_id(self, store):
        rid = store.record_usage("gemini", "gemini-2.0-flash", 100, 50)
        assert isinstance(rid, int)
        assert rid > 0


class TestSchemaMigrationV4:
    def test_v3_db_migrates_to_v4(self, tmp_path: Path):
        """A v3 database gains the new tables on open."""
        db_path = tmp_path / ".cantrip"
        # Create a v3 database.
        store = SessionStore(db_path)
        store.open()
        # Force version to 3 to simulate old DB.
        store._db.execute("UPDATE schema_version SET version = 3")
        store._db.commit()
        store.close()

        # Re-open — migration should create new tables.
        store2 = SessionStore(db_path)
        store2.open()
        # Should be able to use the new tables.
        store2.record_message(role="user", content="test")
        store2.record_event("test_event")
        store2.record_subagent_message("t1", 0, "user", "hi")
        assert len(store2.load_messages()) == 1
        assert len(store2.load_events()) == 1
        assert len(store2.load_subagent_messages("t1")) == 1
        store2.close()
