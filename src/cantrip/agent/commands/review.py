"""``/review`` slash command.

Extracted from :mod:`cantrip.agent.commands.slash` (Phase 113.5).  Owns the
``--severity`` / ``--name`` filter parsing and the combined Markdown report
that merges structured-LLM check results (``cantrip.agent.checks``) with the
deterministic linter diagnostics gathered for the active charm.
"""

from __future__ import annotations

import dataclasses
import pathlib
import typing

if typing.TYPE_CHECKING:
    from cantrip.agent.commands.slash import SlashResult
    from cantrip.agent.core import CantripAgent


# Severities the ``/review`` filter accepts.  Mirrors the ordered tuple
# in :mod:`cantrip.agent.checks`; kept in sync via the unit-test below.
_REVIEW_SEVERITIES: frozenset[str] = frozenset(
    {"critical", "high", "error", "medium", "warning", "low", "info"}
)


@dataclasses.dataclass(frozen=True)
class _ReviewFilters:
    """Parsed ``/review`` filter expression.

    ``None`` means "no filter on that axis".  Severities are matched
    case-insensitively against :attr:`Check.severity`; names use
    :func:`fnmatch.fnmatchcase` so ``--name 'cos-*'`` does what an
    operator expects.
    """

    severities: frozenset[str] | None = None
    name_globs: tuple[str, ...] | None = None


def _parse_review_filters(args: str) -> tuple[_ReviewFilters | None, str | None]:
    """Parse ``--severity`` / ``--name`` args; return ``(filters, error)``.

    Accepts:

    * ``--severity high`` (one value)
    * ``--severity=high``
    * ``--severity high,error`` (comma-separated; whitespace tolerated)
    * Multiple ``--severity`` / ``--name`` flags — accumulated.

    Returns ``(filters, None)`` on success; ``(None, message)`` on a
    parse error.  An empty *args* string yields filters that match
    every check (i.e. behaves like today's bare ``/review``).
    """
    import shlex

    if not args.strip():
        return _ReviewFilters(), None

    try:
        tokens = shlex.split(args)
    except ValueError as exc:
        return None, f"_Bad ``/review`` arguments — {exc}._"

    severities: set[str] = set()
    name_globs: list[str] = []

    def _split_values(raw: str) -> list[str]:
        return [piece.strip() for piece in raw.split(",") if piece.strip()]

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if "=" in token and token.startswith("--"):
            key, _, value = token.partition("=")
            consume_next = False
        elif token in {"--severity", "--name"}:
            key = token
            if i + 1 >= len(tokens):
                return None, f"_``{key}`` needs a value._"
            value = tokens[i + 1]
            consume_next = True
        else:
            return (
                None,
                (
                    f"_Unknown ``/review`` argument: ``{token}``.  "
                    "Use ``--severity <level>`` or ``--name <pattern>``._"
                ),
            )

        if key == "--severity":
            for piece in _split_values(value):
                lowered = piece.lower()
                if lowered not in _REVIEW_SEVERITIES:
                    levels = ", ".join(sorted(_REVIEW_SEVERITIES))
                    return None, f"_Unknown severity ``{piece}``.  Known: {levels}._"
                severities.add(lowered)
        elif key == "--name":
            for piece in _split_values(value):
                name_globs.append(piece)
        else:
            return None, f"_Unknown flag ``{key}``._"

        i += 2 if consume_next else 1

    filters = _ReviewFilters(
        severities=frozenset(severities) if severities else None,
        name_globs=tuple(name_globs) if name_globs else None,
    )
    return filters, None


def _apply_review_filters(checks_list: list, filters: _ReviewFilters) -> list:
    """Return the subset of *checks_list* matching the parsed filters.

    Severities and names are AND-combined — passing ``--severity high
    --name foo`` returns checks whose severity is ``high`` *and* whose
    name matches ``foo``.  Within an axis the matches are OR-combined
    (any listed severity, any listed pattern).
    """
    import fnmatch

    result = []
    for check in checks_list:
        if filters.severities is not None and check.severity.lower() not in filters.severities:
            continue
        if filters.name_globs is not None and not any(
            fnmatch.fnmatchcase(check.name, pattern) for pattern in filters.name_globs
        ):
            continue
        result.append(check)
    return result


