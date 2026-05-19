"""Tests for the COS-pane collapsed-summary string builder."""

from __future__ import annotations

from unittest.mock import MagicMock

from cantrip.tui.widgets.status import _cos_collapsed_summary


def _mock_status(
    app_statuses: list[str],
    *,
    offers: int = 0,
    relations: list[tuple[str, str]] | None = None,
) -> MagicMock:
    """Build the minimum ``statustypes.Status``-shaped mock the summary reads.

    ``_cos_collapsed_summary`` touches ``apps[*].app_status.current``,
    ``apps[*].relations`` (for the pair count), and ``offers`` —
    everything else can stay a generic ``MagicMock``.  Apps are named
    ``app-0``, ``app-1``, …; *relations* is a list of name pairs.
    """
    status = MagicMock()
    status.apps = {}
    rel_map: dict[str, list[MagicMock]] = {}
    for a, b in relations or []:
        rel = MagicMock()
        rel.related_app = b
        rel_map.setdefault(a, []).append(rel)
        back = MagicMock()
        back.related_app = a
        rel_map.setdefault(b, []).append(back)
    for i, current in enumerate(app_statuses):
        name = f"app-{i}"
        app = MagicMock()
        app.app_status.current = current
        app.relations = {"r": rel_map[name]} if name in rel_map else {}
        status.apps[name] = app
    status.offers = {f"offer-{i}": MagicMock() for i in range(offers)}
    return status


def test_all_active_collapses_to_friendly_label():
    status = _mock_status(["active", "active", "active"])
    assert _cos_collapsed_summary(status) == "3 apps · all active  (click to expand)"


def test_mixed_statuses_listed_explicitly():
    # 1 blocked, 2 waiting, 3 active — the old "3/6" form hid this.
    status = _mock_status(["active", "active", "active", "waiting", "waiting", "blocked"])
    assert (
        _cos_collapsed_summary(status)
        == "6 apps · 1 blocked, 2 waiting, 3 active  (click to expand)"
    )


def test_error_surfaces_first():
    """Problem statuses rank ahead of healthy ones."""
    status = _mock_status(["active", "error", "active"])
    assert _cos_collapsed_summary(status) == "3 apps · 1 error, 2 active  (click to expand)"


def test_offers_count_appended_when_nonzero():
    status = _mock_status(["active", "active"], offers=4)
    assert _cos_collapsed_summary(status) == "2 apps · all active · 4 offers  (click to expand)"


def test_no_offers_no_suffix():
    status = _mock_status(["active"], offers=0)
    assert "offers" not in _cos_collapsed_summary(status)


def test_empty_model_does_not_crash():
    status = _mock_status([])
    assert _cos_collapsed_summary(status) == "no apps  (click to expand)"


def test_unknown_future_juju_status_still_shown():
    """A status Juju invents later shouldn't silently vanish from the summary."""
    status = _mock_status(["active", "teleporting"])
    result = _cos_collapsed_summary(status)
    assert "1 active" in result
    assert "1 teleporting" in result


def test_relation_pair_count_is_reported():
    # 3 apps, 2 distinct related pairs (0–1, 1–2).
    status = _mock_status(
        ["active", "active", "active"], relations=[("app-0", "app-1"), ("app-1", "app-2")]
    )
    assert _cos_collapsed_summary(status) == "3 apps · 2 relations · all active  (click to expand)"


def test_single_relation_is_singular():
    status = _mock_status(["active", "active"], relations=[("app-0", "app-1")])
    assert _cos_collapsed_summary(status) == "2 apps · 1 relation · all active  (click to expand)"
