"""YAML-based theme system for the Cantrip TUI.

Loads theme definitions from bundled defaults and an optional user
directory (``~/.config/cantrip/themes/``).  Each YAML file defines
a Textual ``Theme`` with colour palette overrides.
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any

from textual.theme import Theme

log = logging.getLogger(__name__)

# User theme directory.
_USER_THEME_DIR = pathlib.Path.home() / ".config" / "cantrip" / "themes"

# Bundled theme definitions — inline to avoid extra file I/O.
_BUNDLED_THEMES: dict[str, dict[str, Any]] = {
    "cantrip": {
        "dark": True,
        "primary": "#E95420",
        "secondary": "#772953",
        "accent": "#AEA79F",
        "success": "#0E8420",
        "warning": "#F99B11",
        "error": "#DF382C",
        "surface": "#1E1E2E",
        "background": "#181825",
    },
    "ubuntu": {
        "dark": True,
        "primary": "#E95420",
        "secondary": "#772953",
        "accent": "#AEA79F",
        "success": "#38B44A",
        "warning": "#F99B11",
        "error": "#DF382C",
        "surface": "#2C2C2C",
        "background": "#1A1A1A",
    },
    "monokai": {
        "dark": True,
        "primary": "#A6E22E",
        "secondary": "#F92672",
        "accent": "#66D9EF",
        "success": "#A6E22E",
        "warning": "#FD971F",
        "error": "#F92672",
        "surface": "#272822",
        "background": "#1E1F1C",
    },
    "solarized-dark": {
        "dark": True,
        "primary": "#268BD2",
        "secondary": "#2AA198",
        "accent": "#B58900",
        "success": "#859900",
        "warning": "#CB4B16",
        "error": "#DC322F",
        "surface": "#073642",
        "background": "#002B36",
    },
    "light": {
        "dark": False,
        "primary": "#0077B6",
        "secondary": "#7B2D8B",
        "accent": "#555555",
        "success": "#0E8420",
        "warning": "#E67E22",
        "error": "#C0392B",
        "surface": "#F5F5F5",
        "background": "#FFFFFF",
    },
}


def _theme_from_dict(name: str, data: dict[str, Any]) -> Theme:
    """Build a Textual ``Theme`` from a dictionary of colour values."""
    return Theme(
        name=name,
        primary=data.get("primary"),
        secondary=data.get("secondary"),
        accent=data.get("accent"),
        success=data.get("success"),
        warning=data.get("warning"),
        error=data.get("error"),
        surface=data.get("surface"),
        background=data.get("background"),
        dark=data.get("dark", True),
    )


def _load_yaml_theme(path: pathlib.Path) -> Theme | None:
    """Load a single YAML theme file, returning None on failure."""
    try:
        import yaml  # noqa: I001
    except ImportError:
        log.debug("PyYAML not installed — skipping user theme %s", path)
        return None

    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, ValueError) as exc:
        log.warning("Failed to load theme %s: %s", path, exc)
        return None

    if not isinstance(data, dict):
        return None

    name = data.get("name", path.stem)
    palette = data.get("palette", data)
    return _theme_from_dict(name, palette)


def load_all_themes() -> list[Theme]:
    """Load all available themes (bundled + user directory).

    Returns a list of ``Theme`` objects ready to register with
    ``App.register_theme()``.
    """
    themes: list[Theme] = []

    # Bundled themes.
    for name, data in _BUNDLED_THEMES.items():
        themes.append(_theme_from_dict(name, data))

    # User themes from ~/.config/cantrip/themes/*.yaml.
    if _USER_THEME_DIR.is_dir():
        for path in sorted(_USER_THEME_DIR.glob("*.yaml")):
            theme = _load_yaml_theme(path)
            if theme is not None:
                themes.append(theme)
        for path in sorted(_USER_THEME_DIR.glob("*.yml")):
            theme = _load_yaml_theme(path)
            if theme is not None:
                themes.append(theme)

    return themes


def register_themes(app: Any) -> None:
    """Register all available themes with a Textual ``App``."""
    for theme in load_all_themes():
        app.register_theme(theme)
