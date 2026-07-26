#!/usr/bin/env python3
"""Compare local EmbeddingGemma snap vs Voyage on cantrip docs index/search.

Run on a machine where the embeddinggemma-tonyandrewmeyer snap is up
(``http://localhost:8331``) and ``VOYAGE_API_KEY`` is set.  Indexes
the chosen doc site twice — once with each provider — runs a fixed
query set against both indexes, and writes a Markdown report with
timings and top-3 retrieval overlap.

Limitation: token counts are not captured because
``cantrip.docs_index.index.IndexReport`` does not surface them; the
report covers wall-clock, pages, chunks, and embed-batch count
instead.  Adding ``--json`` to ``cantrip docs index`` is the natural
way to plug that gap if it ever matters.

Usage:

    uv run python scripts/embed_benchmark.py                 # site=ops
    uv run python scripts/embed_benchmark.py --site juju
"""

from __future__ import annotations

import argparse
import datetime
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

# Match cantrip.docs_index.index._DEFAULT_CACHE_ROOT.  No env var
# overrides this in the CLI today, so we move the SQLite file aside
# between runs to keep both indexes for the search phase.
CACHE_ROOT = pathlib.Path.home() / ".cache" / "cantrip" / "docs-index"
REPO_ROOT = pathlib.Path(__file__).parent.parent.resolve()
REPORT = REPO_ROOT / "design" / "EMBED_BENCHMARK.md"

VOYAGE_ENV = {
    "CANTRIP_EMBED_PROVIDER": "voyage",
    "CANTRIP_EMBED_MODEL": "voyage-3",
}
LOCAL_ENV = {
    "CANTRIP_EMBED_PROVIDER": "openai",
    "CANTRIP_EMBED_MODEL": "embeddinggemma",
    "OPENAI_EMBED_BASE_URL": "http://localhost:8331/v1",
}

QUERIES: tuple[str, ...] = (
    "how do I write a charm config?",
    "what is the relation interface for ingress?",
    "how do I add metrics?",
    "how do I observe events?",
    "what does ops.testing.Scenario do?",
)

INDEX_REPORT_RE = re.compile(r"pages:\s*(\d+)\s+chunks:\s*(\d+)\s+embed-batches:\s*(\d+)")
SEARCH_HIT_RE = re.compile(r"^\[\d+\.\d+\]\s+(\S+)")


