"""Charmhub API tools for searching and inspecting charms."""

import asyncio
import datetime
import json
import logging
import pathlib
import shutil
from typing import Any

import httpx
import yaml

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.charm_library import (
    DEFAULT_TTL_DAYS,
    SOURCE_CHARMHUB,
    entry_path,
    is_fresh,
    read_meta,
    record_fetch,
)

log = logging.getLogger(__name__)

# Cap search results to avoid blowing up the LLM context window.
MAX_SEARCH_RESULTS = 20

_BASE_URL = "https://api.charmhub.io/v2/charms"

# Cap ``git clone`` so a wedged remote can't park the agent
# indefinitely.  Charm libraries are small, but the cap covers
# slow networks and depth=1 + blob filtering should comfortably
# finish well inside it.
_GIT_CLONE_TIMEOUT_SECONDS = 120.0

# Phase 70.1 — a charm with no release in this many days is treated as
# stale by ``charmhub_search``'s quality flags.  Twelve months matches
# the Librarian guidance: "drop hits that look stale".
_STALE_AFTER_DAYS = 365


def _parse_iso_timestamp(value: str | None) -> datetime.datetime | None:
    """Parse a Charmhub ISO-8601 release timestamp; tolerate odd shapes.

    Charmhub returns ``"2025-08-14T10:32:11.123456+00:00"`` for normal
    releases.  Some legacy entries trail a ``Z`` instead.  Anything we
    can't parse turns into ``None`` so the quality flag silently drops
    rather than crashing the search.
    """
    if not value:
        return None
    text = value.strip().rstrip("Z")
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    return dt


def _quality_flags(
    *,
    released_at: datetime.datetime | None,
    risk: str | None,
    publisher_validation: str | None,
    now: datetime.datetime,
) -> list[str]:
    """Derive the small quality-signal vocabulary the Librarian renders.

    Cheap signals from the search response only — the agent calls
    ``charmhub_info`` or ``charmhub_fetch`` if it wants deeper checks
    (ops-vs-reactive, presence of ``src/charm.py`` …).
    """
    flags: list[str] = []
    if released_at is not None:
        age_days = (now - released_at).days
        if age_days <= _STALE_AFTER_DAYS:
            flags.append("recently-maintained")
        else:
            flags.append("stale")
    if risk:
        # The Charmhub channel risk vocabulary: stable, candidate, beta, edge.
        flags.append(f"channel-{risk}")
    if publisher_validation in {"verified", "canonical"}:
        flags.append(f"publisher-{publisher_validation}")
    return flags


class CharmhubSearchTool(Tool):
    """Search Charmhub for existing charms."""

    @property
    def name(self) -> str:
        return "charmhub_search"

    @property
    def description(self) -> str:
        return (
            "Search Charmhub for existing charms matching a query."
            " Returns name, summary, publisher, and categories for each result."
            " Use this before building an infrastructure charm to check whether"
            " a suitable charm already exists."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g. 'postgresql', 'redis', 'kafka').",
                },
                "category": {
                    "type": "string",
                    "description": ("Optional category filter (e.g. 'databases', 'monitoring')."),
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, category: str | None = None) -> ToolResult:
        """Search Charmhub for charms matching *query*."""
        # Phase 70.1: extra fields populate the Librarian's quality
        # signals (recently-maintained, channel risk, verified publisher)
        # so the subagent can drop stale or borderline hits without a
        # follow-up info fetch.
        params: dict[str, str] = {
            "q": query,
            "fields": (
                "result.categories,result.summary,result.publisher.display-name,"
                "result.publisher.validation,result.links,"
                "default-release.channel.released-at,default-release.channel.risk,"
                "default-release.channel.name"
            ),
        }
        if category:
            params["category"] = category

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "Cantrip/0.1"},
            ) as client:
                response = await client.get(f"{_BASE_URL}/find", params=params)
                response.raise_for_status()
        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                output="",
                error=f"Request timed out searching Charmhub for '{query}'",
            )
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"HTTP {exc.response.status_code} searching Charmhub for '{query}'",
                data={"status_code": exc.response.status_code, "query": query},
            )
        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Connection error searching Charmhub: {exc}",
            )

        try:
            body = response.json()
        except (ValueError, json.JSONDecodeError):
            return ToolResult(
                success=False,
                output="",
                error=f"Charmhub returned non-JSON response (HTTP {response.status_code})",
            )
        raw_results = body.get("results", [])
        total = len(raw_results)
        truncated = total > MAX_SEARCH_RESULTS
        results = raw_results[:MAX_SEARCH_RESULTS]

        now = datetime.datetime.now(datetime.UTC)
        formatted: list[dict[str, Any]] = []
        lines: list[str] = []
        for item in results:
            name = item.get("name", "unknown")
            result_block = item.get("result", {})
            summary = result_block.get("summary", "")
            publisher_block = result_block.get("publisher", {})
            publisher = publisher_block.get("display-name", "unknown")
            publisher_validation = publisher_block.get("validation")
            categories = [c.get("name", "") for c in result_block.get("categories", [])]
            links = result_block.get("links", {}) or {}
            # ``links`` is an array-of-strings dict on Charmhub: a
            # ``source`` key holds a list of repository URLs.  Take the
            # first if present so the Librarian's output contract has a
            # source URL without an extra fetch.
            source_urls = links.get("source") or []
            source_url = source_urls[0] if isinstance(source_urls, list) and source_urls else None

            channel = item.get("default-release", {}).get("channel", {}) or {}
            released_at = _parse_iso_timestamp(channel.get("released-at"))
            risk = channel.get("risk")
            channel_name = channel.get("name")

            flags = _quality_flags(
                released_at=released_at,
                risk=risk,
                publisher_validation=publisher_validation,
                now=now,
            )

            formatted.append(
                {
                    "name": name,
                    "summary": summary,
                    "publisher": publisher,
                    "categories": categories,
                    "source_url": source_url,
                    "released_at": released_at.isoformat() if released_at else None,
                    "channel": channel_name,
                    "risk": risk,
                    "publisher_validation": publisher_validation,
                    "quality_flags": flags,
                }
            )
            cat_str = ", ".join(categories) if categories else "uncategorised"
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"- **{name}** ({cat_str}) — {summary} [by {publisher}]{flag_str}")

        if not lines:
            output = f"No charms found for '{query}'."
        else:
            header = f"Found {total} charm(s) for '{query}'"
            if truncated:
                header += f" (showing first {MAX_SEARCH_RESULTS})"
            header += ":\n"
            output = header + "\n".join(lines)

        return ToolResult(
            success=True,
            output=output,
            data={"results": formatted, "total": total, "query": query},
            caption=f"{total} charm{'s' if total != 1 else ''} for {query!r}",
        )


