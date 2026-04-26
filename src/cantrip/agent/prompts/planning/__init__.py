"""Jinja2-rendered planner prompts.

The three templates in this package replace triple-quoted string constants
that used to live in ``cantrip.agent.planner``.  Keeping them as markdown
templates means the charm-building guidance baked into the planning LLM
calls can be edited without touching Python code, matches the approach
already used for ``system.md.j2``, and keeps ``planner.py`` focused on
control flow rather than domain knowledge.
"""

import pathlib
from typing import Any

_TEMPLATE_DIR = pathlib.Path(__file__).parent

# Jinja2 environment is loaded lazily to avoid import-time I/O; callers
# of ``planner.py`` may never hit the LLM path at all.
_JINJA_ENV: Any = None
_FULL_TEMPLATE: Any = None
_DESIGN_TO_BUILD_TEMPLATE: Any = None
_DAY2_TO_BUILD_TEMPLATE: Any = None


def _get_env() -> Any:
    """Return the shared Jinja2 environment, creating it on first call."""
    global _JINJA_ENV  # noqa: PLW0603
    if _JINJA_ENV is None:
        import jinja2

        _JINJA_ENV = jinja2.Environment(
            loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
            keep_trailing_newline=True,
            undefined=jinja2.StrictUndefined,
        )
    return _JINJA_ENV


def render_full(*, categories: str, context_block: str) -> str:
    """Render the main planning prompt (research → synthesis → confirm)."""
    global _FULL_TEMPLATE  # noqa: PLW0603
    if _FULL_TEMPLATE is None:
        _FULL_TEMPLATE = _get_env().get_template("full.md.j2")
    return _FULL_TEMPLATE.render(categories=categories, context_block=context_block)


def render_design_to_build(*, categories: str, context_block: str) -> str:
    """Render the prompt for generating build tasks from an approved design."""
    global _DESIGN_TO_BUILD_TEMPLATE  # noqa: PLW0603
    if _DESIGN_TO_BUILD_TEMPLATE is None:
        _DESIGN_TO_BUILD_TEMPLATE = _get_env().get_template("design_to_build.md.j2")
    return _DESIGN_TO_BUILD_TEMPLATE.render(categories=categories, context_block=context_block)


def render_day2_to_build(*, categories: str, context_block: str) -> str:
    """Render the prompt for generating tasks from an approved day-2 plan."""
    global _DAY2_TO_BUILD_TEMPLATE  # noqa: PLW0603
    if _DAY2_TO_BUILD_TEMPLATE is None:
        _DAY2_TO_BUILD_TEMPLATE = _get_env().get_template("day2_to_build.md.j2")
    return _DAY2_TO_BUILD_TEMPLATE.render(categories=categories, context_block=context_block)
