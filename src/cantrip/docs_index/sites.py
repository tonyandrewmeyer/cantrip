"""Registry of documentation sites the docs index can crawl.

Each :class:`DocSite` declares the human-readable name (the slug
users type after ``@docs``), the home URL, and the sitemap.xml URL
the crawler walks.  Phase 72.1 ships configuration for the six
canonical Canonical doc surfaces called out in the roadmap; users
opt in per-site via ``cantrip docs index --site <name>``.

The registry is *static* by design — these are well-known canonical
sources, not arbitrary URLs.  Future phases can add a user-extensible
config file if a need emerges; today's surface keeps the trust
boundary clear.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True, slots=True)
class DocSite:
    """One documentation site the index can crawl.

    ``name`` is the short slug users type (``juju``, ``ops``, …).
    ``home_url`` lands a human reader on the front page.
    ``sitemap_url`` is the crawler's enumeration source — every
    target site below exposes a ``sitemap.xml`` at a stable path.
    ``description`` is a one-line summary for ``cantrip docs list``.
    """

    name: str
    home_url: str
    sitemap_url: str
    description: str


# The six canonical surfaces called out in ROADMAP 72.1.  Order is
# the order ``cantrip docs list`` displays them — most-foundational
# first.
SITES: tuple[DocSite, ...] = (
    DocSite(
        name="juju",
        home_url="https://documentation.ubuntu.com/juju/3.6/",
        sitemap_url="https://documentation.ubuntu.com/juju/3.6/sitemap.xml",
        description="Juju documentation (operator framework + CLI)",
    ),
    DocSite(
        name="ops",
        home_url="https://documentation.ubuntu.com/ops/latest/",
        sitemap_url="https://documentation.ubuntu.com/ops/latest/sitemap.xml",
        description="ops library reference (charm authoring API)",
    ),
    DocSite(
        name="charmcraft",
        home_url="https://documentation.ubuntu.com/charmcraft/stable/",
        sitemap_url="https://documentation.ubuntu.com/charmcraft/stable/sitemap.xml",
        description="charmcraft reference (charm packaging tooling)",
    ),
    DocSite(
        name="rockcraft",
        home_url="https://documentation.ubuntu.com/rockcraft/stable/",
        sitemap_url="https://documentation.ubuntu.com/rockcraft/stable/sitemap.xml",
        description="rockcraft reference (OCI image packaging)",
    ),
    DocSite(
        name="jubilant",
        home_url="https://documentation.ubuntu.com/jubilant/",
        sitemap_url="https://documentation.ubuntu.com/jubilant/sitemap.xml",
        description="Jubilant (integration-testing helpers)",
    ),
    DocSite(
        name="charmlibs",
        home_url="https://documentation.ubuntu.com/charmlibs/",
        sitemap_url="https://documentation.ubuntu.com/charmlibs/sitemap.xml",
        description="charm libraries reference (PyPI charm libs)",
    ),
)


def by_name(name: str) -> DocSite | None:
    """Return the :class:`DocSite` whose ``name`` matches *name*."""
    needle = name.strip().lower()
    for site in SITES:
        if site.name == needle:
            return site
    return None


def names() -> tuple[str, ...]:
    """Return every registered site name in display order."""
    return tuple(site.name for site in SITES)
