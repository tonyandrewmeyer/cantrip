"""Tests for the YAML-based theme loader."""

import pathlib
from unittest.mock import MagicMock, patch

from textual.theme import Theme

from cantrip.tui import themes


class TestThemeFromDict:
    """The internal ``_theme_from_dict`` factory."""

    def test_builds_theme_with_palette(self) -> None:
        theme = themes._theme_from_dict(
            "custom",
            {
                "primary": "#ff0000",
                "secondary": "#00ff00",
                "dark": False,
            },
        )
        assert isinstance(theme, Theme)
        assert theme.name == "custom"
        assert theme.primary == "#ff0000"
        assert theme.dark is False

    def test_dark_defaults_to_true(self) -> None:
        theme = themes._theme_from_dict("t", {})
        assert theme.dark is True


class TestLoadYamlTheme:
    """``_load_yaml_theme`` parses a single YAML file."""

    def test_returns_none_for_non_dict_yaml(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("- just a list\n- not a dict\n")
        assert themes._load_yaml_theme(path) is None

    def test_parses_palette_block(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "mine.yaml"
        path.write_text(
            "name: mine\npalette:\n  primary: '#123456'\n  secondary: '#654321'\n  dark: false\n"
        )
        theme = themes._load_yaml_theme(path)
        assert theme is not None
        assert theme.name == "mine"
        assert theme.primary == "#123456"
        assert theme.dark is False

    def test_fallback_to_top_level_when_no_palette_key(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "flat.yaml"
        path.write_text("name: flat\nprimary: '#abcdef'\ndark: true\n")
        theme = themes._load_yaml_theme(path)
        assert theme is not None
        assert theme.primary == "#abcdef"

    def test_name_defaults_to_stem_when_missing(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "derived.yaml"
        path.write_text("primary: '#111111'\n")
        theme = themes._load_yaml_theme(path)
        assert theme is not None
        assert theme.name == "derived"

    def test_read_failure_returns_none(self, tmp_path: pathlib.Path) -> None:
        missing = tmp_path / "no-such-file.yaml"
        assert themes._load_yaml_theme(missing) is None


class TestLoadAllThemes:
    """``load_all_themes`` aggregates bundled + user directory themes."""

    def test_bundled_themes_present(self) -> None:
        with patch.object(themes, "_USER_THEME_DIR", pathlib.Path("/nonexistent")):
            all_themes = themes.load_all_themes()
        names = {t.name for t in all_themes}
        assert {"cantrip", "ubuntu", "monokai", "solarized-dark", "light"} <= names

    def test_picks_up_user_yaml_files(self, tmp_path: pathlib.Path) -> None:
        user_dir = tmp_path / "themes"
        user_dir.mkdir()
        (user_dir / "user-a.yaml").write_text(
            "name: user-a\npalette:\n  primary: '#ffeecc'\n  dark: true\n"
        )
        (user_dir / "user-b.yml").write_text(
            "name: user-b\npalette:\n  primary: '#ccffee'\n  dark: false\n"
        )
        with patch.object(themes, "_USER_THEME_DIR", user_dir):
            all_themes = themes.load_all_themes()
        names = {t.name for t in all_themes}
        assert "user-a" in names
        assert "user-b" in names

    def test_invalid_user_theme_is_skipped(self, tmp_path: pathlib.Path) -> None:
        user_dir = tmp_path / "themes"
        user_dir.mkdir()
        # A file that parses to a non-dict is dropped silently.
        (user_dir / "bad.yaml").write_text("- not\n- a mapping\n")
        with patch.object(themes, "_USER_THEME_DIR", user_dir):
            all_themes = themes.load_all_themes()
        # No "bad" theme, but bundled ones still present.
        assert all(t.name != "bad" for t in all_themes)


class TestRegisterThemes:
    """``register_themes`` wires each theme into the Textual app."""

    def test_registers_every_loaded_theme(self) -> None:
        app = MagicMock()
        with patch.object(themes, "_USER_THEME_DIR", pathlib.Path("/nonexistent")):
            themes.register_themes(app)
        # One call per bundled theme.
        assert app.register_theme.call_count == len(themes._BUNDLED_THEMES)
