"""``/map`` and ``/map-refresh`` — graph-ranked repository symbol map.

Phase 71.1 introduced the repo map; the slash surface offers a compact
default view plus a verbose ``full`` switch.  Lifted out of the
dispatcher in Phase 85.3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cantrip import diagnostics

if TYPE_CHECKING:
    from cantrip.agent.core import CantripAgent


def _format_response(
    headline: str,
    rendered: str,
    file_count: int,
    *,
    shown_count: int | None = None,
    footer_hint: str | None = None,
    fenced: bool = True,
) -> str:
    """Build a Markdown-formatted response for the /map family.

    The dispatcher returns this with ``markdown=True`` so the chat
    surface renders the bold header, fenced code block (when
    ``fenced=True``), and inline code spans as formatting rather
    than literal characters.

    ``fenced=False`` skips the triple-backtick wrapper so a body
    that already contains its own Markdown structure (per-file
    headings, bullet lists) renders with visible landmarks all the
    way down — important for ``/map full``, where a single fenced
    block scrolls past the viewport and looks unformatted to the
    user.

    ``shown_count`` and ``footer_hint`` produce a "showing N of M
    files; use /map full for the rest" footer when the response is a
    summary view.
    """
    if shown_count is not None and shown_count < file_count:
        header = f"**{headline}** (showing {shown_count} of {file_count} files)"
    else:
        header = f"**{headline}** ({file_count} files)"
    body = f"{header}\n\n```\n{rendered}\n```" if fenced else f"{header}\n\n{rendered}"
    if footer_hint:
        body += f"\n\n{footer_hint}"
    return body


def _wants_full(args: str) -> bool:
    """``/map full`` (or ``/map -v``, ``/map all``) opts in to the wall-of-text view."""
    return args.strip().lower() in {"full", "-v", "--verbose", "all"}


def handle_map(agent: CantripAgent, args: str = "") -> str:
    """``/map``: graph-ranked repository symbol map.

    Default output is a compact summary (top files with their
    primary symbol).  ``/map full`` prints the full per-file
    breakdown — useful for digging into a specific area but
    overwhelming as the default in a small chat panel.

    Any unexpected exception lands in the diagnostics log; the
    user sees a friendly notice with the log path so they can hand
    it to a developer.
    """
    rm = agent.repo_map
    if rm is None:
        return (
            "No repository map: this session has no active charm path.  "
            "Open a charm and try again, or set the path with the CLI."
        )
    try:
        rm.build()
        if _wants_full(args):
            rendered = rm.render_full_markdown()
            return _format_response(
                "Repository map",
                rendered,
                len(rm.rankings),
                fenced=False,
            )
        rendered = rm.render_summary()
    except Exception as exc:
        return diagnostics.report_internal_error("/map", exc)
    if not rendered:
        return (
            "Repository map is empty — no parseable Python or charm "
            "metadata found under the active charm path."
        )
    shown = rendered.count("\n") + 1
    footer = "Use `/map full` for the per-file symbol breakdown."
    return _format_response(
        "Repository map",
        rendered,
        len(rm.rankings),
        shown_count=shown,
        footer_hint=footer,
    )


def handle_map_refresh(agent: CantripAgent, args: str = "") -> str:
    """``/map-refresh``: discard the cache and reparse from scratch.

    Same compact-vs-full toggle as ``/map``.
    """
    rm = agent.repo_map
    if rm is None:
        return "No repository map: this session has no active charm path."
    try:
        rm.build(force=True)
        if _wants_full(args):
            rendered = rm.render_full_markdown()
            return _format_response(
                "Repository map rebuilt",
                rendered,
                len(rm.rankings),
                fenced=False,
            )
        rendered = rm.render_summary()
    except Exception as exc:
        return diagnostics.report_internal_error("/map-refresh", exc)
    if not rendered:
        return "Repository map rebuilt — no parseable files found under the active charm path."
    shown = rendered.count("\n") + 1
    footer = "Use `/map-refresh full` for the per-file symbol breakdown."
    return _format_response(
        "Repository map rebuilt",
        rendered,
        len(rm.rankings),
        shown_count=shown,
        footer_hint=footer,
    )
