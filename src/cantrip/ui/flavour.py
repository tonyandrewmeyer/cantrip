"""Flavour-text helper for Cantrip's activity labels.

Cantrip is named after a *cantrip* — a small, quickly-cast spell —
and the software ships charms that run on *juju*.  Status copy
ignored that theme for the first two years of the project; this
module paints over it.  Surfaces that previously said
``"Thinking..."`` now get a randomly-picked spellcasting verb or
short phrase instead: *Conjuring…*, *Scrying…*, *Thumbing the
grimoire…*, and so on.

The pool is deliberately short, present-continuous, UK-English
friendly, and non-offensive.  No sinister "hexing" or "cursing"
(reads as aggression in neutral contexts), no innuendo, and no
appropriation of living magical traditions.  Per-category splits
let research-flavoured work lean on divination verbs and
build-flavoured work lean on forging verbs; :data:`ActivityCategory.THINK`
is the default broad pool used by every current call site.

The :func:`think_pool` accessor is public so the web frontend's
drift test can compare the Python pool against its JS mirror in
``src/cantrip/web/static/cantrip.js`` without importing the
private constants.
"""

from __future__ import annotations

import enum
import random


class ActivityCategory(enum.StrEnum):
    """Hint that narrows the flavour-label pool for a phase.

    :attr:`THINK` is the default — a broad pool used whenever a
    surface doesn't know what the agent is up to beyond "LLM is
    working".  The themed categories draw from smaller, tailored
    pools so a long research phase doesn't inadvertently read
    *forging the binding* and a build phase doesn't inadvertently
    read *consulting the stars*.
    """

    THINK = "think"
    RESEARCH = "research"
    BUILD = "build"


# Generic thinking pool.  Broad on purpose — shows up in the status
# bar whenever the agent is mid-turn and no more specific category
# is known.  Single words and short phrases are both fine; the
# renderer appends an ellipsis so entries should not include one.
_THINK_POOL: tuple[str, ...] = (
    "Incanting",
    "Invoking",
    "Conjuring",
    "Weaving the pattern",
    "Chanting softly",
    "Channelling",
    "Enchanting",
    "Murmuring to the circle",
    "Consulting the oracle",
    "Thumbing the grimoire",
    "Tracing sigils",
    "Drawing the pentagram",
    "Stirring the cauldron",
    "Threading the runes",
    "Whispering to the familiar",
    "Parting the veil",
    "Pondering the arcane",
    "Unrolling the scroll",
    "Checking the almanac",
    "Rifling through the spellbook",
    "Shuffling the tarot",
    "Lighting the candles",
    "Polishing the crystal",
    "Tuning the lute",
    "Counting the motes",
    "Casting bones on the table",
)


# Research leans on divination — peering, consulting, reading.
_RESEARCH_POOL: tuple[str, ...] = (
    "Scrying",
    "Divining",
    "Gazing into the crystal",
    "Peering through the veil",
    "Reading the stars",
    "Consulting the oracle",
    "Thumbing the grimoire",
    "Rifling through the spellbook",
    "Checking the almanac",
    "Unrolling the scroll",
    "Interpreting the omens",
    "Questioning the familiar",
)


# Build leans on forging and binding — making something concrete.
_BUILD_POOL: tuple[str, ...] = (
    "Brewing",
    "Binding",
    "Summoning",
    "Forging",
    "Setting the charm",
    "Weaving the pattern",
    "Conjuring",
    "Stitching the glyphs",
    "Pressing the seal",
    "Stoking the forge",
    "Quenching the blade",
    "Etching the ward",
)


_POOLS: dict[ActivityCategory, tuple[str, ...]] = {
    ActivityCategory.THINK: _THINK_POOL,
    ActivityCategory.RESEARCH: _RESEARCH_POOL,
    ActivityCategory.BUILD: _BUILD_POOL,
}


def pick_activity_label(
    seed: int | str | None = None,
    category: ActivityCategory = ActivityCategory.THINK,
) -> str:
    """Return a themed activity label for *category*.

    ``seed`` pins the random choice so tests can assert stable
    output; production callers pass ``None`` and get a fresh pick
    per invocation.  An unrecognised category falls back to the
    THINK pool rather than raising — a wrong hint is better
    surfaced as a generic label than a crash on the status bar.
    """
    pool = _POOLS.get(category, _THINK_POOL)
    rng = random.Random(seed)
    return rng.choice(pool)


def think_pool() -> tuple[str, ...]:
    """Return the generic THINK pool as a tuple.

    Public so the web frontend's drift test can compare the
    Python-side pool against its JavaScript mirror without
    reaching into module-private constants.
    """
    return _THINK_POOL


def category_pool(category: ActivityCategory) -> tuple[str, ...]:
    """Return the pool for *category* (read-only)."""
    return _POOLS.get(category, _THINK_POOL)


__all__ = [
    "ActivityCategory",
    "category_pool",
    "pick_activity_label",
    "think_pool",
]
