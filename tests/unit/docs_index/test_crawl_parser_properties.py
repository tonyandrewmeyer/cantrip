"""Fuzz-style property tests for ``docs_index.crawl`` parsers.

The example-based tests in ``test_docs_index_pipeline.py`` cover named
sitemaps and HTML fragments.  These property tests pin the
*adversarial-input* contract — the parsers face HTML and XML from
arbitrary upstream Canonical doc sites, and the docs-index pipeline
must not crash on a malformed page.

Invariants under test:

* *``extract_html`` never raises.*  Any byte sequence — random,
  partial-tag-laden, encoding-broken — returns a ``(title, body)``
  tuple of two strings.  Decode errors degrade to ``("", "")`` per
  the documented contract.
* *``extract_html`` is deterministic.*  Same bytes → same output.
* *``extract_html`` body never contains unbalanced tag brackets from
  recognised tags.*  The HTMLParser strips known tags before
  appending text, so anything that came in as a real ``<p>`` /
  ``<script>`` etc. is gone from the output.
* *``parse_sitemap`` is deterministic on well-formed XML.*  Same
  bytes + same host → same URL list.
* *``parse_sitemap`` filters to host.*  Every returned URL has a
  hostname matching the *host* argument.
* *``parse_sitemap`` raises on malformed XML.*  The function
  documents ``ET.ParseError`` for unparseable bytes; callers treat
  that as a site-level error.  The property asserts the *signature*
  of the failure path — random non-XML bytes raise the documented
  exception type and never something else.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from hypothesis import given
from hypothesis import strategies as st

from cantrip.docs_index.crawl import extract_html, parse_sitemap

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def _adversarial_bytes() -> st.SearchStrategy[bytes]:
    """Arbitrary byte sequences — partial tags, broken UTF-8, control chars."""
    return st.binary(min_size=0, max_size=256)


def _almost_html_bytes() -> st.SearchStrategy[bytes]:
    """Byte sequences that mix recognisable HTML tokens with random text."""
    fragments = st.one_of(
        st.sampled_from(
            [
                b"<html>",
                b"</html>",
                b"<head>",
                b"<title>example</title>",
                b"<body>",
                b"<p>",
                b"</p>",
                b"<script>alert(1)</script>",
                b"<style>body{}</style>",
                b"<nav>nav</nav>",
                b"<header>head</header>",
                b"<footer>foot</footer>",
                b"<h1>hi</h1>",
                b"<unclosed-tag",
                b">",
                b"&amp;",
                b"\xff\xfe",  # encoding edge.
            ]
        ),
        st.binary(min_size=0, max_size=32),
    )
    return st.lists(fragments, min_size=0, max_size=8).map(b"".join)


def _hostname() -> st.SearchStrategy[str]:
    return st.sampled_from(["example.com", "docs.example.com", "canonical.example", "ops.io"])


def _well_formed_sitemap(host: str) -> st.SearchStrategy[bytes]:
    """Build a syntactically valid sitemap XML body for *host*.

    Mixes on-host URLs (should appear in output) with off-host URLs
    (should be filtered).  Both ``urlset`` and ``sitemapindex`` shapes
    are exercised.
    """

    def _build(
        on_host_paths: list[str],
        off_host_urls: list[str],
        kind: str,
    ) -> bytes:
        outer = "urlset" if kind == "urlset" else "sitemapindex"
        inner = "url" if kind == "urlset" else "sitemap"
        locs: list[str] = [
            f"<{inner}><loc>https://{host}{path}</loc></{inner}>" for path in on_host_paths
        ]
        locs.extend(f"<{inner}><loc>{url}</loc></{inner}>" for url in off_host_urls)
        body = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<{outer} xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{''.join(locs)}"
            f"</{outer}>"
        )
        return body.encode("utf-8")

    paths = st.lists(
        st.sampled_from(["/", "/docs", "/a", "/b", "/c/d", "/page-1", "/page-2"]),
        min_size=0,
        max_size=4,
    )
    off_host = st.lists(
        st.sampled_from(
            [
                "https://other.example/a",
                "https://elsewhere.io/b",
                "https://nothing.test/c",
            ]
        ),
        min_size=0,
        max_size=3,
    )
    kind = st.sampled_from(["urlset", "sitemapindex"])
    return st.builds(_build, paths, off_host, kind)


# ---------------------------------------------------------------------------
# extract_html invariants
# ---------------------------------------------------------------------------


class TestExtractHTML:
    """``extract_html`` is total — every byte input returns ``(str, str)``."""

    @given(payload=_adversarial_bytes())
    def test_does_not_raise_on_arbitrary_bytes(self, payload: bytes) -> None:
        title, body = extract_html(payload)
        assert isinstance(title, str)
        assert isinstance(body, str)

    @given(payload=_almost_html_bytes())
    def test_does_not_raise_on_almost_html(self, payload: bytes) -> None:
        title, body = extract_html(payload)
        assert isinstance(title, str)
        assert isinstance(body, str)

    @given(payload=_adversarial_bytes())
    def test_is_deterministic(self, payload: bytes) -> None:
        assert extract_html(payload) == extract_html(payload)

    def test_empty_bytes_returns_empty_tuple(self) -> None:
        title, body = extract_html(b"")
        assert title == ""
        assert body == ""

    @given(payload=_almost_html_bytes())
    def test_no_recognised_tag_tokens_in_body(self, payload: bytes) -> None:
        # Tokens like ``<script>``, ``<style>``, ``<nav>``, ``<footer>``,
        # ``<header>`` are members of ``_HTMLBodyExtractor._SKIP_TAGS`` and
        # are stripped along with their contents.  After extraction, the
        # body must not contain a literal ``<script`` substring (the
        # opener of a stripped tag), since handle_starttag consumed it.
        _, body = extract_html(payload)
        for tag in ("<script", "<style", "<nav", "<footer", "<header"):
            assert tag not in body.lower(), (
                f"Body should not retain stripped-tag opener {tag!r}; got {body!r}"
            )


# ---------------------------------------------------------------------------
# parse_sitemap invariants
# ---------------------------------------------------------------------------


class TestParseSitemapHostFilter:
    """``parse_sitemap`` filters URLs to the requested host."""

    @given(host=_hostname(), data=st.data())
    def test_well_formed_sitemap_returns_only_on_host_urls(
        self, host: str, data: st.DataObject
    ) -> None:
        payload = data.draw(_well_formed_sitemap(host))
        urls = parse_sitemap(payload, host=host)
        assert isinstance(urls, list)
        for url in urls:
            assert isinstance(url, str)
            # Every URL must be an on-host URL — the helper filters
            # off-host entries.  We allow any path on the matching
            # host (the parser keeps trailing-slash and depth as-is).
            assert f"://{host}" in url, f"parse_sitemap should only emit on-host URLs; got {url!r}"

    @given(host=_hostname(), data=st.data())
    def test_is_deterministic_on_well_formed_input(self, host: str, data: st.DataObject) -> None:
        payload = data.draw(_well_formed_sitemap(host))
        assert parse_sitemap(payload, host=host) == parse_sitemap(payload, host=host)


class TestParseSitemapMalformedRaises:
    """Random non-XML bytes raise ``ET.ParseError`` — the documented contract."""

    @given(payload=_adversarial_bytes())
    def test_random_bytes_raise_parse_error_or_succeed(self, payload: bytes) -> None:
        # Hypothesis can stumble onto an empty document or a
        # vacuously-well-formed payload.  The strong invariant is that
        # the only exception type the parser raises is
        # ``ET.ParseError``; anything else would break the documented
        # callers that catch precisely this type.
        try:
            urls = parse_sitemap(payload, host="example.com")
        except ET.ParseError:
            return  # Documented exception type — fine.
        # If it didn't raise, the output must still be a well-typed
        # list of strings, even when the XML happened to be parseable
        # but irrelevant.
        assert isinstance(urls, list)
        for url in urls:
            assert isinstance(url, str)

    @given(payload=_adversarial_bytes())
    def test_no_unexpected_exception_types(self, payload: bytes) -> None:
        # Belt-and-braces: anything other than ET.ParseError would
        # break callers.  Catch broadly and re-raise on surprise.
        try:
            parse_sitemap(payload, host="example.com")
        except ET.ParseError:
            return
        except Exception as exc:
            raise AssertionError(
                f"parse_sitemap raised unexpected {type(exc).__name__}: {exc!r}"
            ) from exc
