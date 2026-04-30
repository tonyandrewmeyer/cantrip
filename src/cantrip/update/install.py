"""Installer detection + per-installer upgrade-command rendering + notice text.

Once :func:`cantrip.update.check.check_for_update` returns a hit, the
front-end needs three things: which installer the user used (so the
prompt can name the right upgrade command), the command itself, and
formatted notice text for the CLI / slash-command surfaces.
"""

from __future__ import annotations

import pathlib
import sys

from cantrip.update.types import InstallMethod, UpdateInfo


def detect_install_method() -> InstallMethod:
    """Identify how the running ``cantrip`` was installed.

    Heuristics are ordered cheapest-first by string-match on
    ``sys.executable``.  Returns :attr:`InstallMethod.UNKNOWN` when
    nothing matches — an honest fall-through, not a guess, because
    the wrong upgrade command is worse than no command.
    """
    executable = pathlib.Path(sys.executable)
    text = str(executable)

    # Snap installs live under ``/snap/<name>/<rev>/...``.  Match the
    # path prefix rather than walking parts so a stray ``snap``
    # segment elsewhere in the path doesn't false-positive.
    if text.startswith("/snap/"):
        return InstallMethod.SNAP

    # uv tool: ``~/.local/share/uv/tools/juju-cantrip/bin/python`` and
    # variants under ``/share/uv/tools/`` for system installs.
    if "/.local/share/uv/" in text or "/share/uv/tools/" in text:
        return InstallMethod.UV_TOOL

    # pipx: ``~/.local/pipx/venvs/juju-cantrip/bin/python`` — pipx may
    # also live under ``~/.local/share/pipx/`` on newer installs.
    if "/.local/pipx/" in text or "/.local/share/pipx/" in text or "/pipx/venvs/" in text:
        return InstallMethod.PIPX

    home = str(pathlib.Path.home())

    # Generic venv: ``sys.prefix != sys.base_prefix`` is the most
    # reliable signal that the running interpreter is *some* venv.
    # Done before the ``~/.local/`` check so a venv created at
    # ``~/.local/share/myvenv/`` doesn't get tagged as a pip-user
    # install.
    if sys.prefix != sys.base_prefix:
        return InstallMethod.PIP_VENV

    # pip --user installs the executable into ``~/.local/bin/`` and
    # the package into ``~/.local/lib/python.../site-packages``.
    # When ``sys.prefix == sys.base_prefix`` (system Python) and the
    # executable is under the user's home, this is the most likely
    # explanation.
    if text.startswith(f"{home}/.local/"):
        return InstallMethod.PIP_USER

    return InstallMethod.UNKNOWN


_UPGRADE_COMMANDS: dict[InstallMethod, str] = {
    InstallMethod.UV_TOOL: "uv tool upgrade juju-cantrip",
    InstallMethod.PIPX: "pipx upgrade juju-cantrip",
    InstallMethod.PIP_USER: "uv pip install --user --upgrade juju-cantrip",
    InstallMethod.PIP_VENV: "uv pip install --upgrade juju-cantrip",
    InstallMethod.SNAP: "snap refresh cantrip",
}


def upgrade_command(method: InstallMethod | None = None) -> str | None:
    """Return a copy-pasteable upgrade command for *method*.

    ``None`` (or :attr:`InstallMethod.UNKNOWN`) returns ``None`` so
    callers can fall back to "visit https://pypi.org/project/juju-cantrip/"
    rather than print a misleading command.

    When *method* is None, the install method is resolved through
    ``cantrip.update.detect_install_method`` (the package re-export)
    rather than the local symbol so external monkey-patches at the
    ``cantrip.update`` level still influence this helper's behaviour
    after the Phase 85.7 module split.
    """
    if method is None:
        # Lazy package-level lookup so tests patching
        # ``cantrip.update.detect_install_method`` reach this internal
        # call.  Cheap once the package is loaded; the import inside
        # the function body avoids a module-load-time circular import
        # against ``cantrip.update.__init__``.
        from cantrip import update as _pkg

        method = _pkg.detect_install_method()
    return _UPGRADE_COMMANDS.get(method)


def _headline(info: UpdateInfo) -> str:
    """Return the top-of-notice line that matches the user's situation.

    Yanked-installed versions get a sharper tone because staying on a
    withdrawn release is riskier than missing a feature release.
    """
    if info.installed_yanked:
        return (
            f"Your installed juju-cantrip {info.current} has been yanked; "
            f"upgrading to {info.latest} is recommended."
        )
    return f"A newer juju-cantrip is available: {info.latest} (you have {info.current})."


def format_cli_notice(info: UpdateInfo, *, method: InstallMethod | None = None) -> str:
    """Return a compact two-line notice for the CLI's post-REPL print.

    Line 1: version headline plus the PyPI project URL.  Line 2: the
    installer-aware upgrade command, or a "visit PyPI" fallback when
    :func:`detect_install_method` returned :attr:`InstallMethod.UNKNOWN`.
    Scripts redirect stdout — keeping this short means piping
    ``cantrip --no-tui`` into a log still produces usable output.
    """
    command = upgrade_command(method)
    headline = f"{_headline(info)} See {info.pypi_url}"
    if command is None:
        return f"{headline}\nUpgrade via your usual installer; visit the URL for release notes."
    return f"{headline}\nRun `{command}` to upgrade."


def format_slash_notice(info: UpdateInfo, *, method: InstallMethod | None = None) -> str:
    """Return a markdown notice for the ``/update`` slash command.

    Unlike :func:`format_cli_notice` the output targets a chat
    renderer (TUI ``MessageWidget``, Web markdown-ish renderer, CLI
    ``print``) so the PyPI URL becomes a real markdown link and the
    upgrade command is fenced as ``code``.  Keeps both TUI and Web
    output tidy without each surface duplicating the formatting.
    """
    command = upgrade_command(method)
    headline = _headline(info)
    lines = [f"**{headline}**", f"Release page: <{info.pypi_url}>"]
    if command is not None:
        lines.append(f"Upgrade: `{command}`")
    else:
        lines.append("_Upgrade via your usual installer — visit the URL above._")
    lines.append(
        "_The running process still executes the old code; "
        "restart Cantrip after upgrading to pick up the new release._"
    )
    return "\n".join(lines)
