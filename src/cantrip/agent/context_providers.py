"""Phase 72.2: ``@``-mention context-provider registry.

A user typing ``@diff`` or ``@file path/to/foo.py`` in the chat input
triggers expansion *before* the message reaches the agent: the typed
form gets replaced inline by the provider's contribution, capped at a
per-provider char budget.

Why expansion in the input layer and not as a tool call:

* **One fewer round trip.**  The agent sees a fully-expanded prompt
  and can plan against it immediately instead of issuing a tool call
  to read the same content.
* **Transcript records both forms.**  We log the typed form alongside
  the substituted content, so a user re-reading the session sees
  intent (``@file foo.py``) plus result.
* **Providers can wrap any read-only operation**, not just an existing
  ``Tool``.  ``@problems`` reuses
  :func:`cantrip.agent.lint_context.gather_project_diagnostics`
  directly without a ``Tool`` envelope.

Adding a provider: implement :class:`ContextProvider`, register it in
:func:`cantrip.agent.context_providers_builtin.build_default_registry`,
and add an entry to ``CONTEXT_PROVIDER_CATALOGUE`` so autocomplete
surfaces it.

Third-party providers register via :meth:`ProviderRegistry.register`
from a Phase 46 hook or Phase 45 MCP server bootstrap.
"""

from __future__ import annotations

import dataclasses
import enum
import logging
import re
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import pathlib

log = logging.getLogger(__name__)


# Identifier characters following ``@``.  Letters, digits, hyphen,
# underscore — deliberately excludes ``.`` so an email address like
# ``tony@example.com`` is not treated as a mention.
_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


class ArgStyle(enum.StrEnum):
    """Argument-consumption mode for a provider.

    * ``NONE`` — no arguments (``@diff``, ``@tree``, ``@problems``).
      Anything after the name stays in the surrounding text.
    * ``TOKEN`` — single whitespace-delimited token (``@file <path>``,
      ``@url <url>``, ``@charm <name>``).
    * ``REST_OF_LINE`` — everything to the next newline
      (``@docs <site> <query>``, ``@juju <subcmd>``).
    """

    NONE = "none"
    TOKEN = "token"
    REST_OF_LINE = "rest_of_line"


@dataclasses.dataclass(frozen=True, slots=True)
class ProviderInfo:
    """Public-facing metadata for a provider.

    Surfaced to autocomplete and ``/help``.  Kept separate from the
    expansion implementation so a UI can list providers without
    importing the heavy wrappers (juju, charmhub, webfetch).
    """

    name: str
    summary: str
    arg_style: ArgStyle
    args_hint: str = ""

    @property
    def display(self) -> str:
        """Render as ``@name <hint>`` for autocomplete rows."""
        if self.args_hint:
            return f"@{self.name} {self.args_hint}"
        return f"@{self.name}"


@dataclasses.dataclass(frozen=True, slots=True)
class ContextBlock:
    """The expanded contribution of one mention.

    ``rendered`` is what gets substituted into the message.  ``raw`` is
    the typed form preserved for the transcript.  ``truncated_chars``
    is how many characters were elided to fit the budget so the
    rendered footer can say "N more chars suppressed" honestly.
    ``error`` is non-empty only on failure; the inline rendering
    surfaces it so one broken mention does not abort the rest of the
    message.
    """

    raw: str
    rendered: str
    truncated_chars: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        """``True`` when the expansion succeeded."""
        return not self.error


@dataclasses.dataclass(frozen=True)
class ExpansionContext:
    """Runtime context exposed to providers during expansion.

    Limited surface — providers must not need to reach back into the
    agent object directly.  Fields cover what the baseline providers
    need; new fields are backwards-compatible additions with defaults.
    """

    repo_root: pathlib.Path | None = None
    charm_path: pathlib.Path | None = None


@runtime_checkable
class ContextProvider(Protocol):
    """Protocol every ``@``-provider implements."""

    info: ProviderInfo

    async def expand(self, args: str, ctx: ExpansionContext) -> ContextBlock:
        """Resolve *args* and return a :class:`ContextBlock`."""
        ...


