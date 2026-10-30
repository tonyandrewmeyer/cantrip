"""Drift guards between the CLI and the published user docs.

``docs/src/reference-cli.md`` claims to be the complete reference for
every ``cantrip`` flag, but nothing enforced that claim: flags landed
in ``cantrip.main.parser`` without a matching ``<dt>`` entry, and a
``--watcher`` entry outlived the flag it documented.  The first two
tests pin the two directions of that correspondence.

The third test resolves every internal link in the rendered site.
``{#anchor}`` directives are attached to the *following* heading by
the attrs-block plugin, so a stray blank line — or two stacked
directives, where only the last one applies — silently moves or drops
an anchor while the build still succeeds.
"""

from __future__ import annotations

import argparse
import pathlib
import re

import pytest

from cantrip.main import parser as cli_parser

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_REFERENCE_CLI_MD = _REPO_ROOT / "docs" / "src" / "reference-cli.md"
_RENDERED_DOCS = _REPO_ROOT / "docs" / "docs"

# ``<dt>--flag ARG</dt>`` and ``<dt>-p GOAL, --print GOAL</dt>`` both count.
_DT_FLAG_RE = re.compile(r"<dt>(.*?)</dt>", re.DOTALL)
_LONG_FLAG_RE = re.compile(r"--[a-z0-9][a-z0-9-]*")
_HREF_RE = re.compile(r'href="([^"]+)"')
_ID_RE = re.compile(r'id="([^"]+)"')

# Flags argparse supplies that no reference page should have to repeat.
_IMPLICIT_FLAGS = frozenset({"--help", "--version"})


def _subcommand_parsers() -> dict[str, argparse.ArgumentParser]:
    """Map each top-level subcommand name to its parser."""
    root = cli_parser._build_parser()
    for action in root._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise AssertionError("the top-level parser grew no subparsers")


def _long_options(parser: argparse.ArgumentParser) -> set[str]:
    """Long options declared directly on *parser*, minus the implicit ones."""
    return {
        option
        for action in parser._actions
        if not isinstance(action, argparse._SubParsersAction)
        for option in action.option_strings
        if option.startswith("--") and option not in _IMPLICIT_FLAGS
    }


def _reference_text() -> str:
    return _REFERENCE_CLI_MD.read_text(encoding="utf-8")


def _run_section() -> str:
    """The ``## cantrip run`` section, up to the next top-level heading."""
    lines = _reference_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "## cantrip run")
    rest = lines[start + 1 :]
    length = next(
        (i for i, line in enumerate(rest) if line.startswith("## ")),
        len(rest),
    )
    return "\n".join(lines[start : start + 1 + length])


def _documented_flags(markdown: str) -> set[str]:
    """Long options that carry their own ``<dt>`` entry in *markdown*."""
    return {flag for term in _DT_FLAG_RE.findall(markdown) for flag in _LONG_FLAG_RE.findall(term)}


def test_every_run_flag_has_a_reference_entry() -> None:
    """Each ``cantrip run`` long option is documented as its own term."""
    undocumented = _long_options(_subcommand_parsers()["run"]) - _documented_flags(_run_section())
    assert not undocumented, (
        "cantrip run flags with no <dt> entry under '## cantrip run' in"
        f" docs/src/reference-cli.md: {sorted(undocumented)}"
    )


def test_reference_documents_no_phantom_run_flags() -> None:
    """Each flag the run section documents still exists on the parser."""
    phantom = _documented_flags(_run_section()) - _long_options(_subcommand_parsers()["run"])
    assert not phantom, (
        "docs/src/reference-cli.md documents 'cantrip run' flags that"
        f" argparse does not accept: {sorted(phantom)}"
    )


@pytest.mark.parametrize(
    "subcommand",
    sorted(name for name in _subcommand_parsers() if name != "run"),
)
def test_every_subcommand_flag_is_mentioned(subcommand: str) -> None:
    """Non-``run`` subcommand flags appear somewhere on the reference page.

    Looser than the ``run`` checks on purpose: several of these are
    documented inside a synopsis block or a prose sentence rather than
    a definition list, and tightening that is a formatting decision
    rather than a correctness one.
    """
    parsers = _subcommand_parsers()
    text = _reference_text()
    expected = _long_options(parsers[subcommand])
    for action in parsers[subcommand]._actions:
        if isinstance(action, argparse._SubParsersAction):
            for leaf in action.choices.values():
                expected |= _long_options(leaf)
    missing = sorted(flag for flag in expected if flag not in text)
    assert not missing, (
        f"cantrip {subcommand} flags absent from docs/src/reference-cli.md: {missing}"
    )


def test_internal_links_resolve() -> None:
    """Every relative link in the rendered site points at a real target."""
    ids = {
        path: set(_ID_RE.findall(path.read_text(encoding="utf-8")))
        for path in _RENDERED_DOCS.glob("*.html")
    }
    # The landing page lives outside docs/docs/ but is linked from every page.
    landing = _REPO_ROOT / "docs" / "index.html"
    ids[landing] = set(_ID_RE.findall(landing.read_text(encoding="utf-8")))

    broken: list[str] = []
    for source in sorted(_RENDERED_DOCS.glob("*.html")):
        for href in _HREF_RE.findall(source.read_text(encoding="utf-8")):
            if href.startswith(("http://", "https://", "mailto:", "/")):
                continue
            page, _, anchor = href.partition("#")
            target = (source.parent / page).resolve() if page else source
            if not target.exists():
                broken.append(f"{source.name} -> {href} (no such file)")
                continue
            if anchor and anchor not in ids.get(target, set()):
                broken.append(f"{source.name} -> {href} (no such anchor)")
    assert not broken, "broken internal links in docs/docs/:\n" + "\n".join(broken)
