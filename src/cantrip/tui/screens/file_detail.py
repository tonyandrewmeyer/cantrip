"""File detail modal screen for the charm file tree.

Opened when a file is selected in :class:`~cantrip.tui.widgets.filetree.CharmTreeWidget`.
Shows the path, size, modification time, a best-effort purpose summary
derived from the file contents, the most recent ``git log`` entries
that touched the file, and a short content preview.
"""

import ast
import datetime
import functools
import pathlib
import re
import subprocess
from typing import ClassVar

from rich.console import Group, RenderableType
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.screen import ModalScreen
from textual.widgets import RichLog, Static
from textual.worker import Worker, WorkerState

# Timeout for ``git log`` subprocess (seconds).
_GIT_TIMEOUT = 10

# Number of log entries to request.
_LOG_ENTRIES = 5

# Line / byte budgets for the preview pane.
_PREVIEW_MAX_LINES = 120
_PREVIEW_MAX_BYTES = 32_768

# Pygments theme used by the preview.  ``ansi_dark`` uses the terminal's
# own ANSI palette so the highlight colours adapt to any Cantrip theme
# (cantrip, ubuntu, monokai, solarized-dark) instead of clashing with
# one fixed palette.
_SYNTAX_THEME = "ansi_dark"

# Extensions that look like the charm's key YAML metadata files.
_CHARM_METADATA_NAMES = frozenset(
    {"charmcraft.yaml", "metadata.yaml", "actions.yaml", "config.yaml"}
)

# Hard-coded purposes for files Cantrip itself writes.  Without these,
# binary or non-Pythonic artefacts (the SQLite session, the JSONL audit
# log, the repomap cache) fall through to ``_fallback_purpose`` and
# render as "no structured summary available" — unhelpful for a file
# whose meaning Cantrip knows precisely.
_CANTRIP_FILE_PURPOSES: dict[str, str] = {
    ".cantrip": (
        "**Cantrip session store** — per-charm SQLite database holding "
        "conversation history, agent state, and the durable work queue."
    ),
    ".cantrip-wal": (
        "**SQLite write-ahead log** — companion file for the ``.cantrip`` "
        "session store; holds pending writes until they're checkpointed "
        "back into the main database.  Safe to leave alone."
    ),
    ".cantrip-shm": (
        "**SQLite shared-memory index** — companion file for the "
        "``.cantrip`` session store; coordinates concurrent readers with "
        "the write-ahead log.  Safe to leave alone."
    ),
    ".cantrip-audit.jsonl": (
        "**Cantrip audit log** — append-only JSONL trace; one record per "
        "permission decision and tool call."
    ),
    ".cantrip-repomap.json": (
        "**Cantrip repomap cache** — parsed symbol map of the charm "
        "source tree.  Rebuilt on demand via ``/repomap``."
    ),
    ".cantrip.bak": (
        "**Cantrip session backup** — previous ``.cantrip`` session set "
        "aside when the user started fresh or migrated formats."
    ),
    ".cantrip.tmp": (
        "**Cantrip migration scratch file** — transient SQLite written "
        "while converting a legacy ``.cantrip/`` directory to the "
        "single-file format."
    ),
    ".cantrip.corrupt": (
        "**Cantrip salvaged session** — legacy ``.cantrip/`` directory "
        "preserved when migration could not safely convert it."
    ),
}

# Known children of a ``.cantrip*`` parent directory by exact name.
_CANTRIP_CHILD_PURPOSES: dict[tuple[str, str], str] = {
    (".cantrip", "permissions.yaml"): (
        "**Cantrip permission rules** — per-charm allow/deny lists "
        "evaluated before every tool call."
    ),
    (".cantrip-shared", "decisions.jsonl"): (
        "**Cantrip team-sync decisions** — shared, append-only decision "
        "log checked in so teammates pick up architectural choices."
    ),
}

