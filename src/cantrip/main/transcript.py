"""``cantrip export-transcript`` handler."""

from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys


def _export_transcript(args: argparse.Namespace) -> int:
    """Export a session transcript."""
    charm_path = args.path.resolve()
    db_path = charm_path / ".cantrip"
    if not db_path.exists():
        print(f"Error: no .cantrip file found in {charm_path}")
        return 1

    from cantrip.transcript.export import load_transcript

    try:
        data = load_transcript(
            db_path,
            task_id=getattr(args, "filter_task", None),
            phase=getattr(args, "filter_phase", None),
            since=getattr(args, "filter_since", None),
            branch=getattr(args, "filter_branch", None),
        )
    except sqlite3.DatabaseError as exc:
        print(
            f"Error: {db_path} is not a valid Cantrip session file ({exc}).",
            file=sys.stderr,
        )
        return 1

    fmt = args.fmt
    page_size: int | None = getattr(args, "page_size", None)

    if fmt == "html" and page_size is not None and page_size > 0:
        from cantrip.transcript.html import render_html_paginated

        output_dir = (args.output or charm_path).resolve()
        if output_dir.suffix:
            # User gave a file path — use its parent as the output directory
            # and its stem as the filename prefix.
            stem = output_dir.stem
            output_dir = output_dir.parent
        else:
            stem = "transcript"
        pages = render_html_paginated(data, page_size, stem=stem)
        for filename, html in pages:
            filepath = output_dir / filename
            filepath.write_text(html)
        print(f"Transcript exported to {output_dir}/ ({len(pages)} pages)")
        return 0

    if fmt == "html":
        from cantrip.transcript.html import render_html

        content = render_html(data)
        suffix = ".html"
    elif fmt == "jsonl":
        from cantrip.transcript.jsonl import render_jsonl

        content = render_jsonl(data)
        suffix = ".jsonl"
    elif fmt == "markdown":
        from cantrip.transcript.markdown import render_markdown

        content = render_markdown(data)
        suffix = ".md"
    else:
        print(f"Error: unknown format {fmt}")
        return 1

    output = args.output or (charm_path / f"transcript{suffix}")
    pathlib.Path(output).write_text(content)
    print(f"Transcript exported to {output}")
    return 0