class CharmhubInfoTool(Tool):
    """Retrieve detailed information about a specific charm from Charmhub."""

    @property
    def name(self) -> str:
        return "charmhub_info"

    @property
    def description(self) -> str:
        return (
            "Get detailed information about a charm on Charmhub including its"
            " relations, config options, storage, and containers."
            " Use this after charmhub_search to evaluate whether an existing"
            " charm meets requirements."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Charm name on Charmhub (e.g. 'postgresql-k8s').",
                },
            },
            "required": ["name"],
        }

    async def execute(self, name: str) -> ToolResult:
        """Fetch detailed info for the charm called *name*."""
        fields = "default-release.revision.metadata-yaml,default-release.revision.config-yaml"
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "Cantrip/0.1"},
            ) as client:
                response = await client.get(
                    f"{_BASE_URL}/info/{name}",
                    params={"fields": fields},
                )
                response.raise_for_status()
        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                output="",
                error=f"Request timed out fetching Charmhub info for '{name}'",
            )
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code == 404:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Charm '{name}' not found on Charmhub",
                    data={"status_code": 404, "name": name},
                )
            return ToolResult(
                success=False,
                output="",
                error=f"HTTP {code} fetching Charmhub info for '{name}'",
                data={"status_code": code, "name": name},
            )
        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Connection error fetching Charmhub info: {exc}",
            )

        try:
            body = response.json()
        except (ValueError, json.JSONDecodeError):
            return ToolResult(
                success=False,
                output="",
                error=f"Charmhub returned non-JSON response (HTTP {response.status_code})",
            )
        revision = body.get("default-release", {}).get("revision", {})

        # Parse metadata YAML.
        metadata: dict[str, Any] = {}
        metadata_raw = revision.get("metadata-yaml")
        if metadata_raw:
            try:
                metadata = yaml.safe_load(metadata_raw) or {}
            except yaml.YAMLError:
                metadata = {}

        # Parse config YAML.
        config: dict[str, Any] = {}
        config_raw = revision.get("config-yaml")
        if config_raw:
            try:
                config = yaml.safe_load(config_raw) or {}
            except yaml.YAMLError:
                config = {}

        summary = metadata.get("summary", metadata.get("description", "No description available"))

        # Build human-readable output.
        lines: list[str] = [f"# {name}", ""]
        if summary:
            lines.append(summary)
            lines.append("")

        description = metadata.get("description", "")
        if description and description != summary:
            lines.append(description)
            lines.append("")

        # Relations.
        for section in ("provides", "requires", "peers"):
            relations = metadata.get(section, {})
            if relations:
                lines.append(f"## {section.title()}")
                for rel_name, rel_data in relations.items():
                    iface = (
                        rel_data.get("interface", "unknown")
                        if isinstance(rel_data, dict)
                        else "unknown"
                    )
                    lines.append(f"- **{rel_name}**: `{iface}`")
                lines.append("")

        # Storage.
        storage = metadata.get("storage", {})
        if storage:
            lines.append("## Storage")
            for store_name, store_data in storage.items():
                stype = (
                    store_data.get("type", "unknown")
                    if isinstance(store_data, dict)
                    else "unknown"
                )
                lines.append(f"- **{store_name}**: {stype}")
            lines.append("")

        # Containers.
        containers = metadata.get("containers", {})
        if containers:
            lines.append("## Containers")
            lines.extend(f"- {cname}" for cname in containers)
            lines.append("")

        # Config options.
        options = config.get("options", {})
        if options:
            lines.append("## Config Options")
            for opt_name, opt_data in options.items():
                opt_type = (
                    opt_data.get("type", "string") if isinstance(opt_data, dict) else "string"
                )
                opt_desc = opt_data.get("description", "") if isinstance(opt_data, dict) else ""
                lines.append(f"- **{opt_name}** ({opt_type}): {opt_desc}")
            lines.append("")

        # Caption with charm name + a summary preview when present.
        caption = f"{name}"
        if summary:
            preview = summary.replace("\n", " ").strip()
            if len(preview) > 50:
                preview = preview[:49] + "…"
            caption = f"{name}: {preview}"
        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={
                "name": name,
                "metadata": metadata,
                "config": config,
                "summary": summary,
            },
            caption=caption,
        )


