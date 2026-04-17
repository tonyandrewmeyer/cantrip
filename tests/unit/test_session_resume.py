"""Tests for session resume protocol (Phase 11.3)."""

import sqlite3
from pathlib import Path
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
        agent.state.charm_path = Path("/tmp/my-charm")

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

    def test_sqlite_error_returns_false(self, tmp_path: Path):
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

    def test_value_error_returns_false(self, tmp_path: Path):
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

    def test_active_tasks_reset_to_pending(self, tmp_path: Path):
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
