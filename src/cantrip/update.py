"""Background PyPI version-check and installer detection.

Helpers for the eventual "a newer Cantrip is available" notice in
the TUI, Web, and CLI front-ends.  The check fires in the
background at startup, hits PyPI's JSON API, and caches the result
on disk for 24 hours so the day-to-day startup path doesn't pay for
a network round-trip.

Two opt-outs are honoured by every caller:

- ``CANTRIP_NO_UPDATE_CHECK=1`` — env-var fast path for shell
  scripts and CI.  Any truthy value (``1``, ``true``, ``yes``,
  ``on``) disables the check.
- ``update_check_disabled = true`` in
  ``~/.config/cantrip/settings.json`` — persists across sessions
  for users on corporate networks that block ``pypi.org``.

Also exposes :func:`detect_install_method` and
:func:`upgrade_command` so the user-facing notice can show the
exact command to run for the user's installer (``uv tool``,
``pipx``, ``pip``, snap).

Failure-mode guarantee: every entry point degrades to ``None`` (or
:attr:`InstallMethod.UNKNOWN`) on error so a flaky network or a
missing PyPI metadata field can never crash startup or surface a
traceback to the user.  Failures log at DEBUG only.

This module is the foundation for ROADMAP Phase 63; subphases
63.2/63.4/63.5 build on :func:`check_for_update` and
:func:`detect_install_method`.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import logging
import os
import pathlib
import sys
import time

import httpx
from packaging import version as pkg_version

import cantrip

log = logging.getLogger(__name__)


# Public PyPI JSON endpoint for the ``cantrip`` distribution.  The
# top-level URL (no ``/<version>/`` segment) returns ``info.version``
# pointing at the latest release plus a ``releases`` map keyed by
# version so we can extract upload timestamps without a second call.
_PYPI_URL = "https://pypi.org/pypi/cantrip/json"

# Cache location.  Mirrors the marketplace cache at
# ``~/.cache/cantrip/marketplaces/`` so users with one Cantrip cache
# directory keep all of its contents in one place.  The cache stores
# only the latest-known PyPI version (and its release timestamp); the
# comparison against the installed version happens at read time so
# upgrading to the latest release naturally invalidates the "newer
# version available" verdict on the next launch.
_DEFAULT_CACHE_DIR = pathlib.Path("~/.cache/cantrip")
_CACHE_FILE_NAME = "update.json"
CACHE_DIR_ENV = "CANTRIP_UPDATE_CACHE_DIR"

# 24 hours.  Matches the marketplace cache and the "once per day"
# expectation.  The TTL is checked against the file's mtime so the
# on-disk format stays minimal (no embedded timestamp field).
DEFAULT_CACHE_TTL_SECONDS = 24 * 60 * 60

# Skip-the-whole-thing env var — any truthy value disables the
# check.  Surfaced separately so the CLI can document it without
# importing the helper.
DISABLE_ENV = "CANTRIP_NO_UPDATE_CHECK"

# Optional settings file.  Read leniently: missing file or malformed
# JSON means "no opt-out".  A future settings module can replace
# this disk-poke without changing the helper's surface.
_SETTINGS_PATH = pathlib.Path("~/.config/cantrip/settings.json")


# ── Data classes ──────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class UpdateInfo:
    """A newer release of Cantrip is available on PyPI.

    ``release_timestamp`` is an ISO-8601 string when PyPI supplied
    one (it usually does), or ``None`` when the JSON payload omitted
    the ``releases`` map — the rest of the helper still works
    without it.
    """

    current: str
    latest: str
    pypi_url: str
    release_timestamp: str | None


class InstallMethod(enum.StrEnum):
    """How the running Cantrip was installed.

    Used to surface a copy-pasteable upgrade command tailored to the
    installer.  :attr:`UNKNOWN` is returned when nothing matches —
    callers should fall back to "visit the PyPI URL" rather than
    guessing, because the wrong upgrade command is worse than no
    command at all.
    """

    UV_TOOL = "uv-tool"
    PIPX = "pipx"
    PIP_USER = "pip-user"
    PIP_VENV = "pip-venv"
    SNAP = "snap"
    UNKNOWN = "unknown"


# ── Opt-out plumbing ──────────────────────────────────────────────


def _is_truthy_env(value: str | None) -> bool:
    """Return True for ``"1"`` / ``"true"`` / ``"yes"`` / ``"on"``."""
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _settings_disabled() -> bool:
    """Return True when ``settings.json`` opts out of update checks."""
    path = _SETTINGS_PATH.expanduser()
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A malformed settings file should not silently disable the
        # check — better to nag than to hide the upgrade prompt
        # behind a corrupted file.
        return False
    return bool(data.get("update_check_disabled"))


def update_check_disabled() -> bool:
    """True when the env var or settings file opts out of the check."""
    if _is_truthy_env(os.environ.get(DISABLE_ENV)):
        return True
    return _settings_disabled()


# ── Cache plumbing ────────────────────────────────────────────────


def _cache_dir() -> pathlib.Path:
    """Resolve the on-disk cache directory."""
    override = os.environ.get(CACHE_DIR_ENV)
    if override:
        return pathlib.Path(override).expanduser()
    return _DEFAULT_CACHE_DIR.expanduser()


def _cache_path() -> pathlib.Path:
    return _cache_dir() / _CACHE_FILE_NAME


def _read_cached_latest(now: float | None = None) -> tuple[str, str | None] | None:
    """Return ``(latest_version, release_timestamp)`` from cache, or None.

    ``None`` covers all the "no usable cache" cases: the file is
    missing, the mtime is outside the TTL window, the JSON is
    malformed, or the expected keys are absent.  The single shared
    return type spares callers from juggling sentinel values.
    """
    path = _cache_path()
    if not path.is_file():
        return None
    age = (now if now is not None else time.time()) - path.stat().st_mtime
    if age > DEFAULT_CACHE_TTL_SECONDS or age < 0:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    latest = data.get("latest")
    if not isinstance(latest, str):
        return None
    timestamp = data.get("release_timestamp")
    if timestamp is not None and not isinstance(timestamp, str):
        timestamp = None
    return latest, timestamp


def _write_cache(latest: str, release_timestamp: str | None) -> None:
    """Persist the latest-known PyPI version so the next startup short-circuits.

    Writes are best-effort: a permission failure on ``~/.cache/`` is
    not interesting enough to surface and would only spam the
    startup path.  The check still works, it just pays for the
    network call every time.
    """
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"latest": latest, "release_timestamp": release_timestamp}
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError as exc:
        log.debug("update cache write failed: %s", exc)


# ── The check itself ──────────────────────────────────────────────


def _make_info_if_newer(
    current: str,
    latest: str,
    *,
    release_timestamp: str | None,
) -> UpdateInfo | None:
    """Return :class:`UpdateInfo` when *latest* > *current*, else ``None``.

    ``packaging.version`` parses both PEP 440 releases and pre-release
    tags so a user on ``1.2.0rc1`` is not nagged about ``1.2.0`` —
    that follow-up filter lives in subphase 63.6.
    """
    try:
        if pkg_version.parse(latest) <= pkg_version.parse(current):
            return None
    except pkg_version.InvalidVersion:
        return None
    return UpdateInfo(
        current=current,
        latest=latest,
        pypi_url=f"https://pypi.org/project/cantrip/{latest}/",
        release_timestamp=release_timestamp,
    )


def _extract_latest_and_timestamp(payload: object) -> tuple[str, str | None] | None:
    """Pull ``info.version`` and the matching upload timestamp out of *payload*.

    Returns ``None`` when the payload is shaped wrong — guards every
    field access individually so a future PyPI schema change can only
    silently degrade to "no update visible", never crash.
    """
    if not isinstance(payload, dict):
        return None
    info_block = payload.get("info")
    if not isinstance(info_block, dict):
        return None
    latest = info_block.get("version")
    if not isinstance(latest, str):
        return None
    return latest, _release_timestamp(payload, latest)


def _release_timestamp(payload: dict, version_str: str) -> str | None:
    """Return the upload-time of *version_str* from PyPI ``releases``.

    Picks the first file's ``upload_time_iso_8601`` (preferred) or
    ``upload_time``, or ``None`` if the field is missing.  PyPI
    omits ``releases`` from the per-version JSON endpoint; this
    only ever populates when the project root JSON is fetched.
    """
    releases = payload.get("releases")
    if not isinstance(releases, dict):
        return None
    files = releases.get(version_str)
    if not isinstance(files, list) or not files:
        return None
    first = files[0]
    if not isinstance(first, dict):
        return None
    timestamp = first.get("upload_time_iso_8601") or first.get("upload_time")
    return timestamp if isinstance(timestamp, str) else None


async def check_for_update(
    *,
    timeout: float = 3.0,
    use_cache: bool = True,
) -> UpdateInfo | None:
    """Return :class:`UpdateInfo` if PyPI has a newer ``cantrip`` release.

    Returns ``None`` when:

    - The user has opted out (env var or settings file).
    - A fresh cache entry says we're already on the latest release.
    - The network call fails (HTTP error, DNS failure, timeout,
      JSON parse failure) — failures never propagate, only log at
      DEBUG.
    - The installed version is at or above the PyPI ``info.version``.

    Pass ``use_cache=False`` to bypass the disk cache entirely; the
    ``/update`` slash command in subphase 63.5 will use this path so
    a user who just upgraded can confirm the new version is live.
    """
    if update_check_disabled():
        return None

    current = cantrip.__version__

    if use_cache:
        cached = _read_cached_latest()
        if cached is not None:
            latest, timestamp = cached
            return _make_info_if_newer(current, latest, release_timestamp=timestamp)

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": f"Cantrip/{current}"},
        ) as client:
            response = await client.get(_PYPI_URL)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.debug("PyPI version-check failed: %s", exc)
        return None

    extracted = _extract_latest_and_timestamp(payload)
    if extracted is None:
        return None
    latest, timestamp = extracted
    _write_cache(latest, timestamp)
    return _make_info_if_newer(current, latest, release_timestamp=timestamp)


# ── Installer detection ───────────────────────────────────────────


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

    # uv tool: ``~/.local/share/uv/tools/cantrip/bin/python`` and
    # variants under ``/share/uv/tools/`` for system installs.
    if "/.local/share/uv/" in text or "/share/uv/tools/" in text:
        return InstallMethod.UV_TOOL

    # pipx: ``~/.local/pipx/venvs/cantrip/bin/python`` — pipx may
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
    InstallMethod.UV_TOOL: "uv tool upgrade cantrip",
    InstallMethod.PIPX: "pipx upgrade cantrip",
    InstallMethod.PIP_USER: "pip install --user --upgrade cantrip",
    InstallMethod.PIP_VENV: "pip install --upgrade cantrip",
    InstallMethod.SNAP: "snap refresh cantrip",
}


def upgrade_command(method: InstallMethod | None = None) -> str | None:
    """Return a copy-pasteable upgrade command for *method*.

    ``None`` (or :attr:`InstallMethod.UNKNOWN`) returns ``None`` so
    callers can fall back to "visit https://pypi.org/project/cantrip/"
    rather than print a misleading command.
    """
    if method is None:
        method = detect_install_method()
    return _UPGRADE_COMMANDS.get(method)


__all__ = [
    "CACHE_DIR_ENV",
    "DEFAULT_CACHE_TTL_SECONDS",
    "DISABLE_ENV",
    "InstallMethod",
    "UpdateInfo",
    "check_for_update",
    "detect_install_method",
    "update_check_disabled",
    "upgrade_command",
]
