"""The end-to-end ``is there an update?`` pipeline.

Combines the on-disk opt-out checks, the 24-hour disk cache, and the
PyPI JSON fetch into a single coroutine, :func:`check_for_update`.
Failure-mode guarantee: every entry point degrades to ``None`` on
error so a flaky network or a missing PyPI metadata field can never
crash startup or surface a traceback to the user.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import pathlib
import time

import httpx
from packaging import version as pkg_version

import cantrip
from cantrip.update.release import (
    _format_release_notes,
    extract_release_notes,
    fetch_changelog,
)
from cantrip.update.types import UpdateInfo

log = logging.getLogger(__name__)


# Public PyPI JSON endpoint for the ``juju-cantrip`` distribution.  The
# top-level URL (no ``/<version>/`` segment) returns ``info.version``
# pointing at the latest release plus a ``releases`` map keyed by
# version so we can extract upload timestamps without a second call.
_PYPI_URL = "https://pypi.org/pypi/juju-cantrip/json"

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
    """Return true when the env var or settings file opts out of the check."""
    if _is_truthy_env(os.environ.get(DISABLE_ENV)):
        return True
    return _settings_disabled()


def set_update_check_disabled(disabled: bool) -> pathlib.Path:
    """Persist the ``update_check_disabled`` flag in ``settings.json``.

    Returns the path that was written so callers can surface it in
    confirmation text.  Reads the current settings leniently (a
    malformed file is replaced rather than left in place — the
    user explicitly asked for a toggle, so the sensible thing is
    to write a clean file) and merges the single ``update_check_disabled``
    key so unrelated settings the user may have added are preserved.

    The write is best-effort but raises ``OSError`` on disk failure
    so the slash-command handler can surface the error verbatim —
    silently swallowing a permission denial would leave the user
    thinking their toggle took effect when it didn't.
    """
    path = _SETTINGS_PATH.expanduser()
    data: dict[str, object] = {}
    if path.is_file():
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            data = parsed
    data["update_check_disabled"] = bool(disabled)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write so an interrupted run (crash, Ctrl-C between
    # truncate and write) can't leave the user with no settings file
    # at all and silently discard unrelated keys they had added.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def _cache_dir() -> pathlib.Path:
    """Resolve the on-disk cache directory."""
    override = os.environ.get(CACHE_DIR_ENV)
    if override:
        return pathlib.Path(override).expanduser()
    return _DEFAULT_CACHE_DIR.expanduser()


def _cache_path() -> pathlib.Path:
    return _cache_dir() / _CACHE_FILE_NAME


@dataclasses.dataclass(frozen=True)
class _CachedCheck:
    """What we persist to ``~/.cache/cantrip/update.json``.

    Lives separately from :class:`UpdateInfo` because the cache is
    "what PyPI said last time", whereas ``UpdateInfo`` is "what the
    user should see now".  The version comparison runs at read time
    so upgrading naturally invalidates the verdict on next launch.
    """

    latest: str
    release_timestamp: str | None
    release_notes_markdown: str | None
    installed_yanked: bool


def _read_cached_check(now: float | None = None) -> _CachedCheck | None:
    """Return the cached check result, or None when missing / stale / corrupt.

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
    notes = data.get("release_notes_markdown")
    if notes is not None and not isinstance(notes, str):
        notes = None
    yanked = bool(data.get("installed_yanked", False))
    return _CachedCheck(
        latest=latest,
        release_timestamp=timestamp,
        release_notes_markdown=notes,
        installed_yanked=yanked,
    )


def _write_cache(
    latest: str,
    release_timestamp: str | None,
    *,
    release_notes_markdown: str | None = None,
    installed_yanked: bool = False,
) -> None:
    """Persist the latest-known PyPI verdict so the next startup short-circuits.

    Writes are best-effort: a permission failure on ``~/.cache/`` is
    not interesting enough to surface and would only spam the
    startup path.  The check still works, it just pays for the
    network call every time.
    """
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "latest": latest,
            "release_timestamp": release_timestamp,
            "release_notes_markdown": release_notes_markdown,
            "installed_yanked": installed_yanked,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError as exc:
        log.debug("update cache write failed: %s", exc)


