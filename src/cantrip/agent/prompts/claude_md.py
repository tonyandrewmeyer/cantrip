"""Render a CLAUDE.md file for a charm project."""

from pathlib import Path

import jinja2

_TEMPLATE_DIR = Path(__file__).parent
_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
    keep_trailing_newline=True,
    undefined=jinja2.StrictUndefined,
)
_TEMPLATE = _ENV.get_template("claude_md.md.j2")


def render_claude_md(charm_name: str, charm_type: str | None = None) -> str:
    """Render a CLAUDE.md tailored to a charm project.

    Args:
        charm_name: Name of the charm (used in Juju commands, etc.).
        charm_type: Type of charm — ``"machine"`` or ``"kubernetes"``.
            When *None*, the template includes guidance for both types.

    Returns:
        Rendered Markdown content.
    """
    return _TEMPLATE.render(charm_name=charm_name, charm_type=charm_type)
