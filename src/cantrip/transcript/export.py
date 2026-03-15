"""Transcript export -- reads session data and dispatches to formatters."""

import dataclasses
import pathlib

from cantrip.agent import store as store_mod


@dataclasses.dataclass
class TranscriptData:
    """All session data needed for transcript rendering."""

    charm_name: str = ""
    charm_path: str = ""
    messages: list[dict] = dataclasses.field(default_factory=list)
    tasks: list[dict] = dataclasses.field(default_factory=list)
    subagent_messages: dict[str, list[dict]] = dataclasses.field(
        default_factory=dict,
    )
    events: list[dict] = dataclasses.field(default_factory=list)
    token_usage: dict[str, int] = dataclasses.field(default_factory=dict)


def load_transcript(db_path: pathlib.Path) -> TranscriptData:
    """Load all transcript data from a .cantrip SQLite file."""
    session_store = store_mod.SessionStore(db_path)
    session_store.open()
    try:
        data = TranscriptData()

        # Load session metadata.
        session = session_store.load_session()
        if session:
            data.charm_name = session.charm_name or ""
            data.charm_path = (
                str(session.charm_path) if session.charm_path else ""
            )

        # Load conversation messages.
        data.messages = session_store.load_messages()

        # Load tasks.
        tasks = session_store.load_tasks()
        data.tasks = [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status.value,
                "category": t.category.value,
                "description": t.description,
                "result": t.result,
            }
            for t in tasks
        ]

        # Load subagent messages grouped by task.
        for task in tasks:
            msgs = session_store.load_subagent_messages(task.id)
            if msgs:
                data.subagent_messages[task.id] = msgs

        # Load events.
        data.events = session_store.load_events()

        # Load token usage.
        data.token_usage = session_store.get_total_usage()

        return data
    finally:
        session_store.close()
