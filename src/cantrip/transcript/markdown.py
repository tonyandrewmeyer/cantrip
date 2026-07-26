"""Markdown transcript formatter."""

import json

from cantrip.transcript import export as export_mod


def _fence_for(content: str) -> str:
    """Return a backtick fence long enough to wrap *content* safely.

    CommonMark requires the closing fence to be at least as long as
    the opening fence, so to embed content that itself contains runs
    of backticks (very common in LLM-generated tool output) the fence
    must be longer than the longest run inside.  Falls back to the
    standard triple fence when the content is fence-free.
    """
    longest = 0
    run = 0
    for ch in content:
        if ch == "`":
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return "`" * max(3, longest + 1)


def render_message(msg: dict, *, include_header: bool = True) -> str:
    """Render a single transcript message as Markdown.

    Used by the whole-transcript :func:`render_markdown` and by the
    ``/copy`` slash command (Phase 76) which puts one message on the
    clipboard.  Setting *include_header* to ``False`` drops the
    ``### ROLE (timestamp)`` heading -- ``/copy`` does this so a
    paste into a chat or PR description is just the body.
    """
    parts: list[str] = []
    if include_header:
        role = msg.get("role", "unknown").upper()
        ts = msg.get("timestamp", "")
        parts.append(f"### {role} ({ts})\n")
    if msg.get("content"):
        parts.append(msg["content"])
    for tc in msg.get("tool_calls") or []:
        args_json = json.dumps(tc.get("arguments", {}), indent=2)
        fence = _fence_for(args_json)
        parts.append(
            f"\n<details><summary>Tool: {tc.get('name', 'unknown')}"
            f"</summary>\n\n"
            f"{fence}json\n{args_json}\n{fence}\n"
            f"</details>"
        )
    for tr in msg.get("tool_results") or []:
        prefix = "Error" if tr.get("is_error") else "Result"
        body = str(tr.get("content", ""))
        fence = _fence_for(body)
        parts.append(
            f"\n<details><summary>{prefix}</summary>\n\n{fence}\n{body}\n{fence}\n</details>"
        )
    return "\n".join(parts)


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
            status = task.get("status", "unknown").upper()
            title = task.get("title", "untitled")
            category = task.get("category", "uncategorised")
            sections.append(f"- [{status}] **{title}** ({category})")

    # Conversation.
    sections.append("\n## Conversation\n")
    sections.extend(render_message(msg) for msg in data.messages)

    # Events.
    if data.events:
        sections.append("\n## Events\n")
        for event in data.events:
            ts = event.get("timestamp", "")
            detail_json = json.dumps(event.get("detail", {}))
            sections.append(f"- **{event.get('event_type', 'unknown')}** ({ts}): `{detail_json}`")

    return "\n".join(sections) + "\n"
