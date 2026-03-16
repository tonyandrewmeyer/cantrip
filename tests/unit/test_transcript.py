"""Tests for transcript export and formatters."""

import json
from pathlib import Path

import pytest

from cantrip.agent.state import AgentState
from cantrip.agent.store import SessionStore
from cantrip.transcript.export import TranscriptData, load_transcript
from cantrip.transcript.html import render_html
from cantrip.transcript.jsonl import render_jsonl
from cantrip.transcript.markdown import render_markdown


def _sample_data() -> TranscriptData:
    """Build a minimal transcript for testing."""
    return TranscriptData(
        charm_name="my-charm",
        charm_path="/home/user/my-charm",
        messages=[
            {
                "role": "user",
                "content": "Build a charm",
                "timestamp": "2026-03-15T10:00:00",
            },
            {
                "role": "assistant",
                "content": "Sure, I'll build it.",
                "timestamp": "2026-03-15T10:00:01",
                "tool_calls": [
                    {
                        "name": "write_file",
                        "arguments": {"path": "src/charm.py"},
                    }
                ],
            },
            {
                "role": "tool",
                "content": "",
                "timestamp": "2026-03-15T10:00:02",
                "tool_results": [
                    {
                        "content": "File written",
                        "is_error": False,
                    }
                ],
            },
        ],
        tasks=[
            {
                "id": "task-1",
                "title": "Write charm code",
                "status": "done",
                "category": "build",
                "description": "Write the charm",
                "result": "Done",
            },
        ],
        subagent_messages={
            "task-1": [
                {
                    "role": "system",
                    "content": "You are a build agent.",
                },
                {
                    "role": "assistant",
                    "content": "Building now.",
                },
            ],
        },
        events=[
            {
                "event_type": "session_start",
                "timestamp": "2026-03-15T10:00:00",
                "detail": {"charm_name": "my-charm"},
            },
        ],
        token_usage={"prompt_tokens": 1000, "completion_tokens": 500},
    )


class TestTranscriptData:
    def test_defaults(self):
        data = TranscriptData()
        assert data.charm_name == ""
        assert data.messages == []
        assert data.tasks == []
        assert data.subagent_messages == {}
        assert data.events == []
        assert data.token_usage == {}


class TestLoadTranscript:
    @pytest.fixture()
    def db_path(self, tmp_path: Path) -> Path:
        path = tmp_path / ".cantrip"
        store = SessionStore(path)
        store.open()
        state = AgentState(charm_name="test-charm", charm_path=tmp_path)
        store.save_session(state)
        store.record_message(role="user", content="Hello")
        store.record_message(role="assistant", content="Hi there")
        store.record_event("session_start", {"charm_name": "test-charm"})
        store.close()
        return path

    def test_load_transcript_returns_data(self, db_path):
        data = load_transcript(db_path)
        assert data.charm_name == "test-charm"
        assert len(data.messages) == 2
        assert data.messages[0]["role"] == "user"
        assert len(data.events) == 1

    def test_load_transcript_empty_db(self, tmp_path):
        path = tmp_path / ".cantrip"
        store = SessionStore(path)
        store.open()
        store.close()
        data = load_transcript(path)
        assert data.charm_name == ""
        assert data.messages == []


class TestHtmlRenderer:
    def test_render_contains_charm_name(self):
        data = _sample_data()
        html = render_html(data)
        assert "my-charm" in html

    def test_render_contains_messages(self):
        data = _sample_data()
        html = render_html(data)
        assert "Build a charm" in html

    def test_render_contains_task(self):
        data = _sample_data()
        html = render_html(data)
        assert "Write charm code" in html

    def test_render_contains_events(self):
        data = _sample_data()
        html = render_html(data)
        assert "session_start" in html

    def test_render_contains_token_usage(self):
        data = _sample_data()
        html = render_html(data)
        assert "1000" in html
        assert "500" in html

    def test_render_contains_search_input(self):
        data = _sample_data()
        html = render_html(data)
        assert 'id="search"' in html

    def test_render_empty_data(self):
        data = TranscriptData()
        html = render_html(data)
        assert "<!DOCTYPE html>" in html
        assert "Cantrip Transcript" in html

    def test_render_contains_subagent_messages(self):
        data = _sample_data()
        html = render_html(data)
        assert "Subagent conversation" in html
        assert "Building now." in html


class TestJsonlRenderer:
    def test_render_messages(self):
        data = _sample_data()
        output = render_jsonl(data)
        lines = output.strip().split("\n")
        msg_lines = [json.loads(line) for line in lines if json.loads(line)["type"] == "message"]
        assert len(msg_lines) == 3
        assert msg_lines[0]["role"] == "user"

    def test_render_events(self):
        data = _sample_data()
        output = render_jsonl(data)
        lines = output.strip().split("\n")
        event_lines = [json.loads(line) for line in lines if json.loads(line)["type"] == "event"]
        assert len(event_lines) == 1
        assert event_lines[0]["event_type"] == "session_start"

    def test_render_tasks(self):
        data = _sample_data()
        output = render_jsonl(data)
        lines = output.strip().split("\n")
        task_lines = [json.loads(line) for line in lines if json.loads(line)["type"] == "task"]
        assert len(task_lines) == 1
        assert task_lines[0]["title"] == "Write charm code"

    def test_render_subagent_messages(self):
        data = _sample_data()
        output = render_jsonl(data)
        lines = output.strip().split("\n")
        sub_lines = [
            json.loads(line) for line in lines
            if json.loads(line)["type"] == "subagent_message"
        ]
        assert len(sub_lines) == 2

    def test_render_empty_data(self):
        data = TranscriptData()
        output = render_jsonl(data)
        assert output == ""

    def test_each_line_is_valid_json(self):
        data = _sample_data()
        output = render_jsonl(data)
        for line in output.strip().split("\n"):
            parsed = json.loads(line)
            assert "type" in parsed


