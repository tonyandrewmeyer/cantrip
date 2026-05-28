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

    def test_early_creation_turns_are_tolerated(self):
        """The opening turns may create without read while the charm settles."""
        detector = CacheCascadeDetector()
        # Four creates with no read yet — under the chronic threshold,
        # so still quiet (warm-up is allowed).
        for _ in range(4):
            assert detector.observe(_create()) is None

    def test_chronic_miss_fires_when_cache_never_reads(self):
        """A cache that never reads trips the chronic warning at the threshold.

        This is the blind spot the original detector had: it latched on
        "have we ever read?" and so never fired for a cache that was
        broken from turn one.
        """
        detector = CacheCascadeDetector()
        # Four creates: under threshold, quiet.
        for _ in range(4):
            assert detector.observe(_create()) is None
        # The fifth consecutive create with no read ever trips it.
        warning = detector.observe(_create())
        assert warning is not None
        assert "never hit" in warning.lower()

    def test_chronic_warning_fires_only_once(self):
        """After the chronic warning fires, further creation turns stay quiet."""
        detector = CacheCascadeDetector()
        for _ in range(4):
            detector.observe(_create())
        assert detector.observe(_create()) is not None
        for _ in range(4):
            assert detector.observe(_create()) is None

    def test_a_read_during_warmup_prevents_chronic(self):
        """A read within the warm-up window latches the healthy path, not chronic.

        Once the cache reads even once, the chronic branch can never fire;
        only the cascade branch (was-reading-then-broke) applies.
        """
        detector = CacheCascadeDetector()
        detector.observe(_create())
        detector.observe(_create())
        detector.observe(_read())  # cache started working
        # Now four more creates: chronic can't fire (we have read), and
        # cascade needs only three — so this is the cascade path.
        assert detector.observe(_create()) is None
        assert detector.observe(_create()) is None
        warning = detector.observe(_create())
        assert warning is not None
        assert "cascade" in warning.lower()

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
