"""Chat widget for the TUI."""

import contextlib
import dataclasses
import datetime
from collections.abc import Sequence
from enum import StrEnum

from rich.console import Group, RenderableType
from rich.markdown import Markdown as RichMarkdown
from rich.markup import escape as rich_escape
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, Static

from cantrip.agent.commands.slash import CommandInfo
from cantrip.agent.context_providers import ProviderInfo
from cantrip.ui import flavour

# Duration below which a tool-block widget does not display the
# parenthesised timing — fast calls shouldn't clutter the chat.
_TOOL_BLOCK_DURATION_THRESHOLD_MS = 500


class MessageRole(StrEnum):
    """Role of a chat message."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"
    # Phase 69.3: ``Ctrl-X`` shell mode submissions land as ``SHELL``
    # messages.  They never reach the LLM — the agent's context rebuild
    # only restores rows whose role parses as a ``cantrip.llm.Role``,
    # and ``"shell"`` is deliberately not in that enum — so the cost is
    # zero tokens regardless of what the user typed.
    SHELL = "shell"


class MessageStatus(StrEnum):
    """Status of a message or action."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    ERROR = "error"


@dataclasses.dataclass
class ProgressItem:
    """A progress item within a message."""

    text: str
    status: MessageStatus = MessageStatus.PENDING


@dataclasses.dataclass
class ChatMessage:
    """A chat message."""

    role: MessageRole
    content: str
    timestamp: datetime.datetime = dataclasses.field(default_factory=datetime.datetime.now)
    progress_items: list[ProgressItem] = dataclasses.field(default_factory=list)
    # When true, ``content`` is rendered as Markdown instead of being
    # shown verbatim with Rich markup.  Used for system messages whose
    # body is generated markdown (e.g. the ``/feelings`` parliament
    # report) so headings, bold and list markers display as formatting
    # rather than raw ``#``/``**`` characters.  Search highlighting is
    # skipped for these messages — substituting Rich tags into a
    # Markdown source mangles the formatting.
    markdown: bool = False
    # Reasoning / chain-of-thought the provider exposed for this turn.
    # Claude's extended-thinking blocks and OpenAI-compatible
    # ``reasoning_content`` (Kimi K2, DeepSeek-R1 variants) both land
    # here.  Rendered as a dim ``💭 thinking`` preamble before the
    # answer so the user can tell whether reasoning tokens were spent
    # on their turn.
    reasoning: str = ""


class MessageWidget(Static):
    """Widget for a single chat message.

    Phase 108.1: per-role left-bars dropped from ``thick`` (3-cell
    block) down to ``tall`` (1-cell coloured stripe).  Halves the
    horizontal weight, stops the bar from eating wrap room in
    narrow terminals.
    """

    DEFAULT_CSS = """
    MessageWidget {
        padding: 0 1;
        margin: 1 0;
    }

    MessageWidget.user {
        background: $surface;
        border-left: tall $primary;
    }

    MessageWidget.assistant {
        border-left: tall $secondary;
    }

    MessageWidget.system {
        color: $text-muted;
        text-style: italic;
        border-left: tall $surface;
    }

    MessageWidget.tool {
        color: $text-muted;
        border-left: tall $accent;
        margin: 0;
        padding: 0 1;
    }

    MessageWidget.tool-failed {
        color: $error;
        border-left: tall $error;
    }

    MessageWidget.shell {
        color: $text-muted;
        border-left: tall $warning;
        margin: 0;
        padding: 0 1;
    }

    MessageWidget.shell-failed {
        color: $error;
        border-left: tall $error;
    }

    MessageWidget.shell-hidden {
        text-style: italic;
    }

    MessageWidget.tool-pending {
        color: $text-muted;
        border-left: tall $primary;
        text-style: dim;
    }

    MessageWidget .message-header {
        color: $text-muted;
        text-style: dim;
    }

    MessageWidget .message-content {
        margin-top: 1;
    }

    MessageWidget .progress-item {
        margin-left: 2;
    }

    MessageWidget .progress-pending {
        color: $text-muted;
    }

    MessageWidget .progress-in-progress {
        color: $primary;
    }

    MessageWidget .progress-complete {
        color: $success;
    }

    MessageWidget .progress-error {
        color: $error;
    }
    """

    def __init__(self, message: ChatMessage) -> None:
        """Initialise with a message."""
        super().__init__()
        self.message = message
        self.add_class(message.role.value)
        # Search highlighting state: query and which local match (0-indexed)
        # should be styled as the "active" match.  ``None`` means no search.
        self._search_query: str | None = None
        self._active_local_idx: int | None = None

    def compose(self) -> ComposeResult:
        """Compose the message widget."""
        yield Static(self._render_body(), id="message-body")

    def _render_body(self) -> RenderableType:
        """Build the Rich renderable for this message.

        Returns a plain Rich-markup string by default.  When the message
        is flagged as Markdown, returns a :class:`rich.console.Group`
        combining the header line and a :class:`rich.markdown.Markdown`
        renderable for the body so headings and emphasis render as
        formatting rather than literal ``#``/``**`` characters.
        """
        role_display = {
            MessageRole.USER: "> ",
            MessageRole.ASSISTANT: "",
            MessageRole.SYSTEM: "[system] ",
            MessageRole.TOOL: "",  # Caption carries its own glyph.
            MessageRole.SHELL: "",  # Body opens with ``$``/``$$`` prefix.
        }
        header = role_display.get(self.message.role, "")
        timestamp = self.message.timestamp.strftime("%H:%M")
        header = f"[dim][{timestamp}][/dim] {header}"

        reasoning_block = self._reasoning_markup()

        if self.message.markdown:
            progress_markup = "\n".join(
                f"[progress-{item.status.value.replace('_', '-')}]"
                f"{self._status_char(item.status)}"
                f"[/progress-{item.status.value.replace('_', '-')}] {item.text}"
                for item in self.message.progress_items
            )
            renderables: list[RenderableType] = [header]
            if reasoning_block:
                renderables.append(reasoning_block)
            renderables.append(RichMarkdown(self.message.content))
            if progress_markup:
                renderables.append(progress_markup)
            return Group(*renderables)

        # Plain (non-Markdown) bodies are concatenated into a Textual
        # markup string for the underlying Static.  The header and
        # reasoning paths already escape; the message content used to
        # be inserted raw, which crashed the entire TUI when text
        # contained brackets that look like a Textual tag — e.g. the
        # literal ``[/model]`` that ``/help`` renders to document
        # ``/model [provider[/model]]``.  Escape unconditionally on
        # the no-search path; the search path already escapes per
        # match in ``_highlighted_content``.  TOOL-role messages are
        # composed by ``add_tool_block`` which escapes the caller-
        # supplied caption itself before wrapping the duration suffix
        # in ``[dim]…[/dim]`` markup; escaping again here would render
        # those tags literally.
        if self.message.role in (MessageRole.TOOL, MessageRole.SHELL):
            # ``add_tool_block`` and ``add_shell_message`` both pre-escape
            # the user-supplied parts of the body and keep the dim/colour
            # markup as live tags; escaping again here would render those
            # tags literally.
            content = self.message.content
        else:
            content = (
                self._highlighted_content()
                if self._search_query
                else rich_escape(self.message.content)
            )
        content_lines = []
        if reasoning_block:
            content_lines.append(reasoning_block)
        content_lines.append(content)

        for item in self.message.progress_items:
            status_char = self._status_char(item.status)
            status_class = f"progress-{item.status.value.replace('_', '-')}"
            content_lines.append(
                f"[{status_class}]{status_char}[/{status_class}] {rich_escape(item.text)}"
            )

        return header + "\n".join(content_lines)

    def _reasoning_markup(self) -> str:
        """Return the dim chain-of-thought preamble, or ``""`` when absent."""
        reasoning = self.message.reasoning
        if not reasoning:
            return ""
        body = rich_escape(reasoning)
        return f"[dim italic]💭 thinking\n{body}[/dim italic]\n"

    def _highlighted_content(self) -> str:
        """Return message content with search matches wrapped in Rich tags.

        Escapes existing markup in ``message.content`` to avoid collisions
        with user/assistant text that happens to contain square brackets;
        this is acceptable because highlighting is active only while the
        search bar is open.
        """
        query = self._search_query or ""
        text = self.message.content
        if not query:
            return rich_escape(text)

        lower_text = text.lower()
        lower_query = query.lower()
        parts: list[str] = []
        cursor = 0
        local_idx = 0
        while True:
            pos = lower_text.find(lower_query, cursor)
            if pos < 0:
                parts.append(rich_escape(text[cursor:]))
                break
            parts.append(rich_escape(text[cursor:pos]))
            end = pos + len(query)
            # Active match uses a brighter style so the user can see which
            # occurrence is currently focused.
            style = "black on yellow" if local_idx == self._active_local_idx else "yellow reverse"
            parts.append(f"[{style}]{rich_escape(text[pos:end])}[/{style}]")
            cursor = end
            local_idx += 1
        return "".join(parts)

    def _rerender(self) -> None:
        """Re-render the message body.

        If the widget has been mounted but not yet composed (e.g. streaming
        chunks arrive on the same tick the message was added), the body
        Static won't exist yet; skip silently — the next ``compose()`` call
        will read the current ``message.content`` and render correctly.
        """
        try:
            body = self.query_one("#message-body", Static)
        except NoMatches:
            return
        body.update(self._render_body())

    def count_matches(self, query: str) -> int:
        """Return the number of case-insensitive occurrences of *query*."""
        if not query:
            return 0
        return self.message.content.lower().count(query.lower())

    def apply_highlight(self, query: str | None, active_local_idx: int | None) -> None:
        """Configure search highlighting and re-render."""
        self._search_query = query or None
        self._active_local_idx = active_local_idx
        self._rerender()

    def _status_char(self, status: MessageStatus) -> str:
        """Get status indicator character."""
        return {
            MessageStatus.PENDING: "○",
            MessageStatus.IN_PROGRESS: "⟳",
            MessageStatus.COMPLETE: "✓",
            MessageStatus.ERROR: "✗",
        }.get(status, "○")

    def update_progress(self, index: int, status: MessageStatus) -> None:
        """Update progress item status."""
        if 0 <= index < len(self.message.progress_items):
            self.message.progress_items[index].status = status
            self._rerender()

    def append_content(self, chunk: str) -> None:
        """Append a text chunk to the message content and re-render.

        Used by streaming responses to grow an in-progress message
        without creating a new widget per chunk.
        """
        if not chunk:
            return
        self.message.content += chunk
        self._rerender()


