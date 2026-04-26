"""Jinja2-rendered task descriptions for deterministic planner paths.

The task-generator functions in ``cantrip.agent.planner`` used to build
multi-line ``AgentTask.description`` strings through f-strings with
embedded numbered steps, bolded CRITICAL notes, and free-form charm-
building guidance.  That guidance is exactly the kind of transferable
charming knowledge that belongs in markdown, not Python source —
editing it required opening a 1600-line planner module and navigating
around unrelated control flow.

Each template here renders one task description.  Callers supply the
per-task variables (workload, framework, design text, etc.) via
``render(name, **vars)``; the loader uses the same lazy-caching pattern
as ``prompts.system`` and ``prompts.planning``.

Trailing newlines are stripped (``keep_trailing_newline=False``) to
match the pre-extraction f-string behaviour — task descriptions never
ended with a final newline.
"""

import pathlib
from typing import Any

_TEMPLATE_DIR = pathlib.Path(__file__).parent

_JINJA_ENV: Any = None
_TEMPLATE_CACHE: dict[str, Any] = {}


def _get_env() -> Any:
    """Return the shared Jinja2 environment, creating it on first call."""
    global _JINJA_ENV  # noqa: PLW0603
    if _JINJA_ENV is None:
        import jinja2

        _JINJA_ENV = jinja2.Environment(
            loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
            keep_trailing_newline=False,
            undefined=jinja2.StrictUndefined,
        )
    return _JINJA_ENV


def render(name: str, **variables: Any) -> str:
    """Render the named task-description template with the given variables.

    Args:
        name: Template basename without the ``.md.j2`` suffix
            (e.g. ``"sprint_build"``).
        **variables: Values for the template's ``{{ ... }}`` placeholders.

    Returns:
        The rendered description with no trailing newline.
    """
    template = _TEMPLATE_CACHE.get(name)
    if template is None:
        template = _get_env().get_template(f"{name}.md.j2")
        _TEMPLATE_CACHE[name] = template
    return template.render(**variables)
