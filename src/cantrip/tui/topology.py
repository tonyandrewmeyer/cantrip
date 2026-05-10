"""Shared topology rendering helpers for the TUI's model surfaces.

Both the right-panel status pane (:mod:`cantrip.tui.widgets.status`) and
the F8 integration-graph screen (:mod:`cantrip.tui.screens.graph`) need
the same primitives: the per-status glyph and colour, and the
deduplicated edge list derived from ``app.relations``.  Keeping them in
one place stops the two surfaces from drifting apart (different glyphs,
different dedup rules) the way they had before Phase 90.

No Textual or Rich imports here — this module is pure data so it can be
unit-tested without a mounted DOM.
"""

from __future__ import annotations

import dataclasses
import typing

if typing.TYPE_CHECKING:
    from jubilant import statustypes


# Status → single-glyph indicator.  ``maintenance`` uses a half-filled
# circle, ``error`` an ``x``; everything unknown falls back to the
# hollow "waiting" circle so a status Juju grows later still renders.
STATUS_GLYPH: dict[str, str] = {
    "active": "●",
    "waiting": "○",
    "blocked": "◌",
    "maintenance": "◐",
    "unknown": "○",
    "error": "✗",
}

# Status → Rich/Textual *theme* colour token.  These are the
# ``$variable`` names so callers can interpolate them into Textual
# markup (``[$success]…[/]``); a Rich-only caller can map them to
# concrete colours via its own table.
STATUS_COLOUR: dict[str, str] = {
    "active": "$success",
    "waiting": "$warning",
    "blocked": "$error",
    "maintenance": "$accent",
    "unknown": "$text-muted",
    "error": "$error",
}

# Status → plain Rich colour name, for surfaces (the F8 graph's
# ``RichLog``) that render Rich renderables rather than Textual markup.
STATUS_RICH_COLOUR: dict[str, str] = {
    "active": "green",
    "waiting": "yellow",
    "blocked": "red",
    "maintenance": "blue",
    "unknown": "yellow",
    "error": "red",
}

_DEFAULT_GLYPH = "○"


def status_glyph(status: str) -> str:
    """Single-character indicator for a workload/app status."""
    return STATUS_GLYPH.get(status, _DEFAULT_GLYPH)


def status_colour(status: str) -> str:
    """Textual theme-colour token for a status (e.g. ``"$success"``)."""
    return STATUS_COLOUR.get(status, "$text-muted")


def status_rich_colour(status: str) -> str:
    """Plain Rich colour name for a status (e.g. ``"green"``)."""
    return STATUS_RICH_COLOUR.get(status, "yellow")


@dataclasses.dataclass(frozen=True, slots=True)
class Edge:
    """One relation edge between two apps, oriented for stable display.

    ``a`` and ``b`` are sorted so the same relation always renders the
    same way regardless of which end Juju lists first.  ``interface`` is
    the relation interface name (``ingress``, ``postgresql_client``, …).
    """

    a: str
    b: str
    interface: str


def dedup_edges(status: statustypes.Status, *, visible: set[str] | None = None) -> list[Edge]:
    """Deduplicated relation edges for *status*.

    Juju lists each relation from both ends; this collapses them to one
    :class:`Edge` per ``(app-pair, interface)`` so a topology view shows
    one line per pair rather than two mirrored lines.  When *visible* is
    given, edges with an endpoint outside that set are dropped — the
    caller has filtered the app list and a half-dangling edge would be
    noise.  The result is sorted (by ``a``, then ``b``, then interface)
    for stable rendering.
    """
    seen: set[tuple[str, str, str]] = set()
    edges: list[Edge] = []
    for app_name, app in status.apps.items():
        if visible is not None and app_name not in visible:
            continue
        for related_list in app.relations.values():
            for rel in related_list:
                other = rel.related_app
                if visible is not None and other not in visible:
                    continue
                lo, hi = sorted((app_name, other))
                key = (lo, hi, rel.interface)
                if key in seen:
                    continue
                seen.add(key)
                edges.append(Edge(a=lo, b=hi, interface=rel.interface))
    edges.sort(key=lambda e: (e.a, e.b, e.interface))
    return edges


def edges_touching(edges: list[Edge], app_name: str) -> list[Edge]:
    """Subset of *edges* with *app_name* on either end."""
    return [e for e in edges if app_name in (e.a, e.b)]
