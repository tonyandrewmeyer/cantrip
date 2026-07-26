"""JSONL transcript formatter."""

import json

from cantrip.transcript import export as export_mod


def render_jsonl(data: export_mod.TranscriptData) -> str:
    """Render transcript data as newline-delimited JSON."""
    lines: list[str] = [
        json.dumps({"type": "message", **msg}, default=str) for msg in data.messages
    ]
    lines.extend(json.dumps({"type": "event", **event}, default=str) for event in data.events)
    lines.extend(json.dumps({"type": "task", **task}, default=str) for task in data.tasks)
    for msgs in data.subagent_messages.values():
        lines.extend(
            json.dumps(
                {"type": "subagent_message", **msg},
                default=str,
            )
            for msg in msgs
        )
    if not lines:
        return ""
    return "\n".join(lines) + "\n"
