"""Prompt renderer for the memory auto-writer (Phase 43.2)."""

from __future__ import annotations

import pathlib
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cantrip.agent.memory.writer import WriteMemoryContext

# Characters that could trigger Jinja2 template logic in user-controlled
# strings.  Matches the sanitisation approach in ``system.py``.
_JINJA_SYNTAX = re.compile(r"[{}%]")

_TEMPLATE_DIR = pathlib.Path(__file__).parent

_JINJA_ENV: Any = None
_WRITER_TEMPLATE: Any = None


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


def _get_template() -> Any:
    """Return the writer template, loading it on first call."""
    global _WRITER_TEMPLATE  # noqa: PLW0603
    if _WRITER_TEMPLATE is None:
        _WRITER_TEMPLATE = _get_env().get_template("memory_writer.md.j2")
    return _WRITER_TEMPLATE


def _sanitise(value: str | None) -> str | None:
    """Strip Jinja-significant characters from a user-controlled string."""
    if value is None:
        return None
    return _JINJA_SYNTAX.sub("", value)


def render_memory_writer_prompt(context: WriteMemoryContext) -> str:
    """Render the auto-writer prompt for the given trigger context."""
    cited = [str(path) for path in context.cited_paths]
    return _get_template().render(
        trigger=context.trigger.value,
        summary=_sanitise(context.summary) or "",
        detail=_sanitise(context.detail) or "",
        cited_paths=cited,
        charm_name=_sanitise(context.charm_name),
        charm_path=_sanitise(str(context.charm_path) if context.charm_path else None),
        framework=_sanitise(context.framework),
    )


__all__ = ["render_memory_writer_prompt"]
