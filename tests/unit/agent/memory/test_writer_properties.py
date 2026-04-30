"""Property-based tests for ``memory.writer`` parser helpers.

The example tests in ``test_writer.py`` cover the named LLM-response
shapes we have seen in practice.  This file broadens that coverage in
two ways:

* arbitrary raw text must never crash ``parse_writer_response`` with an
  unexpected exception; it either returns a dict or raises
  ``ValueError``; and
* arbitrary JSON objects must round-trip through the three wrapper
  shapes the parser explicitly supports (bare JSON, fenced JSON, and
  prose around a bare object).
"""

from __future__ import annotations

import json

from hypothesis import given
from hypothesis import strategies as st

from cantrip.agent.memory.writer import parse_writer_response

_JSON_SCALAR = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.text(max_size=20),
)

_JSON_VALUE = st.recursive(
    _JSON_SCALAR,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(min_size=1, max_size=12), children, max_size=4),
    ),
    max_leaves=12,
)

_JSON_OBJECT = st.dictionaries(st.text(min_size=1, max_size=12), _JSON_VALUE, max_size=4)


class TestParseWriterResponseProperties:
    """Invariants of ``parse_writer_response`` over arbitrary input."""

    @given(raw=st.text(max_size=300))
    def test_arbitrary_text_returns_dict_or_value_error(self, raw: str) -> None:
        """Unexpected input must fail predictably, not with stray exceptions."""
        try:
            parsed = parse_writer_response(raw)
        except ValueError:
            return
        assert isinstance(parsed, dict)

    @given(payload=_JSON_OBJECT)
    def test_bare_json_round_trips(self, payload: dict[str, object]) -> None:
        """A bare JSON object parses back to the original payload."""
        assert parse_writer_response(json.dumps(payload)) == payload

    @given(payload=_JSON_OBJECT)
    def test_labelled_fence_round_trips(self, payload: dict[str, object]) -> None:
        """A `````json`` fence is unwrapped before decoding."""
        raw = f"```json\n{json.dumps(payload)}\n```"
        assert parse_writer_response(raw) == payload

    @given(payload=_JSON_OBJECT)
    def test_unlabelled_fence_round_trips(self, payload: dict[str, object]) -> None:
        """An unlabelled code fence behaves the same way."""
        raw = f"```\n{json.dumps(payload)}\n```"
        assert parse_writer_response(raw) == payload

    @given(payload=_JSON_OBJECT)
    def test_surrounding_prose_still_finds_object(self, payload: dict[str, object]) -> None:
        """The fallback object search tolerates explanatory prose around JSON."""
        raw = f"Decision follows:\n\n{json.dumps(payload)}\n\nThanks."
        assert parse_writer_response(raw) == payload
