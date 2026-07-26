"""``docs_search`` tool — agent-invokable retrieval over the docs index.

Phase 72.1.  The agent calls this tool when the user asks "how do I
…" about a charm-ecosystem topic; the tool embeds the query through
the Phase 72.3 :class:`~cantrip.llm.roles.RoleRouter` and runs a
cosine-similarity search against one or every site indexed under
``~/.cache/cantrip/docs-index/``.

Output format is deliberately ``{site, url, excerpt, score}`` per
hit so every snippet the agent surfaces in chat is traceable to a
canonical URL — never paraphrase the docs.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.docs_index import index, sites
from cantrip.docs_index.store import DocsStore, SearchHit
from cantrip.llm.roles import RoleNotConfigured, RoleRouter

if TYPE_CHECKING:
    import pathlib

log = logging.getLogger(__name__)

_DEFAULT_TOP_K = 5
_MAX_TOP_K = 20


class DocsSearchTool(Tool):
    """Similarity-search the indexed Canonical doc surfaces."""

    def __init__(
        self,
        role_router: RoleRouter,
        *,
        cache_root: pathlib.Path | None = None,
    ) -> None:
        """Build the tool.

        *role_router* is the agent's router (provided by
        :class:`~cantrip.agent.core.CantripAgent`); the tool reads
        the embed provider lazily on each invocation so a session
        that picked up a provider mid-run starts working immediately.

        *cache_root* overrides the on-disk index directory; tests
        pass ``tmp_path``, production code defaults to
        ``~/.cache/cantrip/docs-index/``.
        """
        self._router = role_router
        self._cache_root = cache_root

    @property
    def name(self) -> str:
        return "docs_search"

    @property
    def description(self) -> str:
        return (
            "Search the indexed Canonical documentation for charm-ecosystem "
            "topics (Juju, ops, charmcraft, rockcraft, jubilant, charmhub). "
            "Use this BEFORE answering 'how do I ...' questions about charm "
            "authoring instead of relying on memory — the index has the "
            "current canonical reference. Returns up to top_k hits as "
            "{site, url, title, excerpt, score} JSON; cite the URLs verbatim "
            "when answering."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Free-text question or topic.",
                },
                "site": {
                    "type": "string",
                    "description": (
                        "Restrict search to one site (juju, ops, charmcraft, "
                        "rockcraft, jubilant, charmhub).  Omit to search every "
                        "indexed site."
                    ),
                },
                "top_k": {
                    "type": "integer",
                    "description": (
                        f"Maximum hits to return.  Default {_DEFAULT_TOP_K}, "
                        f"capped at {_MAX_TOP_K}."
                    ),
                    "default": _DEFAULT_TOP_K,
                },
            },
            "required": ["query"],
        }

    async def execute(
        self,
        query: str,
        site: str | None = None,
        top_k: int = _DEFAULT_TOP_K,
    ) -> ToolResult:
        """Embed *query* and return top-*k* hits across one or all sites."""
        if not query.strip():
            return ToolResult(
                success=False,
                output="",
                error="docs_search requires a non-empty query.",
                caption="docs_search → empty query",
            )
        capped = max(1, min(int(top_k), _MAX_TOP_K))

        try:
            embed = self._router.get_embed()
        except RoleNotConfigured as exc:
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
                caption="docs_search → no embed provider",
            )

        target_sites = self._resolve_sites(site)
        if not target_sites:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"No docs index found.  Run `cantrip docs index --site {site}`"
                    if site
                    else "No docs index found.  Run `cantrip docs index --all`."
                ),
                caption="docs_search → no index",
            )

        result = await embed.embed([query], input_type="query")
        if not result.vectors:
            return ToolResult(
                success=False,
                output="",
                error="embed provider returned no vector",
                caption="docs_search → embed empty",
            )
        query_vec = result.vectors[0]

        all_hits: list[SearchHit] = []
        for target in target_sites:
            path = index.store_path_for(target.name, root=self._cache_root)
            if not path.exists():
                continue
            store = DocsStore(target.name, path)
            try:
                all_hits.extend(store.search(query_vec, top_k=capped))
            finally:
                store.close()

        if not all_hits:
            return ToolResult(
                success=True,
                output="(no matches)",
                data={"hits": []},
                caption=f"docs_search '{_short(query)}' → 0 hits",
            )

        all_hits.sort(key=lambda hit: -hit.score)
        all_hits = all_hits[:capped]

        payload = [
            {
                "site": hit.site,
                "url": hit.url,
                "title": hit.title,
                "section": hit.section,
                "score": round(hit.score, 4),
                "excerpt": hit.excerpt,
            }
            for hit in all_hits
        ]
        return ToolResult(
            success=True,
            output=json.dumps(payload, indent=2),
            data={"hits": payload},
            caption=f"docs_search '{_short(query)}' → {len(payload)} hits",
        )

    def _resolve_sites(self, requested: str | None) -> list[sites.DocSite]:
        """Return the list of sites to search.

        Filters to sites that actually have an on-disk index — a site
        registered but never crawled would otherwise return no
        results without explanation.  An explicit *requested* name
        that doesn't match any indexed site returns an empty list so
        the caller can render a "run `cantrip docs index`" hint.
        """
        if requested:
            site = sites.by_name(requested)
            if site is None:
                return []
            path = index.store_path_for(site.name, root=self._cache_root)
            return [site] if path.exists() else []
        out: list[sites.DocSite] = []
        for site in sites.SITES:
            path = index.store_path_for(site.name, root=self._cache_root)
            if path.exists():
                out.append(site)
        return out


def _short(text: str, *, length: int = 40) -> str:
    """Trim *text* for use in tool captions."""
    text = text.strip()
    if len(text) <= length:
        return text
    return text[: length - 1] + "…"
