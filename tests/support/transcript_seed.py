"""Helpers for seeding transcript-export test fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cantrip.agent import queue, state, store

if TYPE_CHECKING:
    import pathlib


def seed_cli_export_session(charm_path: pathlib.Path) -> None:
    """Create a `.cantrip` file with enough data for transcript export tests."""
    db_path = charm_path / ".cantrip"
    session_store = store.SessionStore(db_path)
    session_store.open()

    agent_state = state.AgentState(
        charm_name="cli-test-charm",
        charm_path=charm_path,
        charm_type="k8s",
        framework="ops",
    )
    session_store.save_session(agent_state)

    session_store.record_message("user", "Build me a charm")
    session_store.record_message("assistant", "Sure, building your charm now.")
    session_store.record_message(
        "assistant",
        "",
        tool_calls=[
            {"id": "tc1", "name": "write_file", "arguments": {"path": "src/charm.py"}},
        ],
    )
    session_store.record_message(
        "tool",
        "",
        tool_results=[
            {"tool_call_id": "tc1", "content": "Written.", "is_error": False},
        ],
    )
    session_store.record_message("assistant", "Done!")

    tasks = [
        queue.AgentTask(
            id="research",
            title="Research workload",
            status=queue.TaskStatus.DONE,
            category=queue.TaskCategory.RESEARCH,
            result="Researched.",
        ),
        queue.AgentTask(
            id="build",
            title="Build charm",
            status=queue.TaskStatus.DONE,
            category=queue.TaskCategory.BUILD,
            result="Built.",
        ),
    ]
    session_store.save_tasks(tasks)

    session_store.record_subagent_message("research", 0, "system", "You are a subagent.")
    session_store.record_subagent_message("research", 1, "assistant", "Research complete.")

    session_store.record_event("task_started", {"task_id": "research"})
    session_store.record_event("task_completed", {"task_id": "research"})

    session_store.record_usage("gemini", "gemini-2.0-flash", 100, 50)
    session_store.close()