class ProviderRegistry:
    """Mutable registry of ``@``-mention providers.

    A single instance is built at agent construction (with the
    baseline set) and passed to the input layer.  Phase 45 MCP and
    Phase 46 hooks may call :meth:`register` at startup to add
    third-party providers.
    """

    def __init__(self) -> None:
        self._providers: dict[str, ContextProvider] = {}

    def register(self, provider: ContextProvider) -> None:
        """Add *provider*, replacing any prior name match.

        Replacement is intentional — a third-party hook that wants to
        override a baseline provider (e.g. swap ``@diff`` for a
        repo-specific implementation) registers under the same name.
        """
        self._providers[provider.info.name] = provider

    def get(self, name: str) -> ContextProvider | None:
        """Return the provider named *name*, or ``None`` if unknown."""
        return self._providers.get(name)

    def names(self) -> tuple[str, ...]:
        """Sorted tuple of registered provider names (no leading ``@``)."""
        return tuple(sorted(self._providers))

    def catalogue(self) -> tuple[ProviderInfo, ...]:
        """All providers' :class:`ProviderInfo`, sorted by name."""
        return tuple(p.info for _, p in sorted(self._providers.items()))


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class _Mention:
    """One parsed mention with its position in the source string."""

    start: int
    end: int
    name: str
    args: str
    raw: str


def _scan_mentions(
    text: str,
    registry: ProviderRegistry,
) -> list[_Mention]:
    """Walk *text* once and return mentions that resolve to a registered provider.

    Skips:

    * ``@`` that is not at start-of-string or after whitespace, so an
      email (``tony@example.com``) is left alone.
    * Doubled ``@@`` — Phase 67.1 reserves these for thread refs.
    * Content inside triple-backtick fences and inline code spans —
      users routinely paste shell snippets containing ``@`` that are
      not mention syntax.
    * Names that do not match any registered provider — those stay
      verbatim so the message reads naturally if the user mistypes
      a name or means a literal ``@``.
    """
    out: list[_Mention] = []
    i = 0
    n = len(text)
    in_fence = False
    while i < n:
        ch = text[i]
        if ch == "`":
            if text.startswith("```", i):
                in_fence = not in_fence
                i += 3
                continue
            # Inline code span: skip to the matching backtick.
            j = text.find("`", i + 1)
            if j == -1:
                i += 1
                continue
            i = j + 1
            continue
        if in_fence:
            i += 1
            continue
        if ch != "@":
            i += 1
            continue

        # Word boundary: only at start-of-string or after whitespace.
        if i > 0 and not text[i - 1].isspace():
            i += 1
            continue

        # ``@@`` is reserved.  Skip the whole run so we don't reparse.
        if i + 1 < n and text[i + 1] == "@":
            j = i + 1
            while j < n and text[j] == "@":
                j += 1
            i = j
            continue

        match = _NAME_RE.match(text, i + 1)
        if match is None:
            i += 1
            continue
        name = match.group(0)
        provider = registry.get(name)
        if provider is None:
            # Unknown — leave verbatim, advance past the name so we
            # don't repeatedly fail to match the same span.
            i = match.end()
            continue

        style = provider.info.arg_style
        end = match.end()
        args = ""
        if style is ArgStyle.TOKEN:
            cursor = end
            while cursor < n and text[cursor] == " ":
                cursor += 1
            arg_start = cursor
            while cursor < n and not text[cursor].isspace():
                cursor += 1
            if cursor > arg_start:
                args = text[arg_start:cursor]
                end = cursor
        elif style is ArgStyle.REST_OF_LINE:
            cursor = end
            while cursor < n and text[cursor] == " ":
                cursor += 1
            line_end = text.find("\n", cursor)
            if line_end == -1:
                line_end = n
            candidate = text[cursor:line_end].rstrip()
            if candidate:
                args = candidate
                end = line_end

        out.append(
            _Mention(
                start=i,
                end=end,
                name=name,
                args=args,
                raw=text[i:end],
            )
        )
        i = end
    return out


# ---------------------------------------------------------------------------
# Truncation helpers (shared by providers)
# ---------------------------------------------------------------------------


# Conventional 4-chars-per-token estimate.  Tokenisers run a touch
# under, so the cap is conservative.  Used by providers that prefer to
# express budgets in tokens.
_CHARS_PER_TOKEN = 4


def chars_for_tokens(max_tokens: int) -> int:
    """Convert a token budget into a conservative character cap."""
    return max(0, max_tokens) * _CHARS_PER_TOKEN