# Maximum number of top-level entries we list when describing the
# fetched tree.  A representative slice — not the whole repo — keeps
# the LLM's context bounded while signalling "this is what's here".
_FETCH_LISTING_LIMIT = 30


def _resolve_source_url(body: dict[str, Any]) -> str | None:
    """Pick the best repository URL from a Charmhub info payload.

    Charmhub's ``result.links.source`` is the canonical place; some
    publishers only set ``website`` or ``bug-url``.  Take the first
    plausible link we find, in priority order:
    ``source > issues > website``.  The Librarian needs *somewhere*
    to clone from; a stale or off-target URL still beats no URL.
    """
    links = (body.get("result") or {}).get("links") or {}
    for key in ("source", "issues", "website"):
        candidates = links.get(key) or []
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return None


async def _fetch_charm_info(name: str) -> tuple[dict[str, Any] | None, ToolResult | None]:
    """Hit Charmhub's ``info`` endpoint asking only for the link bundle.

    Returns ``(body, None)`` on success or ``(None, error_result)`` on
    failure so callers can short-circuit without re-implementing the
    httpx exception ladder.
    """
    fields = "result.links,result.summary,default-release.revision.revision"
    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "Cantrip/0.1"},
        ) as client:
            response = await client.get(
                f"{_BASE_URL}/info/{name}",
                params={"fields": fields},
            )
            response.raise_for_status()
    except httpx.TimeoutException:
        return None, ToolResult(
            success=False,
            output="",
            error=f"Request timed out fetching Charmhub info for '{name}'",
        )
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code == 404:
            return None, ToolResult(
                success=False,
                output="",
                error=f"Charm '{name}' not found on Charmhub",
                data={"status_code": 404, "name": name},
            )
        return None, ToolResult(
            success=False,
            output="",
            error=f"HTTP {code} fetching Charmhub info for '{name}'",
            data={"status_code": code, "name": name},
        )
    except httpx.RequestError as exc:
        return None, ToolResult(
            success=False,
            output="",
            error=f"Connection error fetching Charmhub info: {exc}",
        )

    try:
        return response.json(), None
    except (ValueError, json.JSONDecodeError):
        return None, ToolResult(
            success=False,
            output="",
            error=f"Charmhub returned non-JSON response (HTTP {response.status_code})",
        )