def _looks_like_traceback(content: str) -> bool:
    """Heuristic: does *content* look like a Python traceback?

    Used by :meth:`ChatWidget.add_system_message` to divert leaked
    tracebacks into the diagnostics log instead of showing them in
    the chat.  Matches the standard Python ``Traceback (most recent
    call last):`` preamble; handles the unicode arrow characters
    Python 3.11+ emits in error highlighting too.
    """
    if not content:
        return False
    needle = "Traceback (most recent call last)"
    return needle in content


def _filter_catalogue(catalogue: Sequence[CommandInfo], value: str) -> list[CommandInfo]:
    """Return catalogue entries whose verb starts with *value*.

    Empty or non-slash values yield no matches, so callers can treat the
    empty list as "nothing to suggest" without a separate null check.
    Matching is case-insensitive and strict-prefix — ``/c`` matches
    ``/cost`` but not ``/mcp``.
    """
    if not value.startswith("/") or " " in value or value == "":
        return []
    prefix = value.lower()
    return [cmd for cmd in catalogue if cmd.verb.lower().startswith(prefix)]


def _trailing_mention_prefix(value: str, cursor_pos: int) -> str | None:
    """Return the ``@<partial>`` segment being typed at *cursor_pos*.

    Used to drive the :class:`MentionSuggestions` popup mid-message:
    "look at @fi" with the cursor at the end yields ``"@fi"`` so the
    popup can offer ``@file``.

    Returns ``None`` when there is no trailing mention — including
    the cases where ``@`` is preceded by a non-space character (an
    email address), the segment contains whitespace (already
    completed), or ``@@`` (Phase 67.1 thread-ref reservation).
    """
    if cursor_pos <= 0 or cursor_pos > len(value):
        return None
    seg = value[:cursor_pos]
    at = seg.rfind("@")
    if at == -1:
        return None
    if at > 0 and not seg[at - 1].isspace():
        return None
    rest = seg[at + 1 :]
    if any(ch.isspace() for ch in rest):
        return None
    if "@" in rest:
        # ``@@`` is reserved.
        return None
    return seg[at:]


def _filter_mentions(
    catalogue: Sequence[ProviderInfo], value: str, cursor_pos: int
) -> tuple[list[ProviderInfo], str]:
    """Return ``(matches, prefix)`` for the trailing-mention popup.

    *prefix* is ``"@<partial>"`` so the input layer can replace exactly
    that span when a completion is accepted.  ``matches`` is empty
    when there is no trailing mention to complete.
    """
    prefix = _trailing_mention_prefix(value, cursor_pos)
    if prefix is None:
        return [], ""
    needle = prefix[1:].lower()  # drop the leading '@'
    matches = [info for info in catalogue if info.name.lower().startswith(needle)]
    return matches, prefix


