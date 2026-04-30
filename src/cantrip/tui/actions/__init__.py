"""Per-surface action handlers for ``CantripApp``.

The TUI's action surface is wide enough that grouping handlers by area
keeps ``tui/app.py`` focused on Textual lifecycle plumbing.  Each module
here exposes free functions that take the app instance as the first
argument; ``CantripApp`` keeps thin ``action_*`` / ``on_*`` methods that
delegate so Textual's binding discovery still works.
"""
