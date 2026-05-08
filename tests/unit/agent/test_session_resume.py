"""Tests for session resume protocol (Phase 11.3)."""

import pathlib
import sqlite3
from unittest.mock import patch

from cantrip.agent.core import CantripAgent
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.llm.base import Role
from tests.conftest import FakeProvider


class TestBuildResumeSummary:
    """Tests for CantripAgent.build_resume_summary."""

    def test_returns_none_for_empty_state(self):
        """An agent with no prior work produces no summary."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)

        result = agent.build_resume_summary()

        assert result is None

    def test_includes_charm_name_and_type(self):
        """Summary includes charm name, type, and path."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.charm_name = "my-charm"
        agent.state.charm_type = "k8s"
        agent.state.charm_path = pathlib.Path("/tmp/my-charm")

        result = agent.build_resume_summary()

        assert result is not None
        assert "my-charm" in result
        assert "k8s" in result
        assert "/tmp/my-charm" in result

    def test_includes_framework(self):
        """Summary includes the framework when set."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.charm_name = "flask-app"
        agent.state.framework = "flask"

        result = agent.build_resume_summary()

        assert result is not None
        assert "flask" in result

    def test_includes_models(self):
        """Summary includes dev and cos model names."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.charm_name = "test-charm"
        agent.state.dev_model = "dev-model"
        agent.state.cos_model = "cos-model"

        result = agent.build_resume_summary()

        assert result is not None
        assert "dev=dev-model" in result
        assert "cos=cos-model" in result

    def test_includes_decisions(self):
        """Summary lists all recorded decisions."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.add_decision("path", "12-factor", reason="Flask app")
        agent.state.add_decision("substrate", "k8s")

        result = agent.build_resume_summary()

        assert result is not None
        assert "path: 12-factor" in result
        assert "substrate: k8s" in result

    def test_includes_task_counts(self):
        """Summary shows done, failed, and pending task counts."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.charm_name = "test"

        agent.work_queue.add_tasks(
            [
                AgentTask(
                    title="Research", category=TaskCategory.RESEARCH, status=TaskStatus.DONE
                ),
                AgentTask(title="Build", category=TaskCategory.BUILD, status=TaskStatus.DONE),
                AgentTask(title="Deploy", category=TaskCategory.DEPLOY, status=TaskStatus.FAILED),
                AgentTask(title="Test", category=TaskCategory.TEST, status=TaskStatus.PENDING),
                AgentTask(title="Debug", category=TaskCategory.DEBUG, status=TaskStatus.BLOCKED),
            ]
        )

        result = agent.build_resume_summary()

        assert result is not None
        assert "2 done" in result
        assert "1 failed" in result
        # Pending includes pending + blocked.
        assert "2 pending" in result

    def test_includes_recent_completed_tasks(self):
        """Summary lists titles of up to 5 recent completed tasks."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)

        tasks = [
            AgentTask(title=f"Task {i}", category=TaskCategory.BUILD, status=TaskStatus.DONE)
            for i in range(7)
        ]
        agent.work_queue.add_tasks(tasks)

        result = agent.build_resume_summary()

        assert result is not None
        # Only the last 5 should appear.
        assert "Task 2" in result
        assert "Task 6" in result
        assert "Task 0" not in result

    def test_injects_message_into_state(self):
        """The summary is injected as a SYSTEM message into state.messages."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.charm_name = "test"

        agent.build_resume_summary()

        assert len(agent.state.messages) == 1
        assert agent.state.messages[0].role == Role.SYSTEM
        assert "[Session resumed]" in agent.state.messages[0].content

    def test_no_message_injected_when_none(self):
        """No message is injected when summary returns None."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)

        agent.build_resume_summary()

        assert len(agent.state.messages) == 0


class TestLoadStateErrorHandling:
    """Tests for CantripAgent.load_state exception handling."""

    def test_sqlite_error_returns_false(self, tmp_path: pathlib.Path):
        """An sqlite3.Error during load_state returns False gracefully."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent._ensure_store()
        assert agent._store is not None

        with patch.object(
            agent._store, "load_session", side_effect=sqlite3.DatabaseError("corrupt")
        ):
            result = agent.load_state()

        assert result is False
        assert agent._store is None

    def test_value_error_returns_false(self, tmp_path: pathlib.Path):
        """A ValueError during load_state returns False gracefully."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent._ensure_store()
        assert agent._store is not None

        with patch.object(agent._store, "load_session", side_effect=ValueError("bad data")):
            result = agent.load_state()

        assert result is False
        assert agent._store is None


class TestStaleTaskRecovery:
    """Tests for resetting stale ACTIVE tasks on load_state."""

    def test_active_tasks_reset_to_pending(self, tmp_path: pathlib.Path):
        """Tasks that were ACTIVE when the session ended are reset to PENDING."""
        provider = FakeProvider()

        # Save a session with an active task.
        agent1 = CantripAgent(provider=provider, charm_path=tmp_path)
        agent1.state.charm_name = "recovery-test"
        agent1.save_state()
        agent1._ensure_store()
        assert agent1._store is not None
        agent1._store.save_tasks(
            [
                AgentTask(
                    id="t1",
                    title="Active task",
                    category=TaskCategory.BUILD,
                    status=TaskStatus.ACTIVE,
                ),
                AgentTask(
                    id="t2", title="Done task", category=TaskCategory.BUILD, status=TaskStatus.DONE
                ),
                AgentTask(
                    id="t3",
                    title="Pending task",
                    category=TaskCategory.BUILD,
                    status=TaskStatus.PENDING,
                ),
            ]
        )

        # Load into a fresh agent.
        agent2 = CantripAgent(provider=provider, charm_path=tmp_path)
        loaded = agent2.load_state()

        assert loaded is True
        tasks = agent2.work_queue.all_tasks()
        task_map = {t.id: t for t in tasks}
        assert task_map["t1"].status == TaskStatus.PENDING
        assert task_map["t2"].status == TaskStatus.DONE
        assert task_map["t3"].status == TaskStatus.PENDING


class TestPreviewSession:
    """Tests for CantripAgent.preview_session — the Phase 31.3 preview path."""

    def test_no_charm_path_returns_empty(self):
        """Preview returns exists=False when no charm path is configured."""
        agent = CantripAgent(provider=FakeProvider())
        preview = agent.preview_session()
        assert preview.exists is False

    def test_no_cantrip_file_returns_empty(self, tmp_path: pathlib.Path):
        """Preview returns exists=False when the file isn't on disk."""
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        preview = agent.preview_session()
        assert preview.exists is False

    def test_returns_session_metadata(self, tmp_path: pathlib.Path):
        """Preview returns charm name, models, and task counts without mutating state."""
        writer = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        writer.state.charm_name = "my-charm"
        writer.state.charm_type = "k8s"
        writer.state.dev_model = "dev"
        writer.state.cos_model = "cos"
        writer.save_state()
        writer._ensure_store()
        assert writer._store is not None
        writer._store.save_tasks(
            [
                AgentTask(
                    id="t1",
                    title="Pending",
                    category=TaskCategory.BUILD,
                    status=TaskStatus.PENDING,
                ),
                AgentTask(
                    id="t2",
                    title="Done",
                    category=TaskCategory.BUILD,
                    status=TaskStatus.DONE,
                ),
            ]
        )

        reader = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        preview = reader.preview_session()

        assert preview.exists is True
        assert preview.charm_name == "my-charm"
        assert preview.charm_type == "k8s"
        assert preview.dev_model == "dev"
        assert preview.cos_model == "cos"
        assert preview.task_counts.get("pending") == 1
        assert preview.task_counts.get("done") == 1
        assert preview.has_unfinished_tasks is True
        assert preview.updated_at is not None
        # Reader's state should be untouched.
        assert reader.state.charm_name is None

    def test_has_unfinished_false_when_all_done(self, tmp_path: pathlib.Path):
        """has_unfinished_tasks is False when tasks are all terminal."""
        writer = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        writer.state.charm_name = "c"
        writer.save_state()
        writer._ensure_store()
        assert writer._store is not None
        writer._store.save_tasks(
            [
                AgentTask(
                    id="t1",
                    title="Done",
                    category=TaskCategory.BUILD,
                    status=TaskStatus.DONE,
                ),
            ]
        )

        reader = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        preview = reader.preview_session()

        assert preview.exists is True
        assert preview.has_unfinished_tasks is False

    def test_preview_does_not_mutate_agent_state(self, tmp_path: pathlib.Path):
        """Calling preview_session must leave agent.state.charm_name as-is."""
        writer = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        writer.state.charm_name = "untouched-probe"
        writer.save_state()

        reader = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        reader.preview_session()
        assert reader.state.charm_name is None
        assert reader.state.messages == []

    def test_corrupt_cantrip_file_returns_empty_preview(self, tmp_path: pathlib.Path):
        """A corrupt .cantrip file degrades to ``exists=False`` rather than raising.

        Without this, a damaged session file would crash every launch.
        The contract documented on ``preview_session`` is that callers
        can branch on ``preview.exists`` without catching, so the
        sqlite3.Error fallback at persistence.py:86 must hold.
        """
        cantrip_db = tmp_path / ".cantrip"
        cantrip_db.write_bytes(b"not a sqlite database, just garbage bytes\n")

        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        preview = agent.preview_session()

        assert preview.exists is False
        assert preview.charm_name is None

    def test_peek_session_failure_returns_empty_preview(self, tmp_path: pathlib.Path):
        """A sqlite error during ``peek_session`` falls through to empty preview.

        Covers the second except in ``preview_session`` (persistence.py:101)
        — the store opens cleanly but a query fails (e.g. schema drift,
        truncated row), and we must not let that crash the launch path.
        """
        writer = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        writer.state.charm_name = "demo"
        writer.save_state()

        reader = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        with patch(
            "cantrip.agent.store.SessionStore.peek_session",
            side_effect=sqlite3.Error("schema mismatch"),
        ):
            preview = reader.preview_session()

        assert preview.exists is False
        assert preview.charm_name is None

    def test_summary_includes_charm_and_counts(self, tmp_path: pathlib.Path):
        """Summary string includes the charm name and a task count breakdown."""
        writer = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        writer.state.charm_name = "my-charm"
        writer.save_state()
        writer._ensure_store()
        assert writer._store is not None
        writer._store.save_tasks(
            [
                AgentTask(
                    id="t1",
                    title="T",
                    category=TaskCategory.BUILD,
                    status=TaskStatus.PENDING,
                ),
            ]
        )

        reader = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        preview = reader.preview_session()

        summary = preview.summary()
        assert "my-charm" in summary
        assert "pending" in summary


