"""Markdown transcript formatter."""

import json

from cantrip.transcript import export as export_mod


def render_markdown(data: export_mod.TranscriptData) -> str:
    """Render transcript data as Markdown."""
    sections: list[str] = []

    heading = "# Cantrip Transcript"
    if data.charm_name:
        heading += f" -- {data.charm_name}"
    sections.append(heading)

    if data.charm_path:
        sections.append(f"**Path:** {data.charm_path}")
    if data.token_usage:
        p = data.token_usage.get("prompt_tokens", 0)
        c = data.token_usage.get("completion_tokens", 0)
        sections.append(f"**Tokens:** {p} prompt + {c} completion")

    # Tasks.
    if data.tasks:
        sections.append("\n## Tasks\n")
        for task in data.tasks:
            status = task["status"].upper()
            sections.append(f"- [{status}] **{task['title']}** ({task['category']})")

    # Conversation.
    sections.append("\n## Conversation\n")
    for msg in data.messages:
        role = msg["role"].upper()
        ts = msg.get("timestamp", "")
        sections.append(f"### {role} ({ts})\n")
        if msg.get("content"):
            sections.append(msg["content"])
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                args_json = json.dumps(
                    tc.get("arguments", {}),
                    indent=2,
                )
                sections.append(
                    f"\n<details><summary>Tool: {tc['name']}"
                    f"</summary>\n\n"
                    f"```json\n{args_json}\n```\n"
                    f"</details>"
                )
        if msg.get("tool_results"):
            for tr in msg["tool_results"]:
                prefix = "Error" if tr.get("is_error") else "Result"
                sections.append(
                    f"\n<details><summary>{prefix}</summary>\n\n"
                    f"```\n{tr.get('content', '')}\n```\n"
                    f"</details>"
                )

    # Events.
    if data.events:
        sections.append("\n## Events\n")
        for event in data.events:
            ts = event.get("timestamp", "")
            detail_json = json.dumps(event.get("detail", {}))
            sections.append(f"- **{event['event_type']}** ({ts}): `{detail_json}`")

    return "\n".join(sections) + "\n"
