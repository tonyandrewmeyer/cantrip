"""Cache-behaviour anomaly detection for the LLM turn loop.

Motivated by Anthropic's April 23 Claude Code postmortem: a
state-management bug quietly forced every turn back into a
cache-creation pattern for a week before anyone connected the
cache-miss symptoms to the root cause.  Cantrip surfaces per-turn
prompt-cache usage passively (``ModelInfoBar``, ``/info``, session
summary) but has no active signal when the pattern turns pathological.

The detector watches the per-turn cache-creation / cache-read deltas
returned by the provider's ``usage`` dict and fires a warning in two
situations:

* **Cascade** — three consecutive turns of creation-without-read after
  a session that *was* previously reading from the cache.  That exact
  transition is the April 23 symptom: the cache was working and then
  silently stopped.

* **Chronic miss** — the cache has *never* produced a read after enough
  turns to rule out normal warm-up.  A single rolling tip write on turn
  one is expected, and the first few turns can legitimately re-create as
  the charm metadata settles; but a Claude session that keeps creating
  and never reads is almost certainly mis-caching (a system prompt below
  the minimum cacheable size, or a prefix that changes shape every
  turn).  The original detector latched on "have we ever read?" and so
  was blind to a cache that was broken from turn one.

A provider without prompt caching reports neither cache field, which
reads as "no cache activity" and never advances either counter, so it
is left alone.

The detector is deliberately stateless from the LLM's point of view —
it observes and warns, never blocks.  Callers decide whether to log,
surface a system message, or both.
"""

from __future__ import annotations

import dataclasses

# Number of consecutive creation-only turns that must follow a
# previously-read session before the cascade warning fires.  Chosen to
# match the roadmap spec (three consecutive turns) and to tolerate the
# one turn of cache creation that's normal after any system-prompt
# change or context swap.
_CASCADE_THRESHOLD = 3

# Number of creation-only turns with *no read ever* before the chronic
# warning fires.  Higher than the cascade threshold because the opening
# turns of a session legitimately re-create the prefix as the charm name,
# models, and environment flags settle; by this many turns a healthy
# cache should have started reading.
_CHRONIC_THRESHOLD = 5


@dataclasses.dataclass
class CacheCascadeDetector:
    """Rolling-window detector for prompt-cache cascades.

    Tracks just enough state to answer "has the cache, which was
    working, recently stopped working?" without holding onto the
    entire usage history.
    """

    _ever_read_from_cache: bool = False
    _creation_streak: int = 0
    _warned: bool = False

    def observe(self, usage: dict[str, int] | None) -> str | None:
        """Feed a provider usage dict.

        Returns a human-readable warning string the first time a cascade
        or a chronic miss is detected, or ``None`` on every other call.
        A provider whose response omits the two ``cache_*`` keys (e.g.
        Gemini today) never triggers the detector — missing fields read
        as "no cache activity", which advances neither counter.
        """
        if not usage:
            return None

        created = usage.get("cache_creation_input_tokens", 0) or 0
        read = usage.get("cache_read_input_tokens", 0) or 0

        if read > 0:
            # Happy path: we read from cache on this turn.  Reset the
            # creation streak and latch the "we've seen reads" flag
            # so the detector can trigger on subsequent cascades.
            self._ever_read_from_cache = True
            self._creation_streak = 0
            return None

        if created > 0:
            # Creation without read.  Normal on the first turn, on a
            # system-prompt change, or right after a compaction —
            # hence the streak requirement.
            self._creation_streak += 1
        else:
            # Neither read nor create — no prompt-cache activity this
            # turn (tool-only turn, streaming with partial usage,
            # provider without caching).  Don't penalise the streak.
            return None

        if self._warned:
            return None

        if self._ever_read_from_cache and self._creation_streak >= _CASCADE_THRESHOLD:
            self._warned = True
            return (
                "Prompt cache cascade detected: "
                f"{self._creation_streak} consecutive turns have re-created the "
                "cache after earlier turns were reading from it.  This usually "
                "means the system prompt or message prefix changed shape, which "
                "silently invalidates the cache and drives up token cost.  Check "
                "recent prompt / skill changes or provider parameters."
            )

        if not self._ever_read_from_cache and self._creation_streak >= _CHRONIC_THRESHOLD:
            self._warned = True
            return (
                "Prompt cache never hit: "
                f"{self._creation_streak} turns have re-created the cache and not "
                "one has read from it.  The cached prefix is probably below the "
                "model's minimum cacheable size, or the tools / system prompt are "
                "changing shape every turn — either way every turn is paying the "
                "full input rate.  Check the system-prompt size and whether the "
                "tools or prompt prefix are stable across turns."
            )
        return None

    def reset_warning(self) -> None:
        """Allow the detector to fire again on a fresh cascade."""
        self._warned = False
        self._creation_streak = 0
