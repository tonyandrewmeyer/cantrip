"""System prompt for the Cantrip agent."""

import pathlib
import re
from typing import Any

# Characters that could trigger Jinja2 template logic.
_JINJA_SYNTAX = re.compile(r"[{}%]")

_TEMPLATE_DIR = pathlib.Path(__file__).parent

# Jinja2 environment and templates are loaded lazily to avoid import-time I/O.
_JINJA_ENV: Any = None
_SYSTEM_TEMPLATE: Any = None
_COMPACT_TEMPLATE: Any = None
_DYNAMIC_TEMPLATE: Any = None


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


def _get_dynamic_template() -> Any:
    """Return the dynamic-context template, loading it on first call."""
    global _DYNAMIC_TEMPLATE  # noqa: PLW0603
    if _DYNAMIC_TEMPLATE is None:
        _DYNAMIC_TEMPLATE = _get_env().get_template("dynamic_context.md.j2")
    return _DYNAMIC_TEMPLATE


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
    memory_index: str | None = None,
    environment_ready: bool | None = None,
    watcher_enabled: bool | None = None,
    substrate: Any = None,
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
        memory_index: Pre-rendered Markdown listing available memories —
            global MEMORY.md contents plus charm-scope titles.  Bodies are
            loaded on demand via the ``memory_read`` tool to keep this
            section small.
        environment_ready: Whether the dev environment is fully provisioned.
        watcher_enabled: Whether the event-driven watcher is active.
        substrate: Phase 97.3 substrate summary (``preflight.SubstrateSummary``).
            Carries the controller list, active-cloud name, and the
            MicroCloud-detected / OpenStack-target hints.  ``None`` skips
            the section.

    The per-turn-volatile sections (the skills index and the repo map)
    live in :func:`build_dynamic_context` instead, so this prompt stays
    byte-stable across turns and the provider's prompt cache keeps
    hitting.  The cache is prefix-keyed, so any change here invalidates
    the whole cached system + message prefix.

    Returns:
        Complete system prompt with context.
    """

    def _sanitise(value: str | None) -> str | None:
        """Strip characters that could be interpreted as Jinja2 template syntax."""
        if value is None:
            return None
        return _JINJA_SYNTAX.sub("", value)

    # Sanitise every user-controlled string to prevent template injection.
    safe_decisions: list[dict] | None = None
    if recent_decisions:
        safe_decisions = [
            {k: _JINJA_SYNTAX.sub("", str(v)) for k, v in d.items()} for d in recent_decisions
        ]

    return _get_template(compact=compact).render(
        charm_name=_sanitise(charm_name),
        charm_path=_sanitise(charm_path),
        charm_type=_sanitise(charm_type),
        framework=_sanitise(framework),
        dev_model=_sanitise(dev_model),
        cos_model=_sanitise(cos_model),
        recent_decisions=safe_decisions,
        memory_index=_sanitise(memory_index),
        environment_ready=environment_ready,
        watcher_enabled=watcher_enabled,
        substrate=substrate,
    )


def build_dynamic_context(
    skills_index: str | None = None,
    repo_map: str | None = None,
) -> str | None:
    """Render the per-turn-volatile context block, or ``None`` when empty.

    The skills index (filtered by the files in play this turn) and the
    repo map (scaled by live context pressure) are recomputed every turn,
    so they must NOT sit in the cached system prompt — placing them there
    invalidates the whole prefix on each call.  Instead they are rendered
    here and appended to the conversation as a trailing ephemeral message
    (see ``CantripAgent._build_dynamic_context_message``), after the
    history cache breakpoint, so the static system + history prefix keeps
    caching and only this small tail is re-sent at full price.

    Args:
        skills_index: Pre-rendered XML listing the skills available to
            load this turn.
        repo_map: Pre-rendered, token-budgeted graph-ranked symbol view of
            the active charm repo.  ``None`` skips the section.

    Returns:
        The rendered Markdown block, or ``None`` when both inputs are empty.
    """
    if not skills_index and not repo_map:
        return None
    rendered = _get_dynamic_template().render(
        skills_index=skills_index,
        repo_map=repo_map,
    )
    return rendered.strip() or None
