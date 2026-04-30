"""Tests for the spellcasting-themed activity-label helper.

Exercises determinism (seeded picks repeat), per-category
uniqueness expectations (themed pools are distinct from each other
even when they overlap with THINK), and a sanity pass on every
label: printable, non-empty, not ending in an ellipsis (callers
append one) and not surrounded by whitespace.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from cantrip.ui import flavour


class TestPickActivityLabel:
    """``pick_activity_label`` returns valid, stable picks."""

    def test_seeded_pick_is_deterministic(self):
        first = flavour.pick_activity_label(seed=42)
        second = flavour.pick_activity_label(seed=42)
        assert first == second

    def test_different_seeds_can_produce_different_labels(self):
        # Not strictly guaranteed for two specific seeds, but the pool
        # is large enough that *somewhere* in a small sample we should
        # see at least two distinct picks — catches the degenerate
        # "always returns pool[0]" regression.
        picks = {flavour.pick_activity_label(seed=i) for i in range(50)}
        assert len(picks) > 1

    def test_string_seed_is_accepted(self):
        label = flavour.pick_activity_label(seed="cantrip")
        assert label in flavour.think_pool()

    def test_none_seed_picks_from_the_pool(self):
        label = flavour.pick_activity_label()
        assert label in flavour.think_pool()

    def test_default_category_is_think(self):
        # Same seed + default should equal same seed + explicit THINK.
        assert flavour.pick_activity_label(seed=123) == flavour.pick_activity_label(
            seed=123,
            category=flavour.ActivityCategory.THINK,
        )

    @pytest.mark.parametrize("category", list(flavour.ActivityCategory))
    def test_category_pick_belongs_to_its_pool(self, category):
        label = flavour.pick_activity_label(seed=7, category=category)
        assert label in flavour.category_pool(category)


class TestPoolSanity:
    """Every pool entry is safe to render into a status bar."""

    @pytest.fixture(
        params=list(flavour.ActivityCategory),
        ids=lambda c: c.value,
    )
    def labels(self, request):
        return flavour.category_pool(request.param)

    def test_no_duplicates_within_a_pool(self, labels):
        assert len(labels) == len(set(labels))

    def test_every_label_is_printable(self, labels):
        for label in labels:
            assert label.isprintable(), f"not printable: {label!r}"

    def test_every_label_is_non_empty(self, labels):
        for label in labels:
            assert label.strip(), f"empty or whitespace: {label!r}"

    def test_every_label_is_reasonably_short(self, labels):
        # Anything longer than 40 chars overflows narrow status bars
        # and wraps awkwardly in the Web indicator.
        for label in labels:
            assert len(label) <= 40, f"too long ({len(label)}): {label!r}"

    def test_labels_have_no_trailing_ellipsis(self, labels):
        # Callers append "..." themselves.  A pre-dotted pool would
        # double up on the status bar.
        for label in labels:
            assert not label.endswith(("...", "…", ".")), f"trailing dot: {label!r}"

    def test_labels_have_no_surrounding_whitespace(self, labels):
        for label in labels:
            assert label == label.strip(), f"whitespace cuff: {label!r}"

    def test_labels_are_capitalised(self, labels):
        # Every pool entry starts with an uppercase letter so the
        # rendered status bar reads like a real verb-phrase.  Callers
        # that need lowercase for e.g. inline text can downcase at the
        # call site.
        for label in labels:
            assert label[:1].isupper(), f"not capitalised: {label!r}"


class TestCategoryPoolsAreDistinct:
    """Themed pools differ from one another even when they overlap with THINK."""

    def test_research_pool_is_smaller_than_think(self):
        # The themed pools are tailored subsets with added divination
        # / forging flavour; they should be strictly narrower than the
        # catch-all.
        assert len(flavour.category_pool(flavour.ActivityCategory.RESEARCH)) < len(
            flavour.think_pool()
        )

    def test_build_pool_is_smaller_than_think(self):
        assert len(flavour.category_pool(flavour.ActivityCategory.BUILD)) < len(
            flavour.think_pool()
        )

    def test_research_and_build_pools_differ(self):
        # Some overlap is fine (e.g. both may include a generic
        # "Conjuring"), but the pools should not be identical — a
        # build phase that reads *scrying* would be confusing.
        research = set(flavour.category_pool(flavour.ActivityCategory.RESEARCH))
        build = set(flavour.category_pool(flavour.ActivityCategory.BUILD))
        assert research != build
        assert research - build  # research has at least one unique verb
        assert build - research


class TestJsPoolDrift:
    """Keep ``cantrip.js`` and ``flavour.think_pool()`` in sync.

    The Web UI picks a flavour client-side when the server broadcasts
    a ``thinking`` event, so the browser ships its own copy of the
    pool.  If the two diverge, the TUI and Web UI use different
    labels, which is exactly the thing this helper exists to avoid.
    """

    def _load_js_pool(self) -> list[str]:
        """Extract the FLAVOUR_POOL array from ``cantrip.js``.

        Parses the JS manually rather than importing a JS engine:
        the pool is a flat array of double-quoted strings, and a
        small regex does the job without adding a test dependency.
        """
        js_path = (
            pathlib.Path(__file__).resolve().parents[3]
            / "src"
            / "cantrip"
            / "web"
            / "static"
            / "cantrip.js"
        )
        text = js_path.read_text(encoding="utf-8")
        match = re.search(
            r"const FLAVOUR_POOL = \[(?P<items>.*?)\];",
            text,
            re.DOTALL,
        )
        assert match, "FLAVOUR_POOL constant not found in cantrip.js"
        items = match.group("items")
        # Each entry is `"…"` on its own line, possibly with a trailing comma.
        return re.findall(r'"([^"]+)"', items)

    def test_js_pool_matches_python_pool(self):
        python_pool = list(flavour.think_pool())
        js_pool = self._load_js_pool()
        assert js_pool == python_pool, (
            "cantrip.js FLAVOUR_POOL has drifted from flavour.think_pool(). "
            "Update both together so the TUI and Web UI pick from the same "
            "list of spells."
        )
