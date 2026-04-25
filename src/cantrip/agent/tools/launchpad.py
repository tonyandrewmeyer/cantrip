"""Launchpad API tools for the Phase 70.1 Librarian subagent.

Charmhub catalogues *published* charms; Launchpad hosts charm
projects that haven't shipped yet (pre-release work, internal
charms, abandoned attempts the Librarian still wants to learn from).
We expose two tools:

* ``launchpad_search`` — full-text project search via the Launchpad
  REST API, returning name, summary, VCS, last-modified date, and
  a quality flag for "recently maintained".
* ``launchpad_fetch`` — for Git-hosted projects, shallow-clones
  ``https://git.launchpad.net/<name>`` into the same charm-library
  cache the Charmhub fetch tool uses.  Bazaar projects are flagged
  but not auto-cloned (no ``bzr`` support in the cache contract).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import shutil
from typing import Any

import httpx

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.charm_library import (
    DEFAULT_TTL_DAYS,
    SOURCE_LAUNCHPAD,
    entry_path,
    is_fresh,
    read_meta,
    record_fetch,
)
from cantrip.agent.tools.charmhub import _STALE_AFTER_DAYS, _summarise_tree

log = logging.getLogger(__name__)

# Launchpad's API root.  ``devel`` is the working REST API; ``1.0``
# exists for backwards compatibility.  We pin to ``devel`` because
# every public Launchpad response uses it today.
_BASE_URL = "https://api.launchpad.net/devel"

# Default Git host for Launchpad-managed projects.  When a project's
# VCS is ``Git`` (not ``Bazaar``), the canonical clone URL follows
# this template.  Project-owned repos under different paths require an
# explicit URL, which the agent can fetch with ``charmhub_fetch`` /
# ``git_clone`` instead.
_GIT_HOST_TEMPLATE = "https://git.launchpad.net/{name}"

# Cap launchpad search results.  Launchpad's ``ws.op=search`` returns
# whole pages (75 per page) and we don't want to flood the LLM context.
MAX_SEARCH_RESULTS = 15


def _parse_iso(value: str | None) -> datetime.datetime | None:
    """Parse a Launchpad ISO-8601 timestamp; tolerate missing TZ.

    Launchpad returns ``"2025-08-14T10:32:11.123456+00:00"`` for normal
    fields.  Anything that won't parse turns into ``None`` so the
    quality flag silently drops.
    """
    if not value:
        return None
    try:
        dt = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    return dt


def _project_quality_flags(
    *,
    last_modified: datetime.datetime | None,
    vcs: str | None,
    now: datetime.datetime,
) -> list[str]:
    """Derive Launchpad-specific quality flags for the Librarian."""
    flags: list[str] = []
    if last_modified is not None:
        age_days = (now - last_modified).days
        if age_days <= _STALE_AFTER_DAYS:
            flags.append("recently-maintained")
        else:
            flags.append("stale")
    if vcs:
        flags.append(f"vcs-{vcs.lower()}")
    return flags


class LaunchpadSearchTool(Tool):
    """Full-text search across Launchpad projects."""

    @property
    def name(self) -> str:
        return "launchpad_search"

    @property
    def description(self) -> str:
        return (
            "Search Launchpad for projects matching a query. "
            "Use this when looking for unpublished or in-progress charms "
            "that don't show up on Charmhub. Returns project name, "
            "summary, VCS type, last-modified date, and quality flags."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search text (e.g. 'kafka operator', 'ldap charm').",
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str) -> ToolResult:
        """Search Launchpad for projects matching *query*."""
        params: dict[str, str] = {
            "ws.op": "search",
            "text": query,
        }
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "Cantrip/0.1", "Accept": "application/json"},
            ) as client:
                response = await client.get(f"{_BASE_URL}/projects", params=params)
                response.raise_for_status()
        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                output="",
                error=f"Request timed out searching Launchpad for '{query}'",
            )
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"HTTP {exc.response.status_code} searching Launchpad for '{query}'",
                data={"status_code": exc.response.status_code, "query": query},
            )
        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Connection error searching Launchpad: {exc}",
            )

        try:
            body = response.json()
        except (ValueError, json.JSONDecodeError):
            return ToolResult(
                success=False,
                output="",
                error=f"Launchpad returned non-JSON response (HTTP {response.status_code})",
            )

        entries = body.get("entries", []) or []
        total = len(entries)
        truncated = total > MAX_SEARCH_RESULTS
        entries = entries[:MAX_SEARCH_RESULTS]

        now = datetime.datetime.now(datetime.UTC)
        formatted: list[dict[str, Any]] = []
        lines: list[str] = []
        for entry in entries:
            name = entry.get("name", "unknown")
            summary = (entry.get("summary") or "").strip()
            vcs = entry.get("vcs")
            last_modified = _parse_iso(entry.get("date_last_modified"))
            web_link = entry.get("web_link") or f"https://launchpad.net/{name}"
            flags = _project_quality_flags(last_modified=last_modified, vcs=vcs, now=now)
            formatted.append(
                {
                    "name": name,
                    "summary": summary,
                    "vcs": vcs,
                    "web_link": web_link,
                    "last_modified": last_modified.isoformat() if last_modified else None,
                    "quality_flags": flags,
                }
            )
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            summary_short = summary if len(summary) <= 120 else summary[:119] + "…"
            lines.append(f"- **{name}** — {summary_short}{flag_str}\n  <{web_link}>")

        if not lines:
            output = f"No Launchpad projects found for '{query}'."
        else:
            header = f"Found {total} Launchpad project(s) for '{query}'"
            if truncated:
                header += f" (showing first {MAX_SEARCH_RESULTS})"
            header += ":\n"
            output = header + "\n".join(lines)

        return ToolResult(
            success=True,
            output=output,
            data={"results": formatted, "total": total, "query": query},
            caption=(f"{total} project{'s' if total != 1 else ''} for {query!r} on Launchpad"),
        )


class LaunchpadFetchTool(Tool):
    """Clone a Launchpad-hosted project into the read-only Librarian cache."""

    @property
    def name(self) -> str:
        return "launchpad_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch a Launchpad project's Git repository into the local "
            "charm-library cache (`~/.cache/cantrip/charm-library/launchpad/<name>/`) "
            "so its files can be inspected with read_file/grep/glob. "
            "Only Git-hosted projects are fetched automatically; "
            "Bazaar projects surface as an error with the upstream URL "
            "for manual inspection. "
            "Re-uses the cached copy when fresh; pass force=True to refetch."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Launchpad project name (e.g. 'charmed-kubeflow').",
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
        """Fetch the Git source for project *name* into the charm-library cache."""
        try:
            entry = entry_path(SOURCE_LAUNCHPAD, name)
        except ValueError as exc:
            return ToolResult(success=False, output="", error=str(exc))

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

        # Look up the project so we can confirm it exists and pick the
        # right VCS path.  Launchpad's REST is permissive — a 404 means
        # the project really isn't there.
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "Cantrip/0.1", "Accept": "application/json"},
            ) as client:
                response = await client.get(f"{_BASE_URL}/{name}")
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code == 404:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Launchpad project '{name}' not found",
                    data={"status_code": 404, "name": name},
                )
            return ToolResult(
                success=False,
                output="",
                error=f"HTTP {code} fetching Launchpad project '{name}'",
                data={"status_code": code, "name": name},
            )
        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                output="",
                error=f"Request timed out fetching Launchpad project '{name}'",
            )
        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Connection error fetching Launchpad project: {exc}",
            )

        try:
            body = response.json()
        except (ValueError, json.JSONDecodeError):
            return ToolResult(
                success=False,
                output="",
                error=f"Launchpad returned non-JSON response (HTTP {response.status_code})",
            )

        vcs = body.get("vcs")
        web_link = body.get("web_link") or f"https://launchpad.net/{name}"

        if vcs is None:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Launchpad project '{name}' has no registered VCS — "
                    f"see {web_link} for any uploaded artefacts."
                ),
                data={"name": name, "web_link": web_link, "vcs": None},
            )
        if vcs.lower() != "git":
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Launchpad project '{name}' uses {vcs} (not Git) — "
                    f"the Librarian cache only auto-fetches Git. "
                    f"Browse {web_link} or use the standard tooling."
                ),
                data={"name": name, "web_link": web_link, "vcs": vcs},
            )

        if not shutil.which("git"):
            return ToolResult(
                success=False,
                output="",
                error="git is not installed — cannot clone Launchpad source.",
                data={"name": name},
            )

        upstream_url = _GIT_HOST_TEMPLATE.format(name=name)

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
        _, stderr_bytes = await proc.communicate()
        if proc.returncode != 0:
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"git clone failed for Launchpad project '{name}' "
                    f"({upstream_url}): {stderr or 'exit ' + str(proc.returncode)}"
                ),
                data={
                    "name": name,
                    "upstream_url": upstream_url,
                    "exit_code": proc.returncode,
                },
            )

        record_fetch(
            entry,
            source=SOURCE_LAUNCHPAD,
            name=name,
            upstream_url=upstream_url,
            revision=None,
        )

        listing = _summarise_tree(entry)
        output = (
            f"# {name}\n\n"
            f"- **path**: `{entry}`\n"
            f"- **upstream**: {upstream_url}\n"
            f"- **web_link**: {web_link}\n\n"
            f"## Top-level entries\n\n{listing}"
        )
        return ToolResult(
            success=True,
            output=output,
            data={
                "name": name,
                "path": str(entry),
                "upstream_url": upstream_url,
                "web_link": web_link,
                "cached": False,
            },
            caption=f"Fetched {name} from Launchpad",
        )
