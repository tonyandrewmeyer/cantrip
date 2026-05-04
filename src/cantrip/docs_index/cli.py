"""``cantrip docs`` CLI surface (Phase 72.1).

Three subcommands:

* ``cantrip docs index --site <name>`` (or ``--all``) — crawl and
  embed one or every registered site.
* ``cantrip docs list`` — show registered sites and which ones have
  an on-disk index already.
* ``cantrip docs search <site> <query>`` — run a similarity search
  against an indexed site without booting the full agent.

The dispatcher returns an exit code so it slots straight into
:func:`cantrip.main.main`'s switch.
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys

from cantrip.docs_index import index, sites
from cantrip.docs_index.store import DocsStore
from cantrip.llm.base import ProviderError
from cantrip.llm.roles import (
    EmbedProvider,
    RoleNotConfigured,
    build_role_router,
)


def dispatch(args: argparse.Namespace) -> int:
    """Route a ``cantrip docs ...`` command to the matching handler."""
    sub = getattr(args, "docs_command", None)
    if sub == "list":
        return _cmd_list(args)
    if sub == "index":
        return _cmd_index(args)
    if sub == "search":
        return _cmd_search(args)
    print(f"Unknown docs subcommand: {sub}", file=sys.stderr)
    return 2


def _cmd_list(args: argparse.Namespace) -> int:
    """Print the registered sites and which ones have an index on disk."""
    import sqlite3

    root = getattr(args, "root", None) or index.cache_root()
    print(f"Cache root: {root}\n")
    print(f"{'Site':<12} {'Indexed':<8} {'Chunks':<8} {'Description'}")
    print(f"{'-' * 12} {'-' * 8} {'-' * 8} {'-' * 40}")
    for site in sites.SITES:
        path = index.store_path_for(site.name, root=root)
        if path.exists():
            try:
                store = DocsStore(site.name, path)
                try:
                    count = store.count()
                finally:
                    store.close()
            except sqlite3.DatabaseError:
                # Treat a corrupt or hand-edited index.db like a
                # missing index — the user's other sites should still
                # render in the table rather than the whole listing
                # crashing on one bad file.
                indexed = "corrupt"
                chunk_str = "-"
            else:
                indexed = "yes"
                chunk_str = str(count)
        else:
            indexed = "no"
            chunk_str = "-"
        print(f"{site.name:<12} {indexed:<8} {chunk_str:<8} {site.description}")
    return 0


def _cmd_index(args: argparse.Namespace) -> int:
    """Crawl and embed one or every registered site.

    Builds the embed provider via :func:`build_role_router` so the
    same env-var / CLI-flag precedence the agent uses applies here:
    a user with ``CANTRIP_EMBED_PROVIDER=voyage`` set in their shell
    can run ``cantrip docs index --site ops`` without redeclaring
    the provider on every invocation.
    """
    site_name = getattr(args, "site", None)
    all_sites = getattr(args, "all_sites", False)
    if not site_name and not all_sites:
        print(
            "Error: pass --site <name> or --all to choose what to index.",
            file=sys.stderr,
        )
        return 2
    if site_name and all_sites:
        print("Error: --site and --all are mutually exclusive.", file=sys.stderr)
        return 2

    try:
        router = build_role_router(
            embed_provider=getattr(args, "embed_provider", None),
            embed_model=getattr(args, "embed_model", None),
        )
    except (ValueError, ProviderError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        embed = router.get_embed()
    except RoleNotConfigured as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    targets: list[sites.DocSite]
    if all_sites:
        targets = list(sites.SITES)
    else:
        site = sites.by_name(site_name)
        if site is None:
            valid = ", ".join(sites.names())
            print(
                f"Error: unknown site {site_name!r}. Valid: {valid}",
                file=sys.stderr,
            )
            return 1
        targets = [site]

    exit_code = 0
    for site in targets:
        print(f"Indexing {site.name} ({site.home_url}) …")
        try:
            report = asyncio.run(_run_index(site, embed))
        except (ProviderError, OSError) as exc:
            print(f"  Error: {exc}", file=sys.stderr)
            exit_code = 1
            continue
        print(
            f"  pages: {report.pages_crawled}  chunks: {report.chunks_indexed}  "
            f"embed-batches: {report.embed_calls}  errors: {len(report.errors)}"
        )
        if report.errors:
            for url in report.errors[:5]:
                print(f"    skipped: {url}")
            if len(report.errors) > 5:
                print(f"    (… {len(report.errors) - 5} more)")
    return exit_code


async def _run_index(site: sites.DocSite, embed: EmbedProvider) -> index.IndexReport:
    """Wrapper so ``asyncio.run`` has a single coroutine to drive."""
    return await index.index_site(site, embed)


def _cmd_search(args: argparse.Namespace) -> int:
    """Run a similarity search against one indexed site.

    Uses the configured embed provider to vectorise *query*, then
    cosine-searches the per-site store.  Output is plain text — one
    hit per line, with score, URL, and excerpt — so this command
    composes with shell pipelines.
    """
    site = sites.by_name(args.site)
    if site is None:
        valid = ", ".join(sites.names())
        print(f"Error: unknown site {args.site!r}. Valid: {valid}", file=sys.stderr)
        return 1
    path = index.store_path_for(site.name)
    if not path.exists():
        print(
            f"Error: {site.name} is not indexed yet. Run: cantrip docs index --site {site.name}",
            file=sys.stderr,
        )
        return 1

    try:
        router = build_role_router()
        embed = router.get_embed()
    except (ValueError, ProviderError, RoleNotConfigured) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    import sqlite3

    try:
        hits = asyncio.run(_run_search(site, args.query, embed, path, args.top_k))
    except sqlite3.DatabaseError as exc:
        print(
            f"Error: index for {site.name!r} is corrupt ({exc}). "
            f"Run: cantrip docs index --site {site.name}",
            file=sys.stderr,
        )
        return 1
    if not hits:
        print("(no hits)")
        return 0
    for hit in hits:
        print(f"[{hit.score:0.3f}] {hit.url}")
        if hit.title:
            print(f"        {hit.title}")
        print(f"        {hit.excerpt[:200]}")
        print()
    return 0


async def _run_search(
    site: sites.DocSite,
    query: str,
    embed: EmbedProvider,
    path: pathlib.Path,
    top_k: int,
) -> list:
    """Embed the query, open the per-site store, and search."""
    result = await embed.embed([query], input_type="query")
    if not result.vectors:
        return []
    store = DocsStore(site.name, path)
    try:
        return store.search(result.vectors[0], top_k=top_k)
    finally:
        store.close()
