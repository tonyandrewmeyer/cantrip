"""Render an AGENTS.md file for a charm project."""

import pathlib

import jinja2

_TEMPLATE_DIR = pathlib.Path(__file__).parent
_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
    keep_trailing_newline=True,
    undefined=jinja2.StrictUndefined,
)
_TEMPLATE = _ENV.get_template("agents_md.md.j2")


def render_agents_md(charm_name: str, charm_type: str | None = None) -> str:
    """Render an AGENTS.md tailored to a charm project.

    Args:
        charm_name: Name of the charm (used in Juju commands, etc.).
        charm_type: Type of charm — ``"machine"`` or ``"kubernetes"``.
            When *None*, the template includes guidance for both types.

    Returns:
        Rendered Markdown content.
    """
    return _TEMPLATE.render(charm_name=charm_name, charm_type=charm_type)
