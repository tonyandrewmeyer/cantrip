"""Seed a .cantrip database for spread testing.

Usage: python seed_db.py <charm_directory>

Creates the directory if needed and populates it with a realistic
session database suitable for testing transcript export.
"""

import pathlib
import sys

# Ensure the project root is on sys.path so cantrip can be imported.
_project_root = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_project_root / "src"))

from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus  # noqa: E402
from cantrip.agent.state import AgentState  # noqa: E402
from cantrip.agent.store import SessionStore  # noqa: E402


def seed(charm_dir: pathlib.Path) -> None:
    """Populate a .cantrip database with test data."""
    charm_dir.mkdir(parents=True, exist_ok=True)
    db_path = charm_dir / ".cantrip"

    store = SessionStore(db_path)
    store.open()

    state = AgentState(
        charm_name="spread-test-charm",
        charm_path=charm_dir,
        charm_type="k8s",
        framework="ops",
    )
    store.save_session(state)

    # Conversation messages.
    store.record_message("user", "Build a Redis charm for Kubernetes")
    store.record_message("assistant", "I will research Redis and build a charm.")
    store.record_message(
        "assistant",
        "",
        tool_calls=[
            {
                "id": "tc1",
                "name": "web_fetch",
                "arguments": {"url": "https://redis.io/docs/"},
            },
        ],
    )
    store.record_message(
        "tool",
        "",
        tool_results=[
            {
                "tool_call_id": "tc1",
                "content": "Redis documentation fetched.",
                "is_error": False,
            },
        ],
    )
    store.record_message("assistant", "Research complete. Proceeding to build.")

    # Tasks.
    tasks = [
        AgentTask(
            id="research",
            title="Research Redis",
            status=TaskStatus.DONE,
            category=TaskCategory.RESEARCH,
            description="Investigate Redis deployment patterns.",
            result="Redis supports RDB and AOF persistence.",
        ),
        AgentTask(
            id="build",
            title="Build the charm",
            status=TaskStatus.DONE,
            category=TaskCategory.BUILD,
            description="Scaffold and implement the charm.",
            result="Charm code written.",
        ),
        AgentTask(
            id="deploy",
            title="Deploy to dev model",
            status=TaskStatus.PENDING,
            category=TaskCategory.DEPLOY,
            description="Deploy the charm to a Juju model.",
        ),
    ]
    store.save_tasks(tasks)

    # Subagent messages.
    store.record_subagent_message("research", 0, "system", "You are an autonomous subagent.")
    store.record_subagent_message(
        "research", 1, "assistant", "Redis uses RDB snapshots for persistence."
    )

    # Events.
    store.record_event("task_started", {"task_id": "research"})
    store.record_event("task_completed", {"task_id": "research"})
    store.record_event("task_started", {"task_id": "build"})
    store.record_event("task_completed", {"task_id": "build"})

    # Token usage.
    store.record_usage("gemini", "gemini-2.0-flash", 1200, 400)

    store.close()
    print(f"Seeded {db_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <charm_directory>")
        sys.exit(1)
    seed(pathlib.Path(sys.argv[1]))
