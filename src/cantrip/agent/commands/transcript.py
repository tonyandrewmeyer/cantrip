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
