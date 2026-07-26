"""Workshop-environment system-prompt injection.

When Cantrip runs inside a Canonical Workshop sandbox, the Cantrip SDK's
``setup-project`` hook seeds ``~/.config/cantrip/workshop-prompt.md`` with
environment-specific guidance (container constraints, persistent mount
locations, remote-controller-first Juju model, …).  This module exposes the
file's content so the system prompt can include it when present.

The probe is cached at module load: the file is small, but
``_build_system_prompt`` is hot and we don't want a syscall on every turn.
If the user edits the file they can restart Cantrip to pick up the change —
the same pattern as ``~/.config/cantrip/settings.json``.
"""

import pathlib

_WORKSHOP_PROMPT_PATH = pathlib.Path("~/.config/cantrip/workshop-prompt.md").expanduser()


class _Sentinel:
    """Type for the "not yet probed" cache value."""


_MISSING = _Sentinel()
_cached: str | _Sentinel | None = _MISSING


def workshop_prompt_text() -> str | None:
    """Return the workshop environment prompt text, or ``None`` when absent.

    The file is read from ``~/.config/cantrip/workshop-prompt.md``.  Inside a
    Workshop sandbox the path is a persistent mount declared by the Cantrip
    SDK and seeded by ``setup-project``.  Outside a Workshop the file
    normally does not exist and we return ``None``.

    Cached on first call.
    """
    global _cached
    if isinstance(_cached, _Sentinel):
        try:
            _cached = _WORKSHOP_PROMPT_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            _cached = None
        except OSError:
            # Unreadable mount (permissions, broken symlink) is not a fatal
            # error — degrade to "no workshop prompt" and continue.
            _cached = None
    return _cached


def reset_cache() -> None:
    """Reset the cached probe — for tests only."""
    global _cached
    _cached = _MISSING
