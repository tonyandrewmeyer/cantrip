"""MCP marketplace discovery (Phase 45.5).

Marketplaces are user-supplied catalogues of available MCP servers,
mirroring the format Codex / Cursor / Claude Code converged on during
the Oct 2025 – Apr 2026 window.  Cantrip is a **read-only** consumer:
``/mcp marketplace`` lists what's available so the user can copy a
server descriptor into their own ``cantrip.mcp.yaml``.  No automatic
installation — the user always opts in explicitly.

Three source types are supported, declared in ``cantrip.mcp.yaml``:

* ``github: <owner>/<repo>`` — fetch ``marketplace.json`` from the
  repo's main branch via raw.githubusercontent.com.
* ``directory: <path>`` — read ``<path>/marketplace.json`` from disk.
  Useful for offline development and corporate mirrors.
* ``url: <url>`` — HTTP GET on the URL.

Marketplace responses are cached at ``~/.cache/cantrip/marketplaces/``
so the slash command stays snappy.  ``/mcp marketplace refresh``
forces a re-fetch.

The expected ``marketplace.json`` schema, kept deliberately minimal:

```json
{
  "name": "anthropic-mcp-servers",
  "description": "Official MCP server registry",
  "servers": {
    "filesystem": {
      "description": "Local filesystem access",
      "transport": "stdio",
      "command": "npx",
      "args": ["@modelcontextprotocol/server-filesystem", "${HOME}"]
    },
    "github": {
      "description": "GitHub API access",
      "transport": "stdio",
      "command": "npx",
      "args": ["@modelcontextprotocol/server-github"],
      "env_required": ["GITHUB_TOKEN"]
    }
  }
}
```

Servers are surfaced read-only — Cantrip's ``ServerConfig`` is **not**
populated automatically.  The user copies the relevant block into their
``cantrip.mcp.yaml`` after reviewing what each server does.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import logging
import os
import pathlib
import time
from typing import Any

from cantrip.mcp.exceptions import MCPConfigError

log = logging.getLogger(__name__)


# Default cache directory for marketplace responses.
_DEFAULT_CACHE_DIR = pathlib.Path("~/.cache/cantrip/marketplaces")
CACHE_DIR_ENV = "CANTRIP_MCP_MARKETPLACE_CACHE"

# How long a cached marketplace is considered fresh.  Within this window
# Cantrip skips network/disk I/O entirely; a manual ``refresh`` always
# bypasses the cache.
DEFAULT_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours

# Default branch for GitHub-sourced marketplaces.  Most repos use
# ``main`` now; the user can pin a different branch via the URL form
# if they need ``master``, a release tag, or a fork.
_GITHUB_DEFAULT_BRANCH = "main"


class SourceKind(enum.StrEnum):
    """How Cantrip locates a marketplace's ``marketplace.json``."""

    GITHUB = "github"
    DIRECTORY = "directory"
    URL = "url"


@dataclasses.dataclass(frozen=True)
class MarketplaceSource:
    """A single marketplace source declared by the user.

    Exactly one of ``github`` / ``directory`` / ``url`` is set; the
    parser enforces that.  ``label`` is a human-readable identifier
    derived from the source for the ``/mcp marketplace`` output.
    """

    kind: SourceKind
    location: str  # owner/repo, filesystem path, or URL.

    @property
    def label(self) -> str:
        """Short identifier used in /mcp marketplace output."""
        return f"{self.kind.value}:{self.location}"

    def fetch_url(self) -> str | None:
        """Build the HTTP URL Cantrip will fetch (None for filesystem)."""
        if self.kind == SourceKind.GITHUB:
            return (
                f"https://raw.githubusercontent.com/{self.location}/"
                f"{_GITHUB_DEFAULT_BRANCH}/marketplace.json"
            )
        if self.kind == SourceKind.URL:
            return self.location
        return None


@dataclasses.dataclass(frozen=True)
class MarketplaceServer:
    """One server descriptor from a marketplace's ``servers`` block.

    Mirrors Cantrip's :class:`ServerConfig` in shape so a user can
    paste the descriptor directly into ``cantrip.mcp.yaml`` with
    minimal edits.  All fields are informational — Cantrip never
    auto-instantiates a marketplace server.
    """

    name: str
    description: str = ""
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = dataclasses.field(default_factory=list)
    env_required: list[str] = dataclasses.field(default_factory=list)
    url: str | None = None
    scopes: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class Marketplace:
    """A loaded marketplace, with the source it came from."""

    source: MarketplaceSource
    name: str
    description: str
    servers: list[MarketplaceServer]
    fetched_at: float  # Unix timestamp; ``0`` for fresh-this-call.