def run(
    cmd: list[str], env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run *cmd* with the current env plus *env_extra* overrides."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, env=env, capture_output=True, text=True)


def preflight() -> None:
    """Bail early if the snap isn't up or the Voyage key is missing."""
    if not os.environ.get("VOYAGE_API_KEY"):
        sys.exit("VOYAGE_API_KEY not set — needed for the Voyage half of the comparison.")
    health = run(["curl", "-s", "-f", "-m", "3", "http://localhost:8331/v1/models"])
    if health.returncode != 0:
        sys.exit(
            "Local embeddinggemma snap not reachable at http://localhost:8331/v1.\n"
            "Try: sudo snap start embeddinggemma-tonyandrewmeyer"
        )


def index_with(label: str, env_extra: dict[str, str], site: str) -> dict[str, object]:
    """Wipe the per-site cache and re-index, returning timings + counts."""
    site_dir = CACHE_ROOT / site
    if site_dir.exists():
        shutil.rmtree(site_dir)

    print(f"[{label}] indexing {site} …")
    t0 = time.monotonic()
    result = run(
        ["uv", "run", "cantrip", "docs", "index", "--site", site],
        env_extra=env_extra,
    )
    wall = time.monotonic() - t0
    if result.returncode != 0:
        sys.exit(f"[{label}] index failed:\n{result.stderr}")
    print(result.stdout.rstrip())

    pages = chunks = batches = 0
    for line in result.stdout.splitlines():
        match = INDEX_REPORT_RE.search(line)
        if match:
            pages, chunks, batches = (int(g) for g in match.groups())
            break
    return {
        "label": label,
        "wall_seconds": round(wall, 2),
        "pages": pages,
        "chunks": chunks,
        "batches": batches,
    }


def stash_index(label: str, site: str, holding: pathlib.Path) -> None:
    """Copy the just-built per-site index to a holding dir for later restore."""
    src = CACHE_ROOT / site
    dst = holding / label / site
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def restore_index(label: str, site: str, holding: pathlib.Path) -> None:
    """Restore the named provider's index into the active cache root."""
    src = holding / label / site
    dst = CACHE_ROOT / site
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def search_top3(site: str, query: str, env_extra: dict[str, str]) -> list[str]:
    """Run ``cantrip docs search`` and return the top-3 URLs."""
    result = run(
        ["uv", "run", "cantrip", "docs", "search", site, query, "--top-k", "3"],
        env_extra=env_extra,
    )
    if result.returncode != 0:
        sys.exit(f"search failed for {query!r}:\n{result.stderr}")
    urls: list[str] = []
    for line in result.stdout.splitlines():
        match = SEARCH_HIT_RE.match(line)
        if match:
            urls.append(match.group(1))
    return urls[:3]


def write_report(
    site: str,
    voyage: dict[str, object],
    local: dict[str, object],
    voyage_hits: list[list[str]],
    local_hits: list[list[str]],
) -> None:
    """Write the Markdown verdict to ``design/EMBED_BENCHMARK.md``."""
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
    overlaps = [len(set(v) & set(loc)) for v, loc in zip(voyage_hits, local_hits, strict=True)]
    avg_overlap_pct = (sum(overlaps) / (3 * len(QUERIES))) * 100 if QUERIES else 0.0

    lines: list[str] = []
    lines.append("# Embed benchmark — local EmbeddingGemma vs Voyage")
    lines.append("")
    lines.append(f"_Run: {today} (UTC), site: `{site}`_")
    lines.append("")
    lines.append("## Index timings")
    lines.append("")
    lines.append("| Provider | Wall (s) | Pages | Chunks | Embed batches |")
    lines.append("|---|---:|---:|---:|---:|")
    lines.extend(
        f"| {row['label']} | {row['wall_seconds']} | {row['pages']} | "
        f"{row['chunks']} | {row['batches']} |"
        for row in (voyage, local)
    )
    lines.append("")
    lines.append("## Top-3 retrieval overlap")
    lines.append("")
    lines.append(
        f"Average top-3 URL overlap: **{avg_overlap_pct:.1f}%** across {len(QUERIES)} queries."
    )
    lines.append("")
    lines.append("| Query | Overlap (of 3) |")
    lines.append("|---|---:|")
    for query, overlap in zip(QUERIES, overlaps, strict=True):
        lines.append(f"| {query} | {overlap} |")
    lines.append("")
    lines.append("## Per-query top-3")
    lines.append("")
    for query, v_urls, l_urls in zip(QUERIES, voyage_hits, local_hits, strict=True):
        lines.append(f"### {query}")
        lines.append("")
        lines.append("**Voyage:**")
        lines.append("")
        lines.extend(f"- {url}" for url in v_urls)
        lines.append("")
        lines.append("**Local (EmbeddingGemma):**")
        lines.append("")
        lines.extend(f"- {url}" for url in l_urls)
        lines.append("")
    lines.append("## Verdict")
    lines.append("")
    lines.append(
        "_Fill in by hand based on the numbers above. Trigger to default the "
        "local snap on: top-3 overlap ≥ 70% AND wall-clock within 3× of Voyage._"
    )
    lines.append("")

    REPORT.write_text("\n".join(lines))


def main() -> int:
    """Run the embedding benchmark and write its report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--site",
        default="ops",
        help="Doc site to index (one of: juju, ops, charmcraft, rockcraft, jubilant, charmlibs).",
    )
    args = parser.parse_args()
    site = args.site

    preflight()

    holding = pathlib.Path.home() / ".cache" / "cantrip" / "embed-benchmark"
    holding.mkdir(parents=True, exist_ok=True)

    voyage = index_with("voyage", VOYAGE_ENV, site)
    stash_index("voyage", site, holding)

    local = index_with("local", LOCAL_ENV, site)
    stash_index("local", site, holding)

    print()
    print("Searching with Voyage …")
    restore_index("voyage", site, holding)
    voyage_hits = [search_top3(site, q, VOYAGE_ENV) for q in QUERIES]

    print("Searching with local snap …")
    restore_index("local", site, holding)
    local_hits = [search_top3(site, q, LOCAL_ENV) for q in QUERIES]

    write_report(site, voyage, local, voyage_hits, local_hits)
    today = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
    rel = REPORT.relative_to(REPO_ROOT)
    print()
    print(f"Report written to {rel}")
    print()
    print("To open a draft PR (run yourself, the script doesn't push):")
    print(f"  git checkout -b embed-benchmark-{today}")
    print(f"  git add {rel}")
    print(f"  git commit -m 'docs(benchmark): EmbeddingGemma vs Voyage on docs/{site}'")
    print(
        "  gh pr create --draft "
        "--title 'Embed benchmark: EmbeddingGemma vs Voyage' "
        f'--body "See {rel}"'
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
