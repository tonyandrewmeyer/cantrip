"""Tests for the Web UI's server-side Markdown renderer."""

from cantrip.web import markdown as md_render


def test_empty_input_returns_empty_string() -> None:
    assert md_render.render("") == ""
    assert md_render.render(None) == ""  # type: ignore[arg-type]


def test_basic_inline_formatting() -> None:
    html = md_render.render("**bold** and *italic* and `code`")
    assert "<strong>bold</strong>" in html
    assert "<em>italic</em>" in html
    assert "<code>code</code>" in html


def test_nested_unordered_list() -> None:
    source = "- outer\n  - inner\n  - inner2\n- outer2"
    html = md_render.render(source)
    # Nested list must produce a nested <ul>.
    assert html.count("<ul>") >= 2


def test_asterisk_bullets_work() -> None:
    """Old regex renderer only handled ``- ``; ``*`` bullets now render."""
    html = md_render.render("* one\n* two")
    assert "<ul>" in html
    assert "<li>one</li>" in html
    assert "<li>two</li>" in html


def test_tables_render() -> None:
    source = "| a | b |\n|---|---|\n| 1 | 2 |"
    html = md_render.render(source)
    assert "<table>" in html
    assert "<th>a</th>" in html
    assert "<td>1</td>" in html


def test_links_render_with_href() -> None:
    html = md_render.render("[click](https://example.com)")
    assert '<a href="https://example.com">click</a>' in html


def test_bare_urls_autolink() -> None:
    """``linkify=True`` turns bare URLs into clickable links."""
    html = md_render.render("Visit https://example.com today")
    assert 'href="https://example.com"' in html


def test_images_render() -> None:
    html = md_render.render("![alt text](http://example.com/x.png)")
    assert "<img" in html
    assert 'src="http://example.com/x.png"' in html
    assert 'alt="alt text"' in html


def test_code_block_preserves_content() -> None:
    source = "```python\ndef foo():\n    pass\n```"
    html = md_render.render(source)
    assert "<pre>" in html
    assert "<code" in html
    assert "def foo():" in html


def test_raw_html_script_is_escaped() -> None:
    """Raw HTML is disabled; ``<script>`` must be escaped to text."""
    html = md_render.render("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_javascript_scheme_in_link_is_rejected() -> None:
    """``markdown-it-py`` refuses to parse ``javascript:`` URLs as links."""
    html = md_render.render("[xss](javascript:alert(1))")
    # The renderer falls back to treating the whole thing as plain
    # text when the URL is rejected, so no ``<a>`` tag pointing at
    # ``javascript:`` survives.  The literal substring may remain as
    # escaped text but never as an attribute value.
    assert 'href="javascript:' not in html
    assert "<a" not in html


def test_hard_breaks_inside_paragraph() -> None:
    """``breaks=True`` preserves single newlines as ``<br>``."""
    html = md_render.render("line one\nline two")
    assert "<br" in html


def test_strikethrough() -> None:
    html = md_render.render("~~deleted~~")
    assert "<s>deleted</s>" in html