def truncate(
    *,
    raw: str,
    rendered: str,
    max_chars: int,
    note: str = "",
) -> ContextBlock:
    """Return a :class:`ContextBlock` capped at *max_chars*.

    The footer mirrors the Phase 72.2 spec — keeps the user informed
    rather than silently dropping content.  *note* lets a provider
    add a follow-up hint (e.g. "use ``@file <path> --full`` to
    override") without rewriting the truncation arithmetic.
    """
    if max_chars <= 0 or len(rendered) <= max_chars:
        return ContextBlock(raw=raw, rendered=rendered)
    suffix_bits = ["[truncated {elided} chars]"]
    if note:
        suffix_bits.append(note)
    suffix_template = "\n\n" + " ".join(suffix_bits)
    # Reserve room for the rendered footer; cap body so total fits.
    elided_estimate = len(rendered) - max_chars
    placeholder = suffix_template.format(elided=elided_estimate)
    body_cap = max(0, max_chars - len(placeholder))
    body = rendered[:body_cap]
    elided = len(rendered) - len(body)
    return ContextBlock(
        raw=raw,
        rendered=body + suffix_template.format(elided=elided),
        truncated_chars=elided,
    )


# ---------------------------------------------------------------------------
# Expansion entry point
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ExpansionResult:
    """Outcome of expanding every mention in a user message.

    ``raw`` and ``expanded`` are both kept so the transcript can record
    both forms.  ``blocks`` lists each mention's contribution so a
    surface can render "expanded N mentions, K errors" if it wants.
    """

    raw: str
    expanded: str
    blocks: tuple[ContextBlock, ...]

    @property
    def changed(self) -> bool:
        """``True`` iff at least one mention expanded.

        Lets callers skip the transcript split when nothing changed —
        most messages contain no mentions, so ``raw`` and ``expanded``
        would be identical.
        """
        return self.raw != self.expanded

    def summary(self) -> str:
        """One-line description of expansion outcomes for the UI.

        Renders as ``@file foo.py (1.2k), @diff (340) [@boom: error]``.
        Intentionally compact — surfaces append it as a system note
        below the user's message, not as a chat bubble of its own.
        """
        if not self.blocks:
            return ""
        bits: list[str] = []
        for block in self.blocks:
            size = len(block.rendered)
            if block.error:
                bits.append(f"{block.raw} [error]")
                continue
            if size >= 1000:
                bits.append(f"{block.raw} ({size / 1000:.1f}k chars)")
            else:
                bits.append(f"{block.raw} ({size} chars)")
        return ", ".join(bits)


def _format_multiline(raw: str, rendered: str) -> str:
    """Wrap a multi-line block with a fence anchored to the typed form.

    Long expanded blocks otherwise blur into surrounding prose; the
    fence labels each contribution so the agent — and a human reader
    of the transcript — sees ``[@diff]`` … ``[/@diff]`` markers even
    when the rendered content contains code fences of its own.
    """
    return f"\n[{raw}]\n{rendered}\n[/{raw}]\n"


async def expand_mentions(
    text: str,
    registry: ProviderRegistry,
    ctx: ExpansionContext,
) -> ExpansionResult:
    """Replace every recognised ``@<name> [args]`` in *text* with its block.

    Order is preserved.  Unknown names are left verbatim — see
    :func:`_scan_mentions`.  Each provider's ``expand`` runs
    sequentially; the surface area of mentions per message is small
    enough that simplicity beats the debug cost of parallel calls.

    Errors raised by an individual provider are caught and surfaced
    inline as ``[@<name>: error: <msg>]`` so one broken mention does
    not abort the whole message.
    """
    mentions = _scan_mentions(text, registry)
    if not mentions:
        return ExpansionResult(raw=text, expanded=text, blocks=())

    parts: list[str] = []
    blocks: list[ContextBlock] = []
    cursor = 0
    for mention in mentions:
        parts.append(text[cursor : mention.start])
        provider = registry.get(mention.name)
        if provider is None:
            # Defence in depth — scanner already filters.
            parts.append(mention.raw)
            cursor = mention.end
            continue
        try:
            block = await provider.expand(mention.args, ctx)
        except Exception as exc:
            log.warning("@%s expansion failed: %s", mention.name, exc, exc_info=True)
            block = ContextBlock(
                raw=mention.raw,
                rendered=f"[@{mention.name}: error: {exc}]",
                error=str(exc),
            )
        blocks.append(block)
        if "\n" in block.rendered:
            parts.append(_format_multiline(mention.raw, block.rendered))
        else:
            parts.append(block.rendered)
        cursor = mention.end
    parts.append(text[cursor:])
    return ExpansionResult(
        raw=text,
        expanded="".join(parts),
        blocks=tuple(blocks),
    )