class TestMarkdownRenderer:
    def test_render_contains_heading(self):
        data = _sample_data()
        md = render_markdown(data)
        assert "# Cantrip Transcript -- my-charm" in md

    def test_render_contains_tokens(self):
        data = _sample_data()
        md = render_markdown(data)
        assert "1000 prompt + 500 completion" in md

    def test_render_contains_tasks(self):
        data = _sample_data()
        md = render_markdown(data)
        assert "Write charm code" in md
        assert "DONE" in md

    def test_render_contains_messages(self):
        data = _sample_data()
        md = render_markdown(data)
        assert "Build a charm" in md
        assert "USER" in md
        assert "ASSISTANT" in md

    def test_render_contains_tool_details(self):
        data = _sample_data()
        md = render_markdown(data)
        assert "Tool: write_file" in md

    def test_render_contains_events(self):
        data = _sample_data()
        md = render_markdown(data)
        assert "session_start" in md

    def test_render_empty_data(self):
        data = TranscriptData()
        md = render_markdown(data)
        assert "# Cantrip Transcript" in md


# ===================================================================
# TestFilteredExport
# ===================================================================


class TestFilteredExport:
    """Tests for filtered transcript export (--task, --phase, --since)."""

    @pytest.fixture()
    def db_path(self, tmp_path: Path) -> Path:
        """Build a .cantrip DB with varied tasks and messages."""
        path = tmp_path / ".cantrip"
        store = SessionStore(path)
        store.open()
        state = AgentState(charm_name="filter-test", charm_path=tmp_path)
        store.save_session(state)

        store.record_message(role="user", content="Hello")
        store.record_message(role="assistant", content="Hi there")
        store.record_event("session_start", {"charm_name": "filter-test"})

        from cantrip.agent.queue import AgentTask, TaskCategory

        tasks = [
            AgentTask(
                id="research-1",
                title="Research workload",
                category=TaskCategory.RESEARCH,
            ),
            AgentTask(
                id="build-1",
                title="Build charm",
                category=TaskCategory.BUILD,
            ),
            AgentTask(
                id="test-1",
                title="Run tests",
                category=TaskCategory.TEST,
            ),
        ]
        store.save_tasks(tasks)
        store.record_subagent_message("build-1", 0, "system", "You are a builder")
        store.record_subagent_message("build-1", 1, "assistant", "Building...")

        store.close()
        return path

    def test_unfiltered_loads_everything(self, db_path):
        data = load_transcript(db_path)
        assert len(data.tasks) == 3
        assert len(data.messages) == 2

    def test_filter_by_task_id(self, db_path):
        data = load_transcript(db_path, task_id="build-1")
        assert len(data.tasks) == 1
        assert data.tasks[0]["id"] == "build-1"
        # Subagent messages for the selected task should be included.
        assert "build-1" in data.subagent_messages
        assert len(data.subagent_messages["build-1"]) == 2

    def test_filter_by_task_id_excludes_others(self, db_path):
        data = load_transcript(db_path, task_id="research-1")
        assert len(data.tasks) == 1
        assert data.tasks[0]["id"] == "research-1"
        # No subagent messages for research task.
        assert "build-1" not in data.subagent_messages

    def test_filter_by_phase_research(self, db_path):
        data = load_transcript(db_path, phase="research")
        categories = {t["category"] for t in data.tasks}
        assert "research" in categories
        assert "build" not in categories
        assert "test" not in categories

    def test_filter_by_phase_build(self, db_path):
        data = load_transcript(db_path, phase="build")
        assert len(data.tasks) == 1
        assert data.tasks[0]["category"] == "build"

    def test_filter_by_phase_test(self, db_path):
        """Test phase includes both test and debug categories."""
        data = load_transcript(db_path, phase="test")
        assert len(data.tasks) == 1
        assert data.tasks[0]["category"] == "test"

    def test_filter_by_since(self, db_path):
        """Messages and events before the since timestamp are excluded."""
        # Use a far-future timestamp — should exclude everything.
        data = load_transcript(db_path, since="2099-01-01T00:00:00")
        assert len(data.messages) == 0
        assert len(data.events) == 0
        # Tasks are not filtered by timestamp.
        assert len(data.tasks) == 3

    def test_filter_by_since_includes_recent(self, db_path):
        """A past timestamp includes all messages."""
        data = load_transcript(db_path, since="2020-01-01T00:00:00")
        assert len(data.messages) == 2
        assert len(data.events) >= 1

    def test_nonexistent_task_id_gives_empty(self, db_path):
        data = load_transcript(db_path, task_id="nonexistent")
        assert len(data.tasks) == 0
        assert data.subagent_messages == {}

    def test_unknown_phase_gives_empty(self, db_path):
        data = load_transcript(db_path, phase="unknown")
        assert len(data.tasks) == 0
