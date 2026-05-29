"""Tests for transcript export and formatters."""

import json
import pathlib

import pytest

from cantrip.agent.state import AgentState
from cantrip.agent.store import SessionStore
from cantrip.transcript.export import TranscriptData, load_transcript
from cantrip.transcript.html import render_html, render_html_paginated
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
        assert data.checkpoints == {}
        assert data.replay_savings == {}


class TestLoadTranscript:
    @pytest.fixture()
    def db_path(self, tmp_path: pathlib.Path) -> pathlib.Path:
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

    def test_load_transcript_populates_checkpoints(self, tmp_path):
        """Phase 52.5: checkpoints for included tasks land in TranscriptData."""
        from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
        from cantrip.agent.runtime.durability import (
            KIND_LLM_RESPONSE,
            KIND_TOOL_RESULT,
            CheckpointStore,
        )

        path = tmp_path / ".cantrip"
        store = SessionStore(path)
        store.open()
        # A task must exist and be persisted so load_transcript surfaces it.
        task = AgentTask(
            id="task-abc",
            title="Build stuff",
            category=TaskCategory.BUILD,
            description="",
            status=TaskStatus.DONE,
        )
        store.save_tasks([task])
        cps = CheckpointStore(store)
        cps.record("task-abc", "llm_turn", 1, "h1", KIND_LLM_RESPONSE, {"turn": 1})
        cps.record(
            "task-abc",
            "tool:read_file",
            1,
            "h2",
            KIND_TOOL_RESULT,
            {
                "success": True,
                "output": "x",
                "data": {},
                "error": None,
                "images": [],
                "caption": None,
            },
        )
        store.close()

        data = load_transcript(path)
        assert "task-abc" in data.checkpoints
        rows = data.checkpoints["task-abc"]
        assert [(r["step_name"], r["ordinal"], r["kind"]) for r in rows] == [
            ("llm_turn", 1, KIND_LLM_RESPONSE),
            ("tool:read_file", 1, KIND_TOOL_RESULT),
        ]
        assert rows[0]["input_hash"] == "h1"
        assert rows[0]["created_at"]

    def test_load_transcript_populates_replay_savings(self, tmp_path):
        """Phase 52.6: aggregated replayed tokens land in TranscriptData."""
        path = tmp_path / ".cantrip"
        store = SessionStore(path)
        store.open()
        # Two checkpoint_hit events with token stamps — what the durability
        # wrapper records on llm_response replays.
        store.record_event(
            "checkpoint_hit",
            {
                "task_id": "t1",
                "step_name": "llm_turn",
                "ordinal": 1,
                "kind": "llm_response",
                "prompt_tokens": 100,
                "completion_tokens": 20,
            },
        )
        store.record_event(
            "checkpoint_hit",
            {
                "task_id": "t1",
                "step_name": "llm_turn",
                "ordinal": 2,
                "kind": "llm_response",
                "prompt_tokens": 50,
                "completion_tokens": 10,
            },
        )
        store.close()

        data = load_transcript(path)
        assert data.replay_savings == {
            "prompt_tokens": 150,
            "completion_tokens": 30,
            "request_count": 2,
        }


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


