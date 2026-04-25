"""Placeholder entry point for the ``juju-cantrip`` distribution.

The real package is in development and will replace this teaser in an
upcoming release.
"""

from __future__ import annotations

import sys

from juju_cantrip import __version__

TEASER = f"""\
juju-cantrip {__version__} — coming soon.

Cantrip is an AI-powered autonomous agent that builds Juju charms.
This release reserves the name on PyPI; the real package ships shortly.

Watch https://github.com/tonyandrewmeyer/cantrip for updates.
"""


def main() -> int:
    sys.stdout.write(TEASER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