class SlashCommandSuggestions(Widget):
    """Inline suggestion popup for slash commands.

    Rendered directly above :class:`ChatInput` so users typing ``/c`` see
    the ``/cost`` entry (and any other matches) without having to remember
    the full verb.  The widget is the single source of truth for which
    entry is "active" — Tab on the input reads :meth:`active` to know
    which verb to insert.

    The widget stays mounted at all times.  A ``-visible`` CSS class
    flips it between a collapsed (``display: none``) and expanded state
    so toggling is a one-liner and doesn't fight the compose tree.
    """

    DEFAULT_CSS = """
    SlashCommandSuggestions {
        display: none;
        height: auto;
        max-height: 8;
        background: $panel;
        border-top: solid $primary;
        border-bottom: solid $primary;
        padding: 0;
    }

    SlashCommandSuggestions.-visible {
        display: block;
    }

    SlashCommandSuggestions .suggestion-row {
        height: 1;
        padding: 0 1;
    }

    SlashCommandSuggestions .suggestion-row.-active {
        background: $accent;
        color: $text;
    }

    SlashCommandSuggestions .suggestion-row.-spare {
        display: none;
    }
    """

    def __init__(
        self,
        catalogue: Sequence[CommandInfo],
        *,
        id: str | None = None,
    ) -> None:
        """Initialise with the set of catalogue entries to draw from."""
        super().__init__(id=id)
        self._catalogue: list[CommandInfo] = list(catalogue)
        self._matches: list[CommandInfo] = []
        self._active_index: int = 0

    def compose(self) -> ComposeResult:
        """Mount one :class:`Static` row per catalogue entry.

        The rows are a pre-sized pool: we toggle the ``-spare`` class on
        rows past the current match count rather than re-mounting
        children on every keystroke.
        """
        for _ in range(max(len(self._catalogue), 1)):
            yield Static("", classes="suggestion-row -spare")

    def update_from_value(self, value: str) -> None:
        """Refilter against *value* and re-render; hide on zero matches."""
        matches = _filter_catalogue(self._catalogue, value)
        self._matches = matches
        if not matches:
            self._active_index = 0
            self.remove_class("-visible")
            self._render_rows()
            return
        if self._active_index >= len(matches):
            self._active_index = 0
        self.add_class("-visible")
        self._render_rows()

    @property
    def is_visible(self) -> bool:
        """Whether the popup is currently showing."""
        return self.has_class("-visible")

    @property
    def matches(self) -> tuple[CommandInfo, ...]:
        """Current match list (read-only copy)."""
        return tuple(self._matches)

    def active(self) -> CommandInfo | None:
        """Return the currently highlighted suggestion, or ``None``."""
        if not self.is_visible or not self._matches:
            return None
        return self._matches[self._active_index]

    def sole_match(self, value: str) -> CommandInfo | None:
        """Return the unique catalogue match for *value*, or ``None``.

        Independent of the popup's visibility — used by Tab to accept a
        single-match completion even when the popup was dismissed via
        Escape.
        """
        matches = _filter_catalogue(self._catalogue, value)
        return matches[0] if len(matches) == 1 else None

    def move(self, delta: int) -> None:
        """Move the active row by *delta*, wrapping at both ends."""
        if not self.is_visible or not self._matches:
            return
        self._active_index = (self._active_index + delta) % len(self._matches)
        self._render_rows()

    def hide(self) -> None:
        """Force the popup closed (e.g. on Escape)."""
        self._matches = []
        self._active_index = 0
        self.remove_class("-visible")
        self._render_rows()

    def _render_rows(self) -> None:
        """Push the current match list into the row pool.

        Rows beyond the match count get the ``-spare`` class so CSS
        hides them; active row gets ``-active`` for the highlight.
        """
        try:
            rows = list(self.query(".suggestion-row"))
        except NoMatches:
            return
        for idx, row in enumerate(rows):
            if idx >= len(self._matches):
                row.set_class(True, "-spare")
                row.set_class(False, "-active")
                if isinstance(row, Static):
                    row.update("")
                continue
            row.set_class(False, "-spare")
            row.set_class(idx == self._active_index, "-active")
            cmd = self._matches[idx]
            if isinstance(row, Static):
                verb = rich_escape(cmd.verb)
                summary = rich_escape(cmd.summary)
                row.update(f"{verb:<12} [dim]{summary}[/dim]")