class TestHtmlPaginated:
    """Tests for paginated HTML export."""

    @staticmethod
    def _many_messages(count: int) -> TranscriptData:
        """Build transcript data with *count* conversation messages."""
        messages = [
            {
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"Message {i}",
                "timestamp": f"2026-03-15T10:{i:04d}",
            }
            for i in range(count)
        ]
        return TranscriptData(
            charm_name="paged-charm",
            messages=messages,
            tasks=[
                {
                    "id": "t1",
                    "title": "Some task",
                    "status": "done",
                    "category": "build",
                }
            ],
            events=[
                {
                    "event_type": "session_start",
                    "timestamp": "2026-03-15T10:00:00",
                    "detail": {},
                }
            ],
        )

    def test_single_page_when_fewer_than_page_size(self):
        data = self._many_messages(5)
        pages = render_html_paginated(data, page_size=10)
        assert len(pages) == 1
        filename, html = pages[0]
        assert filename == "transcript_1.html"
        # Pagination nav is hidden when there is only one page.
        assert "Previous" not in html
        assert "Next" not in html

    def test_splits_into_correct_number_of_pages(self):
        data = self._many_messages(25)
        pages = render_html_paginated(data, page_size=10)
        assert len(pages) == 3
        assert pages[0][0] == "transcript_1.html"
        assert pages[1][0] == "transcript_2.html"
        assert pages[2][0] == "transcript_3.html"

    def test_first_page_has_tasks_and_events(self):
        data = self._many_messages(25)
        pages = render_html_paginated(data, page_size=10)
        first_html = pages[0][1]
        assert "Some task" in first_html
        assert "session_start" in first_html

    def test_later_pages_omit_tasks_and_events(self):
        data = self._many_messages(25)
        pages = render_html_paginated(data, page_size=10)
        second_html = pages[1][1]
        assert "Some task" not in second_html
        assert "session_start" not in second_html

    def test_messages_split_across_pages(self):
        data = self._many_messages(25)
        pages = render_html_paginated(data, page_size=10)
        # Page 1 has messages 0–9.
        assert "Message 0" in pages[0][1]
        assert "Message 9" in pages[0][1]
        assert "Message 10" not in pages[0][1]
        # Page 2 has messages 10–19.
        assert "Message 10" in pages[1][1]
        assert "Message 19" in pages[1][1]
        # Page 3 has messages 20–24.
        assert "Message 20" in pages[2][1]
        assert "Message 24" in pages[2][1]

    def test_navigation_links(self):
        data = self._many_messages(25)
        pages = render_html_paginated(data, page_size=10)
        first_html = pages[0][1]
        assert "Previous" not in first_html
        assert "transcript_2.html" in first_html
        middle_html = pages[1][1]
        assert "transcript_1.html" in middle_html
        assert "transcript_3.html" in middle_html
        last_html = pages[2][1]
        assert "transcript_2.html" in last_html
        assert "Next" not in last_html

    def test_custom_stem(self):
        data = self._many_messages(5)
        pages = render_html_paginated(data, page_size=10, stem="session")
        assert pages[0][0] == "session_1.html"

    def test_page_info_displayed(self):
        data = self._many_messages(25)
        pages = render_html_paginated(data, page_size=10)
        assert "Page 1 of 3" in pages[0][1]
        assert "Page 2 of 3" in pages[1][1]
        assert "Page 3 of 3" in pages[2][1]

    def test_empty_data_produces_single_page(self):
        data = TranscriptData()
        pages = render_html_paginated(data, page_size=10)
        assert len(pages) == 1
        assert "<!DOCTYPE html>" in pages[0][1]


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
            json.loads(line) for line in lines if json.loads(line)["type"] == "subagent_message"
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

    def test_render_malformed_task_missing_fields(self):
        """Tasks with missing fields use defaults instead of raising KeyError."""
        data = TranscriptData(tasks=[{"id": "t1"}])
        md = render_markdown(data)
        assert "UNKNOWN" in md
        assert "untitled" in md
        assert "uncategorised" in md

    def test_render_malformed_message_missing_role(self):
        """Messages with missing role use default instead of raising KeyError."""
        data = TranscriptData(messages=[{"content": "test"}])
        md = render_markdown(data)
        assert "UNKNOWN" in md

    def test_render_malformed_tool_call_missing_name(self):
        """Tool calls with missing name use default instead of raising KeyError."""
        data = TranscriptData(
            messages=[
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"arguments": {}}],
                }
            ]
        )
        md = render_markdown(data)
        assert "Tool: unknown" in md

    def test_render_malformed_event_missing_type(self):
        """Events with missing event_type use default instead of raising KeyError."""
        data = TranscriptData(events=[{"detail": {}}])
        md = render_markdown(data)
        assert "**unknown**" in md

    def test_render_tool_result_with_triple_backticks(self):
        """Tool results that themselves contain ``` must not break the surrounding fence.

        LLM-generated content routinely contains markdown code fences;
        a fixed triple-backtick fence collapses on the embedded run.
        The renderer expands the fence so the closing fence is unique.
        """
        data = TranscriptData(
            messages=[
                {
                    "role": "assistant",
                    "content": "",
                    "tool_results": [
                        {"content": "Here's some code:\n```python\nprint(1)\n```\nDone."}
                    ],
                }
            ]
        )
        md = render_markdown(data)
        # Opening + closing fence must be at least four backticks long
        # so the embedded ``` doesn't terminate the block.
        assert "````\n" in md
        # The embedded triple-backticks survive verbatim inside the wider fence.
        assert "```python\nprint(1)\n```" in md

    def test_render_tool_call_args_with_backticks(self):
        """Tool call arguments containing ``` get a wider fence too."""
        data = TranscriptData(
            messages=[
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"name": "edit", "arguments": {"snippet": "fence: ```"}}],
                }
            ]
        )
        md = render_markdown(data)
        # The serialised JSON contains escaped backticks; the fence must
        # be longer than any backtick run in the JSON payload.
        assert "````json\n" in md


# ===================================================================
# TestFilteredExport
# ===================================================================


class TestFilteredExport:
    """Tests for filtered transcript export (--task, --phase, --since)."""

    @pytest.fixture()
    def db_path(self, tmp_path: pathlib.Path) -> pathlib.Path:
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

    def test_filter_by_since_keeps_timestampless(self, db_path, monkeypatch):
        """A message without a timestamp survives --since filtering.

        Pre-migration or corrupt rows can lack a timestamp; silently
        dropping them under a time filter is worse than over-including
        a row whose time is unknown.
        """
        from cantrip.agent import store as store_mod

        real_load = store_mod.SessionStore.load_active_branch

        def patched(self, head=None):
            msgs = real_load(self, head)
            msgs.append({"id": 999, "role": "system", "content": "ghost", "timestamp": None})
            return msgs

        monkeypatch.setattr(store_mod.SessionStore, "load_active_branch", patched)
        data = load_transcript(db_path, since="2099-01-01T00:00:00")
        # Real (past-dated) messages are excluded; the timestampless ghost survives.
        assert [m.get("content") for m in data.messages] == ["ghost"]

    def test_nonexistent_task_id_gives_empty(self, db_path):
        data = load_transcript(db_path, task_id="nonexistent")
        assert len(data.tasks) == 0
        assert data.subagent_messages == {}

    def test_unknown_phase_gives_empty(self, db_path):
        data = load_transcript(db_path, phase="unknown")
        assert len(data.tasks) == 0
