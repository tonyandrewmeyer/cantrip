"""Server-side Markdown rendering for Web UI chat messages.

Centralised so every ``chat_message`` broadcast goes through the same
renderer — we used to ship plain text and render with hand-rolled regex
in the browser, which missed tables, links, images, nested lists, and
``*`` bullets.  Rendering server-side means the frontend can ``innerHTML``
the result and the browser's regex parser never runs.

Security: raw HTML in Markdown is disabled (``html=False``), so
``<script>``, ``<iframe>``, etc. are escaped rather than passed through.
``markdown-it-py`` also normalises link URLs and strips ``javascript:``
schemes by default, so user-provided links can't execute code.
"""

import markdown_it

_MD = markdown_it.MarkdownIt(
    "commonmark",
    {
        # Disable raw HTML — assistant output is untrusted for HTML purposes.
        "html": False,
        # Auto-link bare URLs so ``https://example.com`` becomes clickable.
        "linkify": True,
        # Typographic quotes / dashes stay off: charm names and CLI flags
        # contain characters we don't want rewritten.
        "typographer": False,
        # Preserve hard line breaks inside paragraphs so agent responses
        # keep the newlines the LLM wrote.
        "breaks": True,
    },
).enable(["table", "strikethrough", "linkify"])


def render(text: str) -> str:
    """Render Markdown *text* to HTML.

    Returns an empty string for empty input so the caller can always
    inject the result into ``innerHTML`` without defensive checks.
    """
    if not text:
        return ""
    return _MD.render(text)