def _summarise_tree(entry_dir: pathlib.Path) -> str:
    """Render a short tree-listing summary for the fetched charm.

    Top-level files plus a one-line per-subdirectory entry (with the
    file count).  Caps at :data:`_FETCH_LISTING_LIMIT` rows so the
    output stays readable when the agent reads it back via the chat
    transcript.
    """
    rows: list[str] = []
    children = sorted(entry_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    shown = 0
    for child in children:
        if child.name.startswith(".") or child.name == "_cache_meta.json":
            continue
        if shown >= _FETCH_LISTING_LIMIT:
            rows.append(f"… ({len(children) - shown} more entries)")
            break
        if child.is_dir():
            try:
                count = sum(1 for _ in child.rglob("*"))
            except OSError:
                count = 0
            rows.append(f"- `{child.name}/` ({count} entries)")
        else:
            rows.append(f"- `{child.name}`")
        shown += 1
    return "\n".join(rows) if rows else "_(empty tree)_"


class CharmhubFetchTool(Tool):
    """Clone a charm's upstream source into the read-only Librarian cache."""

    @property
    def name(self) -> str:
        return "charmhub_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch a Charmhub charm's source repository into the local "
            "charm-library cache (`~/.cache/cantrip/charm-library/charmhub/<name>/`) "
            "so its files can be inspected with read_file/grep/glob. "
            "Uses the source URL from the charm's Charmhub metadata; falls "
            "back to issues/website links when no source link is set. "
            "Re-uses the cached copy when fresh; pass force=True to refetch."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Charm name on Charmhub (e.g. 'postgresql-k8s').",
                },
                "force": {
                    "type": "boolean",
                    "description": (
                        "Refetch even when the cache entry is still within its "
                        "freshness window (default: false)."
                    ),
                },
            },
            "required": ["name"],
        }

    async def execute(self, name: str, force: bool = False) -> ToolResult:
        """Fetch the source for *name* into the charm-library cache."""
        try:
            entry = entry_path(SOURCE_CHARMHUB, name)
        except ValueError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        # Cache hit — short-circuit unless the caller forced a refetch.
        if not force and is_fresh(entry, ttl_days=DEFAULT_TTL_DAYS):
            meta = read_meta(entry) or {}
            listing = _summarise_tree(entry)
            output = (
                f"# {name} (cached)\n\n"
                f"- **path**: `{entry}`\n"
                f"- **upstream**: {meta.get('upstream_url', 'unknown')}\n"
                f"- **fetched_at**: {meta.get('fetched_at', 'unknown')}\n\n"
                f"## Top-level entries\n\n{listing}"
            )
            return ToolResult(
                success=True,
                output=output,
                data={
                    "name": name,
                    "path": str(entry),
                    "upstream_url": meta.get("upstream_url"),
                    "fetched_at": meta.get("fetched_at"),
                    "cached": True,
                },
                caption=f"{name} (cached)",
            )

        body, err = await _fetch_charm_info(name)
        if err is not None:
            return err
        assert body is not None  # narrows for the type checker.

        upstream_url = _resolve_source_url(body)
        if not upstream_url:
            summary = (body.get("result") or {}).get("summary") or ""
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Charm '{name}' has no source / issues / website link on "
                    f"Charmhub — cannot fetch a source tree. "
                    f"Use charmhub_info for the metadata fields instead."
                ),
                data={"name": name, "summary": summary, "links_missing": True},
            )

        if not shutil.which("git"):
            return ToolResult(
                success=False,
                output="",
                error="git is not installed — cannot clone Charmhub source.",
                data={"name": name, "upstream_url": upstream_url},
            )

        # Clear any stale cached copy before reattempting (force or
        # expired).  The clone will recreate the directory.
        if entry.exists():
            shutil.rmtree(entry, ignore_errors=True)
        entry.parent.mkdir(parents=True, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            "git",
            "clone",
            "--depth=1",
            "--filter=blob:none",
            upstream_url,
            str(entry),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=_GIT_CLONE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"git clone for '{name}' timed out after "
                    f"{_GIT_CLONE_TIMEOUT_SECONDS:.0f}s ({upstream_url})"
                ),
                data={
                    "name": name,
                    "upstream_url": upstream_url,
                    "timeout": True,
                },
            )
        if proc.returncode != 0:
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"git clone failed for '{name}' "
                    f"({upstream_url}): {stderr or 'exit ' + str(proc.returncode)}"
                ),
                data={
                    "name": name,
                    "upstream_url": upstream_url,
                    "exit_code": proc.returncode,
                },
            )

        revision_bundle = body.get("default-release") or {}
        revision = (revision_bundle.get("revision") or {}).get("revision")
        record_fetch(
            entry,
            source=SOURCE_CHARMHUB,
            name=name,
            upstream_url=upstream_url,
            revision=str(revision) if revision is not None else None,
        )

        listing = _summarise_tree(entry)
        output = (
            f"# {name}\n\n"
            f"- **path**: `{entry}`\n"
            f"- **upstream**: {upstream_url}\n"
            f"- **revision**: {revision if revision is not None else 'unknown'}\n\n"
            f"## Top-level entries\n\n{listing}"
        )
        return ToolResult(
            success=True,
            output=output,
            data={
                "name": name,
                "path": str(entry),
                "upstream_url": upstream_url,
                "revision": revision,
                "cached": False,
            },
            caption=f"Fetched {name}",
        )
