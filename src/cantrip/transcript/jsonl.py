"""JSONL transcript formatter."""

import json

from cantrip.transcript import export as export_mod


def render_jsonl(data: export_mod.TranscriptData) -> str:
    """Render transcript data as newline-delimited JSON."""
    lines: list[str] = []
    for msg in data.messages:
        lines.append(json.dumps({"type": "message", **msg}, default=str))
    for event in data.events:
        lines.append(json.dumps({"type": "event", **event}, default=str))
    for task in data.tasks:
        lines.append(json.dumps({"type": "task", **task}, default=str))
    for _task_id, msgs in data.subagent_messages.items():
        for msg in msgs:
            lines.append(
                json.dumps(
                    {"type": "subagent_message", **msg}, default=str,
                )
            )
    if not lines:
        return ""
    return "\n".join(lines) + "\n"
