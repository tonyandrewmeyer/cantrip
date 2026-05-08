"""``cantrip skill export`` handler (Phase 50.2)."""

from __future__ import annotations

import argparse
import sys


def _skill_export(args: argparse.Namespace) -> int:
    """Export a discovered skill to a SKILL.md file (Phase 50.2).

    Uses the default :class:`SkillsIndex` — bundled + external dirs — so a
    user can round-trip their own ``~/.config/cantrip/skills/<foo>/SKILL.md``
    skill through the export step to, say, paste a sanitised copy into a
    gist or PR.
    """
    from cantrip.agent import skill_export
    from cantrip.agent.skills import SkillsIndex

    index = SkillsIndex()
    index.discover()

    try:
        result = skill_export.export_skill(
            args.name,
            args.path,
            index=index,
            charm_path=args.charm_path,
            force=args.force,
        )
    except skill_export.SkillExportError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(f"Exported {result.name!r} to {result.output_path}")
    if result.redactions:
        print(f"Redacted {result.redactions} secret-pattern match(es).")
    return 0
