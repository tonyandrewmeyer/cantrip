"""HTML transcript formatter."""

import pathlib

import jinja2

from cantrip.transcript import export as export_mod

_TEMPLATE_DIR = pathlib.Path(__file__).parent / "templates"

# Lazily loaded Jinja2 environment.
_env: jinja2.Environment | None = None


def _get_env() -> jinja2.Environment:
    """Return the Jinja2 environment, creating it on first call."""
    global _env  # noqa: PLW0603
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
