"""TUI accessibility smoke — keyboard binding surface.

The TUI's most important accessibility lever is *keyboard navigation
completeness*: every action must be reachable from the keyboard, and
every visible binding must carry a human-readable description so the
Footer (and any screen reader reading it) can narrate the user's
options.  See ``design/TUI_ACCESSIBILITY.md`` for the broader
rationale and the manual-test recipe.

These tests walk every ``BINDINGS`` declaration in the App and Screen
classes and pin three invariants:

* every shown binding has a non-empty description,
* every binding's ``action`` name resolves to an ``action_<name>``
  method on the class (a Cantrip method or a Textual built-in
  inherited from :class:`textual.app.App` /
  :class:`textual.screen.Screen`),
* no two shown bindings collide on the same key inside one
  ``BINDINGS`` block.

A regression in any of these would silently break keyboard
discoverability — the surface a screen-reader user reaches first.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest
from textual.binding import Binding

import cantrip.tui.app as app_module
import cantrip.tui.screens as screens_pkg


def _screen_classes() -> list[type]:
    """Discover every Screen subclass under ``cantrip.tui.screens`` that
    declares a ``BINDINGS`` list of its own.

    Walks each submodule, then filters to classes whose ``BINDINGS`` is
    defined on the class itself (not inherited) so the test names a
    real owner for any failure.
    """
    found: list[type] = []
    for info in pkgutil.iter_modules(screens_pkg.__path__):
        module = importlib.import_module(f"{screens_pkg.__name__}.{info.name}")
        for name in dir(module):
            obj = getattr(module, name)
            if not isinstance(obj, type):
                continue
            if obj.__module__ != module.__name__:
                continue
            # Only include classes that declare BINDINGS *themselves*.
            if "BINDINGS" not in vars(obj):
                continue
            found.append(obj)
    # Sort by module + class name so test failure output is stable.
    found.sort(key=lambda c: (c.__module__, c.__name__))
    return found


def _binding_sources() -> list[tuple[type, list[Binding]]]:
    """Yield ``(class, [Binding, ...])`` for every screen + the App."""
    sources: list[tuple[type, list[Binding]]] = [
        (app_module.CantripApp, list(app_module.CantripApp.BINDINGS)),
    ]
    for cls in _screen_classes():
        sources.append((cls, list(cls.BINDINGS)))
    return sources


def _format_binding(b: Binding) -> str:
    return f"Binding(key={b.key!r}, action={b.action!r}, description={b.description!r})"


class TestBindingDescriptions:
    """Every shown binding carries a non-empty description for the Footer."""

    def test_every_shown_binding_has_description(self) -> None:
        violations: list[str] = []
        for cls, bindings in _binding_sources():
            for b in bindings:
                if not isinstance(b, Binding):
                    continue
                if not b.show:
                    continue
                if b.description:
                    continue
                violations.append(f"{cls.__module__}.{cls.__name__}: {_format_binding(b)}")
        assert not violations, "Shown bindings missing description:\n  " + "\n  ".join(violations)


class TestBindingActionsResolve:
    """Every binding's action name resolves to a callable on the class."""

    def test_every_action_method_exists(self) -> None:
        violations: list[str] = []
        for cls, bindings in _binding_sources():
            for b in bindings:
                if not isinstance(b, Binding):
                    continue
                # Textual binding actions are plain method names — the
                # callable is ``action_<name>`` on the class or any
                # base in the MRO (App + Screen ship a lot of
                # built-ins like ``dismiss`` / ``quit`` /
                # ``focus_next``).
                method_name = f"action_{b.action}"
                if hasattr(cls, method_name):
                    continue
                violations.append(
                    f"{cls.__module__}.{cls.__name__}: "
                    f"{_format_binding(b)} → expected method {method_name!r} not found"
                )
        assert not violations, "Bindings with unresolved actions:\n  " + "\n  ".join(violations)


class TestBindingNoKeyCollisions:
    """No two shown bindings inside the same ``BINDINGS`` share a key.

    Hidden (``show=False``) bindings can intentionally share a key with
    a shown one — that's how the App binds both ``ctrl+c`` and
    ``escape`` to the same cancel action with only one footer hint —
    so the test only checks the *shown* set.
    """

    def test_no_shown_key_collisions_within_a_screen(self) -> None:
        violations: list[str] = []
        for cls, bindings in _binding_sources():
            shown_keys: list[str] = []
            for b in bindings:
                if not isinstance(b, Binding):
                    continue
                if not b.show:
                    continue
                shown_keys.append(b.key)
            seen: set[str] = set()
            duplicates: list[str] = []
            for key in shown_keys:
                if key in seen and key not in duplicates:
                    duplicates.append(key)
                seen.add(key)
            if duplicates:
                violations.append(
                    f"{cls.__module__}.{cls.__name__}: duplicate shown keys {duplicates!r}"
                )
        assert not violations, "Duplicate shown-binding keys:\n  " + "\n  ".join(violations)


class TestBindingDiscovery:
    """The discovery walk finds the screens we expect.

    Defensive check: if a refactor moves screens out of
    ``cantrip.tui.screens`` (or splits one screen across two modules),
    the discovery list shouldn't drop to a surprising count without
    someone noticing.
    """

    @pytest.fixture(scope="class")
    def discovered(self) -> list[type]:
        return _screen_classes()

    def test_finds_the_well_known_screens(self, discovered: list[type]) -> None:
        names = {cls.__name__ for cls in discovered}
        # A non-exhaustive list of screens that have been around long
        # enough to count as load-bearing — if one of these is
        # missing, the discovery walk has regressed (or someone
        # renamed a screen without updating the test).
        expected = {
            "TranscriptScreen",
            "LogScreen",
            "ResumePromptScreen",
            "HelpScreen",
            "GraphScreen",
        }
        missing = expected - names
        assert not missing, f"Discovery walk missed expected screens: {sorted(missing)}"
