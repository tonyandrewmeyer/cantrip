"""HTML transcript formatter."""

import math
import pathlib

import jinja2

from cantrip.transcript import export as export_mod

_TEMPLATE_DIR = pathlib.Path(__file__).parent / "templates"

# Lazily loaded Jinja2 environment.
_env: jinja2.Environment | None = None


def _get_env() -> jinja2.Environment:
    """Return the Jinja2 environment, creating it on first call."""
    global _env
    if _env is None:
        _env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=True,
        )
    return _env


def render_html(data: export_mod.TranscriptData) -> str:
    """Render transcript data as a self-contained HTML page."""
    env = _get_env()
    template = env.get_template("transcript.html.j2")
    return template.render(
        charm_name=data.charm_name,
        charm_path=data.charm_path,
        messages=data.messages,
        tasks=data.tasks,
        subagent_messages=data.subagent_messages,
        events=data.events,
        token_usage=data.token_usage,
    )


def render_html_paginated(
    data: export_mod.TranscriptData,
    page_size: int,
    stem: str = "transcript",
) -> list[tuple[str, str]]:
    """Render transcript data as multiple HTML pages.

    Conversation messages are split into chunks of *page_size*.  Tasks
    and events appear on the first page only.  Each page includes
    previous/next navigation links.

    Returns a list of ``(filename, html_content)`` pairs.
    """
    total_messages = len(data.messages)
    total_pages = max(1, math.ceil(total_messages / page_size))
    env = _get_env()
    template = env.get_template("transcript.html.j2")

    pages: list[tuple[str, str]] = []
    for page_num in range(1, total_pages + 1):
        start = (page_num - 1) * page_size
        end = start + page_size
        page_messages = data.messages[start:end]

        # Tasks and events only on page 1.
        page_tasks = data.tasks if page_num == 1 else []
        page_subagent = data.subagent_messages if page_num == 1 else {}
        page_events = data.events if page_num == 1 else []

        prev_file = f"{stem}_{page_num - 1}.html" if page_num > 1 else ""
        next_file = f"{stem}_{page_num + 1}.html" if page_num < total_pages else ""

        html = template.render(
            charm_name=data.charm_name,
            charm_path=data.charm_path,
            messages=page_messages,
            tasks=page_tasks,
            subagent_messages=page_subagent,
            events=page_events,
            token_usage=data.token_usage,
            # Pagination context.
            page=page_num,
            total_pages=total_pages,
            prev_page=prev_file,
            next_page=next_file,
        )
        pages.append((f"{stem}_{page_num}.html", html))

    return pages