class TestArchiveSession:
    """Tests for CantripAgent.archive_session."""

    def test_no_file_returns_none(self, tmp_path: pathlib.Path):
        """archive_session returns None when there's nothing to archive."""
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        assert agent.archive_session() is None

    def test_renames_to_backup(self, tmp_path: pathlib.Path):
        """archive_session moves .cantrip to .cantrip.bak-TIMESTAMP."""
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        agent.state.charm_name = "to-be-archived"
        agent.save_state()
        db_path = tmp_path / ".cantrip"
        assert db_path.is_file()

        backup = agent.archive_session()

        assert backup is not None
        assert not db_path.exists()
        assert backup.exists()
        assert backup.name.startswith(".cantrip.bak-")
        # The store has been reset so the next save starts fresh.
        assert agent._store is None

    def test_fresh_session_starts_empty_after_archive(self, tmp_path: pathlib.Path):
        """After archiving, save_state creates a new empty database."""
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        agent.state.charm_name = "stale"
        agent.save_state()

        agent.archive_session()
        agent.state.charm_name = "fresh"
        agent.save_state()

        reader = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        reader.load_state()
        assert reader.state.charm_name == "fresh"


class TestResumedMustReadDirective:
    """Tests for the Phase 103.1 ``was_resumed`` flag and prompt directive.

    A resumed session has the LLM's in-conversation memory of file bytes
    rehydrated from SQLite, but the on-disk bytes may have drifted.  The
    flag arms a one-shot system-prompt directive telling the model to
    ``read_file`` first; the directive clears the moment the model
    obliges so it doesn't bloat steady-state turns.
    """

    def test_was_resumed_set_after_load_state(self, tmp_path: pathlib.Path):
        """A successful ``load_state`` arms the must-read directive."""
        writer = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        writer.state.charm_name = "resumed"
        writer.save_state()

        reader = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        assert reader.state.was_resumed is False  # default before load
        loaded = reader.load_state()

        assert loaded is True
        assert reader.state.was_resumed is True

    def test_was_resumed_stays_false_when_no_session(self, tmp_path: pathlib.Path):
        """A failed ``load_state`` (no session) leaves the flag at its default."""
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        loaded = agent.load_state()
        assert loaded is False
        assert agent.state.was_resumed is False

    def test_directive_in_system_prompt_when_armed(self, tmp_path: pathlib.Path):
        """The system prompt carries the directive while ``was_resumed`` is set."""
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        agent.state.was_resumed = True

        prompt = agent._build_system_prompt()

        # Pin the recognisable signal — the heading and the imperative.
        assert "Resumed session — re-read before editing" in prompt
        assert "read_file" in prompt

    def test_directive_absent_when_not_resumed(self, tmp_path: pathlib.Path):
        """Default sessions don't carry the resume directive."""
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        assert agent.state.was_resumed is False

        prompt = agent._build_system_prompt()
        assert "Resumed session — re-read before editing" not in prompt

    async def test_successful_read_file_clears_flag(self, tmp_path: pathlib.Path):
        """A successful ``read_file`` clears the resume directive flag."""
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        agent.state.was_resumed = True

        target = tmp_path / "x.txt"
        target.write_text("hello")

        result = await agent._execute_tool("read_file", {"path": str(target)})
        assert result.success
        assert agent.state.was_resumed is False

        # And the directive disappears from the next prompt build.
        assert "Resumed session — re-read before editing" not in agent._build_system_prompt()

    async def test_failed_read_file_keeps_flag(self, tmp_path: pathlib.Path):
        """A failing ``read_file`` (missing path) does *not* clear the flag.

        The model hasn't actually seen on-disk bytes if the read failed,
        so we keep the directive armed until a real successful read.
        """
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        agent.state.was_resumed = True

        result = await agent._execute_tool(
            "read_file", {"path": str(tmp_path / "nonexistent.txt")}
        )
        assert result.success is False
        assert agent.state.was_resumed is True

    async def test_other_tools_dont_clear_flag(self, tmp_path: pathlib.Path):
        """A non-read tool call leaves the must-read flag armed."""
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        agent.state.was_resumed = True

        # ``list_directory`` is a successful, side-effect-free tool but
        # it's not ``read_file`` — the model still hasn't proven it has
        # seen the bytes of a specific file.
        result = await agent._execute_tool("list_directory", {"path": str(tmp_path)})
        assert result.success
        assert agent.state.was_resumed is True


