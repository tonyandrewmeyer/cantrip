"""System prompt for the Cantrip agent."""

from pathlib import Path
from typing import Any

_TEMPLATE_DIR = Path(__file__).parent

# Jinja2 environment and templates are loaded lazily to avoid import-time I/O.
_JINJA_ENV: Any = None
_SYSTEM_TEMPLATE: Any = None
_COMPACT_TEMPLATE: Any = None


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


def _get_template(*, compact: bool = False) -> Any:
    """Return the system prompt template, loading it on first call."""
    if compact:
        global _COMPACT_TEMPLATE  # noqa: PLW0603
        if _COMPACT_TEMPLATE is None:
            _COMPACT_TEMPLATE = _get_env().get_template("system_compact.md.j2")
        return _COMPACT_TEMPLATE

    global _SYSTEM_TEMPLATE  # noqa: PLW0603
    if _SYSTEM_TEMPLATE is None:
        _SYSTEM_TEMPLATE = _get_env().get_template("system.md.j2")
    return _SYSTEM_TEMPLATE


class _LazyPrompt:
    """Lazy string that renders the default system prompt on first access.

    Behaves like a str so that existing code (``len(SYSTEM_PROMPT)``,
    ``"x" in SYSTEM_PROMPT``, etc.) keeps working without change.
    """

    def __init__(self) -> None:
        self._value: str | None = None

    def _resolve(self) -> str:
        if self._value is None:
            self._value = build_system_prompt()
        return self._value

    def __str__(self) -> str:
        return self._resolve()

    def __repr__(self) -> str:
        return repr(self._resolve())

    def __contains__(self, item: str) -> bool:
        return item in self._resolve()

    def __len__(self) -> int:
        return len(self._resolve())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self._resolve() == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._resolve())


# Default prompt rendered lazily on first access.
SYSTEM_PROMPT: Any = _LazyPrompt()


def build_system_prompt(
    charm_name: str | None = None,
    charm_path: str | None = None,
    charm_type: str | None = None,
    framework: str | None = None,
    dev_model: str | None = None,
    cos_model: str | None = None,
    recent_decisions: list[dict] | None = None,
    skills_index: str | None = None,
    environment_ready: bool | None = None,
    watcher_enabled: bool | None = None,
    compact: bool = False,
) -> str:
    """Build the full system prompt with current context.

    Args:
        charm_name: Name of the current charm project.
        charm_path: Path to the charm directory.
        charm_type: Type of charm (machine or k8s).
        framework: Detected framework (flask, django, etc.).
        dev_model: Name of the development Juju model.
        cos_model: Name of the COS Juju model.
        recent_decisions: List of recent decisions made.
        skills_index: Pre-rendered XML listing available skills.
        environment_ready: Whether the dev environment is fully provisioned.
        watcher_enabled: Whether the event-driven watcher is active.

    Returns:
        Complete system prompt with context.
    """
    return _get_template(compact=compact).render(
        charm_name=charm_name,
        charm_path=charm_path,
        charm_type=charm_type,
        framework=framework,
        dev_model=dev_model,
        cos_model=cos_model,
        recent_decisions=recent_decisions,
        skills_index=skills_index,
        environment_ready=environment_ready,
        watcher_enabled=watcher_enabled,
    )
