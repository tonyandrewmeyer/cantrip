"""Integration tests: transcript export pipeline.

Exercises the full round-trip from agent conversation through SQLite
persistence to transcript export in all three formats (HTML, Markdown,
JSONL), including filter options (--task, --phase, --since).
"""

import json
import pathlib

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.agent.state import AgentState
from cantrip.agent.store import SessionStore
from cantrip.llm.base import Response, ToolCall
from cantrip.transcript.export import load_transcript
from cantrip.transcript.html import render_html
from cantrip.transcript.jsonl import render_jsonl
from cantrip.transcript.markdown import render_markdown
from tests.conftest import FakeProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_database(db_path: pathlib.Path) -> SessionStore:
    """Create a .cantrip database with realistic session data.

    Returns the open store so callers can add more data if needed.
    """
    store = SessionStore(db_path)
    store.open()

    state = AgentState(
        charm_name="test-redis",
        charm_path=db_path.parent,
        charm_type="k8s",
        framework="ops",
    )
    store.save_session(state)

    # Two conversation messages.
    store.record_message("user", "Build a Redis charm")
    store.record_message("assistant", "Sure, I will build a Redis charm for you.")

    # A tool-call message.
    store.record_message(
        "assistant",
        "",
        tool_calls=[{"id": "tc1", "name": "write_file", "arguments": {"path": "src/charm.py"}}],
    )
    store.record_message(
        "tool",
        "",
        tool_results=[{"tool_call_id": "tc1", "content": "File written.", "is_error": False}],
    )

    # Tasks spanning two phases.
    tasks = [
        AgentTask(
            id="research-redis",
            title="Research Redis",
            status=TaskStatus.DONE,
            category=TaskCategory.RESEARCH,
            description="Investigate Redis deployment patterns.",
            result="Redis uses RDB snapshots.",
        ),
        AgentTask(
            id="build-charm",
            title="Build the charm",
            status=TaskStatus.DONE,
            category=TaskCategory.BUILD,
            description="Scaffold and implement the charm.",
            result="Charm scaffolded.",
        ),
        AgentTask(
            id="deploy-charm",
            title="Deploy the charm",
            status=TaskStatus.PENDING,
            category=TaskCategory.DEPLOY,
            description="Deploy to a dev model.",
        ),
    ]
    store.save_tasks(tasks)

    # Subagent messages for the research task.
    store.record_subagent_message("research-redis", 0, "system", "You are an autonomous subagent.")
    store.record_subagent_message(
        "research-redis", 1, "assistant", "Redis uses RDB snapshots for persistence."
    )

    # Events.
    store.record_event("task_started", {"task_id": "research-redis"})
    store.record_event("task_completed", {"task_id": "research-redis"})

    # Token usage.
    store.record_usage("gemini", "gemini-2.0-flash", 500, 200)
    store.record_usage("gemini", "gemini-2.0-flash", 300, 150)

    return store


# ---------------------------------------------------------------------------
# Round-trip: agent conversation → save → export → verify
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTranscriptRoundTrip:
    """Conversation → SQLite → export → verify content."""

    @pytest.mark.asyncio
    async def test_conversation_exported_to_all_formats(self, tmp_path: pathlib.Path):
        """Run a multi-turn conversation, save, export in all formats."""
        provider = FakeProvider(
            [
                # First turn: agent calls write_file.
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="wf1",
                            name="write_file",
                            arguments={
                                "path": "src/charm.py",
                                "content": "import ops\n",
                            },
                        ),
                    ],
                ),
                Response(content="Charm created."),
                # Second turn: plain text.
                Response(content="Anything else?"),
            ]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.charm_name = "my-redis"

        await agent.process_message("Build a Redis charm")
        await agent.process_message("Looks good")
        agent.save_state()

        # Load transcript from the persisted database.
        db_path = tmp_path / ".cantrip"
        assert db_path.exists()
        data = load_transcript(db_path)

        assert data.charm_name == "my-redis"
        assert len(data.messages) >= 4  # At least user + tool-call + tool-result + final

        # Render in all three formats and sanity-check output.
        html = render_html(data)
        assert "my-redis" in html
        assert "<html" in html

        md = render_markdown(data)
        assert "my-redis" in md
        assert "## Conversation" in md

        jsonl = render_jsonl(data)
        lines = [line for line in jsonl.strip().split("\n") if line]
        assert len(lines) >= 4
        for line in lines:
            parsed = json.loads(line)
            assert "type" in parsed

    @pytest.mark.asyncio
    async def test_state_round_trip_preserves_transcript(self, tmp_path: pathlib.Path):
        """Save state, create a new agent, load state, export — data intact."""
        provider = FakeProvider([Response(content="Hello!")])
        agent1 = CantripAgent(provider=provider, charm_path=tmp_path)
        agent1.state.charm_name = "roundtrip-charm"
        await agent1.process_message("Hello")
        agent1.save_state()

        # New agent, same path.
        agent2 = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        loaded = agent2.load_state()
        assert loaded is True
        assert agent2.state.charm_name == "roundtrip-charm"

        data = load_transcript(tmp_path / ".cantrip")
        assert data.charm_name == "roundtrip-charm"
        assert len(data.messages) >= 2


