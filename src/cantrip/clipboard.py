"""OSC 52 clipboard helper.

Surfaces (TUI / CLI) call into here when a slash command wants to put
text on the user's system clipboard.  The TUI prefers Textual's own
``App.copy_to_clipboard`` (it manages OSC 52 negotiation against the
host terminal); the CLI talks to the controlling tty directly.

OSC 52 is the universally portable terminal-clipboard escape: it works
through tmux/screen and over plain ssh as long as the terminal
emulator agrees to it.  Most modern emulators (kitty, alacritty, foot,
iTerm2, gnome-terminal, Windows Terminal) ship it on by default; tmux
needs ``set -g set-clipboard on`` and a recent enough version.
"""

from __future__ import annotations

import base64
import sys
from typing import IO

# Maximum payload OSC 52 will accept on most terminals.  xterm caps the
# raw escape at 100KB by default; tmux is stricter still.  Truncate
# silently rather than blowing up the terminal -- the slash command's
# confirmation message includes the full text anyway.
MAX_CLIPBOARD_BYTES = 75_000


def osc52_sequence(text: str) -> bytes:
    """Return the OSC 52 escape that copies *text* to the clipboard.

    Format: ``ESC ] 52 ; c ; <base64 payload> BEL``.  ``c`` selects
    the system clipboard (as opposed to the X11 primary selection).
    """
    payload = text.encode("utf-8")[:MAX_CLIPBOARD_BYTES]
    encoded = base64.b64encode(payload).decode("ascii")
    return f"\x1b]52;c;{encoded}\x07".encode()


def write_to_terminal(text: str, *, stream: IO[bytes] | None = None) -> bool:
    """Emit OSC 52 for *text* to the controlling terminal.

    Returns ``True`` when the bytes were written.  Returns ``False``
    when the destination is not a tty -- callers should report a
    fall-back ("clipboard not available") rather than raising.

    *stream* defaults to :data:`sys.__stdout__`'s underlying buffer so
    Textual's stdout interception (it captures :data:`sys.stdout`) is
    bypassed -- otherwise the escape would land inside the chat
    widget rather than at the terminal.
    """
    if stream is None:
        target = getattr(sys, "__stdout__", None)
        if target is None or not target.isatty():
            return False
        buffer = getattr(target, "buffer", None)
        if buffer is None:
            return False
        stream = buffer
    try:
        stream.write(osc52_sequence(text))
        stream.flush()
    except (OSError, ValueError):
        return False
    return True


__all__ = [
    "MAX_CLIPBOARD_BYTES",
    "osc52_sequence",
    "write_to_terminal",
]
