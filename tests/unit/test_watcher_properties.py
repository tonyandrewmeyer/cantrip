"""Property-based tests for ``watcher.diff_snapshots``.

``diff_snapshots`` turns a pair of ``StatusSnapshot`` objects into a
list of ``WatcherEvent`` describing what changed between them.  The
example-based tests in ``tests/unit/test_watcher.py`` cover named
scenarios; these property tests lean on the fact that the function
is pure and operates on tidy frozen dataclasses, so arbitrary inputs
can stress every branch without hand-crafted fixtures.

The invariants under test, listed once so the test bodies stay terse:

* *None old snapshot.*  ``diff_snapshots(None, any)`` is always ``[]``
  — the watcher reports only *changes*, and there's nothing to
  compare against on the first tick.
* *Self-identity.*  ``diff_snapshots(s, s)`` is ``[]``; a snapshot
  diffed against itself sees no change.
* *Doesn't raise.*  For any pair of snapshots, the function returns
  cleanly — no ``KeyError``, no ``AttributeError``.  Property test
  frameworks catch this automatically because any raise fails the
  example.
* *Event app names are real.*  Every event's ``.app`` appears in the
  union of app names across the two snapshots (or is ``None``).
* *Event unit names are real.*  Same rule for ``.unit`` — every
  non-``None`` unit name must appear in some ``AppSnapshot.units`` on
  either side.
* *Source is always "status".*  The ``loki`` branch is produced by a
  different code path; ``diff_snapshots`` only ever emits status
  events.
* *Dedup keys are populated.*  ``WatcherEvent.__post_init__`` fills
  ``dedup_key`` when empty; no event should slip through with it
  blank.
* *Swap symmetry for additions/removals.*  The count of ``new_app``
  events in ``A→B`` equals the count of ``removed_app`` in ``B→A``,
  and vice versa.  Same for ``new_unit`` / ``removed_unit`` and
  ``new_offer`` / ``removed_offer``.
"""

from __future__ import annotations

import string

from hypothesis import given
from hypothesis import strategies as st