# ---------------------------------------------------------------------------
# Export filters
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTranscriptFilters:
    """Verify --task, --phase, and --since filters."""

    def test_filter_by_task(self, tmp_path: pathlib.Path):
        """Only the specified task and its subagent messages are included."""
        db_path = tmp_path / ".cantrip"
        store = _seed_database(db_path)
        store.close()

        data = load_transcript(db_path, task_id="research-redis")

        assert len(data.tasks) == 1
        assert data.tasks[0]["id"] == "research-redis"
        assert "research-redis" in data.subagent_messages
        # Conversation messages are still included (for context).
        assert len(data.messages) >= 1

    def test_filter_by_phase_research(self, tmp_path: pathlib.Path):
        """Phase=research includes only research and confirm tasks."""
        db_path = tmp_path / ".cantrip"
        store = _seed_database(db_path)
        store.close()

        data = load_transcript(db_path, phase="research")

        task_categories = {t["category"] for t in data.tasks}
        assert task_categories <= {"research", "confirm"}
        # The build and deploy tasks should be excluded.
        task_ids = {t["id"] for t in data.tasks}
        assert "build-charm" not in task_ids
        assert "deploy-charm" not in task_ids

    def test_filter_by_phase_build(self, tmp_path: pathlib.Path):
        """Phase=build includes only build tasks."""
        db_path = tmp_path / ".cantrip"
        store = _seed_database(db_path)
        store.close()

        data = load_transcript(db_path, phase="build")

        assert len(data.tasks) == 1
        assert data.tasks[0]["id"] == "build-charm"

    def test_filter_by_since(self, tmp_path: pathlib.Path):
        """Since filter excludes older messages and events."""
        db_path = tmp_path / ".cantrip"
        store = _seed_database(db_path)

        # Record a message with a known future timestamp by inserting directly.
        store._db.execute(
            "INSERT INTO messages (role, content, timestamp) VALUES (?, ?, ?)",
            ("user", "A late message", "2099-01-01T00:00:00"),
        )
        store._db.commit()
        store.close()

        data = load_transcript(db_path, since="2099-01-01T00:00:00")

        # Only the late message should survive the filter.
        assert len(data.messages) == 1
        assert data.messages[0]["content"] == "A late message"


# ---------------------------------------------------------------------------
# Subagent messages and events
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTranscriptSubagentAndEvents:
    """Verify subagent messages and events appear in exports."""

    def test_subagent_messages_in_export(self, tmp_path: pathlib.Path):
        """Subagent messages for included tasks are present in the export."""
        db_path = tmp_path / ".cantrip"
        store = _seed_database(db_path)
        store.close()

        data = load_transcript(db_path)

        assert "research-redis" in data.subagent_messages
        msgs = data.subagent_messages["research-redis"]
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert "autonomous subagent" in msgs[0]["content"]

    def test_events_in_export(self, tmp_path: pathlib.Path):
        """Events are included in the export."""
        db_path = tmp_path / ".cantrip"
        store = _seed_database(db_path)
        store.close()

        data = load_transcript(db_path)

        assert len(data.events) >= 2
        event_types = {e["event_type"] for e in data.events}
        assert "task_started" in event_types
        assert "task_completed" in event_types

    def test_token_usage_in_export(self, tmp_path: pathlib.Path):
        """Aggregate token usage is included."""
        db_path = tmp_path / ".cantrip"
        store = _seed_database(db_path)
        store.close()

        data = load_transcript(db_path)

        assert data.token_usage["prompt_tokens"] == 800
        assert data.token_usage["completion_tokens"] == 350

    def test_subagent_messages_in_all_formats(self, tmp_path: pathlib.Path):
        """Subagent messages appear in HTML, Markdown, and JSONL output."""
        db_path = tmp_path / ".cantrip"
        store = _seed_database(db_path)
        store.close()

        data = load_transcript(db_path)

        html = render_html(data)
        assert "research-redis" in html or "Redis" in html

        md = render_markdown(data)
        # Tasks section should list the research task.
        assert "Research Redis" in md

        jsonl = render_jsonl(data)
        # At least one subagent_message line should be present.
        lines = jsonl.strip().split("\n")
        subagent_lines = [line for line in lines if '"type": "subagent_message"' in line]
        assert len(subagent_lines) >= 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTranscriptEdgeCases:
    """Edge cases and error resilience."""

    def test_empty_database(self, tmp_path: pathlib.Path):
        """Export from a freshly created database produces valid empty output."""
        db_path = tmp_path / ".cantrip"
        store = SessionStore(db_path)
        store.open()
        store.close()

        data = load_transcript(db_path)

        assert data.messages == []
        assert data.tasks == []
        assert data.events == []

        # All renderers should handle empty data gracefully.
        html = render_html(data)
        assert "<html" in html

        md = render_markdown(data)
        assert "Cantrip Transcript" in md

        jsonl = render_jsonl(data)
        assert jsonl == ""

    def test_filter_nonexistent_task(self, tmp_path: pathlib.Path):
        """Filtering by a task ID that doesn't exist returns no tasks."""
        db_path = tmp_path / ".cantrip"
        store = _seed_database(db_path)
        store.close()

        data = load_transcript(db_path, task_id="no-such-task")

        assert data.tasks == []
        assert data.subagent_messages == {}

    def test_combined_filters(self, tmp_path: pathlib.Path):
        """Phase and since filters combine correctly."""
        db_path = tmp_path / ".cantrip"
        store = _seed_database(db_path)
        store.close()

        # Phase=build should give one task; since far in the future should
        # give no messages.
        data = load_transcript(db_path, phase="build", since="2099-01-01T00:00:00")

        assert len(data.tasks) == 1
        assert data.tasks[0]["id"] == "build-charm"
        assert data.messages == []
