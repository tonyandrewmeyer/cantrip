"""``/export`` — write the live session transcript to a file.

Supports HTML, JSONL, and Markdown renderers.  The default output
path is ``<charm>/transcript.<ext>``; an explicit path overrides.
Lifted out of the dispatcher in Phase 85.3.
"""

from __future__ import annotations

import pathlib
import shlex
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cantrip.agent.commands.slash import SlashResult
    from cantrip.agent.core import CantripAgent


_EXPORT_FORMATS: dict[str, str] = {
    "html": ".html",
    "jsonl": ".jsonl",
    "markdown": ".md",
}


def export_transcript(agent: CantripAgent, args: str) -> str:
    """Export the live session transcript to a file.

    ``args`` is the whitespace-separated remainder of the slash command;
    a leading token matching an entry in :data:`_EXPORT_FORMATS` selects
    the format, and a trailing token is treated as the output path.  Any
    token that is neither is reported as an error so the user does not
    silently overwrite an unintended file.
    """
    charm_path: pathlib.Path | None = getattr(agent.state, "charm_path", None)
    if charm_path is None:
        return "_Cannot export: no charm path for this session._"
    db_path = charm_path / ".cantrip"
    if not db_path.exists():
        return f"_Cannot export: no `.cantrip` file at {charm_path}._"

    try:
        tokens = shlex.split(args)
    except ValueError as exc:
        return f"_Could not parse arguments: {exc}._"

    fmt = "html"
    output: pathlib.Path | None = None
    if tokens and tokens[0].lower() in _EXPORT_FORMATS:
        fmt = tokens.pop(0).lower()
    if tokens:
        output = pathlib.Path(tokens.pop(0)).expanduser()
    if tokens:
        return "_Usage: `/export [html|jsonl|markdown] [path]` — unexpected extra arguments._"

    suffix = _EXPORT_FORMATS[fmt]
    destination = output or (charm_path / f"transcript{suffix}")

    # Import lazily so the slash module stays importable in environments
    # where the transcript renderers' optional dependencies are unusual.
    from cantrip.transcript import export as transcript_export

    data = transcript_export.load_transcript(db_path)

    if fmt == "html":
        from cantrip.transcript.html import render_html

        content = render_html(data)
    elif fmt == "jsonl":
        from cantrip.transcript.jsonl import render_jsonl

        content = render_jsonl(data)
    else:
        from cantrip.transcript.markdown import render_markdown

        content = render_markdown(data)

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
    except OSError as exc:
        return f"_Failed to write {destination}: {exc}._"

    return f"Exported transcript ({fmt}) to `{destination}`."


def _handle_copy(agent: CantripAgent, args: str) -> SlashResult:
    """Copy a single chat message to the system clipboard (Phase 76).

    With no argument, picks the most recent assistant message.
    With ``last`` (any role), picks the most recent message regardless
    of role.  With a positive integer ``N``, picks the N-th message in
    1-based session order (useful when the user can see the index in
    an export but not in the live chat -- ``/export markdown`` to
    cross-reference).

    Returns a :class:`SlashResult` whose ``text`` is a one-line
    confirmation and whose ``clipboard_text`` carries the rendered
    Markdown for the surface to put on the user's clipboard.  Falls
    back to embedding the body in ``text`` when copy is not viable
    (no charm path, no messages) so the user still sees an
    actionable response.
    """
    from cantrip.agent.commands.slash import SlashResult

    charm_path: pathlib.Path | None = getattr(agent.state, "charm_path", None)
    if charm_path is None:
        return SlashResult(text="_Cannot copy: no charm path for this session._")
    db_path = charm_path / ".cantrip"
    if not db_path.exists():
        return SlashResult(text=f"_Cannot copy: no `.cantrip` file at {charm_path}._")

    # Lazy import: keeps the slash module importable even when the
    # transcript renderers' optional deps are unusual.
    from cantrip.transcript import export as transcript_export
    from cantrip.transcript.markdown import render_message

    data = transcript_export.load_transcript(db_path)
    messages = data.messages
    if not messages:
        return SlashResult(text="_Nothing to copy: this session has no messages yet._")

    selector = args.strip().lower()
    target: dict | None = None
    label: str
    if selector in ("", "assistant"):
        target = next(
            (m for m in reversed(messages) if (m.get("role") or "").lower() == "assistant"),
            None,
        )
        if target is None:
            # Fall back to the most recent message of any role rather
            # than refusing — when the agent's first turn errors out
            # before producing an assistant message, the user still
            # sees content on screen and reasonably expects /copy to
            # capture *something*.  The label makes the role explicit
            # so it's clear what landed on the clipboard.
            if selector == "assistant":
                return SlashResult(
                    text="_Nothing to copy: no assistant messages in this session yet._"
                )
            target = messages[-1]
            role = (target.get("role") or "message").lower()
            label = f"last {role} message (no assistant messages yet)"
        else:
            label = "last assistant message"
    elif selector == "last":
        target = messages[-1]
        role = (target.get("role") or "message").lower()
        label = f"last {role} message"
    else:
        try:
            index = int(selector)
        except ValueError:
            return SlashResult(
                text=(
                    "_Usage: `/copy` (last assistant message), `/copy last` "
                    "(last message of any role), or `/copy <N>` (1-based "
                    "message index)._"
                )
            )
        if index < 1 or index > len(messages):
            return SlashResult(
                text=f"_Cannot copy: message index {index} out of range (1..{len(messages)})._"
            )
        target = messages[index - 1]
        label = f"message #{index} ({(target.get('role') or 'unknown').lower()})"

    body = render_message(target, include_header=False).strip()
    if not body:
        return SlashResult(text=f"_Nothing to copy: the {label} has no body._")

    return SlashResult(
        text=f"Copied {label} to clipboard ({len(body)} chars).",
        clipboard_text=body,
    )


def _handle_share(agent: CantripAgent) -> SlashResult:
    """Dispatch the ``/share`` slash command.

    Returns an immediate "Uploading..." prelude plus a followup that
    exports the HTML transcript, uploads it as a secret gist via
    ``gh gist create``, and resolves to the gist URL.  When ``gh`` is
    unavailable we still want the user to have *something* useful —
    the followup writes the export locally and returns a
    copy-pasteable ``gh gist create`` command.
    """
    from cantrip.agent.commands.share import share_to_gist
    from cantrip.agent.commands.slash import SlashResult

    charm_path: pathlib.Path | None = getattr(agent.state, "charm_path", None)
    if charm_path is None:
        return SlashResult(text="_Cannot share: no charm path for this session._")
    db_path = charm_path / ".cantrip"
    if not db_path.exists():
        return SlashResult(text=f"_Cannot share: no `.cantrip` file at {charm_path}._")

    return SlashResult(
        text="Uploading session as a secret gist…",
        followup=share_to_gist(db_path, charm_path),
    )
