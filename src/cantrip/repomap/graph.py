"""File-level reference graph + PageRank.

Aider-style: nodes are *files*, edges are weighted by how often a
file references names defined in another file.  PageRank surfaces the
most-referenced files, and the renderer shows their top symbols.
"""

from __future__ import annotations

import collections
import dataclasses
from collections.abc import Iterable

from cantrip.repomap.symbols import FileSymbols, Symbol

# PageRank parameters.  Damping and iteration count match the values
# Brin/Page used in the original paper; convergence below 1e-6 on a
# graph this small (a charm has dozens of files at most) takes well
# under 30 iterations in practice.
_DAMPING = 0.85
_MAX_ITERATIONS = 50
_CONVERGENCE = 1e-6


@dataclasses.dataclass(frozen=True)
class FileRanking:
    """A file plus its PageRank score and the symbols defined within."""

    file: str
    score: float
    symbols: tuple[Symbol, ...]


def build_graph(files: list[FileSymbols]) -> dict[str, dict[str, float]]:
    """Build a weighted directed graph from caller files to definer files.

    Edge weight = number of references the caller has to names defined
    in the target file.  Multiple references between the same pair
    accumulate.  Self-edges (a file referencing its own definitions)
    are dropped — they would inflate a file's rank artificially.
    """
    # Index: name -> set of files that define it.  Names defined in
    # multiple files spread the edge weight across them.
    defining_files: dict[str, set[str]] = collections.defaultdict(set)
    for fs in files:
        for sym in fs.definitions:
            defining_files[sym.name].add(fs.file)

    edges: dict[str, dict[str, float]] = collections.defaultdict(
        lambda: collections.defaultdict(float)
    )
    for fs in files:
        for ref in fs.references:
            targets = defining_files.get(ref)
            if not targets:
                continue
            # Spread weight across multiple definers so a name defined
            # in three files contributes 1/3 to each edge.
            weight = 1.0 / len(targets)
            for target in targets:
                if target == fs.file:
                    continue  # Skip self-edges.
                edges[fs.file][target] += weight
    return edges


def pagerank(edges: dict[str, dict[str, float]], nodes: Iterable[str]) -> dict[str, float]:
    """Compute PageRank scores via power iteration.

    All known files are seeded so isolated files (no incoming/outgoing
    edges) still get the base ``(1 - damping) / N`` score and remain
    visible in the rendered map.
    """
    node_set = set(nodes) | set(edges.keys())
    for outs in edges.values():
        node_set.update(outs.keys())
    if not node_set:
        return {}
    n = len(node_set)
    base = (1.0 - _DAMPING) / n
    score = dict.fromkeys(node_set, 1.0 / n)

    # Pre-compute outgoing weight totals so we can normalise per node.
    out_total: dict[str, float] = {}
    for src, outs in edges.items():
        out_total[src] = sum(outs.values())

    for _ in range(_MAX_ITERATIONS):
        # Dangling nodes (no outgoing edges) redistribute their score
        # uniformly — without this, rank "leaks" out of the system.
        dangling_mass = sum(score[node] for node in node_set if out_total.get(node, 0.0) == 0.0)
        dangling_share = _DAMPING * dangling_mass / n

        new_score = dict.fromkeys(node_set, base + dangling_share)
        for src, outs in edges.items():
            total = out_total.get(src, 0.0)
            if total == 0.0:
                continue
            contribution = _DAMPING * score[src] / total
            for dst, w in outs.items():
                new_score[dst] += contribution * w

        delta = sum(abs(new_score[k] - score[k]) for k in node_set)
        score = new_score
        if delta < _CONVERGENCE:
            break
    return score


def rank_files(files: list[FileSymbols]) -> list[FileRanking]:
    """Build the graph, run PageRank, and pair scores with symbols.

    The output is sorted by descending score; ties broken by file path
    so the order is deterministic — important for cache invalidation
    and for tests.
    """
    edges = build_graph(files)
    nodes = [fs.file for fs in files]
    scores = pagerank(edges, nodes)
    by_file = {fs.file: fs for fs in files}
    rankings = [
        FileRanking(
            file=fs.file,
            score=scores.get(fs.file, 0.0),
            symbols=tuple(fs.definitions),
        )
        for fs in files
    ]
    rankings.sort(key=lambda r: (-r.score, r.file))
    # Suppress unused-var warning for ``by_file`` — kept for future use
    # (per-symbol ranking would index into it).
    del by_file
    return rankings
