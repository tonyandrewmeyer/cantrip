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

# Repo slug for fetching ``CHANGELOG.md`` at the matching tag.  An
# env-var override exists so tests don't hit the live GitHub raw
# endpoint.  The default mirrors the ``Repository`` field in
# ``pyproject.toml``.
_DEFAULT_REPO_SLUG = "tonyandrewmeyer/cantrip"
REPO_SLUG_ENV = "CANTRIP_UPDATE_REPO"
_CHANGELOG_URL_TEMPLATE = "https://raw.githubusercontent.com/{slug}/v{version}/CHANGELOG.md"

# Cap on the number of release-notes lines we keep in the cache so a
# pathological CHANGELOG can't bloat ``~/.cache/cantrip/update.json``
# beyond a few KB.  The UI layer applies its own (smaller) cap when
# rendering — this is just a safety net for the on-disk store.
_RELEASE_NOTES_LINE_CAP = 200

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

    ``release_notes_markdown`` is the concatenated ``## <version>``
    sections from the project's published ``CHANGELOG.md``, newest
    first, covering everything strictly between *current* and
    *latest*.  ``None`` when the changelog couldn't be fetched
    (untagged release, network failure) or no release notes were
    found between the two versions — the upgrade prompt should
    still surface the version number even when notes are absent.

    ``installed_yanked`` is True when PyPI has marked one or more
    files of the *currently installed* version as yanked.  The UI
    layer uses this to switch the prompt's tone from "an upgrade is
    available" to "your installed version has been yanked;
    upgrading is recommended".
    """

    current: str
    latest: str
    pypi_url: str
    release_timestamp: str | None
    release_notes_markdown: str | None = None
    installed_yanked: bool = False


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


# ── The check itself ──────────────────────────────────────────────


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
        pypi_url=f"https://pypi.org/project/cantrip/{latest}/",
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


# ── Changelog fetch and parse ─────────────────────────────────────


def _repo_slug() -> str:
    """Return the GitHub ``owner/repo`` slug for the changelog fetch."""
    return os.environ.get(REPO_SLUG_ENV) or _DEFAULT_REPO_SLUG


def _changelog_url(version: str) -> str:
    """Build the raw GitHub URL for ``CHANGELOG.md`` at the matching tag."""
    return _CHANGELOG_URL_TEMPLATE.format(slug=_repo_slug(), version=version)


async def fetch_changelog(version: str, *, timeout: float = 3.0) -> str | None:
    """Fetch the project's ``CHANGELOG.md`` at the ``v{version}`` tag.

    Returns the raw markdown body or ``None`` when:

    - The tag doesn't exist yet (a release landed on ``main`` but
      wasn't tagged — common for pre-releases).
    - The HTTP call fails for any reason (timeout, DNS, 404, parse).
    - The repo slug is missing or malformed.

    Failures log at DEBUG and never propagate so a slow GitHub can
    only suppress the inline release notes, never crash the check.
    """
    url = _changelog_url(version)
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": f"Cantrip/{cantrip.__version__}"},
        ) as client:
            response = await client.get(url)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.text
    except httpx.HTTPError as exc:
        log.debug("CHANGELOG fetch failed for %s: %s", version, exc)
        return None


def _normalise_section_version(heading_text: str) -> str | None:
    """Extract the version token from a ``## <version>`` heading body.

    The heading body may include trailers like ``— 2024-01-01`` or
    ``(2024-01-01)``; we keep only the leading token so it parses as
    a PEP 440 version.  Returns ``None`` when the leading token isn't
    a recognisable version (e.g. ``Unreleased``).
    """
    token = heading_text.strip().split()[0] if heading_text.strip() else ""
    # Strip a leading ``v`` so both ``## v1.0.0`` and ``## 1.0.0``
    # parse — some projects prefix every heading with ``v``.
    if token.startswith("v") or token.startswith("V"):
        token = token[1:]
    try:
        pkg_version.parse(token)
    except pkg_version.InvalidVersion:
        return None
    return token


def extract_release_notes(
    markdown: str,
    *,
    current: str,
    latest: str,
) -> list[tuple[str, str]]:
    """Return ``(version, body)`` sections strictly between *current* and *latest*.

    Walks ``## <version>`` headings line-by-line — no markdown-parser
    dependency.  ``## Unreleased`` (and any other unparseable heading
    body) is skipped: users upgrading to a tagged release shouldn't
    see post-release churn.

    Sections are returned newest-first.  The version range is
    ``current < section_version <= latest`` so the user sees notes
    for every release they're about to skip past, including the
    target itself.
    """
    try:
        current_parsed = pkg_version.parse(current)
        latest_parsed = pkg_version.parse(latest)
    except pkg_version.InvalidVersion:
        return []

    sections: list[tuple[str, list[str]]] = []
    current_section: tuple[str, list[str]] | None = None
    for line in markdown.splitlines():
        # Match exactly two leading hashes followed by a space — three
        # hashes is a subsection (``### Added``) which belongs in the
        # current section's body.
        if line.startswith("## ") and not line.startswith("### "):
            heading = line[3:]
            version = _normalise_section_version(heading)
            if version is None:
                # ``## Unreleased`` or any other non-version heading
                # ends the previous section without starting a new one.
                current_section = None
                continue
            current_section = (version, [])
            sections.append(current_section)
            continue
        if current_section is not None:
            current_section[1].append(line)

    relevant: list[tuple[str, str]] = []
    for version, body_lines in sections:
        try:
            section_parsed = pkg_version.parse(version)
        except pkg_version.InvalidVersion:
            continue
        if not (current_parsed < section_parsed <= latest_parsed):
            continue
        relevant.append((version, "\n".join(body_lines).strip("\n")))

    # Newest first.  ``packaging.version`` gives a total order, so
    # sorting by the parsed version is reliable across pre-releases.
    relevant.sort(key=lambda pair: pkg_version.parse(pair[0]), reverse=True)
    return relevant


def _format_release_notes(sections: list[tuple[str, str]]) -> str | None:
    """Stitch ``(version, body)`` sections back into one markdown blob.

    Returns ``None`` when the input is empty so the caller can store
    "no notes" as a real ``None`` in :class:`UpdateInfo` rather than
    an empty string that's awkward to test for.  Truncates to the
    cache-side line cap as a safety net against pathological
    changelogs; the UI layer applies its own (smaller) cap when
    rendering.
    """
    if not sections:
        return None
    blocks: list[str] = []
    for version, body in sections:
        blocks.append(f"## {version}\n\n{body}".rstrip())
    text = "\n\n".join(blocks)
    lines = text.splitlines()
    if len(lines) > _RELEASE_NOTES_LINE_CAP:
        truncated = lines[:_RELEASE_NOTES_LINE_CAP]
        truncated.append("")
        truncated.append(f"_… release notes truncated at {_RELEASE_NOTES_LINE_CAP} lines._")
        text = "\n".join(truncated)
    return text


async def check_for_update(
    *,
    timeout: float = 3.0,
    use_cache: bool = True,
    include_release_notes: bool = True,
) -> UpdateInfo | None:
    """Return :class:`UpdateInfo` if PyPI has a newer ``cantrip`` release.

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


# ── Notice rendering ──────────────────────────────────────────────


def _headline(info: UpdateInfo) -> str:
    """Return the top-of-notice line that matches the user's situation.

    Yanked-installed versions get a sharper tone because staying on a
    withdrawn release is riskier than missing a feature release.
    """
    if info.installed_yanked:
        return (
            f"Your installed cantrip {info.current} has been yanked; "
            f"upgrading to {info.latest} is recommended."
        )
    return f"A newer cantrip is available: {info.latest} (you have {info.current})."


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


__all__ = [
    "CACHE_DIR_ENV",
    "DEFAULT_CACHE_TTL_SECONDS",
    "DISABLE_ENV",
    "REPO_SLUG_ENV",
    "InstallMethod",
    "UpdateInfo",
    "check_for_update",
    "detect_install_method",
    "extract_release_notes",
    "fetch_changelog",
    "format_cli_notice",
    "update_check_disabled",
    "upgrade_command",
]