class MentionSuggestions(Widget):
    """Inline suggestion popup for ``@``-mention context providers.

    Mirrors :class:`SlashCommandSuggestions` but for the ``@`` prefix.
    Triggers when the input has a trailing ``@<partial>`` segment at
    the cursor — e.g. typing "look at @fi" pops the ``@file`` match
    so Tab can complete it without breaking the rest of the message.

    The widget tracks the typed prefix (``self._prefix``) so the
    input layer can replace exactly that span on acceptance instead
    of overwriting the whole input.
    """

    DEFAULT_CSS = """
    MentionSuggestions {
        display: none;
        height: auto;
        max-height: 8;
        background: $panel;
        border-top: solid $primary;
        border-bottom: solid $primary;
        padding: 0;
    }

    MentionSuggestions.-visible {
        display: block;
    }

    MentionSuggestions .suggestion-row {
        height: 1;
        padding: 0 1;
    }

    MentionSuggestions .suggestion-row.-active {
        background: $accent;
        color: $text;
    }

    MentionSuggestions .suggestion-row.-spare {
        display: none;
    }
    """

    def __init__(
        self,
        catalogue: Sequence[ProviderInfo] = (),
        *,
        id: str | None = None,
    ) -> None:
        """Initialise with the given catalogue (may be empty until agent boot)."""
        super().__init__(id=id)
        self._catalogue: list[ProviderInfo] = list(catalogue)
        self._matches: list[ProviderInfo] = []
        self._active_index: int = 0
        self._prefix: str = ""

    def compose(self) -> ComposeResult:
        """Mount one row per catalogue entry, sized for the maximum the agent might supply."""
        # Pre-allocate generously: the catalogue grows dynamically when
        # third-party providers register, so size the pool above the
        # baseline count to avoid re-mounting children later.
        slots = max(len(self._catalogue), 12)
        for _ in range(slots):
            yield Static("", classes="suggestion-row -spare")

    def update_catalogue(self, catalogue: Sequence[ProviderInfo]) -> None:
        """Replace the catalogue (called once after agent boot, or on hook reload)."""
        self._catalogue = list(catalogue)

    def update_from_input(self, value: str, cursor_pos: int) -> None:
        """Refilter against *value* / *cursor_pos*; hide on zero matches."""
        matches, prefix = _filter_mentions(self._catalogue, value, cursor_pos)
        self._matches = matches
        self._prefix = prefix
        if not matches:
            self._active_index = 0
            self.remove_class("-visible")
            self._render_rows()
            return
        if self._active_index >= len(matches):
            self._active_index = 0
        self.add_class("-visible")
        self._render_rows()

    @property
    def is_visible(self) -> bool:
        """Whether the popup is currently showing."""
        return self.has_class("-visible")

    @property
    def matches(self) -> tuple[ProviderInfo, ...]:
        """Current match list (read-only copy)."""
        return tuple(self._matches)

    @property
    def prefix(self) -> str:
        """The typed ``@<partial>`` segment the popup is completing."""
        return self._prefix

    def active(self) -> ProviderInfo | None:
        """Return the currently highlighted suggestion, or ``None``."""
        if not self.is_visible or not self._matches:
            return None
        return self._matches[self._active_index]

    def move(self, delta: int) -> None:
        """Move the active row by *delta*, wrapping at both ends."""
        if not self.is_visible or not self._matches:
            return
        self._active_index = (self._active_index + delta) % len(self._matches)
        self._render_rows()

    def hide(self) -> None:
        """Force the popup closed (e.g. on Escape)."""
        self._matches = []
        self._active_index = 0
        self._prefix = ""
        self.remove_class("-visible")
        self._render_rows()

    def _render_rows(self) -> None:
        """Push the current match list into the row pool."""
        try:
            rows = list(self.query(".suggestion-row"))
        except NoMatches:
            return
        for idx, row in enumerate(rows):
            if idx >= len(self._matches):
                row.set_class(True, "-spare")
                row.set_class(False, "-active")
                if isinstance(row, Static):
                    row.update("")
                continue
            row.set_class(False, "-spare")
            row.set_class(idx == self._active_index, "-active")
            info = self._matches[idx]
            if isinstance(row, Static):
                display = rich_escape(info.display)
                summary = rich_escape(info.summary)
                row.update(f"{display:<24} [dim]{summary}[/dim]")


class ChatInput(Input):
    """Chat input with slash-command and ``@``-mention autocomplete.

    Previously ``/`` on an empty input opened search, but that shortcut
    swallowed the leading character of slash commands (``/help``,
    ``/memory``, ``/feelings``, …) and made them unreachable from the TUI.
    Search is now bound only to Ctrl+F; ``/`` is a normal character.

    Two suggestion popups can be bound: a :class:`SlashCommandSuggestions`
    for ``/`` verbs (active when the input is a single ``/<word>`` token)
    and a :class:`MentionSuggestions` for ``@`` context providers
    (active when the cursor sits at a trailing ``@<partial>`` segment).
    Up/Down/Tab/Escape route to whichever popup is currently visible —
    they are mutually exclusive in practice because the trigger
    conditions don't overlap.
    """

    # Phase 69.3: shell-mode placeholders.  Stored as class constants so
    # tests and the Ctrl-X handler agree on the exact prompt strings.
    AGENT_PLACEHOLDER = "Type your message..."
    SHELL_PLACEHOLDER = "$ shell command (Ctrl-X to leave shell mode)"

    class ShellModeChanged(Message):
        """Emitted whenever Ctrl-X flips the shell-mode flag.

        Lets ``CantripApp`` refresh the status bar / styling without
        ChatInput needing a back-reference to the surrounding screen.
        """

        def __init__(self, shell_mode: bool) -> None:
            super().__init__()
            self.shell_mode = shell_mode

    def __init__(self, *args, **kwargs) -> None:
        """Initialise with no bound suggestions widgets."""
        super().__init__(*args, **kwargs)
        self._suggestions: SlashCommandSuggestions | None = None
        self._mentions: MentionSuggestions | None = None
        # Tracks whether Enter routes to the shell helper or the agent.
        self.shell_mode: bool = False

    def toggle_shell_mode(self) -> bool:
        """Flip shell mode and update the prompt glyph / border in place.

        Returns the new ``shell_mode`` value so callers can publish a
        status-bar change in the same step.  Posts a
        :class:`ShellModeChanged` message regardless of direction so
        any listening surface stays in sync.
        """
        self.shell_mode = not self.shell_mode
        if self.shell_mode:
            self.add_class("-shell-mode")
            self.placeholder = self.SHELL_PLACEHOLDER
        else:
            self.remove_class("-shell-mode")
            self.placeholder = self.AGENT_PLACEHOLDER
        self.post_message(self.ShellModeChanged(self.shell_mode))
        return self.shell_mode

    def bind_suggestions(self, widget: SlashCommandSuggestions) -> None:
        """Attach the slash-command popup."""
        self._suggestions = widget

    def bind_mentions(self, widget: MentionSuggestions) -> None:
        """Attach the ``@``-mention popup."""
        self._mentions = widget

    def _accept_suggestion(self, cmd: CommandInfo) -> None:
        """Replace the input value with *cmd*'s verb plus a space."""
        self.value = f"{cmd.verb} "
        self.cursor_position = len(self.value)
        if self._suggestions is not None:
            self._suggestions.hide()

    def _accept_mention(self, info: ProviderInfo) -> None:
        """Replace the trailing ``@<partial>`` with ``@<name> ``.

        Surrounding text is preserved so the user can complete a
        mention mid-message without losing the prose they already typed.
        """
        if self._mentions is None:
            return
        prefix = self._mentions.prefix
        if not prefix:
            self._mentions.hide()
            return
        cursor = self.cursor_position
        head = self.value[: cursor - len(prefix)]
        tail = self.value[cursor:]
        replacement = f"@{info.name} "
        self.value = head + replacement + tail
        self.cursor_position = len(head) + len(replacement)
        self._mentions.hide()

    def _active_panel(
        self,
    ) -> SlashCommandSuggestions | MentionSuggestions | None:
        """Return the currently visible suggestion panel, if any."""
        if self._suggestions is not None and self._suggestions.is_visible:
            return self._suggestions
        if self._mentions is not None and self._mentions.is_visible:
            return self._mentions
        return None

    def on_key(self, event: events.Key) -> None:
        """Route arrow/Tab/Escape to the visible suggestion popup.

        Phase 69.3: ``Ctrl-X`` toggles shell mode regardless of any
        suggestion popup state.  The toggle takes precedence so the
        user can always escape back to the agent surface even with a
        slash-suggestion popup mid-keystroke.
        """
        if event.key == "ctrl+x":
            # Hide any popup before flipping — the suggestion catalogue
            # only makes sense for agent input.
            panel_open = self._active_panel()
            if panel_open is not None:
                panel_open.hide()
            self.toggle_shell_mode()
            event.stop()
            event.prevent_default()
            return

        panel = self._active_panel()
        key = event.key

        if key == "escape" and panel is not None:
            panel.hide()
            event.stop()
            event.prevent_default()
            return

        if key in {"up", "down"} and panel is not None:
            panel.move(-1 if key == "up" else 1)
            event.stop()
            event.prevent_default()
            return

        if key == "tab":
            if isinstance(panel, MentionSuggestions):
                info = panel.active()
                if info is not None:
                    self._accept_mention(info)
                    event.stop()
                    event.prevent_default()
                    return
            if self._suggestions is not None:
                cmd = self._suggestions.active() or self._suggestions.sole_match(self.value)
                if cmd is not None:
                    self._accept_suggestion(cmd)
                    event.stop()
                    event.prevent_default()


