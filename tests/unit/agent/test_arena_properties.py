"""Property-based tests for ``arena.parse_pick``.

The example tests in ``test_arena.py`` cover the canonical aliases.
This property test pins down the broader contract: classification
depends only on the stripped, lower-cased whole message.  We do not
want future "helpful" fuzzy matching to start treating arbitrary chat
messages as arena picks.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from cantrip.agent.race.arena import ArenaOutcome, parse_pick

_EXPECTED_BY_ALIAS = {
    "a": ArenaOutcome.PICKED_A,
    "pick a": ArenaOutcome.PICKED_A,
    "left": ArenaOutcome.PICKED_A,
    "b": ArenaOutcome.PICKED_B,
    "pick b": ArenaOutcome.PICKED_B,
    "right": ArenaOutcome.PICKED_B,
    "tie": ArenaOutcome.TIE,
    "equal": ArenaOutcome.TIE,
    "both": ArenaOutcome.TIE,
    "neither": ArenaOutcome.TIE,
    "t": ArenaOutcome.TIE,
    "skip": ArenaOutcome.SKIPPED,
    "cancel": ArenaOutcome.SKIPPED,
    "abort": ArenaOutcome.SKIPPED,
    "never mind": ArenaOutcome.SKIPPED,
}


class TestParsePickProperties:
    """Exact-match invariants for arena pick parsing."""

    @given(raw=st.text(max_size=100))
    def test_classification_depends_only_on_normalised_exact_alias(self, raw: str) -> None:
        """Only exact aliases should classify as picks after normalisation."""
        expected = _EXPECTED_BY_ALIAS.get(raw.strip().lower(), ArenaOutcome.UNRECOGNISED)
        assert parse_pick(raw) == expected
