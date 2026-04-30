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
``pipx``, ``uv pip``, snap).  The pip-installed cases are
surfaced as ``uv pip`` invocations rather than bare ``pip`` to
match the project's uv-everywhere stance — ``uv pip`` reads the
same venv / ``--user`` site-packages as pip, so the upgrade
still lands in the right place even when the original install
used ``pip`` directly.

Failure-mode guarantee: every entry point degrades to ``None`` (or
:attr:`InstallMethod.UNKNOWN`) on error so a flaky network or a
missing PyPI metadata field can never crash startup or surface a
traceback to the user.  Failures log at DEBUG only.

This module is the foundation for ROADMAP Phase 63; subphases
63.2/63.4/63.5 build on :func:`check_for_update` and
:func:`detect_install_method`.

Module layout (Phase 85.7 split):

* ``types``    — :class:`UpdateInfo` and :class:`InstallMethod`.
* ``release``  — GitHub ``CHANGELOG.md`` fetch + ``## <version>``
  section extraction.
* ``check``    — opt-out / cache plumbing and the
  :func:`check_for_update` orchestrator.
* ``install``  — installer detection, upgrade-command rendering,
  and the CLI / slash notice formatters.

The ``httpx`` re-export below keeps existing test patches —
``mock.patch("cantrip.update.httpx.AsyncClient")`` — pointing at
the live module after the split, since modules are singletons.
"""

from __future__ import annotations

# Re-export ``httpx`` so existing test patches against
# ``cantrip.update.httpx.AsyncClient`` continue to land on the live
# httpx module (modules are singletons; patching here patches the
# import seen by both ``check`` and ``release``).
import httpx as httpx

# Submodule re-exports.  Redundant aliases mark these as intentional
# re-exports for ruff; tests reach for some of the private names
# (``_PYPI_URL``, ``_parse_yaml``-style implementation details) so
# they all surface here even when not in ``__all__``.
from cantrip.update.check import _CACHE_FILE_NAME as _CACHE_FILE_NAME
from cantrip.update.check import _DEFAULT_CACHE_DIR as _DEFAULT_CACHE_DIR
from cantrip.update.check import _PYPI_URL as _PYPI_URL
from cantrip.update.check import _SETTINGS_PATH as _SETTINGS_PATH
from cantrip.update.check import CACHE_DIR_ENV as CACHE_DIR_ENV
from cantrip.update.check import DEFAULT_CACHE_TTL_SECONDS as DEFAULT_CACHE_TTL_SECONDS
from cantrip.update.check import DISABLE_ENV as DISABLE_ENV
from cantrip.update.check import _cache_dir as _cache_dir
from cantrip.update.check import _cache_path as _cache_path
from cantrip.update.check import _CachedCheck as _CachedCheck
from cantrip.update.check import _extract_latest_and_timestamp as _extract_latest_and_timestamp
from cantrip.update.check import _fetch_and_extract_notes as _fetch_and_extract_notes
from cantrip.update.check import _is_truthy_env as _is_truthy_env
from cantrip.update.check import _is_version_yanked as _is_version_yanked
from cantrip.update.check import _make_info_if_newer as _make_info_if_newer
from cantrip.update.check import _read_cached_check as _read_cached_check
from cantrip.update.check import _release_timestamp as _release_timestamp
from cantrip.update.check import _settings_disabled as _settings_disabled
from cantrip.update.check import _write_cache as _write_cache
from cantrip.update.check import check_for_update as check_for_update
from cantrip.update.check import set_update_check_disabled as set_update_check_disabled
from cantrip.update.check import update_check_disabled as update_check_disabled
from cantrip.update.install import _UPGRADE_COMMANDS as _UPGRADE_COMMANDS
from cantrip.update.install import _headline as _headline
from cantrip.update.install import detect_install_method as detect_install_method
from cantrip.update.install import format_cli_notice as format_cli_notice
from cantrip.update.install import format_slash_notice as format_slash_notice
from cantrip.update.install import upgrade_command as upgrade_command
from cantrip.update.release import _CHANGELOG_URL_TEMPLATE as _CHANGELOG_URL_TEMPLATE
from cantrip.update.release import _DEFAULT_REPO_SLUG as _DEFAULT_REPO_SLUG
from cantrip.update.release import _RELEASE_NOTES_LINE_CAP as _RELEASE_NOTES_LINE_CAP
from cantrip.update.release import REPO_SLUG_ENV as REPO_SLUG_ENV
from cantrip.update.release import _changelog_url as _changelog_url
from cantrip.update.release import _format_release_notes as _format_release_notes
from cantrip.update.release import _normalise_section_version as _normalise_section_version
from cantrip.update.release import _repo_slug as _repo_slug
from cantrip.update.release import extract_release_notes as extract_release_notes
from cantrip.update.release import fetch_changelog as fetch_changelog
from cantrip.update.types import InstallMethod as InstallMethod
from cantrip.update.types import UpdateInfo as UpdateInfo

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
    "format_slash_notice",
    "set_update_check_disabled",
    "update_check_disabled",
    "upgrade_command",
]