def _make_info_if_newer(
    current: str,
    latest: str,
    *,
    release_timestamp: str | None,
    release_notes_markdown: str | None = None,
    installed_yanked: bool = False,
) -> UpdateInfo | None:
    """Return :class:`UpdateInfo` when *latest* > *current*, else ``None``.

    Applies two filters before returning a hit:

    * **Version comparison.** ``packaging.version`` orders both PEP
      440 releases and pre-release tags so an out-of-order PyPI
      response can't surface a downgrade nag.
    * **Pre-release filter.** A user on a stable release (``1.0.0``)
      is not nagged about an upcoming pre-release (``1.1.0rc1``).
      Users *already on* a pre-release see other pre-releases —
      they've opted into the bleeding edge by installing one.
    """
    try:
        latest_parsed = pkg_version.parse(latest)
        current_parsed = pkg_version.parse(current)
    except pkg_version.InvalidVersion:
        return None
    if latest_parsed <= current_parsed:
        return None
    # Pre-release filter: only nag stable users about stable releases.
    if latest_parsed.is_prerelease and not current_parsed.is_prerelease:
        return None
    return UpdateInfo(
        current=current,
        latest=latest,
        pypi_url=f"https://pypi.org/project/juju-cantrip/{latest}/",
        release_timestamp=release_timestamp,
        release_notes_markdown=release_notes_markdown,
        installed_yanked=installed_yanked,
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


def _is_version_yanked(payload: object, version_str: str) -> bool:
    """Return True when any file of *version_str* is marked yanked on PyPI.

    PyPI's per-file ``yanked`` flag is a single bool; the per-version
    array can mix yanked and unyanked files (rare in practice — usually
    every file for a release is yanked together).  We treat *any*
    yanked file as "this release was yanked" because once one wheel is
    pulled the release shouldn't be relied on, regardless of whether a
    sibling sdist survives.

    Returns False when the version isn't in ``releases`` at all
    (editable installs, dev versions, releases predating PyPI's yank
    metadata).  A missing version isn't a yank — it's a no-op.
    """
    if not isinstance(payload, dict):
        return False
    releases = payload.get("releases")
    if not isinstance(releases, dict):
        return False
    files = releases.get(version_str)
    if not isinstance(files, list) or not files:
        return False
    return any(isinstance(f, dict) and bool(f.get("yanked")) for f in files)


async def check_for_update(
    *,
    timeout: float = 3.0,
    use_cache: bool = True,
    include_release_notes: bool = True,
) -> UpdateInfo | None:
    """Return :class:`UpdateInfo` if PyPI has a newer ``juju-cantrip`` release.

    Returns ``None`` when:

    - The user has opted out (env var or settings file).
    - A fresh cache entry says we're already on the latest release.
    - The network call fails (HTTP error, DNS failure, timeout,
      JSON parse failure) — failures never propagate, only log at
      DEBUG.
    - The installed version is at or above the PyPI ``info.version``.
    - The newest PyPI release is a pre-release and the user is on a
      stable release (the pre-release filter from subphase 63.6).

    Pass ``use_cache=False`` to bypass the disk cache entirely; the
    ``/update`` slash command in subphase 63.5 will use this path so
    a user who just upgraded can confirm the new version is live.
    Pass ``include_release_notes=False`` to skip the secondary
    GitHub fetch when only the version comparison is needed (the
    Web ``/api/update-status`` endpoint may want this for a leaner
    payload, for example).
    """
    if update_check_disabled():
        return None

    current = cantrip.__version__

    if use_cache:
        cached = _read_cached_check()
        if cached is not None:
            return _make_info_if_newer(
                current,
                cached.latest,
                release_timestamp=cached.release_timestamp,
                release_notes_markdown=cached.release_notes_markdown,
                installed_yanked=cached.installed_yanked,
            )

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
    yanked = _is_version_yanked(payload, current)

    notes_markdown: str | None = None
    if include_release_notes:
        notes_markdown = await _fetch_and_extract_notes(
            current=current,
            latest=latest,
            timeout=timeout,
        )

    _write_cache(
        latest,
        timestamp,
        release_notes_markdown=notes_markdown,
        installed_yanked=yanked,
    )
    return _make_info_if_newer(
        current,
        latest,
        release_timestamp=timestamp,
        release_notes_markdown=notes_markdown,
        installed_yanked=yanked,
    )


async def _fetch_and_extract_notes(
    *,
    current: str,
    latest: str,
    timeout: float,
) -> str | None:
    """Fetch the changelog at ``v{latest}`` and slice out the relevant range.

    Returns the formatted markdown blob (newest-first) or ``None``
    when the changelog couldn't be fetched or contained no usable
    sections in the (current, latest] range.
    """
    raw = await fetch_changelog(latest, timeout=timeout)
    if raw is None:
        return None
    sections = extract_release_notes(raw, current=current, latest=latest)
    return _format_release_notes(sections)
