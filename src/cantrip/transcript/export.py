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
    # Phase 52.5: step-level checkpoint rows grouped by task_id.  Each
    # inner dict carries step_name / ordinal / input_hash / kind /
    # created_at so the transcript viewer can show what's cached for
    # each task without decoding the blobs (blobs are on-demand via
    # ``cantrip checkpoints show``).
    checkpoints: dict[str, list[dict]] = dataclasses.field(default_factory=dict)
    # Phase 52.6: sum of tokens avoided via checkpoint replay over the
    # session's lifetime — ``{prompt_tokens, completion_tokens,
    # request_count}``.  Populated from the ``checkpoint_hit`` event
    # log so replayed turns show up in cost reports even though the
    # live provider call never fired.
    replay_savings: dict[str, int] = dataclasses.field(default_factory=dict)


# Task categories grouped into phases for --phase filtering.
_PHASE_CATEGORIES: dict[str, set[str]] = {
    "research": {"research", "confirm"},
    "build": {"build"},
    "deploy": {"deploy"},
    "test": {"test", "debug"},
}


def load_transcript(
    db_path: pathlib.Path,
    *,
    task_id: str | None = None,
    phase: str | None = None,
    since: str | None = None,
) -> TranscriptData:
    """Load transcript data from a .cantrip SQLite file.

    Optional filters narrow the export:

    *task_id* — include only the specified task and its subagent
    conversation (conversation-loop messages and events are still
    included for context).

    *phase* — include only tasks whose category belongs to the phase
    (``research``, ``build``, ``deploy``, ``test``).

    *since* — include only messages and events at or after the given
    ISO 8601 timestamp.
    """
    session_store = store_mod.SessionStore(db_path)
    session_store.open()
    try:
        data = TranscriptData()

        # Load session metadata.
        session = session_store.load_session()
        if session:
            data.charm_name = session.charm_name or ""
            data.charm_path = str(session.charm_path) if session.charm_path else ""

        # Load conversation messages, with optional time filter.
        all_messages = session_store.load_messages()
        if since:
            data.messages = [m for m in all_messages if str(m.get("timestamp", "")) >= since]
        else:
            data.messages = all_messages

        # Load tasks, with optional task_id / phase filter.
        tasks = session_store.load_tasks()
        allowed_categories: set[str] | None = None
        if phase:
            allowed_categories = _PHASE_CATEGORIES.get(phase, set())

        task_dicts = []
        for t in tasks:
            if task_id and t.id != task_id:
                continue
            if allowed_categories is not None and t.category.value not in allowed_categories:
                continue
            task_dicts.append(
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status.value,
                    "category": t.category.value,
                    "description": t.description,
                    "result": t.result,
                }
            )
        data.tasks = task_dicts

        # Load subagent messages only for included tasks.
        included_task_ids = {t["id"] for t in data.tasks}
        for task in tasks:
            if task.id not in included_task_ids:
                continue
            msgs = session_store.load_subagent_messages(task.id)
            if msgs:
                data.subagent_messages[task.id] = msgs

        # Load events, with optional time filter.
        data.events = session_store.load_events(since=since)

        # Load token usage.
        data.token_usage = session_store.get_total_usage()

        # Phase 52.6 — aggregate tokens replayed from checkpoints so
        # cost reports can show the savings alongside live usage.
        data.replay_savings = session_store.get_replay_savings()

        # Phase 52.5 — attach step checkpoints per included task so the
        # transcript viewer can show what's cached for a task without
        # having to re-open the database.  Blobs are excluded here; the
        # ``cantrip checkpoints show`` CLI decodes individual rows on
        # demand.
        for task in tasks:
            if task.id not in included_task_ids:
                continue
            rows = session_store.list_checkpoints_for_task(task.id)
            if not rows:
                continue
            data.checkpoints[task.id] = [
                {
                    "step_name": row["step_name"],
                    "ordinal": int(row["ordinal"]),
                    "input_hash": row["input_hash"],
                    "kind": row["result_kind"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]

        return data
    finally:
        session_store.close()
