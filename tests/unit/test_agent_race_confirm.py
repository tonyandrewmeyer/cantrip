"""Tests for ``CantripAgent.handle_race_confirmation``.

Targets ROADMAP 47.4 pre-race CONFIRM task resolution.  Uses
``FakeProvider`` and does not touch the filesystem beyond the
``tmp_path`` charm directory.
"""

from pathlib import Path

from cantrip.agent.core import CantripAgent
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.agent.race import RACE_CONFIRM_PREFIX
from tests.conftest import FakeProvider


def _agent(tmp_path: Path) -> CantripAgent:
    return CantripAgent(provider=FakeProvider(), charm_path=tmp_path)


def _queue_parent_and_confirm(
    agent: CantripAgent,
    parent_id: str,
    *,
    title: str = "Build the charm",
) -> tuple[AgentTask, AgentTask]:
    """Seed the work queue with a BLOCKED parent and its race-CONFIRM child."""
    parent = AgentTask(id=parent_id, title=title, category=TaskCategory.BUILD)
    agent.work_queue.add_task(parent)
    agent.work_queue.set_blocked(parent_id, "Awaiting race cost confirmation")
    confirm = AgentTask(
        id=f"{RACE_CONFIRM_PREFIX}{parent_id}",
        title=f"Confirm race for '{title}'",
        category=TaskCategory.CONFIRM,
        description="Proceed with race?",
        dependencies=[parent_id],
    )
    agent.work_queue.add_task(confirm)
    agent.work_queue.set_blocked(confirm.id, confirm.description)
    return parent, confirm


class TestHandleRaceConfirmation:
    def test_approved_flips_decision_and_unblocks_parent(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        parent, confirm = _queue_parent_and_confirm(agent, "p1")

        msg = agent.handle_race_confirmation(confirm.id, approved=True)

        assert parent.race_decision == "approved"
        assert agent.work_queue.get_task(parent.id).status == TaskStatus.PENDING
        assert agent.work_queue.get_task(confirm.id).status == TaskStatus.DONE
        assert "multiple models" in msg

    def test_declined_flips_decision_and_unblocks_parent(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        parent, confirm = _queue_parent_and_confirm(agent, "p2", title="Build again")

        msg = agent.handle_race_confirmation(confirm.id, approved=False)

        assert parent.race_decision == "declined"
        assert agent.work_queue.get_task(parent.id).status == TaskStatus.PENDING
        assert agent.work_queue.get_task(confirm.id).status == TaskStatus.DONE
        assert "single model" in msg

    def test_missing_parent_returns_graceful_message(self, tmp_path: Path) -> None:
        # Simulate a CONFIRM task that outlives its parent — the handler
        # should still resolve the CONFIRM rather than raising.
        agent = _agent(tmp_path)
        confirm_id = f"{RACE_CONFIRM_PREFIX}ghost"
        confirm = AgentTask(
            id=confirm_id,
            title="Confirm race for 'ghost'",
            category=TaskCategory.CONFIRM,
            description="Proceed with race?",
            dependencies=[],
        )
        agent.work_queue.add_task(confirm)
        agent.work_queue.set_blocked(confirm_id, confirm.description)

        msg = agent.handle_race_confirmation(confirm_id, approved=True)

        assert "ghost" in msg
        assert agent.work_queue.get_task(confirm_id).status == TaskStatus.DONE
