"""Shared cache helpers for the Phase 70.1 Librarian tools.

Charmhub and Launchpad ``_fetch`` tools clone charm sources into a
single read-only cache rooted at ``~/.cache/cantrip/charm-library/``
so the Librarian subagent can grep across them with the standard
filesystem tools.  The layout is:

    <cache_root>/<source>/<name>/<source-tree>
    <cache_root>/<source>/<name>/_cache_meta.json

``source`` is ``charmhub`` or ``launchpad``; ``name`` is the
upstream charm or project slug (slashes flattened to dashes so the
on-disk layout is one directory deep per entry).  The metadata
sidecar tracks the fetch timestamp and the upstream URL so
``is_fresh`` can decide whether a cached entry needs a refetch.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
from typing import Any

# Phase 70.1 — the Librarian's quality bar treats charm sources as
# stale after this many days.  A short TTL keeps the cache cheap to
# refresh; the agent can always pass ``force=True`` for a hard miss.
DEFAULT_TTL_DAYS = 7

# Source tag in cache paths for Charmhub-fetched charms.
SOURCE_CHARMHUB = "charmhub"

# Source tag in cache paths for Launchpad-fetched projects.
SOURCE_LAUNCHPAD = "launchpad"

_META_FILENAME = "_cache_meta.json"

# Environment override so tests can point at a tmpdir without
# scribbling on the user's real cache.  Mirrors the convention
# ``cantrip.update`` uses for ``CANTRIP_CACHE_DIR``.
_CACHE_ROOT_ENV = "CANTRIP_CHARM_LIBRARY_DIR"


def cache_root() -> pathlib.Path:
    """Return the charm-library cache root.

    Honours :envvar:`CANTRIP_CHARM_LIBRARY_DIR` so tests can redirect
    writes; otherwise falls back to ``~/.cache/cantrip/charm-library/``.
    The directory is *not* created here — callers create it lazily so
    a no-op tool invocation doesn't leave an empty cache dir behind.
    """
    override = os.environ.get(_CACHE_ROOT_ENV)
    if override:
        return pathlib.Path(override).expanduser()
    return pathlib.Path("~/.cache/cantrip/charm-library").expanduser()


def _safe_name(name: str) -> str:
    """Flatten a slug to a single directory-safe segment.

    Launchpad project names can include ``+``; Charmhub names are
    already dash-separated.  We strip path separators so an attacker-
    controlled slug can't escape the cache root.
    """
    return name.replace("/", "-").replace("\\", "-").strip()


def entry_path(source: str, name: str) -> pathlib.Path:
    """Return the cache directory for a single charm/project entry.

    The directory is *not* created — callers handle that themselves so
    the cache stays empty when a fetch errors out before producing a
    tree.
    """
    safe = _safe_name(name)
    if not safe:
        raise ValueError(f"Refusing to cache entry with empty name: {name!r}")
    return cache_root() / source / safe


def meta_path(entry: pathlib.Path) -> pathlib.Path:
    """Return the metadata sidecar path inside *entry*."""
    return entry / _META_FILENAME


def read_meta(entry: pathlib.Path) -> dict[str, Any] | None:
    """Read the cache metadata sidecar; return ``None`` when absent or unreadable.

    A corrupt sidecar is treated as missing — the next ``record_fetch``
    overwrites it.  We don't surface the parse error because the
    Librarian's only signal here is "is the cache fresh"; the answer
    on a corrupt file is "no".
    """
    sidecar = meta_path(entry)
    if not sidecar.is_file():
        return None
    try:
        with sidecar.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def record_fetch(
    entry: pathlib.Path,
    *,
    source: str,
    name: str,
    upstream_url: str,
    revision: str | None = None,
) -> None:
    """Stamp the cache entry with fetch metadata.

    Creates the entry directory if needed.  Overwrites any prior
    sidecar so the freshness check uses the most recent fetch.
    """
    entry.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": source,
        "name": name,
        "upstream_url": upstream_url,
        "revision": revision,
        "fetched_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    with meta_path(entry).open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def is_fresh(
    entry: pathlib.Path,
    *,
    ttl_days: int = DEFAULT_TTL_DAYS,
    now: datetime.datetime | None = None,
) -> bool:
    """Return ``True`` when *entry*'s sidecar is within ``ttl_days``.

    A missing or corrupt sidecar is *not* fresh — the caller should
    refetch.  ``now`` is overridable so tests don't depend on the wall
    clock.
    """
    meta = read_meta(entry)
    if meta is None:
        return False
    fetched_at_raw = meta.get("fetched_at")
    if not isinstance(fetched_at_raw, str):
        return False
    try:
        fetched_at = datetime.datetime.fromisoformat(fetched_at_raw)
    except ValueError:
        return False
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=datetime.UTC)
    moment = now or datetime.datetime.now(datetime.UTC)
    return (moment - fetched_at).days < ttl_days