from cantrip.agent.watcher import (
    AppSnapshot,
    OfferSnapshot,
    StatusSnapshot,
    UnitSnapshot,
    diff_snapshots,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


# Short lower-case alphanumeric names — real app/relation names can be longer
# but the diff logic doesn't care about length, and keeping strings short
# improves shrinking behaviour when a property fails.
_name = st.text(alphabet=string.ascii_lowercase + string.digits, min_size=1, max_size=6)

# Juju workload statuses the diff function special-cases: ``maintenance`` is
# ignored as transient; ``error`` triggers the hook-failure branch.  Include
# a fuzz value too so the generic branch gets exercised.
_status = st.sampled_from(
    ["active", "waiting", "blocked", "maintenance", "error", "unknown", "other"]
)


@st.composite
def _unit(draw: st.DrawFn, app_name: str, unit_id: int) -> UnitSnapshot:
    """A single unit snapshot scoped to *app_name*."""
    return UnitSnapshot(
        name=f"{app_name}/{unit_id}",
        workload_status=draw(_status),
        workload_message=draw(st.text(max_size=30)),
        agent_status=draw(_status),
    )


@st.composite
def _app(draw: st.DrawFn) -> AppSnapshot:
    """An app snapshot with 0..3 units and 0..3 relations."""
    name = draw(_name)
    unit_ids = draw(st.lists(st.integers(min_value=0, max_value=10), max_size=3, unique=True))
    units = tuple(draw(_unit(name, uid)) for uid in unit_ids)
    relations = frozenset(draw(st.lists(_name, max_size=3, unique=True)))
    return AppSnapshot(
        name=name,
        status=draw(_status),
        status_message=draw(st.text(max_size=20)),
        units=units,
        relations=relations,
    )


@st.composite
def _offer(draw: st.DrawFn) -> OfferSnapshot:
    """A cross-model offer snapshot."""
    return OfferSnapshot(
        name=draw(_name),
        application=draw(_name),
        endpoints=frozenset(draw(st.lists(_name, max_size=3, unique=True))),
        active_connected_count=draw(st.integers(min_value=0, max_value=10)),
        total_connected_count=draw(st.integers(min_value=0, max_value=10)),
    )


def _unique_by_name(items: list[AppSnapshot | OfferSnapshot]) -> tuple:
    """Keep the first occurrence of each ``.name`` — Hypothesis can pick
    the same name twice because it sampled independently for each app."""
    seen: set[str] = set()
    out: list[AppSnapshot | OfferSnapshot] = []
    for item in items:
        if item.name in seen:
            continue
        seen.add(item.name)
        out.append(item)
    return tuple(out)


@st.composite
def _snapshot(draw: st.DrawFn) -> StatusSnapshot:
    """A full model snapshot with 0..4 apps and 0..3 offers, both name-unique."""
    raw_apps = draw(st.lists(_app(), max_size=4))
    apps = _unique_by_name(raw_apps)
    raw_offers = draw(st.lists(_offer(), max_size=3))
    offers = _unique_by_name(raw_offers)
    return StatusSnapshot(apps=apps, offers=offers)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _app_names(snap: StatusSnapshot) -> set[str]:
    """Every name an event's ``.app`` can legitimately carry.

    Events from the apps branches name real apps.  Offer events,
    however, set ``.app`` to the offer's ``application`` field, which
    is free-form metadata on the offer — it doesn't have to match a
    real app in the snapshot (and in practice may name an app that
    was removed, or that lives in a different model).  Treat the
    union as "any app label anchored somewhere in the snapshot pair."
    """
    names = {a.name for a in snap.apps}
    names.update(o.application for o in snap.offers)
    return names


def _unit_names(snap: StatusSnapshot) -> set[str]:
    return {u.name for a in snap.apps for u in a.units}


def _count_category(events: list, category: str) -> int:
    return sum(1 for e in events if e.category == category)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestDiffSnapshotsProperties:
    """Invariants of ``diff_snapshots`` over arbitrary snapshot pairs."""

    @given(new=_snapshot())
    def test_none_old_returns_empty(self, new: StatusSnapshot) -> None:
        """No baseline means nothing to diff — first tick is silent."""
        assert diff_snapshots(None, new) == []

    @given(snap=_snapshot())
    def test_self_diff_is_empty(self, snap: StatusSnapshot) -> None:
        """A snapshot diffed against itself sees no change."""
        assert diff_snapshots(snap, snap) == []

    @given(old=_snapshot(), new=_snapshot())
    def test_events_reference_real_apps(self, old: StatusSnapshot, new: StatusSnapshot) -> None:
        """Every ``.app`` on returned events names a real app in one snapshot."""
        universe = _app_names(old) | _app_names(new)
        for event in diff_snapshots(old, new):
            if event.app is not None:
                assert event.app in universe, (
                    f"Event references unknown app {event.app!r}: {event.summary}"
                )

    @given(old=_snapshot(), new=_snapshot())
    def test_events_reference_real_units(self, old: StatusSnapshot, new: StatusSnapshot) -> None:
        """Every non-``None`` ``.unit`` names a unit in one snapshot."""
        universe = _unit_names(old) | _unit_names(new)
        for event in diff_snapshots(old, new):
            if event.unit is not None:
                assert event.unit in universe, (
                    f"Event references unknown unit {event.unit!r}: {event.summary}"
                )

    @given(old=_snapshot(), new=_snapshot())
    def test_all_events_have_status_source(self, old: StatusSnapshot, new: StatusSnapshot) -> None:
        """``diff_snapshots`` only emits ``status`` events — never ``loki``."""
        for event in diff_snapshots(old, new):
            assert event.source == "status", (
                f"Unexpected source {event.source!r} on {event.category!r} event"
            )

    @given(old=_snapshot(), new=_snapshot())
    def test_dedup_keys_are_populated(self, old: StatusSnapshot, new: StatusSnapshot) -> None:
        """Every event gets a non-empty ``dedup_key`` via ``__post_init__``."""
        for event in diff_snapshots(old, new):
            assert event.dedup_key, f"Empty dedup_key on {event.category!r} event"

    @given(a=_snapshot(), b=_snapshot())
    def test_new_app_mirrors_removed_app_on_swap(
        self, a: StatusSnapshot, b: StatusSnapshot
    ) -> None:
        """Swapping old/new should mirror the add/remove counts.

        A→B's ``new_app`` count must equal B→A's ``removed_app`` count,
        and vice versa.  This proves the function isn't silently
        dropping one direction of change.
        """
        a_to_b = diff_snapshots(a, b)
        b_to_a = diff_snapshots(b, a)
        assert _count_category(a_to_b, "new_app") == _count_category(b_to_a, "removed_app")
        assert _count_category(a_to_b, "removed_app") == _count_category(b_to_a, "new_app")

    @given(a=_snapshot(), b=_snapshot())
    def test_new_unit_mirrors_removed_unit_on_swap(
        self, a: StatusSnapshot, b: StatusSnapshot
    ) -> None:
        """Same swap symmetry for unit add/remove events."""
        a_to_b = diff_snapshots(a, b)
        b_to_a = diff_snapshots(b, a)
        assert _count_category(a_to_b, "new_unit") == _count_category(b_to_a, "removed_unit")
        assert _count_category(a_to_b, "removed_unit") == _count_category(b_to_a, "new_unit")

    @given(a=_snapshot(), b=_snapshot())
    def test_new_offer_mirrors_removed_offer_on_swap(
        self, a: StatusSnapshot, b: StatusSnapshot
    ) -> None:
        """Same swap symmetry for cross-model offer add/remove events."""
        a_to_b = diff_snapshots(a, b)
        b_to_a = diff_snapshots(b, a)
        assert _count_category(a_to_b, "new_offer") == _count_category(b_to_a, "removed_offer")
        assert _count_category(a_to_b, "removed_offer") == _count_category(b_to_a, "new_offer")
