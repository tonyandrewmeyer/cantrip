"""GitHub ``CHANGELOG.md`` fetch and ``## <version>`` section extraction.

Used by :func:`cantrip.update.check.check_for_update` to attach release
notes to the :class:`UpdateInfo` it returns.  Failures degrade to
``None`` so a slow GitHub or a missing tag can't break the version
check itself.
"""

from __future__ import annotations

import logging
import os

import httpx
from packaging import version as pkg_version

import cantrip

log = logging.getLogger(__name__)


# Repo slug for fetching ``CHANGELOG.md`` at the matching tag.  An
# env-var override exists so tests don't hit the live GitHub raw
# endpoint.  The default mirrors the ``Repository`` field in
# ``pyproject.toml``.
_DEFAULT_REPO_SLUG = "tonyandrewmeyer/cantrip"
REPO_SLUG_ENV = "CANTRIP_UPDATE_REPO"
_CHANGELOG_URL_TEMPLATE = "https://raw.githubusercontent.com/{slug}/v{version}/CHANGELOG.md"

# Cap on the number of release-notes lines we keep in the cache so a
# pathological CHANGELOG can't bloat ``~/.cache/cantrip/update.json``
# beyond a few KB.  The UI layer applies its own (smaller) cap when
# rendering — this is just a safety net for the on-disk store.
_RELEASE_NOTES_LINE_CAP = 200


def _repo_slug() -> str:
    """Return the GitHub ``owner/repo`` slug for the changelog fetch."""
    return os.environ.get(REPO_SLUG_ENV) or _DEFAULT_REPO_SLUG


def _changelog_url(version: str) -> str:
    """Build the raw GitHub URL for ``CHANGELOG.md`` at the matching tag."""
    return _CHANGELOG_URL_TEMPLATE.format(slug=_repo_slug(), version=version)


async def fetch_changelog(version: str, *, timeout: float = 3.0) -> str | None:
    """Fetch the project's ``CHANGELOG.md`` at the ``v{version}`` tag.

    Returns the raw markdown body or ``None`` when:

    - The tag doesn't exist yet (a release landed on ``main`` but
      wasn't tagged — common for pre-releases).
    - The HTTP call fails for any reason (timeout, DNS, 404, parse).
    - The repo slug is missing or malformed.

    Failures log at DEBUG and never propagate so a slow GitHub can
    only suppress the inline release notes, never crash the check.
    """
    url = _changelog_url(version)
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": f"Cantrip/{cantrip.__version__}"},
        ) as client:
            response = await client.get(url)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.text
    except httpx.HTTPError as exc:
        log.debug("CHANGELOG fetch failed for %s: %s", version, exc)
        return None


def _normalise_section_version(heading_text: str) -> str | None:
    """Extract the version token from a ``## <version>`` heading body.

    The heading body may include trailers like ``— 2024-01-01`` or
    ``(2024-01-01)``; we keep only the leading token so it parses as
    a PEP 440 version.  Returns ``None`` when the leading token isn't
    a recognisable version (e.g. ``Unreleased``).
    """
    token = heading_text.strip().split()[0] if heading_text.strip() else ""
    # Strip a leading ``v`` so both ``## v1.0.0`` and ``## 1.0.0``
    # parse — some projects prefix every heading with ``v``.
    if token.startswith("v") or token.startswith("V"):
        token = token[1:]
    try:
        pkg_version.parse(token)
    except pkg_version.InvalidVersion:
        return None
    return token


def extract_release_notes(
    markdown: str,
    *,
    current: str,
    latest: str,
) -> list[tuple[str, str]]:
    """Return ``(version, body)`` sections strictly between *current* and *latest*.

    Walks ``## <version>`` headings line-by-line — no markdown-parser
    dependency.  ``## Unreleased`` (and any other unparseable heading
    body) is skipped: users upgrading to a tagged release shouldn't
    see post-release churn.

    Sections are returned newest-first.  The version range is
    ``current < section_version <= latest`` so the user sees notes
    for every release they're about to skip past, including the
    target itself.
    """
    try:
        current_parsed = pkg_version.parse(current)
        latest_parsed = pkg_version.parse(latest)
    except pkg_version.InvalidVersion:
        return []

    sections: list[tuple[str, list[str]]] = []
    current_section: tuple[str, list[str]] | None = None
    for line in markdown.splitlines():
        # Match exactly two leading hashes followed by a space — three
        # hashes is a subsection (``### Added``) which belongs in the
        # current section's body.
        if line.startswith("## ") and not line.startswith("### "):
            heading = line[3:]
            version = _normalise_section_version(heading)
            if version is None:
                # ``## Unreleased`` or any other non-version heading
                # ends the previous section without starting a new one.
                current_section = None
                continue
            current_section = (version, [])
            sections.append(current_section)
            continue
        if current_section is not None:
            current_section[1].append(line)

    relevant: list[tuple[str, str]] = []
    for version, body_lines in sections:
        try:
            section_parsed = pkg_version.parse(version)
        except pkg_version.InvalidVersion:
            continue
        if not (current_parsed < section_parsed <= latest_parsed):
            continue
        relevant.append((version, "\n".join(body_lines).strip("\n")))

    # Newest first.  ``packaging.version`` gives a total order, so
    # sorting by the parsed version is reliable across pre-releases.
    relevant.sort(key=lambda pair: pkg_version.parse(pair[0]), reverse=True)
    return relevant


def _format_release_notes(sections: list[tuple[str, str]]) -> str | None:
    """Stitch ``(version, body)`` sections back into one markdown blob.

    Returns ``None`` when the input is empty so the caller can store
    "no notes" as a real ``None`` in :class:`UpdateInfo` rather than
    an empty string that's awkward to test for.  Truncates to the
    cache-side line cap as a safety net against pathological
    changelogs; the UI layer applies its own (smaller) cap when
    rendering.
    """
    if not sections:
        return None
    blocks: list[str] = []
    for version, body in sections:
        blocks.append(f"## {version}\n\n{body}".rstrip())
    text = "\n\n".join(blocks)
    lines = text.splitlines()
    if len(lines) > _RELEASE_NOTES_LINE_CAP:
        truncated = lines[:_RELEASE_NOTES_LINE_CAP]
        truncated.append("")
        truncated.append(f"_… release notes truncated at {_RELEASE_NOTES_LINE_CAP} lines._")
        text = "\n".join(truncated)
    return text