def default_cache_dir() -> pathlib.Path:
    """Resolve the marketplace response cache directory."""
    override = os.environ.get(CACHE_DIR_ENV)
    if override:
        return pathlib.Path(override).expanduser()
    return _DEFAULT_CACHE_DIR.expanduser()


# ── Source parsing ─────────────────────────────────────────────────────


def parse_source(spec: dict[str, Any], *, source_label: str) -> MarketplaceSource:
    """Validate one marketplace entry from YAML and return a source.

    Each entry must specify exactly one of ``github``, ``directory``,
    ``url``.  Extra keys are rejected so a typo doesn't silently
    select the wrong kind.
    """
    if not isinstance(spec, dict):
        raise MCPConfigError(f"marketplace entry in {source_label} must be a mapping")
    fields = {k: v for k, v in spec.items() if v is not None}
    kinds = [k for k in ("github", "directory", "url") if k in fields]
    if len(kinds) != 1:
        raise MCPConfigError(
            f"marketplace entry in {source_label} must specify exactly one of "
            "`github`, `directory`, `url`"
        )
    extra = set(fields) - set(kinds)
    if extra:
        raise MCPConfigError(
            f"marketplace entry in {source_label}: unexpected keys "
            f"{sorted(extra)} (only {kinds[0]!r} is allowed for this entry)"
        )
    kind = kinds[0]
    value = fields[kind]
    if not isinstance(value, str) or not value.strip():
        raise MCPConfigError(
            f"marketplace entry in {source_label}: `{kind}` must be a non-empty string"
        )
    if kind == "github" and "/" not in value:
        raise MCPConfigError(
            f"marketplace entry in {source_label}: `github` value must be `<owner>/<repo>`"
        )
    return MarketplaceSource(kind=SourceKind(kind), location=value.strip())


# ── Loader ─────────────────────────────────────────────────────────────


