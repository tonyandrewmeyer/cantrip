"""Tests for the prompt-cache cascade detector (Phase 78.1)."""

from cantrip.agent.cache_monitor import CacheCascadeDetector


def _read(n: int = 1000) -> dict[str, int]:
    """Usage dict shaped like a cache-read turn."""
    return {
        "prompt_tokens": n,
        "completion_tokens": 50,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": n,
    }


def _create(n: int = 1000) -> dict[str, int]:
    """Usage dict shaped like a cache-creation (miss) turn."""
    return {
        "prompt_tokens": n,
        "completion_tokens": 50,
        "cache_creation_input_tokens": n,
        "cache_read_input_tokens": 0,
    }


def _neither() -> dict[str, int]:
    """Usage dict with no cache activity at all (e.g. non-caching provider)."""
    return {
        "prompt_tokens": 100,
        "completion_tokens": 10,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


class TestCacheCascadeDetector:
    """Behavioural tests replicating the April 23 symptom."""

    def test_april_23_cascade_fires_after_three_creation_turns(self):
        """Three creation turns after at least one read fires the warning."""
        detector = CacheCascadeDetector()

        # Establish a cache-reading baseline.
        assert detector.observe(_read()) is None
        assert detector.observe(_read()) is None
        assert detector.observe(_read()) is None

        # First two creations are allowed — prompt changes can cause one
        # natural miss and we want to tolerate noise.
        assert detector.observe(_create()) is None
        assert detector.observe(_create()) is None

        # The third consecutive creation trips the detector.
        warning = detector.observe(_create())
        assert warning is not None
        assert "cascade" in warning.lower()

    def test_warning_fires_only_once(self):
        """After the warning fires, subsequent cascades stay quiet."""
        detector = CacheCascadeDetector()
        detector.observe(_read())
        detector.observe(_create())
        detector.observe(_create())
        first = detector.observe(_create())
        assert first is not None

        # Four more creation turns — should stay quiet, not retrigger
        # on every additional turn.
        for _ in range(4):
            assert detector.observe(_create()) is None

    def test_fresh_session_never_fires_without_prior_reads(self):
        """A session that has never read from the cache can't cascade.

        The detector only warns on the "was working, now failing"
        pattern — the first few turns after a prompt change are
        allowed to create without being flagged.
        """
        detector = CacheCascadeDetector()
        for _ in range(10):
            assert detector.observe(_create()) is None

    def test_read_turn_resets_streak(self):
        """A single read turn interrupts the creation streak."""
        detector = CacheCascadeDetector()
        detector.observe(_read())
        detector.observe(_create())
        detector.observe(_create())
        # One read between the second and third creation resets the
        # count; the next create should be a new streak of 1.
        detector.observe(_read())
        assert detector.observe(_create()) is None
        assert detector.observe(_create()) is None

    def test_no_cache_activity_does_not_count_against_streak(self):
        """A turn with zero cache activity neither creates nor reads."""
        detector = CacheCascadeDetector()
        detector.observe(_read())
        detector.observe(_create())
        detector.observe(_create())
        # Tool-only turn: neither creation nor read.  Doesn't advance
        # the streak, so this interleaving shouldn't trip the warning.
        assert detector.observe(_neither()) is None
        assert detector.observe(_create()) is not None  # now third create.

    def test_missing_usage_returns_none(self):
        """An empty or absent usage dict is treated as a no-op."""
        detector = CacheCascadeDetector()
        assert detector.observe(None) is None
        assert detector.observe({}) is None

    def test_partial_usage_without_cache_keys_returns_none(self):
        """A provider without cache fields (e.g. Gemini) never trips the detector."""
        detector = CacheCascadeDetector()
        bare = {"prompt_tokens": 500, "completion_tokens": 10}
        for _ in range(10):
            assert detector.observe(bare) is None

    def test_reset_warning_allows_refire(self):
        """``reset_warning`` clears both the one-shot latch and the streak."""
        detector = CacheCascadeDetector()
        detector.observe(_read())
        detector.observe(_create())
        detector.observe(_create())
        detector.observe(_create())  # first warning.

        detector.reset_warning()

        # New cascade can now fire after another three creates.
        assert detector.observe(_create()) is None
        assert detector.observe(_create()) is None
        assert detector.observe(_create()) is not None
