"""Tests for ``CantripAgent`` lifecycle helpers.

Covers ``start_executor`` / ``stop_executor``, ``build_resume_summary``,
``load_state`` restoration branches, MCP registry plumbing, the
``_on_mcp_elicitation`` bridge, and ``complete_mcp_elicitation``.
"""

import pathlib
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.agent.state import Decision
from cantrip.llm.base import Role
from cantrip.ui import events as ui_events
from tests.conftest import FakeProvider


def _agent(tmp_path: pathlib.Path | None = None) -> CantripAgent:
    return CantripAgent(provider=FakeProvider(), charm_path=tmp_path)


# ---------------------------------------------------------------------------
# start_executor / stop_executor
# ---------------------------------------------------------------------------


class TestExecutorLifecycle:
    """Executor start / stop plumbing."""

    def test_start_creates_executor_and_subscribes_callback(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        fake_executor = MagicMock()
        fake_executor.running = False

        with patch(
            "cantrip.agent.core.BackgroundExecutor",
            return_value=fake_executor,
        ) as cls:
            agent.start_executor()
        cls.assert_called_once()
        fake_executor.start.assert_called_once()
        assert agent._executor is fake_executor

    def test_start_max_concurrency_threaded_to_executor(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        with patch("cantrip.agent.core.BackgroundExecutor") as cls:
            cls.return_value.running = False
            agent.start_executor(max_concurrency=5)
        kwargs = cls.call_args.kwargs
        assert kwargs["max_concurrency"] == 5

    def test_start_is_noop_when_already_running(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        existing = MagicMock()
        existing.running = True
        agent._executor = existing
        with patch("cantrip.agent.core.BackgroundExecutor") as cls:
            agent.start_executor()
        cls.assert_not_called()

    def test_work_queue_publishes_to_bus_after_start(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        with patch("cantrip.agent.core.BackgroundExecutor") as cls:
            cls.return_value.running = False
            agent.start_executor()

        captured: list = []
        agent.event_bus.subscribe(ui_events.EventType.TASK_UPDATED, lambda e: captured.append(e))
        task = AgentTask(id="t1", title="do", category=TaskCategory.BUILD)
        # ``_on_task_changed`` was wired up by start_executor.
        agent.work_queue._on_task_changed(task)
        assert len(captured) == 1
        assert captured[0].payload["id"] == "t1"

    @pytest.mark.asyncio
    async def test_stop_executor_clears_reference(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        fake = MagicMock()
        fake.stop = AsyncMock()
        agent._executor = fake
        await agent.stop_executor()
        assert agent._executor is None

    @pytest.mark.asyncio
    async def test_stop_executor_noop_when_none(self) -> None:
        agent = _agent()
        await agent.stop_executor()  # must not raise


# ---------------------------------------------------------------------------
# build_resume_summary
# ---------------------------------------------------------------------------


class TestBuildResumeSummary:
    """Formatter that inlines prior session state as a system message."""

    def test_returns_none_when_state_is_empty(self) -> None:
        agent = _agent()
        assert agent.build_resume_summary() is None

    def test_summarises_charm_and_decisions(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        agent.state.charm_name = "my-charm"
        agent.state.charm_type = "k8s"
        agent.state.charm_path = tmp_path
        agent.state.framework = "paas"
        agent.state.dev_model = "dev"
        agent.state.cos_model = "cos"
        agent.state.decisions = [Decision(type="substrate", choice="k8s")]

        summary = agent.build_resume_summary()
        assert summary is not None
        assert "my-charm" in summary
        assert "k8s" in summary
        assert "paas" in summary
        assert "dev" in summary
        assert "substrate" in summary
        # Summary is appended to messages as a SYSTEM message.
        assert agent.state.messages[-1].role == Role.SYSTEM
        assert agent.state.messages[-1].content == summary

    def test_summarises_task_progress(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        agent.state.charm_name = "c"

        done_task = AgentTask(id="t1", title="Finished research", category=TaskCategory.RESEARCH)
        done_task.status = TaskStatus.DONE
        failed_task = AgentTask(id="t2", title="Broken build", category=TaskCategory.BUILD)
        failed_task.status = TaskStatus.FAILED
        pending_task = AgentTask(id="t3", title="Pending", category=TaskCategory.TEST)
        agent.work_queue.add_tasks([done_task, failed_task, pending_task])

        summary = agent.build_resume_summary()
        assert summary is not None
        assert "1 done" in summary
        assert "1 failed" in summary
        assert "1 pending" in summary
        assert "Finished research" in summary


# ---------------------------------------------------------------------------
# load_state — branches not covered by existing round-trip test
# ---------------------------------------------------------------------------


class TestLoadStateBranches:
    """load_state error-handling + message/task restoration."""

    def test_sqlite_error_clears_store(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        # Inject a broken store.
        broken = MagicMock()
        broken.load_session.side_effect = sqlite3.Error("corrupt")
        agent._store = broken
        agent._store_initialised = True
        assert agent.load_state() is False
        assert agent._store is None

    def test_restores_messages_and_resets_active_tasks(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)

        # Seed a previous session and save it.
        agent.state.charm_name = "prev"
        mid_flight = AgentTask(id="inflight", title="Building", category=TaskCategory.BUILD)
        mid_flight.status = TaskStatus.ACTIVE
        agent.work_queue.add_task(mid_flight)
        agent.save_state()
        # Record messages via the store (what _record_message does).
        assert agent._store is not None
        agent._store.record_message(role="user", content="old user message")
        agent._store.record_message(role="assistant", content="old assistant reply")

        # Fresh agent resumes.
        agent2 = _agent(tmp_path)
        assert agent2.load_state() is True
        assert agent2.state.charm_name == "prev"
        # Active task reset to pending on resume.
        restored = agent2.work_queue.get_task("inflight")
        assert restored is not None
        assert restored.status == TaskStatus.PENDING
        # Messages restored.
        roles = [m.role for m in agent2.state.messages]
        assert Role.USER in roles
        assert Role.ASSISTANT in roles

    def test_message_with_invalid_role_skipped(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        agent._ensure_store()
        store = agent._store
        assert store is not None
        loaded = MagicMock()
        loaded.charm_name = "n"
        loaded.charm_path = None
        loaded.charm_type = None
        loaded.framework = None
        loaded.dev_model = None
        loaded.cos_model = None
        loaded.decisions = []

        store.load_session = MagicMock(return_value=loaded)
        store.load_compaction_counters = MagicMock(return_value=(0, 0, False, False))
        store.load_active_branch = MagicMock(
            return_value=[
                {"role": "not_a_role", "content": "dropped"},
                {"role": "user", "content": ""},  # empty content dropped
                {"role": "user", "content": "keep"},
            ]
        )
        store.load_tasks = MagicMock(return_value=[])

        assert agent.load_state() is True
        kept = [m for m in agent.state.messages if m.content == "keep"]
        assert len(kept) == 1


# ---------------------------------------------------------------------------
# MCP registry plumbing
# ---------------------------------------------------------------------------


class TestMcpPlumbing:
    """``mcp_registry`` / ``mcp_marketplace_*`` / ``start_mcp`` / ``stop_mcp``."""

    def test_mcp_registry_is_lazy_and_cached(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        with (
            patch("cantrip.agent.core.load_mcp_configs", return_value=[]),
            patch(
                "cantrip.agent.core.MCPRegistry",
                return_value=MagicMock(),
            ) as cls,
        ):
            r1 = agent.mcp_registry
            r2 = agent.mcp_registry
        assert r1 is r2
        cls.assert_called_once()

    def test_mcp_marketplace_sources_cached(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        with patch(
            "cantrip.agent.core.load_marketplace_sources",
            return_value=[MagicMock(name="src")],
        ) as loader:
            one = agent.mcp_marketplace_sources
            two = agent.mcp_marketplace_sources
        loader.assert_called_once()
        assert one == two

    def test_mcp_marketplace_loader_is_lazy(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        with patch(
            "cantrip.agent.core.MarketplaceLoader",
            return_value=MagicMock(),
        ) as cls:
            a = agent.mcp_marketplace_loader
            b = agent.mcp_marketplace_loader
        assert a is b
        cls.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_mcp_idempotent(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        fake = MagicMock()
        fake.start_all = AsyncMock()
        agent._mcp_registry_cache = fake

        await agent.start_mcp()
        await agent.start_mcp()  # second call is a no-op
        fake.start_all.assert_awaited_once()
        fake.set_elicitation_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_mcp_noop_when_registry_uninitialised(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        agent._mcp_registry_cache = None
        await agent.stop_mcp()  # must not raise

    @pytest.mark.asyncio
    async def test_stop_mcp_calls_stop_all(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        fake = MagicMock()
        fake.stop_all = AsyncMock()
        agent._mcp_registry_cache = fake
        agent._mcp_started = True
        await agent.stop_mcp()
        fake.stop_all.assert_awaited_once()


# ---------------------------------------------------------------------------
# _on_mcp_elicitation + complete_mcp_elicitation
# ---------------------------------------------------------------------------


class TestMcpElicitation:
    """The elicitation request → event bus bridge."""

    def test_unknown_request_type_is_ignored(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        # Not an ElicitationRequest — bridge should short-circuit.
        captured: list = []
        agent.event_bus.subscribe(
            ui_events.EventType.MCP_ELICITATION_REQUEST,
            lambda e: captured.append(e),
        )
        agent._on_mcp_elicitation("not-a-request")
        assert captured == []

    def test_valid_request_published_to_bus(self, tmp_path: pathlib.Path) -> None:
        from cantrip.mcp.elicitation import ElicitationRequest

        agent = _agent(tmp_path)
        captured: list = []
        agent.event_bus.subscribe(
            ui_events.EventType.MCP_ELICITATION_REQUEST,
            lambda e: captured.append(e),
        )
        req = ElicitationRequest(
            request_id="r1",
            server_name="s",
            mode="form",
            message="Please confirm",
            requested_schema=None,
            url=None,
        )
        agent._on_mcp_elicitation(req)
        assert len(captured) == 1
        assert captured[0].payload["request_id"] == "r1"
        assert captured[0].payload["server_name"] == "s"

    def test_complete_without_registry_returns_false(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        agent._mcp_registry_cache = None
        assert agent.complete_mcp_elicitation("r1", "accept") is False

    def test_complete_forwards_to_registry(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        fake = MagicMock()
        fake.complete_elicitation.return_value = True
        agent._mcp_registry_cache = fake
        assert agent.complete_mcp_elicitation("r1", "accept", {"x": 1}) is True
        fake.complete_elicitation.assert_called_once_with("r1", "accept", {"x": 1})
