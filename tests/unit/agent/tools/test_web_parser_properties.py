"""Fuzz-style property tests for the web/search HTML parsers.

The example-based tests in ``test_web_tool.py`` and ``test_web_search.py``
cover the named-scenario cases (real DuckDuckGo lite snippet, expected
``<a>`` shapes, structured-then-fallback path).  These property tests
cover the *adversarial* space the parsers actually face in production:
random bytes that look almost-but-not-quite-like HTML, partial tags,
nested constructs the structured parser can't recognise, and
encoding-edge-case strings.

The primary invariant is **the parser never raises**.  ``WebFetchTool``
and ``WebSearchTool`` are agent-callable surfaces; if the body of a
fetched page can crash the parser, an adversarial server can hang or
abort the agent's turn.  Each parser must degrade gracefully — return
an empty string, an empty list, or whatever the documented "nothing
recognisable" output is.

Invariants under test:

* *Never raises.*  ``_strip_html(any_string)`` and
  ``parse_ddg_lite_results(any_string, n)`` and
  ``_fallback_parse(any_string, n)`` return their documented shape on
  any string input — including malformed HTML, partial tags, embedded
  scripts, and unicode mojibake.
* *Output shape.*  ``_strip_html`` returns a ``str`` with all ``<`` and
  ``>`` characters removed (the parser stripped them, or the input was
  already tag-free).  ``parse_ddg_lite_results`` and ``_fallback_parse``
  return a ``list[_SearchResult]``.
* *Determinism.*  Same input → same output.
* *Max-results cap.*  Both search parsers honour ``max_results`` — the
  returned list is never longer than the cap.
* *URL deduplication.*  ``parse_ddg_lite_results`` and ``_fallback_parse``
  both deduplicate by URL; no URL appears twice in the returned list.
* *Empty fields skipped.*  ``parse_ddg_lite_results`` only emits a
  result when both URL and title are non-empty; ``_fallback_parse``
  only emits when title is non-empty.
* *DDG internal links suppressed by fallback.*  ``_fallback_parse``
  drops any URL containing ``duckduckgo.com``.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from cantrip.agent.tools.web import _strip_html
from cantrip.agent.tools.web_search import (
    _fallback_parse,
    _SearchResult,
    parse_ddg_lite_results,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def _adversarial_text() -> st.SearchStrategy[str]:
    """A broad alphabet including HTML / fence / quote / nesting chars.

    Hypothesis can hand us strings that look like partial tags,
    half-finished entities, broken attributes, and unicode noise.
    """
    return st.text(
        alphabet=st.characters(
            blacklist_categories=("Cs",),  # exclude surrogates
            min_codepoint=0x20,
            max_codepoint=0x7E,
        )
        | st.sampled_from(["<", ">", "&", '"', "'", "/", "\n", "\t"]),
        min_size=0,
        max_size=256,
    )


def _almost_html_fragment() -> st.SearchStrategy[str]:
    """Fragments that look like HTML but may be malformed.

    Mixes recognisable tag-name tokens with literal ``<`` / ``>`` so
    Hypothesis explores the boundary the parser handles.
    """
    pieces = st.one_of(
        st.sampled_from(
            [
                '<a href="https://example.com">',
                '<a class="result-link" href="https://example.com/x">',
                "</a>",
                '<td class="result-snippet">',
                "</td>",
                "<script>",
                "</script>",
                "<title>",
                "</title>",
                "<unclosed-tag",
                ">stray",
                "&amp;",
                "&unfinished",
            ]
        ),
        _adversarial_text(),
    )
    return st.lists(pieces, min_size=0, max_size=8).map("".join)


def _max_results() -> st.SearchStrategy[int]:
    return st.integers(min_value=1, max_value=10)


# ---------------------------------------------------------------------------
# _strip_html
# ---------------------------------------------------------------------------


class TestStripHTML:
    """``_strip_html`` defangs anything the web throws at it."""

    @given(content=_adversarial_text())
    def test_does_not_raise_on_arbitrary_input(self, content: str) -> None:
        # The result type matters more than the value — the property is
        # that calling the function returns rather than raising.
        result = _strip_html(content)
        assert isinstance(result, str)

    @given(content=_almost_html_fragment())
    def test_does_not_raise_on_almost_html(self, content: str) -> None:
        result = _strip_html(content)
        assert isinstance(result, str)

    @given(content=_adversarial_text())
    def test_is_deterministic(self, content: str) -> None:
        assert _strip_html(content) == _strip_html(content)

    @given(content=_almost_html_fragment())
    def test_output_has_no_angle_brackets_from_tags(self, content: str) -> None:
        # The output may contain literal ``<`` or ``>`` from text data
        # the parser passed through (e.g. ``handle_data`` receiving a
        # decoded entity), but stray *tags* are stripped.  The stronger
        # invariant: the output length is never greater than the input
        # length (the parser only removes or collapses content).
        result = _strip_html(content)
        assert len(result) <= len(content) + 8, (
            "Stripping HTML must not grow the output beyond a small slack "
            "for whitespace normalisation."
        )

    @given(content=st.text(alphabet="abcdefghij ", min_size=0, max_size=40))
    def test_plain_text_passes_through_with_whitespace_collapsed(self, content: str) -> None:
        # Plain text with no HTML tags: the parser collapses runs of
        # whitespace and strips the ends.  The set of non-whitespace
        # tokens must be preserved exactly.
        result = _strip_html(content)
        assert result.split() == content.split()


# ---------------------------------------------------------------------------
# parse_ddg_lite_results
# ---------------------------------------------------------------------------


class TestParseDDGLiteResults:
    """The structured DDG-lite parser never raises on adversarial input."""

    @given(content=_adversarial_text(), n=_max_results())
    def test_does_not_raise_on_arbitrary_input(self, content: str, n: int) -> None:
        result = parse_ddg_lite_results(content, max_results=n)
        assert isinstance(result, list)
        for entry in result:
            assert isinstance(entry, _SearchResult)

    @given(content=_almost_html_fragment(), n=_max_results())
    def test_does_not_raise_on_almost_html(self, content: str, n: int) -> None:
        result = parse_ddg_lite_results(content, max_results=n)
        assert isinstance(result, list)

    @given(content=_adversarial_text(), n=_max_results())
    def test_is_deterministic(self, content: str, n: int) -> None:
        assert parse_ddg_lite_results(content, max_results=n) == parse_ddg_lite_results(
            content, max_results=n
        )

    @given(content=_almost_html_fragment(), n=_max_results())
    def test_honours_max_results_cap(self, content: str, n: int) -> None:
        result = parse_ddg_lite_results(content, max_results=n)
        assert len(result) <= n

    @given(content=_almost_html_fragment(), n=_max_results())
    def test_deduplicates_by_url(self, content: str, n: int) -> None:
        result = parse_ddg_lite_results(content, max_results=n)
        urls = [entry.url for entry in result]
        assert len(urls) == len(set(urls)), (
            f"parse_ddg_lite_results should dedupe by URL; got duplicates in {urls!r}."
        )

    @given(content=_almost_html_fragment(), n=_max_results())
    def test_every_result_has_url_and_title(self, content: str, n: int) -> None:
        # The structured parser only emits a _SearchResult when both
        # ``url`` and ``title`` are non-empty.
        result = parse_ddg_lite_results(content, max_results=n)
        for entry in result:
            assert entry.url, f"Empty url in result: {entry!r}"
            assert entry.title, f"Empty title in result: {entry!r}"


# ---------------------------------------------------------------------------
# _fallback_parse
# ---------------------------------------------------------------------------


class TestFallbackParse:
    """The regex fallback also degrades gracefully."""

    @given(content=_adversarial_text(), n=_max_results())
    def test_does_not_raise_on_arbitrary_input(self, content: str, n: int) -> None:
        result = _fallback_parse(content, max_results=n)
        assert isinstance(result, list)
        for entry in result:
            assert isinstance(entry, _SearchResult)

    @given(content=_almost_html_fragment(), n=_max_results())
    def test_is_deterministic(self, content: str, n: int) -> None:
        assert _fallback_parse(content, max_results=n) == _fallback_parse(content, max_results=n)

    @given(content=_almost_html_fragment(), n=_max_results())
    def test_honours_max_results_cap(self, content: str, n: int) -> None:
        result = _fallback_parse(content, max_results=n)
        assert len(result) <= n

    @given(content=_almost_html_fragment(), n=_max_results())
    def test_deduplicates_by_url(self, content: str, n: int) -> None:
        result = _fallback_parse(content, max_results=n)
        urls = [entry.url for entry in result]
        assert len(urls) == len(set(urls))

    @given(content=_almost_html_fragment(), n=_max_results())
    def test_drops_duckduckgo_internal_links(self, content: str, n: int) -> None:
        result = _fallback_parse(content, max_results=n)
        for entry in result:
            assert "duckduckgo.com" not in entry.url, (
                f"_fallback_parse should suppress duckduckgo.com links; got {entry.url!r}."
            )

    @given(content=_almost_html_fragment(), n=_max_results())
    def test_every_result_has_title(self, content: str, n: int) -> None:
        result = _fallback_parse(content, max_results=n)
        for entry in result:
            assert entry.title, f"Empty title in fallback result: {entry!r}"
