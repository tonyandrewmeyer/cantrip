"""Drift guard between the tool catalogue and the ``paths`` permission section.

The ``paths`` section of ``.cantrip/permissions.yaml`` is the only
part of the gate that looks at filenames, and it finds them by
reading a fixed tuple of argument names
(:data:`~cantrip.agent.permissions._PATH_ARGUMENT_KEYS`).  A tool
whose path argument is spelled some other way is therefore invisible
to the section: the rule does not lose a race, it never runs.  That
is how the built-in ``*.env`` deny came to stop
``read_file(path=".env")`` while letting ``showboat(file=".env")``,
``extract_design_decisions(db_path=".env")`` and
``git_add(files=[".env"])`` through untouched.

Widening the tuple fixes today's catalogue; this module stops the
next tool from quietly reopening the gap.  It walks the real registry
(``build_tools()`` + ``expand_leaves`` so subcommand leaves such as
``git_add`` and ``juju_refresh`` are included), classifies each
declared parameter, and fails when a path-shaped one is neither
covered nor listed in :data:`_EXEMPT_PARAMETERS` with a reason.

Classification is deliberately generous — it flags on the parameter
name *or* on a description that talks about paths or directories.
False positives are cheap: a new entry in ``_EXEMPT_PARAMETERS``
costs one line and records the judgement.  A false negative is a
silently unenforced permission rule.
"""

from __future__ import annotations

import re

from cantrip.agent import permissions
from cantrip.agent.tools import build_tools, expand_leaves

# Parameter names that are path-shaped on sight, independent of how
# their description happens to be worded.
_PATH_NAME_HINTS = frozenset(
    {
        "cwd",
        "directories",
        "file",
        "filename",
        "files",
        "kubeconfig",
        "path",
        "workdir",
    }
)

#: Suffixes that make a parameter name path-shaped (``charm_path``,
#: ``output_dir``, ``rock_file``, ``files``, …).
_PATH_NAME_SUFFIXES = ("_path", "_paths", "_dir", "_dirs", "_file", "_files")

#: A description that names a filesystem location.  ``\b`` keeps this
#: off words like ``pathological`` and off ``--min-severity``-style
#: prose that merely contains the letters.
_PATH_DESCRIPTION_RE = re.compile(r"\b(?:path|paths|directory|directories)\b", re.IGNORECASE)

#: Parameters the classifier flags that are *not* filesystem paths, with
#: the reason each is exempt.  Keep this list short and justified — an
#: entry here is a decision that the ``paths`` section should not see
#: the argument, not a way to silence the test.
_EXEMPT_PARAMETERS: dict[tuple[str, str], str] = {
    ("glob", "max_results"): (
        "A result-count cap.  The description mentions 'file paths' because "
        "that is what the tool returns, not because this argument is one."
    ),
    ("gh_repo_bootstrap", "repo"): (
        "An OWNER/REPO slug.  The description mentions a path only to say "
        "the slug is detected from the separate ``path`` argument."
    ),
    ("juju_deploy", "charm"): (
        "A charm name or a path to a local .charm file.  Charm names are the "
        "common case, and matching a bare name against path globs would "
        "mis-fire; the deploy surface is gated by the ``tools`` section."
    ),
}


def _is_path_shaped(name: str, schema: dict[str, object]) -> bool:
    """Return whether *name* / *schema* look like a filesystem location."""
    if name in _PATH_NAME_HINTS or name.endswith(_PATH_NAME_SUFFIXES):
        return True
    description = schema.get("description")
    if not isinstance(description, str):
        return False
    return bool(_PATH_DESCRIPTION_RE.search(description))


def _declared_parameters() -> list[tuple[str, str, dict[str, object]]]:
    """Return ``(tool_name, parameter_name, schema)`` for the whole registry."""
    rows: list[tuple[str, str, dict[str, object]]] = []
    for tool in expand_leaves(build_tools()):
        parameters = tool.parameters or {}
        properties = parameters.get("properties") or {}
        if not isinstance(properties, dict):
            continue
        for parameter_name, schema in properties.items():
            rows.append((tool.name, parameter_name, schema if isinstance(schema, dict) else {}))
    return rows


class TestPathArgumentCoverage:
    """``_PATH_ARGUMENT_KEYS`` versus the live tool catalogue."""

    def test_registry_is_non_trivial(self):
        """Guard the guard — an empty registry would pass everything."""
        rows = _declared_parameters()
        assert len(rows) > 100
        assert any(name == "path" for _, name, _ in rows)

    def test_every_path_argument_is_covered_or_exempt(self):
        """No tool may carry a path argument the ``paths`` section cannot see."""
        covered = frozenset(permissions._PATH_ARGUMENT_KEYS)
        uncovered: list[str] = []
        for tool_name, parameter_name, schema in _declared_parameters():
            if parameter_name in covered:
                continue
            if not _is_path_shaped(parameter_name, schema):
                continue
            if (tool_name, parameter_name) in _EXEMPT_PARAMETERS:
                continue
            uncovered.append(f"{tool_name}.{parameter_name}: {schema.get('description')!r}")
        assert not uncovered, (
            "These tool parameters look like filesystem paths but are invisible "
            "to the ``paths`` permission section, so a path rule silently will "
            "not apply to them.  Add the argument name to "
            "``permissions._PATH_ARGUMENT_KEYS``, or add it to "
            "``_EXEMPT_PARAMETERS`` in this module with the reason it is not a "
            "path:\n  " + "\n  ".join(sorted(uncovered))
        )

    def test_exemptions_still_describe_live_parameters(self):
        """A stale exemption hides a real gap — fail when one stops applying."""
        declared = {(tool, name) for tool, name, _ in _declared_parameters()}
        stale = sorted(key for key in _EXEMPT_PARAMETERS if key not in declared)
        assert not stale, (
            f"``_EXEMPT_PARAMETERS`` names parameters that no longer exist; drop them: {stale}"
        )

    def test_exemptions_are_not_also_covered(self):
        """An exempt name that is also in the keys tuple is a contradiction."""
        covered = frozenset(permissions._PATH_ARGUMENT_KEYS)
        both = sorted(name for _, name in _EXEMPT_PARAMETERS if name in covered)
        assert not both, (
            "These parameters are both exempted here and listed in "
            f"``_PATH_ARGUMENT_KEYS``; the exemption is dead: {both}"
        )

    def test_every_key_is_used_by_some_tool(self):
        """A key no tool declares is dead weight — flag it so the tuple stays honest."""
        declared = {name for _, name, _ in _declared_parameters()}
        # ``filename`` is kept deliberately: it is the conventional alias
        # for a path argument and costs one dict lookup, so a tool (or an
        # MCP server, whose schemas are not in this registry) that uses it
        # is covered from the start.
        unused = sorted(key for key in permissions._PATH_ARGUMENT_KEYS if key not in declared)
        assert unused == ["filename"], (
            "``_PATH_ARGUMENT_KEYS`` has entries no catalogued tool declares. "
            "Either a tool was renamed and the key should follow, or the key "
            f"should go: {unused}"
        )