# Bucket descriptions for files inside a known sub-directory of any
# ``.cantrip*`` ancestor, keyed by the immediate parent's name.
_CANTRIP_BUCKET_PURPOSES: dict[str, str] = {
    "checks": (
        "**Cantrip acceptance check** — Markdown spec describing one "
        "must-pass condition before the agent reports a phase complete."
    ),
    "commands": (
        "**Cantrip custom slash command** — Markdown definition of a "
        "user-supplied ``/<name>`` command."
    ),
    "memory": (
        "**Cantrip team-sync memory** — shared note the agent reads back "
        "across runs (lives under ``.cantrip-shared/memory/``)."
    ),
}


class FileDetailScreen(ModalScreen):
    """Modal screen showing metadata and content for a selected file."""

    DEFAULT_CSS = """
    FileDetailScreen {
        align: center middle;
    }

    #file-container {
        width: 90%;
        height: 90%;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }

    #file-title {
        width: 100%;
        height: 1;
        padding-bottom: 1;
    }

    .title-text {
        text-style: bold;
        width: 1fr;
    }

    .title-hint {
        color: $text-muted;
        width: auto;
    }

    #file-footer {
        dock: bottom;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }

    #file-footer .clickable {
        margin-right: 2;
        width: auto;
    }

    .clickable:hover {
        background: $surface-darken-1;
        color: $text;
    }

    #file-output {
        height: 1fr;
    }
    """

    BINDINGS: ClassVar[list] = [
        Binding("escape", "dismiss", "Close"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, path: pathlib.Path, charm_root: pathlib.Path | None = None) -> None:
        """Initialise with the selected file path."""
        super().__init__()
        self._path = path
        self._charm_root = charm_root

    @property
    def _display_path(self) -> str:
        """Return the path relative to the charm root when possible."""
        if self._charm_root is not None:
            try:
                return str(self._path.relative_to(self._charm_root))
            except ValueError:
                pass
        return str(self._path)

    def compose(self) -> ComposeResult:
        """Compose the file detail layout."""
        with Vertical(id="file-container"):
            with Horizontal(id="file-title"):
                yield Static(self._display_path, classes="title-text")
                # Two clickable footer-like widgets in the title bar so
                # mouse users have a button-shaped target.  The visible
                # text reads "[ Esc Close ]" so keyboard users still
                # see the binding.  ``markup=False`` keeps Textual from
                # eating the brackets as a (broken) style tag.
                yield Static(
                    "[ Esc Close ]", id="file-close", classes="title-hint clickable", markup=False
                )
            yield RichLog(id="file-output", wrap=True, markup=True)
            with Horizontal(id="file-footer"):
                yield Static(
                    "[ r Refresh ]", id="file-refresh-btn", classes="clickable", markup=False
                )
                yield Static(
                    "[ Esc Close ]", id="file-close-btn", classes="clickable", markup=False
                )

    def on_mount(self) -> None:
        """Populate everything that's cheap, then fire git log in a worker."""
        self._render_all()
        self._fetch_git_log()

    def action_refresh(self) -> None:
        """Re-read the file and re-fetch git log."""
        self._render_all()
        self._fetch_git_log()

    def on_click(self, event: Click) -> None:
        """Route clicks on the footer Statics to the matching action.

        Bindings carry the ``r`` and ``Esc`` keyboard shortcuts; this
        handler makes the text-shaped "buttons" actually behave like
        buttons when clicked, which is the affordance the user expects
        when the visible string is wrapped in square brackets.
        """
        widget = event.widget
        if widget is None:
            return
        wid = getattr(widget, "id", None)
        if wid == "file-refresh-btn":
            self.action_refresh()
            event.stop()
        elif wid in ("file-close-btn", "file-close"):
            self.dismiss()
            event.stop()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_all(self, git_log: str | None = None) -> None:
        """Rewrite the output log with stats + purpose + git log + preview."""
        output = self.query_one("#file-output", RichLog)
        output.clear()

        output.write(f"[dim]{_format_stats(self._path)}[/dim]")
        output.write("")
        output.write("[bold cyan]Purpose[/bold cyan]")
        output.write(_infer_purpose(self._path))
        output.write("")
        output.write("[bold cyan]Recent changes[/bold cyan]")
        if git_log is None:
            output.write("[dim]Fetching git log…[/dim]")
        else:
            output.write(git_log)
        output.write("")
        output.write("[bold cyan]Content preview[/bold cyan]")
        output.write(_render_preview(self._path))

    def _render_git_log(self, body: str) -> None:
        """Re-render the output log with the resolved git log body."""
        self._render_all(git_log=body)

    # ------------------------------------------------------------------
    # Git log — subprocess in a worker thread
    # ------------------------------------------------------------------

    def _fetch_git_log(self) -> None:
        """Kick off a background worker to fetch git log for the file."""
        self.run_worker(
            functools.partial(self._git_log_blocking, self._path),
            name="file_git_log",
            exclusive=True,
            thread=True,
        )

    @staticmethod
    def _git_log_blocking(path: pathlib.Path) -> str:
        """Run ``git log`` for a single file and return its text output."""
        cmd = [
            "git",
            "-C",
            str(path.parent),
            "log",
            "--follow",
            f"-n{_LOG_ENTRIES}",
            "--pretty=format:%h|%ar|%an|%s",
            "--",
            path.name,
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT,
            )
        except FileNotFoundError:
            return "__error__:git not installed"
        except subprocess.TimeoutExpired:
            return "__error__:git log timed out"

        if result.returncode != 0:
            stderr = (result.stderr or "").strip().splitlines()
            # Outside a git repo; no log to show.
            first_line = stderr[0] if stderr else "unknown error"
            return f"__error__:{first_line}"

        return result.stdout

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Render the git log when its worker completes."""
        if event.worker.name != "file_git_log":
            return
        if event.worker.state != WorkerState.SUCCESS:
            return

        raw = event.worker.result or ""
        if raw.startswith("__error__:"):
            reason = raw.removeprefix("__error__:")
            if "not a git repository" in reason.lower() or reason == "":
                body = "[dim]Not tracked by git.[/dim]"
            else:
                body = f"[dim]git log failed: {reason}[/dim]"
        elif not raw.strip():
            body = "[dim]No commits touch this file.[/dim]"
        else:
            body = _format_git_log(raw)

        self._render_git_log(body)


# ---------------------------------------------------------------------------
# Pure helpers (exported for tests)
# ---------------------------------------------------------------------------


def _format_stats(path: pathlib.Path) -> str:
    """Return a single-line size + modification time summary."""
    try:
        stat = path.stat()
    except OSError:
        return "[dim]File not readable.[/dim]"

    size = _format_size(stat.st_size)
    mtime = datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.UTC)
    return f"{size} · modified {_format_relative_time(mtime)}"


def _format_size(bytes_: int) -> str:
    """Format a byte count as a short human string."""
    if bytes_ < 1024:
        return f"{bytes_} B"
    if bytes_ < 1024 * 1024:
        return f"{bytes_ / 1024:.1f} KB"
    return f"{bytes_ / (1024 * 1024):.1f} MB"


def _format_relative_time(when: datetime.datetime) -> str:
    """Format an absolute time as a short 'N <units> ago' string."""
    now = datetime.datetime.now(tz=datetime.UTC)
    delta = now - when
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} min ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = seconds // 86400
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    months = days // 30
    if months < 12:
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years != 1 else ''} ago"


def _infer_purpose(path: pathlib.Path) -> str:
    """Return a best-effort purpose summary for a file.

    Cantrip-owned ``.cantrip*`` artefacts win first — their meaning is
    fixed by the writer, not inferable from content.  Then:
    Python: module docstring.
    Markdown: first H1 plus the first non-heading paragraph.
    YAML (charmcraft / metadata): ``summary`` or ``description`` field.
    TOML: ``[project]`` description.
    Fallback: a short summary line based on extension.
    """
    suffix = path.suffix.lower()
    name = path.name.lower()

    if not path.exists():
        return "[dim]Could not read file.[/dim]"

    cantrip = _cantrip_artefact_purpose(path)
    if cantrip is not None:
        return cantrip

    text = _read_text_safely(path, max_bytes=16_384)
    if text is None:
        return _fallback_purpose(path)

    if suffix == ".py":
        doc = _python_module_docstring(text)
        if doc:
            return doc
    elif suffix == ".md":
        md = _markdown_first_section(text)
        if md:
            return md
    elif suffix in {".yaml", ".yml"} and name in _CHARM_METADATA_NAMES:
        yaml_purpose = _yaml_summary(text)
        if yaml_purpose:
            return yaml_purpose
    elif suffix == ".toml":
        toml_purpose = _toml_description(text)
        if toml_purpose:
            return toml_purpose

    return _fallback_purpose(path)


def _cantrip_artefact_purpose(path: pathlib.Path) -> str | None:
    """Return a hard-coded purpose for files Cantrip itself creates.

    Recognises top-level ``.cantrip*`` files in the charm root, files
    directly under a ``.cantrip*`` parent (``permissions.yaml``,
    ``decisions.jsonl``), and any file inside a ``checks/``,
    ``commands/`` or ``memory/`` bucket nested under such a parent.

    Returns ``None`` for paths Cantrip does not own — including the
    contents of ``.cantrip-worktrees/<task-id>/``, which are real charm
    files whose own content describes them better than the worktree
    location ever could.
    """
    name = path.name
    # Backup files include a timestamp suffix (``.cantrip.bak-20260101_120000``);
    # collapse to the canonical entry.
    if name.startswith(".cantrip.bak"):
        return _CANTRIP_FILE_PURPOSES[".cantrip.bak"]
    if name in _CANTRIP_FILE_PURPOSES:
        return _CANTRIP_FILE_PURPOSES[name]

    parent_names = [p.name for p in path.parents]
    for parent_name in parent_names:
        match = _CANTRIP_CHILD_PURPOSES.get((parent_name, name))
        if match is not None:
            return match

    # Bucketed fallback — only fires when an ancestor is a ``.cantrip*``
    # directory, so unrelated ``checks/`` or ``memory/`` directories
    # elsewhere in the tree are left alone.
    immediate_parent = parent_names[0] if parent_names else ""
    if immediate_parent in _CANTRIP_BUCKET_PURPOSES and any(
        ancestor.startswith(".cantrip") for ancestor in parent_names[1:]
    ):
        return _CANTRIP_BUCKET_PURPOSES[immediate_parent]

    return None


def _python_module_docstring(text: str) -> str | None:
    """Return the first available docstring as the module's purpose.

    Tries module → first top-level class → first top-level function so
    a file like ``charm.py`` whose only docstring lives on the
    ``MyCharm`` class still surfaces a meaningful summary instead of
    falling through to "no structured summary available".
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    module_doc = ast.get_docstring(tree)
    if module_doc:
        return module_doc.strip()
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            doc = ast.get_docstring(node)
            if doc:
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                return f"**{kind} {node.name}** — {doc.strip()}"
    return None


def _markdown_first_section(text: str) -> str | None:
    """Return first H1 plus the first paragraph beneath it, if any.

    If there's no H1 but the file starts with plain text, returns the
    first paragraph alone.  Returns ``None`` for empty input or a file
    whose first lines are all lower-level headings.
    """
    lines = text.splitlines()
    heading: str | None = None
    body_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if heading is None and stripped.startswith("# "):
            heading = stripped.removeprefix("# ").strip()
            continue
        if not stripped:
            if body_lines:
                break
            continue
        if stripped.startswith("#"):
            # H2+ terminates the first section.
            if heading is not None or body_lines:
                break
            continue
        body_lines.append(stripped)
        if len(" ".join(body_lines)) > 280:
            break
    if heading and body_lines:
        return f"**{heading}**\n\n{' '.join(body_lines)}"
    if heading:
        return f"**{heading}**"
    if body_lines:
        return " ".join(body_lines)
    return None


def _yaml_summary(text: str) -> str | None:
    """Return the ``summary`` or ``description`` field from a YAML doc."""
    summary = _scalar_field(text, "summary")
    description = _scalar_field(text, "description")
    if summary and description:
        return f"**{summary}**\n\n{description}"
    return summary or description


def _toml_description(text: str) -> str | None:
    """Return the ``[project]`` / ``[package]`` description value."""
    match = re.search(r'^\s*description\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1).strip() if match else None


def _scalar_field(text: str, key: str) -> str | None:
    """Return the first top-level scalar value for *key*.

    Only matches lines at column 0 (top-level in the YAML doc).  Handles
    both single-line and folded/literal (``>`` / ``|``) scalars.
    """
    pattern = rf"^{re.escape(key)}\s*:\s*(.*?)$"
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip()
    # Trim matching quotes.
    for quote in ('"', "'"):
        if value.startswith(quote) and value.endswith(quote):
            value = value[1:-1]
            break
    if value in {">", "|", ">-", "|-"}:
        # Folded / literal scalar — collect indented lines below.
        lines = text.splitlines()
        # Find the line that started the scalar.
        for i, line in enumerate(lines):
            if re.match(pattern, line):
                collected: list[str] = []
                for follow in lines[i + 1 :]:
                    if follow.strip() == "":
                        if collected:
                            break
                        continue
                    if not follow.startswith(" "):
                        break
                    collected.append(follow.strip())
                return " ".join(collected) if collected else None
    return value or None


def _fallback_purpose(path: pathlib.Path) -> str:
    """Return generic purpose line when no content-specific summary was found."""
    suffix = path.suffix.lower() or "(no extension)"
    return f"[dim]{suffix} file — no structured summary available.[/dim]"


def _render_preview(path: pathlib.Path) -> RenderableType:
    """Return a syntax-highlighted preview of the file.

    Returns a :class:`rich.syntax.Syntax` block for text content (with
    line numbers and Pygments-driven highlighting), wrapped in a
    :class:`rich.console.Group` plus a dim truncation notice when the
    file exceeds the preview budget.  Binary / empty / unreadable files
    return a plain :class:`rich.text.Text` notice instead.
    """
    text = _read_text_safely(path, max_bytes=_PREVIEW_MAX_BYTES)
    if text is None:
        return Text("Binary content detected — preview skipped.", style="dim italic")
    if not text:
        return Text("Empty file.", style="dim italic")

    lines = text.splitlines()
    truncated = len(lines) > _PREVIEW_MAX_LINES
    if truncated:
        lines = lines[:_PREVIEW_MAX_LINES]
    body = "\n".join(lines)

    lexer = _guess_lexer(path, body)
    syntax = Syntax(
        body,
        lexer,
        theme=_SYNTAX_THEME,
        line_numbers=True,
        word_wrap=False,
        background_color="default",
    )

    if truncated:
        return Group(
            syntax,
            Text(
                f"… (first {_PREVIEW_MAX_LINES} lines)",
                style="dim italic",
            ),
        )
    return syntax


def _guess_lexer(path: pathlib.Path, body: str) -> str:
    """Return the Pygments lexer alias for *path*.

    Rich's ``Syntax.guess_lexer`` looks at both the filename and the
    content (for shebangs, emacs modelines, etc.) and returns the
    Pygments lexer short name.  Falls back to plain text when nothing
    matches.
    """
    return Syntax.guess_lexer(str(path), body)


def _read_text_safely(path: pathlib.Path, *, max_bytes: int) -> str | None:
    """Read up to *max_bytes* of text; return ``None`` if binary content."""
    try:
        raw = path.read_bytes()[:max_bytes]
    except OSError:
        return None
    # Reject binary files via a simple NUL-byte heuristic.
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("latin-1")
        except UnicodeDecodeError:
            return None


def _format_git_log(raw: str) -> str:
    """Format ``git log --pretty=format:%h|%ar|%an|%s`` output into Rich markup."""
    lines: list[str] = []
    for line in raw.splitlines():
        parts = line.split("|", 3)
        if len(parts) != 4:
            lines.append(line)
            continue
        sha, age, author, subject = parts
        lines.append(
            f"[bold cyan]{sha}[/bold cyan]  [dim]{age}[/dim]  [italic]{author}[/italic]: {subject}"
        )
    return "\n".join(lines) if lines else "[dim]No commits touch this file.[/dim]"