def _handle_review(agent: CantripAgent, args: str) -> SlashResult:
    """``/review``: run loaded prompt-based checks against the charm.

    Each check is one structured LLM call (Phase 70.4); results are
    aggregated into a single Markdown report.  When the active charm
    also has linter diagnostics (Phase 72.4 ruff/ty/charmlint), they
    appear underneath as a deterministic-checks section so the user
    sees one combined view.

    ``args`` accepts ``--severity <level>`` and ``--name <pattern>``
    filters (CHECKS.md "Future work" item 3 — Phase 70.4 follow-up).
    Both flags are repeatable and accept comma-separated values;
    ``--name`` uses ``fnmatch`` so ``--name 'cos-*'`` matches every
    check whose name starts with ``cos-``.
    """
    from cantrip.agent import checks
    from cantrip.agent.commands.slash import SlashResult
    from cantrip.agent.context import lint_context

    filters, error = _parse_review_filters(args)
    if filters is None:
        usage = (
            "**Usage:** ``/review [--severity <level>] [--name <pattern>]``\n"
            "Severity values: critical, high, error, medium, warning, low, info "
            "(comma-separated; flag is repeatable).\n"
            "``--name`` accepts ``fnmatch`` globs (e.g. ``cos-*``); "
            "repeatable to OR multiple patterns."
        )
        return SlashResult(
            text=f"{error or ''}\n\n{usage}".strip(),
            markdown=True,
        )

    charm_path = getattr(agent.state, "charm_path", None)
    if charm_path is None:
        return SlashResult(
            text=(
                "**Cannot run /review:** no charm path for this session.  "
                "Open a charm with the CLI and try again."
            ),
            markdown=True,
        )

    provider = getattr(agent, "provider", None)
    if provider is None:
        return SlashResult(
            text="**Cannot run /review:** no LLM provider attached to this agent.",
            markdown=True,
        )

    charm_root = pathlib.Path(charm_path)

    async def _run() -> str:
        index = checks.CheckIndex(project_root=charm_root)
        discovered = index.discover()
        if not discovered and not index.shadows:
            return (
                "_No checks configured._  Drop a markdown file under "
                "``.cantrip/checks/`` (repo) or "
                "``~/.config/cantrip/checks/`` (user) to add one — "
                "see ``design/CHECKS.md`` for the schema."
            )
        filtered = _apply_review_filters(discovered, filters)
        if not filtered and (filters.severities is not None or filters.name_globs is not None):
            return _render_filter_miss(filters, discovered)
        report = await checks.run_all_checks(
            filtered,
            provider=provider,
            charm_root=charm_root,
            shadows=index.shadows,
        )
        sections = [report.to_text()]
        diag = await lint_context.gather_project_diagnostics(charm_root)
        if not diag.is_empty():
            sections.append("---")
            sections.append(diag.to_text(header="Deterministic checks"))
        return "\n\n".join(sections)

    prelude = "Running review checks…"
    return SlashResult(text=prelude, followup=_run(), markdown=True)


def _render_filter_miss(filters: _ReviewFilters, discovered: list) -> str:
    """Render an honest "no checks matched" hint when filters elide everything."""
    bits: list[str] = []
    if filters.severities is not None:
        bits.append(f"severity in [{', '.join(sorted(filters.severities))}]")
    if filters.name_globs is not None:
        bits.append(f"name matches [{', '.join(filters.name_globs)}]")
    have = ", ".join(sorted(c.name for c in discovered)) or "_none_"
    return (
        "_No checks matched the filter — " + " and ".join(bits) + f".  Configured checks: {have}._"
    )