class SearchBar(Widget):
    """Search bar shown above the chat scroll area when searching is active.

    Holds its own ``Input`` and a status label showing match position.  Emits
    ``Changed`` whenever the query changes and ``Dismissed`` when the user
    presses Escape or Enter-with-empty-value.  Next/previous navigation is
    driven by the containing widget.
    """

    DEFAULT_CSS = """
    SearchBar {
        height: 1;
        display: none;
    }

    SearchBar.-visible {
        display: block;
    }

    SearchBar #search-row {
        height: 1;
    }

    SearchBar #search-input {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0;
        background: $boost;
    }

    SearchBar #search-status {
        width: auto;
        min-width: 14;
        height: 1;
        padding: 0 1;
        color: $text-muted;
        background: $boost;
    }
    """

    class Changed(Message):
        """Posted when the query text changes."""

        def __init__(self, query: str) -> None:
            super().__init__()
            self.query = query

    class Dismissed(Message):
        """Posted when the user dismisses the search bar."""

    class Navigate(Message):
        """Posted when the user requests the next/previous match."""

        def __init__(self, *, forward: bool) -> None:
            super().__init__()
            self.forward = forward

    def compose(self) -> ComposeResult:
        """Compose the search bar."""
        with Horizontal(id="search-row"):
            yield Input(placeholder="Search chat... (Enter: next, Esc: close)", id="search-input")
            yield Static("", id="search-status")

    def show(self) -> None:
        """Reveal and focus the search bar."""
        self.add_class("-visible")
        input_widget = self.query_one("#search-input", Input)
        input_widget.focus()

    def hide(self) -> None:
        """Hide the search bar and clear its query."""
        self.remove_class("-visible")
        self.query_one("#search-input", Input).value = ""
        self.set_status("")

    @property
    def is_open(self) -> bool:
        """Whether the search bar is currently shown."""
        return self.has_class("-visible")

    @property
    def query_text(self) -> str:
        """The current search text."""
        try:
            return self.query_one("#search-input", Input).value
        except NoMatches:
            return ""

    def set_status(self, text: str) -> None:
        """Update the match counter label."""
        with contextlib.suppress(NoMatches):
            self.query_one("#search-status", Static).update(text)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Propagate changes so the host can re-run the search."""
        if event.input.id == "search-input":
            event.stop()
            self.post_message(self.Changed(event.value))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter inside the search field jumps to the next match."""
        if event.input.id == "search-input":
            event.stop()
            self.post_message(self.Navigate(forward=True))

    def on_key(self, event) -> None:
        """Escape closes the search bar."""
        if not self.is_open:
            return
        if event.key == "escape":
            event.stop()
            self.post_message(self.Dismissed())


class ThinkingIndicator(Static):
    """On-brand thinking indicator (Phase 108.7).

    Replaces Textual's stock five-dot ``LoadingIndicator`` with a
    single-line phrase ``<spinner>  <verb>…`` rendered in
    ``$primary``.  The spinner cycles through a 10-frame braille
    pattern at 100 ms per frame; the verb is drawn from
    :func:`cantrip.ui.flavour.pick_activity_label` so the indicator
    is on-theme with the rest of Cantrip's "small spell" copy
    (Phase 62 / M62).

    The verb is picked once at mount time and stays stable for the
    lifetime of the indicator — a verb that changes mid-spin reads
    as decorative noise and undermines the implicit promise that
    the label tracks reality.  Per-phase verb rotation is a
    follow-up: the caller mounts a fresh indicator each phase,
    each fresh indicator picks a verb appropriate to its category.
    """

    # 10-frame braille spinner.  Smooth at 100 ms per frame; the
    # rotation is symmetric so cycle wrap-around isn't visible.
    _SPINNER_FRAMES: tuple[str, ...] = (
        "⠋",
        "⠙",
        "⠹",
        "⠸",
        "⠼",
        "⠴",
        "⠦",
        "⠧",
        "⠇",
        "⠏",
    )

    DEFAULT_CSS = """
    ThinkingIndicator {
        height: 1;
        padding: 0 1;
        margin: 1 0;
        color: $primary;
    }
    """

    def __init__(
        self,
        category: flavour.ActivityCategory = flavour.ActivityCategory.THINK,
        *,
        id: str | None = None,
    ) -> None:
        """Pick a verb up-front; defer mounting until ``compose``.

        ``id`` lets the host (``ChatWidget.show_thinking``) tag the
        widget so ``hide_thinking`` can find and remove it without
        keeping a back-reference.
        """
        super().__init__("", id=id)
        self._verb = flavour.pick_activity_label(category=category)
        self._frame_index = 0
        self._timer: object | None = None

    def on_mount(self) -> None:
        """Start the spinner timer and render the first frame.

        Held on ``self._timer`` so :meth:`on_unmount` can cancel
        it — without that, a stale timer keeps refreshing a removed
        widget and Textual logs a noisy ``NoMatches``.
        """
        self._refresh()
        self._timer = self.set_interval(0.1, self._tick)

    def on_unmount(self) -> None:
        """Cancel the spinner timer when the indicator is removed."""
        if self._timer is not None:
            with contextlib.suppress(Exception):
                self._timer.stop()
            self._timer = None

    def _tick(self) -> None:
        """Advance the spinner one frame and rerender."""
        self._frame_index = (self._frame_index + 1) % len(self._SPINNER_FRAMES)
        self._refresh()

    def _refresh(self) -> None:
        """Push the current ``<spinner>  <verb>…`` content into the Static."""
        glyph = self._SPINNER_FRAMES[self._frame_index]
        # ``rich_escape`` keeps the verb safe in case the catalogue
        # ever grows an entry with stray markup-look-alike brackets.
        self.update(f"{glyph}  {rich_escape(self._verb)}…")

    @property
    def verb(self) -> str:
        """The current verb label (for tests / drift assertions)."""
        return self._verb