class MarketplaceLoader:
    """Fetch + cache marketplace catalogues.

    Constructed once per agent.  ``load_all(sources)`` returns a list
    of loaded marketplaces; failed fetches are logged and skipped so a
    transient outage doesn't take the slash command down.
    """

    def __init__(
        self,
        *,
        cache_dir: pathlib.Path | None = None,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self._cache_dir = cache_dir or default_cache_dir()
        self._cache_ttl = cache_ttl_seconds

    @property
    def cache_dir(self) -> pathlib.Path:
        """The directory where marketplace responses are cached."""
        return self._cache_dir

    async def load_all(
        self,
        sources: list[MarketplaceSource],
        *,
        refresh: bool = False,
    ) -> list[Marketplace]:
        """Load every source.  Failures degrade to skipped + logged.

        ``refresh=True`` bypasses the cache entirely and re-fetches
        every source, used by ``/mcp marketplace refresh``.
        """
        out: list[Marketplace] = []
        for src in sources:
            try:
                market = await self.load(src, refresh=refresh)
            except (OSError, MCPConfigError) as exc:
                log.warning("Marketplace %s unavailable: %s", src.label, exc)
                continue
            out.append(market)
        return out

    async def load(
        self,
        source: MarketplaceSource,
        *,
        refresh: bool = False,
    ) -> Marketplace:
        """Load one marketplace, using the cache when fresh."""
        if not refresh:
            cached = self._read_cache(source)
            if cached is not None:
                return cached
        raw = await self._fetch_raw(source)
        market = self._parse(source, raw)
        self._write_cache(source, raw)
        return market

    # ── Internal helpers ────────────────────────────────────────────

    def _cache_path(self, source: MarketplaceSource) -> pathlib.Path:
        # Replace path separators so the cache file name is filesystem-safe.
        slug = source.label.replace("/", "_").replace(":", "__")
        return self._cache_dir / f"{slug}.json"

    def _read_cache(self, source: MarketplaceSource) -> Marketplace | None:
        path = self._cache_path(source)
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > self._cache_ttl:
            return None
        try:
            # ``errors="replace"`` so a hand-edited cache file with non-UTF-8
            # bytes degrades to "re-fetch" rather than crashing the listing
            # — ``UnicodeDecodeError`` is a ``ValueError``, not an ``OSError``.
            raw = path.read_text(errors="replace")
        except OSError as exc:
            log.debug("Cache read failed for %s: %s", source.label, exc)
            return None
        try:
            return self._parse(source, raw, fetched_at=path.stat().st_mtime)
        except MCPConfigError as exc:
            log.warning("Cached marketplace %s is corrupt: %s; will re-fetch", source.label, exc)
            return None

    def _write_cache(self, source: MarketplaceSource, raw: str) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            path = self._cache_path(source)
            path.write_text(raw)
        except OSError as exc:
            log.debug("Cache write failed for %s: %s", source.label, exc)

    async def _fetch_raw(self, source: MarketplaceSource) -> str:
        """Fetch the raw marketplace JSON text."""
        if source.kind == SourceKind.DIRECTORY:
            return self._read_directory(source)
        url = source.fetch_url()
        if url is None:
            raise MCPConfigError(f"marketplace {source.label} has no fetchable URL")
        return await self._http_get(url)

    @staticmethod
    def _read_directory(source: MarketplaceSource) -> str:
        path = pathlib.Path(source.location).expanduser() / "marketplace.json"
        if not path.is_file():
            raise OSError(f"no marketplace.json at {path}")
        # ``errors="replace"`` so a marketplace.json with stray non-UTF-8 bytes
        # surfaces as a JSON parse error in ``_parse`` rather than crashing the
        # caller (``UnicodeDecodeError`` is a ``ValueError``, not an ``OSError``).
        return path.read_text(errors="replace")

    @staticmethod
    async def _http_get(url: str) -> str:
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=15)
        # aiohttp.ClientError isn't OSError, so callers that catch
        # OSError to "skip and continue" would otherwise propagate the
        # error and take down the whole /mcp marketplace listing.
        try:
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.get(url) as resp,
            ):
                if resp.status != 200:
                    raise OSError(f"HTTP {resp.status} fetching {url}")
                return await resp.text()
        except aiohttp.ClientError as exc:
            raise OSError(f"HTTP fetch failed for {url}: {exc}") from exc

    @staticmethod
    def _parse(
        source: MarketplaceSource,
        raw: str,
        *,
        fetched_at: float | None = None,
    ) -> Marketplace:
        """Parse a marketplace response into the dataclass shape."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MCPConfigError(f"marketplace {source.label}: malformed JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise MCPConfigError(f"marketplace {source.label}: top-level value must be a mapping")
        servers_raw = data.get("servers") or {}
        if not isinstance(servers_raw, dict):
            raise MCPConfigError(f"marketplace {source.label}: `servers` must be a mapping")
        servers: list[MarketplaceServer] = []
        for name, descriptor in servers_raw.items():
            if not isinstance(name, str) or not name.strip():
                raise MCPConfigError(
                    f"marketplace {source.label}: server name must be a non-empty string"
                )
            if not isinstance(descriptor, dict):
                raise MCPConfigError(
                    f"marketplace {source.label}: server {name!r} must be a mapping"
                )
            servers.append(_parse_server_descriptor(name.strip(), descriptor, source))
        return Marketplace(
            source=source,
            name=str(data.get("name") or source.label),
            description=str(data.get("description") or ""),
            servers=servers,
            fetched_at=fetched_at if fetched_at is not None else time.time(),
        )


def _parse_server_descriptor(
    name: str, descriptor: dict[str, Any], source: MarketplaceSource
) -> MarketplaceServer:
    """Build a :class:`MarketplaceServer` from one entry."""
    transport = str(descriptor.get("transport", "stdio")).lower()
    args_raw = descriptor.get("args") or []
    if not isinstance(args_raw, list) or not all(isinstance(a, str) for a in args_raw):
        raise MCPConfigError(
            f"marketplace {source.label}: server {name!r}: `args` must be a list of strings"
        )
    env_required_raw = descriptor.get("env_required") or []
    if not isinstance(env_required_raw, list) or not all(
        isinstance(e, str) for e in env_required_raw
    ):
        raise MCPConfigError(
            f"marketplace {source.label}: server {name!r}: "
            "`env_required` must be a list of strings"
        )
    scopes_raw = descriptor.get("scopes") or []
    if not isinstance(scopes_raw, list) or not all(isinstance(s, str) for s in scopes_raw):
        raise MCPConfigError(
            f"marketplace {source.label}: server {name!r}: `scopes` must be a list of strings"
        )
    return MarketplaceServer(
        name=name,
        description=str(descriptor.get("description") or ""),
        transport=transport,
        command=descriptor.get("command") if isinstance(descriptor.get("command"), str) else None,
        args=list(args_raw),
        env_required=list(env_required_raw),
        url=descriptor.get("url") if isinstance(descriptor.get("url"), str) else None,
        scopes=list(scopes_raw),
    )


__all__ = [
    "CACHE_DIR_ENV",
    "DEFAULT_CACHE_TTL_SECONDS",
    "Marketplace",
    "MarketplaceLoader",
    "MarketplaceServer",
    "MarketplaceSource",
    "SourceKind",
    "default_cache_dir",
    "parse_source",
]
