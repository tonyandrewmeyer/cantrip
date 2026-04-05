"""Tests for AgentState, Decision, TestResults, and executor noop detection."""

from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.agent.routing import TaskSnapshot, snapshot_from_queue
from cantrip.agent.state import AgentState, Decision, TestResults


class TestAgentState:
    """Tests for the AgentState dataclass."""

    def test_defaults(self):
        state = AgentState()
        assert state.charm_name is None
        assert state.charm_path is None
        assert state.charm_type is None
        assert state.framework is None
        assert state.dev_model is None
        assert state.cos_model is None
        assert state.mode == "build"
        assert state.environment_ready is False
        assert state.messages == []
        assert state.decisions == []
        assert state.design_proposal is None
        assert state.audit_report is None

    def test_add_decision(self):
        state = AgentState()
        state.add_decision("substrate", "Kubernetes", "Good for containers")
        assert len(state.decisions) == 1
        assert state.decisions[0].type == "substrate"
        assert state.decisions[0].choice == "Kubernetes"
        assert state.decisions[0].reason == "Good for containers"

    def test_add_multiple_decisions(self):
        state = AgentState()
        state.add_decision("substrate", "K8s")
        state.add_decision("charm_path", "Custom")
        state.add_decision("charmhub", "Build new")
        assert len(state.decisions) == 3

    def test_add_decision_without_reason(self):
        state = AgentState()
        state.add_decision("substrate", "Machine")
        assert state.decisions[0].reason is None


class TestDecision:
    """Tests for the Decision dataclass."""

    def test_to_dict(self):
        d = Decision(type="substrate", choice="K8s", reason="Best fit")
        as_dict = d.to_dict()
        assert as_dict["type"] == "substrate"
        assert as_dict["choice"] == "K8s"
        assert as_dict["reason"] == "Best fit"
        assert "timestamp" in as_dict

    def test_to_dict_none_reason(self):
        d = Decision(type="substrate", choice="K8s")
        as_dict = d.to_dict()
        assert as_dict["reason"] is None

    def test_timestamp_populated(self):
        d = Decision(type="test", choice="value")
        assert d.timestamp is not None


class TestTestResults:
    """Tests for TestResults formatting."""

    def test_all_passed(self):
        tr = TestResults(test_type="unit", passed=10)
        summary = tr.format_summary()
        assert "10 passed" in summary
        assert "✓" in summary

    def test_failures(self):
        tr = TestResults(test_type="unit", passed=8, failed=2)
        summary = tr.format_summary()
        assert "2 failed" in summary
        assert "✗" in summary

    def test_errors(self):
        tr = TestResults(test_type="unit", passed=5, error=1)
        summary = tr.format_summary()
        assert "1 error" in summary
        assert "✗" in summary

    def test_skipped(self):
        tr = TestResults(test_type="unit", passed=10, skipped=3)
        summary = tr.format_summary()
        assert "3 skipped" in summary

    def test_empty_results(self):
        tr = TestResults(test_type="unit")
        assert tr.format_summary() == ""

    def test_integration_type(self):
        tr = TestResults(test_type="integration", passed=5)
        assert tr.test_type == "integration"


class TestExecutorIsNoop:
    """Tests for the _is_noop static method on BackgroundExecutor.

    _is_noop is a simple method: returns True only when both fingerprints
    are non-empty and identical.
    """

    def test_identical_fingerprints_is_noop(self):
        assert BackgroundExecutor._is_noop(None, "abc123", "abc123") is True

    def test_different_fingerprints_not_noop(self):
        assert BackgroundExecutor._is_noop(None, "abc", "def") is False

    def test_empty_before_not_noop(self):
        """Empty 'before' fingerprint means we couldn't capture state — not a noop."""
        assert BackgroundExecutor._is_noop(None, "", "abc") is False

    def test_empty_after_not_noop(self):
        assert BackgroundExecutor._is_noop(None, "abc", "") is False

    def test_both_empty_not_noop(self):
        assert BackgroundExecutor._is_noop(None, "", "") is False


class TestSnapshotFromQueue:
    """Tests for building routing snapshots from live task objects."""

    def test_basic_conversion(self):
        tasks = [
            AgentTask(id="t1", title="Research", category=TaskCategory.RESEARCH),
            AgentTask(id="t2", title="Build", category=TaskCategory.BUILD,
                      dependencies=["t1"]),
        ]
        state = snapshot_from_queue(
            tasks, active_subagent_count=0, max_concurrency=3,
            has_charm_path=True, has_dev_model=True,
        )
        assert len(state.tasks) == 2
        assert state.tasks[0].id == "t1"
        assert state.tasks[0].category == "research"
        assert state.tasks[0].status == TaskSnapshot.PENDING
        assert state.tasks[1].dependencies == ("t1",)

    def test_status_mapping(self):
        """All TaskStatus values map correctly to TaskSnapshot."""
        from cantrip.agent.queue import TaskStatus

        for status in TaskStatus:
            task = AgentTask(id="x", title="X", category=TaskCategory.BUILD, status=status)
            state = snapshot_from_queue([task], 0, 1)
            assert state.tasks[0].status.value == status.value

    def test_noop_count_preserved(self):
        task = AgentTask(id="t1", title="T", category=TaskCategory.BUILD)
        task.noop_count = 3
        state = snapshot_from_queue([task], 0, 1)
        assert state.tasks[0].noop_count == 3

    def test_paused_and_draining_flags(self):
        state = snapshot_from_queue([], 0, 1, paused=True, draining=True)
        assert state.paused is True
        assert state.draining is True

    def test_empty_tasks(self):
        state = snapshot_from_queue([], 0, 3)
        assert len(state.tasks) == 0
        assert state.is_terminal is True