class ChatWidget(Widget):
    """Widget for chat history and input.

    Phase 108.1: the chat-history frame is gone.  The per-message
    left-bars already differentiate roles; the surrounding box was
    pure double-chrome and stole horizontal real estate.
    """

    class SearchClosed(Message):
        """Posted when the user dismisses the search bar."""

    DEFAULT_CSS = """
    ChatWidget {
        height: 100%;
    }

    ChatWidget #chat-history {
        height: 1fr;
        padding: 1;
    }

    ChatWidget #chat-scroll {
        height: 1fr;
    }

    ChatWidget .welcome-message {
        padding: 1 0;
    }

    /* Phase 108.2: the wordmark is the title; ``$primary`` tints
     * it on-brand (Ubuntu orange under the default theme).  The
     * body and examples drop down to neutral text so the eye lands
     * on the mark first. */
    ChatWidget .welcome-wordmark {
        color: $primary;
        text-style: bold;
        padding-bottom: 0;
    }

    ChatWidget .welcome-body {
        padding-bottom: 1;
    }

    ChatWidget .welcome-examples {
        padding-bottom: 1;
    }

    ChatWidget .welcome-footer {
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs) -> None:
        """Initialise the chat widget."""
        super().__init__(**kwargs)
        self._messages: list[ChatMessage] = []
        # Flattened list of (message_widget, local_match_index) pairs for the
        # current search query, rebuilt on every query change.
        self._match_index: list[tuple[MessageWidget, int]] = []
        self._active_match: int = 0
        # Phase 82: tool-call-id → pending tool block widget, so a
        # later TOOL_INVOKED can replace the spinner caption with the
        # post-call summary in place rather than appending a new line.
        self._pending_tool_blocks: dict[str, MessageWidget] = {}

    def compose(self) -> ComposeResult:
        """Compose the chat widget."""
        with Vertical(id="chat-history"):
            yield SearchBar(id="search-bar")
            yield ScrollableContainer(id="chat-scroll")

    def on_mount(self) -> None:
        """Handle mount."""
        self._show_welcome()

    # Phase 108.2: 2-row block-letter wordmark replaces the plain
    # "Welcome to Cantrip" title.  Hand-built from the half-block
    # character set so it renders cleanly in any monospace terminal
    # (no figlet dependency, no font fallback) and stays under 30
    # columns wide so the 80-column smoke snapshot does not wrap.
    # The leading two-space indent matches the example list below
    # for vertical alignment.
    _WORDMARK = "  █▀▀ ▄▀█ █▄ █ ▀█▀ █▀▄ █ █▀█\n  █▄▄ █▀█ █ ▀█  █  █▀▄ █ █▀▀"

    def _show_welcome(self) -> None:
        """Show welcome message.

        Tiered layout: a 2-row block-letter wordmark in ``$primary``
        (Phase 108.2), a one-line description, a short list of
        example prompts, and a muted footer of keyboard shortcuts.
        The examples deliberately showcase Cantrip's range — fresh
        workload, upstream source URL, and improve-an-existing-charm —
        rather than workloads that already have first-class Charmhub
        charms (postgres, mysql, redis), which are better off reused.
        """
        scroll = self.query_one("#chat-scroll", ScrollableContainer)
        scroll.mount(
            Static(
                self._WORDMARK,
                classes="welcome-message welcome-wordmark",
            )
        )
        scroll.mount(
            Static(
                "Describe a workload and I'll build a production-ready "
                "Juju charm for it — scaffold, code, test, and deploy.",
                classes="welcome-message welcome-body",
            )
        )
        scroll.mount(
            Static(
                "Try asking:\n"
                "  \u203a build a charm for my Flask app at ./backend\n"
                "  \u203a charm Overleaf, the collaborative LaTeX editor\n"
                "  \u203a build from https://github.com/example/cool-service\n"
                "  \u203a improve the charm in ./my-charm",
                classes="welcome-message welcome-examples",
            )
        )
        scroll.mount(
            Static(
                "F1 help  \u00b7  /help commands  \u00b7  q quit",
                classes="welcome-message welcome-footer",
            )
        )

    def add_message(self, message: ChatMessage) -> MessageWidget:
        """Add a message to the chat."""
        self._messages.append(message)

        scroll = self.query_one("#chat-scroll", ScrollableContainer)

        # Clear welcome message on first real message
        if len(self._messages) == 1:
            scroll.remove_children()

        widget = MessageWidget(message)
        scroll.mount(widget)
        scroll.scroll_end(animate=False)

        return widget

    def add_user_message(self, content: str) -> MessageWidget:
        """Add a user message."""
        return self.add_message(ChatMessage(role=MessageRole.USER, content=content))

    def add_assistant_message(
        self,
        content: str,
        progress_items: list[str] | None = None,
        *,
        reasoning: str = "",
    ) -> MessageWidget:
        """Add an assistant message with optional progress items and reasoning."""
        items = [ProgressItem(text=item) for item in (progress_items or [])]
        return self.add_message(
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content=content,
                progress_items=items,
                reasoning=reasoning,
            )
        )

    def set_reasoning(self, widget: MessageWidget, reasoning: str) -> None:
        """Attach reasoning text to an existing message widget and re-render.

        Streaming agent responses arrive content-first; reasoning is
        accumulated alongside and surfaces at the end of the turn
        (Claude extended thinking, Kimi K2 ``reasoning_content``).
        Callers pump chunks via :meth:`append_streaming_chunk` and then
        call this once to bolt the reasoning onto the same widget.
        """
        if not reasoning:
            return
        widget.message.reasoning = reasoning
        widget._rerender()

    def add_system_message(
        self,
        content: str,
        progress_items: list[str] | None = None,
        *,
        markdown: bool = False,
    ) -> MessageWidget:
        """Add a system message with optional progress items.

        Pass ``markdown=True`` when ``content`` is a Markdown document
        (headings, lists, emphasis) so it renders as formatting instead
        of raw syntax — used for the ``/feelings`` parliament report.

        If *content* looks like a Python traceback (a developer
        artifact that should never make it into the chat), the body
        is replaced with a friendly notice and the original is
        appended to the diagnostics log so a developer can review it
        later.  This is a last-resort safety net — every code path
        that surfaces an exception should already route through
        ``cantrip.diagnostics.report_internal_error``.
        """
        if _looks_like_traceback(content):
            from cantrip import diagnostics

            log_path = diagnostics.log_path()
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(
                        "\n"
                        + "=" * 72
                        + "\n"
                        + datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
                        + "  chat-leaked traceback\n"
                        + "-" * 72
                        + "\n"
                        + content
                        + "\n"
                    )
            except OSError:
                pass
            content = (
                f"Sorry, something went wrong.  The full traceback was written "
                f"to `{log_path}` — please share that file when reporting the issue."
            )
        items = [ProgressItem(text=item) for item in (progress_items or [])]
        return self.add_message(
            ChatMessage(
                role=MessageRole.SYSTEM,
                content=content,
                progress_items=items,
                markdown=markdown,
            )
        )

    def add_tool_block(
        self,
        caption: str,
        *,
        success: bool,
        duration_ms: int | None = None,
        tool_call_id: str | None = None,
    ) -> MessageWidget:
        """Add a compact tool-invocation block to the chat (Phase 75).

        Rendered between agent messages so the user can see *what the
        agent just did* without opening the transcript viewer.  Keeps
        the trailing-colon preambles from reading as broken speech —
        the colon is now followed by a visible tool block.

        ``caption`` is the one-line human summary the agent's
        ``TOOL_INVOKED`` event carries.  ``success=False`` recolours
        the block's left border to the error colour and swaps the
        leading glyph.  ``duration_ms`` is appended in parentheses
        when supplied so slow calls stand out.

        Phase 82: when ``tool_call_id`` matches a pending block added
        earlier via :meth:`add_pending_tool_block`, the pending block
        is updated *in place* rather than appending a new line — so
        the user sees one block per tool call (spinner → result),
        not two.
        """
        if tool_call_id is not None and tool_call_id in self._pending_tool_blocks:
            return self.resolve_tool_block(
                tool_call_id,
                caption,
                success=success,
                duration_ms=duration_ms,
            )
        glyph = "🔧" if success else "✗"
        suffix = ""
        if duration_ms is not None and duration_ms >= _TOOL_BLOCK_DURATION_THRESHOLD_MS:
            suffix = f" [dim]({duration_ms} ms)[/dim]"
        content = f"{glyph} {rich_escape(caption)}{suffix}"
        widget = self.add_message(
            ChatMessage(
                role=MessageRole.TOOL,
                content=content,
            )
        )
        if not success:
            widget.add_class("tool-failed")
        return widget

    def add_pending_tool_block(
        self,
        caption: str,
        *,
        tool_call_id: str,
    ) -> MessageWidget:
        """Add a "running now" tool block tagged with ``tool_call_id`` (Phase 82).

        Mirrors :meth:`add_tool_block` but uses a spinner glyph
        (``⟳``) and the dim ``tool-pending`` class so the user can
        tell at a glance the call hasn't finished yet.  The matching
        :meth:`resolve_tool_block` call (when the post-call event
        arrives) updates this same widget in place rather than adding
        a second chat line.

        Replacing a pending block for the same id is a no-op — we
        keep the existing widget so a stray duplicate event never
        leaks an orphan spinner.
        """
        existing = self._pending_tool_blocks.get(tool_call_id)
        if existing is not None:
            return existing
        content = f"⟳ {rich_escape(caption)}"
        widget = self.add_message(
            ChatMessage(
                role=MessageRole.TOOL,
                content=content,
            )
        )
        widget.add_class("tool-pending")
        self._pending_tool_blocks[tool_call_id] = widget
        return widget

    def resolve_tool_block(
        self,
        tool_call_id: str,
        caption: str,
        *,
        success: bool,
        duration_ms: int | None = None,
    ) -> MessageWidget:
        """Replace a pending tool block in place with its post-call form (Phase 82).

        Looks up the widget registered by
        :meth:`add_pending_tool_block`, rewrites its caption, swaps
        the spinner glyph for the success / failure indicator, and
        drops the ``tool-pending`` class.  If no pending block is
        registered for *tool_call_id* (renderer started after the
        pending event, or the agent crashed mid-call), falls back to
        :meth:`add_tool_block` so the user still sees *something*.
        """
        widget = self._pending_tool_blocks.pop(tool_call_id, None)
        if widget is None:
            return self.add_tool_block(
                caption,
                success=success,
                duration_ms=duration_ms,
            )
        glyph = "🔧" if success else "✗"
        suffix = ""
        if duration_ms is not None and duration_ms >= _TOOL_BLOCK_DURATION_THRESHOLD_MS:
            suffix = f" [dim]({duration_ms} ms)[/dim]"
        widget.message.content = f"{glyph} {rich_escape(caption)}{suffix}"
        widget.remove_class("tool-pending")
        if success:
            widget.remove_class("tool-failed")
        else:
            widget.add_class("tool-failed")
        # ``_rerender`` is a no-op pre-mount; the next compose pass
        # picks up the updated content from ``message.content``.
        widget._rerender()
        return widget

    def add_shell_message(
        self,
        argv: Sequence[str],
        *,
        output: str,
        exit_code: int,
        hidden_from_agent: bool = False,
    ) -> MessageWidget:
        """Add a Phase 69.3 shell-mode block to the chat.

        Renders a ``$ cmd`` prompt followed by the captured output.  The
        block is visually distinct from agent tool calls (warning-tinted
        left border) so the user can see at a glance that this line was
        their own keystroke, not a model action.  ``hidden_from_agent``
        switches to the ``$$`` prompt and italicises the body so the
        incognito state is visible — the same flag also rides on the
        persisted metadata so future context-assembly can filter the
        row out cleanly.
        """
        prompt_glyph = "$$" if hidden_from_agent else "$"
        cmd_text = rich_escape(" ".join(argv))
        if hidden_from_agent:
            header = f"[dim]{prompt_glyph}[/dim] [italic]{cmd_text}[/italic]"
        else:
            header = f"[dim]{prompt_glyph}[/dim] {cmd_text}"
        body = rich_escape(output.rstrip()) if output else "[dim](no output)[/dim]"
        if exit_code != 0:
            body = f"{body}\n[dim]exit {exit_code}[/dim]"
        content = f"{header}\n{body}"
        widget = self.add_message(ChatMessage(role=MessageRole.SHELL, content=content))
        if exit_code != 0:
            widget.add_class("shell-failed")
        if hidden_from_agent:
            widget.add_class("shell-hidden")
        return widget

    def scrub_pending_tool_blocks(self) -> int:
        """Resolve any orphan pending blocks as cancelled (Phase 82).

        Called from the TUI when a turn ends without a matching
        ``TOOL_INVOKED`` for every ``TOOL_INVOKED_PENDING`` — typically
        because the user cancelled mid-tool or the dispatcher raised.
        Each orphan turns into a failed tool block carrying a
        ``cancelled`` caption so the chat never leaves a dangling
        spinner.  Returns the number of blocks scrubbed.
        """
        if not self._pending_tool_blocks:
            return 0
        # Materialise the keys before mutation: ``resolve_tool_block``
        # pops from the same dict.
        ids = list(self._pending_tool_blocks)
        for tcid in ids:
            self.resolve_tool_block(tcid, "cancelled", success=False)
        return len(ids)

    def append_streaming_chunk(self, widget: MessageWidget, chunk: str) -> None:
        """Append *chunk* to *widget* and keep the scroll pinned to the bottom.

        The caller typically obtains *widget* from ``add_assistant_message("")``
        before streaming begins, then pumps chunks in via this method as they
        arrive from ``process_message_streaming``.
        """
        widget.append_content(chunk)
        scroll = self.query_one("#chat-scroll", ScrollableContainer)
        scroll.scroll_end(animate=False)

    def remove_message(self, widget: MessageWidget) -> None:
        """Remove a message widget from the chat."""
        if widget.message in self._messages:
            self._messages.remove(widget.message)
        widget.remove()

    def show_thinking(
        self,
        category: flavour.ActivityCategory = flavour.ActivityCategory.THINK,
    ) -> None:
        """Show an animated thinking indicator in the chat area.

        Phase 108.7: replaces Textual's stock ``LoadingIndicator``
        (five pulsing dots) with a single-line on-brand
        :class:`ThinkingIndicator` — braille spinner plus a flavour
        verb drawn from ``cantrip.ui.flavour``.  Caller passes
        ``category`` to bias the verb pool (research / build /
        default think); ``ChatWidget`` itself doesn't track the
        agent's phase, so the simple shape is "fresh indicator
        each phase = fresh verb".

        Short-circuits when an indicator is already mounted: ``the
        agent is thinking`` is a single state, so a second call
        without an intervening :meth:`hide_thinking` is treated as
        idempotent.  Avoids a ``DuplicateIds`` race when
        ``widget.remove()`` (which is scheduled, not synchronous)
        hasn't completed before the next mount.
        """
        if self.query(ThinkingIndicator):
            return
        scroll = self.query_one("#chat-scroll", ScrollableContainer)
        scroll.mount(ThinkingIndicator(category=category, id="thinking-indicator"))
        scroll.scroll_end(animate=False)

    def hide_thinking(self) -> None:
        """Remove the thinking indicator if present."""
        for widget in self.query("#thinking-indicator"):
            widget.remove()

    def clear(self) -> None:
        """Clear chat history."""
        self._messages.clear()
        scroll = self.query_one("#chat-scroll", ScrollableContainer)
        scroll.remove_children()
        self._show_welcome()
        # Any in-flight search is no longer meaningful.
        self._match_index.clear()
        self._active_match = 0
        with contextlib.suppress(NoMatches):
            self.query_one(SearchBar).hide()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def open_search(self) -> None:
        """Reveal the search bar and focus its input."""
        try:
            bar = self.query_one(SearchBar)
        except NoMatches:
            return
        bar.show()

    def close_search(self) -> None:
        """Clear highlights and hide the search bar."""
        self._clear_highlights()
        with contextlib.suppress(NoMatches):
            self.query_one(SearchBar).hide()
        self.post_message(self.SearchClosed())

    @property
    def search_active(self) -> bool:
        """Whether the search bar is currently visible."""
        try:
            return self.query_one(SearchBar).is_open
        except NoMatches:
            return False

    def on_search_bar_changed(self, event: SearchBar.Changed) -> None:
        """Re-run the search each time the query text changes."""
        event.stop()
        self._run_search(event.query)

    def on_search_bar_dismissed(self, event: SearchBar.Dismissed) -> None:
        """Handle Esc inside the search bar."""
        event.stop()
        self.close_search()

    def on_search_bar_navigate(self, event: SearchBar.Navigate) -> None:
        """Handle next/previous requests from the search bar."""
        event.stop()
        self.navigate_match(forward=event.forward)

    def navigate_match(self, *, forward: bool = True) -> None:
        """Move to the next (or previous) match and scroll it into view."""
        if not self._match_index:
            return
        delta = 1 if forward else -1
        self._active_match = (self._active_match + delta) % len(self._match_index)
        self._apply_highlights()
        self._scroll_to_active()
        self._update_status_label()

    def _run_search(self, query: str) -> None:
        """Rebuild the match list for *query* and highlight all matches."""
        query = query.strip()
        self._clear_highlights()
        if not query:
            self._update_status_label()
            return

        scroll = self.query_one("#chat-scroll", ScrollableContainer)
        matches: list[tuple[MessageWidget, int]] = []
        for widget in scroll.query(MessageWidget):
            count = widget.count_matches(query)
            matches.extend((widget, local) for local in range(count))
        self._match_index = matches
        self._active_match = 0
        self._apply_highlights()
        if matches:
            self._scroll_to_active()
        self._update_status_label()

    def _apply_highlights(self) -> None:
        """Push the current query / active-match state into every widget."""
        if not self._match_index:
            return
        query = self.query_one(SearchBar).query_text
        # Group match positions by widget so we can set the active local idx
        # only on the widget that owns the active global match.
        active_widget, active_local = self._match_index[self._active_match]
        seen: set[int] = set()
        for widget, _ in self._match_index:
            if id(widget) in seen:
                continue
            seen.add(id(widget))
            local_idx = active_local if widget is active_widget else None
            widget.apply_highlight(query, local_idx)

    def _clear_highlights(self) -> None:
        """Remove highlights from any widget that was previously highlighted."""
        seen: set[int] = set()
        for widget, _ in self._match_index:
            if id(widget) in seen:
                continue
            seen.add(id(widget))
            widget.apply_highlight(None, None)
        self._match_index.clear()
        self._active_match = 0

    def _scroll_to_active(self) -> None:
        """Scroll the chat area so the active match is visible."""
        if not self._match_index:
            return
        widget, _ = self._match_index[self._active_match]
        scroll = self.query_one("#chat-scroll", ScrollableContainer)
        scroll.scroll_to_widget(widget, animate=False)

    def _update_status_label(self) -> None:
        """Refresh the match-count text shown next to the search input."""
        try:
            bar = self.query_one(SearchBar)
        except NoMatches:
            return
        if not bar.query_text.strip():
            bar.set_status("")
        elif not self._match_index:
            bar.set_status("no matches")
        else:
            bar.set_status(f"{self._active_match + 1}/{len(self._match_index)}")
