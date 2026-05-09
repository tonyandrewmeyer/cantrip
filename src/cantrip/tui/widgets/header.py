"""Slim contextual header for the Cantrip TUI (Phase 108.8).

Replaces Textual's stock :class:`textual.widgets.Header`, which
shipped a generic ``⭘`` glyph plus ``Title — Subtitle`` chrome
that carried no actual project context.  The new header carries
the four signals a user actually wants at a glance:

* ``✦ cantrip`` — brand mark in ``$primary``.
* ``provider/model`` — which LLM is doing the work.
* ``~/<rel>`` — which charm working tree is open.
* ``branch:<name>`` — current git branch when the tree is a repo.

Each segment is dropped when its underlying value is empty so a
brand-new session before any agent attaches still renders a
clean "``✦ cantrip``" line rather than three orphan separators.
The sequence is readable on an 80-column terminal at the
common combination (model name + tree name + ``main`` branch).
"""

from __future__ import annotations

import contextlib
import pathlib

from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

# Single brand mark — also used by the welcome wordmark in
# ``ChatWidget`` so the two surfaces speak the same vocabulary.
_BRAND_MARK = "✦ cantrip"


def _format_path(path: pathlib.Path | None) -> str:
    """Render *path* compactly for the header.

    Under ``$HOME`` collapses to ``~/<rel>``; otherwise returns
    the bare absolute path.  ``None`` and empty paths return
    ``""`` so the segment is dropped at render time.
    """
    if path is None:
        return ""
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return str(path)
    home = pathlib.Path.home()
    try:
        rel = resolved.relative_to(home)
    except ValueError:
        return str(resolved)
    return f"~/{rel}" if str(rel) != "." else "~"


class CantripHeader(Widget):
    """A one-line header showing brand, model, path, and git branch.

    Reactives are pushed by the app: ``CantripApp`` calls
    :meth:`set_state` (or assigns the reactives directly) whenever
    the agent's model resolves, the charm path changes, or the
    autonomous git layer switches branches.  The widget is
    mount-stable — no compose churn between updates — so per-tick
    refresh is just a Static ``.update()``.
    """

    DEFAULT_CSS = """
    CantripHeader {
        dock: top;
        height: 1;
        padding: 0 1;
        background: $primary-background;
    }
    """

    model_name: reactive[str] = reactive("", init=False)
    charm_path: reactive[pathlib.Path | None] = reactive(None, init=False)
    git_branch: reactive[str] = reactive("", init=False)

    def compose(self) -> ComposeResult:
        """One Static is enough — content is updated on every reactive change."""
        yield Static("", id="cantrip-header-text")

    def on_mount(self) -> None:
        """Render the initial line so a quick mount-and-test sees the brand."""
        self._refresh()

    def _refresh(self) -> None:
        """Rebuild the header line from the current reactive values."""
        segments: list[str] = [f"[bold $primary]{_BRAND_MARK}[/bold $primary]"]
        if self.model_name:
            segments.append(self.model_name)
        path_label = _format_path(self.charm_path)
        if path_label:
            segments.append(path_label)
        if self.git_branch:
            segments.append(f"branch:{self.git_branch}")
        with contextlib.suppress(NoMatches):
            self.query_one("#cantrip-header-text", Static).update(" · ".join(segments))


# Textual discovers watcher methods by name; wire each reactive to
# ``_refresh`` rather than copy-pasting four watchers.
for _attr in ("model_name", "charm_path", "git_branch"):
    setattr(CantripHeader, f"watch_{_attr}", lambda self: self._refresh())


__all__ = ["CantripHeader"]
