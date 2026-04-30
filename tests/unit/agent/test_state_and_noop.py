"""Tests for AgentState, Decision, TestResults, and executor noop detection."""

import datetime
import pathlib

import pytest

from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.agent.routing import TaskSnapshot, snapshot_from_queue
from cantrip.agent.state import (
    AgentState,
    Decision,
    TestResults,
    append_shared_decision,
    load_shared_decisions,
    shared_decisions_path,
)


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

    def test_default_source_is_local(self):
        d = Decision(type="t", choice="c")
        assert d.source == "local"

    def test_to_dict_includes_source(self):
        d = Decision(type="t", choice="c", source="shared")
        assert d.to_dict()["source"] == "shared"


# ── Phase 51b.2: shared decisions log ──────────────────────────────────


class TestSharedDecisionsLog:
    """Filesystem helpers for the team-sync decisions JSONL file."""

    def test_shared_decisions_path_resolves_under_charm_root(self, tmp_path: pathlib.Path) -> None:
        # Sibling of the SQLite ``.cantrip`` file, not nested inside it
        # (see ``shared_decisions_path`` docstring for why).
        assert shared_decisions_path(tmp_path) == tmp_path / ".cantrip-shared" / "decisions.jsonl"

    def test_works_when_dot_cantrip_is_a_file(self, tmp_path: pathlib.Path) -> None:
        """Production layout: ``.cantrip`` is the SQLite file.

        The shared decisions log still has to function.  The original
        spec path of ``.cantrip/shared/decisions.jsonl`` would collide
        with the SQLite file; the sibling-path convention removes the
        collision.
        """
        (tmp_path / ".cantrip").write_text("fake sqlite")
        d = Decision(type="t", choice="c")
        append_shared_decision(tmp_path, d)
        loaded = load_shared_decisions(tmp_path)
        assert [(x.type, x.choice) for x in loaded] == [("t", "c")]

    def test_append_creates_parent_dir_and_writes_json_line(self, tmp_path: pathlib.Path) -> None:
        d = Decision(
            type="substrate",
            choice="K8s",
            reason="containers",
            timestamp=datetime.datetime(2026, 4, 30, 12, 0, 0),
        )
        append_shared_decision(tmp_path, d)
        target = shared_decisions_path(tmp_path)
        assert target.is_file()
        line = target.read_text(encoding="utf-8").strip()
        import json

        payload = json.loads(line)
        assert payload == {
            "type": "substrate",
            "choice": "K8s",
            "reason": "containers",
            "timestamp": "2026-04-30T12:00:00",
        }

    def test_append_is_appendonly(self, tmp_path: pathlib.Path) -> None:
        for i in range(3):
            append_shared_decision(
                tmp_path,
                Decision(type="t", choice=f"c{i}"),
            )
        lines = shared_decisions_path(tmp_path).read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        assert "c0" in lines[0]
        assert "c2" in lines[2]

    def test_append_swallows_filesystem_error(
        self, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Make the target a directory so opening for append fails.
        target = shared_decisions_path(tmp_path)
        target.parent.mkdir(parents=True)
        target.mkdir()
        d = Decision(type="t", choice="c")
        # Best-effort: should not raise.
        append_shared_decision(tmp_path, d)

    def test_load_returns_empty_when_file_absent(self, tmp_path: pathlib.Path) -> None:
        assert load_shared_decisions(tmp_path) == []

    def test_load_round_trips_appended_entries(self, tmp_path: pathlib.Path) -> None:
        d1 = Decision(type="t1", choice="c1", reason="r1")
        d2 = Decision(type="t2", choice="c2")
        append_shared_decision(tmp_path, d1)
        append_shared_decision(tmp_path, d2)
        loaded = load_shared_decisions(tmp_path)
        assert [(d.type, d.choice, d.reason) for d in loaded] == [
            ("t1", "c1", "r1"),
            ("t2", "c2", None),
        ]
        assert all(d.source == "shared" for d in loaded)

    def test_load_skips_malformed_lines(self, tmp_path: pathlib.Path) -> None:
        target = shared_decisions_path(tmp_path)
        target.parent.mkdir(parents=True)
        target.write_text(
            "\n"  # blank line ignored
            "not json\n"
            '{"type": "ok", "choice": "yes"}\n'
            '"a string, not an object"\n'
            '{"choice": "missing-type"}\n'
            '{"type": "missing-choice"}\n',
            encoding="utf-8",
        )
        loaded = load_shared_decisions(tmp_path)
        assert [(d.type, d.choice) for d in loaded] == [("ok", "yes")]

    def test_load_falls_back_on_bad_timestamp(self, tmp_path: pathlib.Path) -> None:
        target = shared_decisions_path(tmp_path)
        target.parent.mkdir(parents=True)
        target.write_text(
            '{"type": "t", "choice": "c", "timestamp": "not-an-iso"}\n',
            encoding="utf-8",
        )
        loaded = load_shared_decisions(tmp_path)
        assert len(loaded) == 1
        # Timestamp falls back to "now" — just check it's a real datetime.
        assert isinstance(loaded[0].timestamp, datetime.datetime)


class TestTeamDecisionsWritesEnv:
    """``CANTRIP_TEAM_DECISIONS_WRITES`` is honoured with safe fallbacks."""

    def test_default_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cantrip.agent.state import _resolve_team_decisions_writes

        monkeypatch.delenv("CANTRIP_TEAM_DECISIONS_WRITES", raising=False)
        assert _resolve_team_decisions_writes() == "local"

    def test_shared_value_picked_up(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cantrip.agent.state import _resolve_team_decisions_writes

        monkeypatch.setenv("CANTRIP_TEAM_DECISIONS_WRITES", " SHARED ")
        assert _resolve_team_decisions_writes() == "shared"

    def test_invalid_value_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cantrip.agent.state import _resolve_team_decisions_writes

        monkeypatch.setenv("CANTRIP_TEAM_DECISIONS_WRITES", "ask")
        # ``ask`` is not a supported decisions mode — falls back to local.
        assert _resolve_team_decisions_writes() == "local"


class TestAddDecisionSharedDispatch:
    """``AgentState.add_decision`` writes to the shared log when configured."""

    def test_local_mode_does_not_write_shared_file(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("CANTRIP_TEAM_DECISIONS_WRITES", raising=False)
        state = AgentState(charm_path=tmp_path)
        state.add_decision("t", "c")
        assert not shared_decisions_path(tmp_path).exists()

    def test_shared_mode_writes_to_shared_file(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CANTRIP_TEAM_DECISIONS_WRITES", "shared")
        state = AgentState(charm_path=tmp_path)
        state.add_decision("substrate", "K8s", "containers")
        loaded = load_shared_decisions(tmp_path)
        assert [(d.type, d.choice, d.reason) for d in loaded] == [
            ("substrate", "K8s", "containers"),
        ]

    def test_shared_mode_without_charm_path_skips_silently(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CANTRIP_TEAM_DECISIONS_WRITES", "shared")
        state = AgentState(charm_path=None)
        state.add_decision("t", "c")  # Must not raise.
        assert state.decisions[0].source == "local"


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
            AgentTask(id="t2", title="Build", category=TaskCategory.BUILD, dependencies=["t1"]),
        ]
        state = snapshot_from_queue(
            tasks,
            active_subagent_count=0,
            max_concurrency=3,
            has_charm_path=True,
            has_dev_model=True,
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