class TestEditStringMissesCounter:
    """Tests for the Phase 103.4 ``edit_string_misses`` counter.

    The counter ticks up when ``edit_file`` / ``multi_edit`` fail their
    ``old_string`` match and back down when a subsequent edit on the
    same file succeeds.  Surfaced via ``/cost`` so the operator can spot
    a session burning rounds on hallucinated edit strings.
    """

    async def test_failed_edit_increments_counter(self, tmp_path: pathlib.Path):
        """A failed ``edit_file`` ticks the counter for the affected path."""
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        target = tmp_path / "f.py"
        target.write_text("alpha\n")
        # The miss path the tool reports is the resolved absolute path.
        resolved = str(target.resolve())

        result = await agent._execute_tool(
            "edit_file",
            {
                "path": str(target),
                "old_string": "nonexistent",
                "new_string": "x",
            },
        )

        assert result.success is False
        assert agent.state.edit_string_misses.get(resolved, 0) == 1

    async def test_successful_edit_decrements_counter(self, tmp_path: pathlib.Path):
        """A subsequent successful edit on the same file decrements."""
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        target = tmp_path / "f.py"
        target.write_text("alpha\n")
        resolved = str(target.resolve())
        agent.state.edit_string_misses[resolved] = 3  # pretend prior misses

        result = await agent._execute_tool(
            "edit_file",
            {
                "path": str(target),
                "old_string": "alpha",
                "new_string": "beta",
            },
        )

        assert result.success
        assert agent.state.edit_string_misses[resolved] == 2

    async def test_counter_clears_when_resolved(self, tmp_path: pathlib.Path):
        """The path drops out of the dict when its count hits zero."""
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        target = tmp_path / "f.py"
        target.write_text("alpha\n")
        resolved = str(target.resolve())
        agent.state.edit_string_misses[resolved] = 1

        await agent._execute_tool(
            "edit_file",
            {
                "path": str(target),
                "old_string": "alpha",
                "new_string": "beta",
            },
        )

        # Resolved cleanly; the path is gone from the dict so ``/cost``
        # has nothing to surface.
        assert resolved not in agent.state.edit_string_misses

    async def test_decrement_floored_at_zero(self, tmp_path: pathlib.Path):
        """Successful edits on a file with no recorded misses are no-ops."""
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        target = tmp_path / "f.py"
        target.write_text("alpha\n")

        result = await agent._execute_tool(
            "edit_file",
            {
                "path": str(target),
                "old_string": "alpha",
                "new_string": "beta",
            },
        )

        assert result.success
        # No prior miss → the counter shouldn't go negative or seed a
        # spurious zero entry.
        assert agent.state.edit_string_misses == {}

    async def test_other_files_untouched(self, tmp_path: pathlib.Path):
        """A miss on file A leaves file B's counter unchanged."""
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        a = tmp_path / "a.py"
        a.write_text("alpha\n")
        b = tmp_path / "b.py"
        b.write_text("beta\n")
        agent.state.edit_string_misses[str(b.resolve())] = 4

        result = await agent._execute_tool(
            "edit_file",
            {
                "path": str(a),
                "old_string": "missing",
                "new_string": "x",
            },
        )

        assert result.success is False
        # ``a`` got incremented; ``b`` is unchanged.
        assert agent.state.edit_string_misses[str(a.resolve())] == 1
        assert agent.state.edit_string_misses[str(b.resolve())] == 4


class TestTranscriptTail:
    """Tests for CantripAgent.transcript_tail."""

    def test_returns_last_n_messages(self, tmp_path: pathlib.Path):
        """transcript_tail returns the last N persisted messages."""
        writer = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        writer.state.charm_name = "c"
        writer.save_state()
        writer._ensure_store()
        assert writer._store is not None
        for i in range(5):
            writer._store.record_message(role="user", content=f"msg-{i}")

        reader = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        tail = reader.transcript_tail(limit=3)

        assert len(tail) == 3
        assert tail[-1].content == "msg-4"
        assert tail[0].content == "msg-2"

    def test_empty_when_no_store(self, tmp_path: pathlib.Path):
        """transcript_tail returns [] when no store exists."""
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        assert agent.transcript_tail() == []
