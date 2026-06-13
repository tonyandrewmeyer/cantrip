"""Repository-map and code-intelligence services for the agent.

This module hosts :class:`RepoMapService`, a service composed onto
:class:`~cantrip.agent.core.CantripAgent`. It lazily builds and caches the
repository map and code-intelligence index, refreshes them on demand, and
renders the repo-map summary for prompt injection. All caches stay on the
agent; the service reads and writes them through ``self._agent``.
"""

from __future__ import annotations

import logging
import typing

from cantrip.codeintel import CodeIntel
from cantrip.repomap import RepoMap

if typing.TYPE_CHECKING:
    from cantrip.agent.core import CantripAgent

log = logging.getLogger("cantrip.agent.core")


class RepoMapService:
    """Repository-map and code-intelligence construction, caching, and rendering."""

    def __init__(self, agent: CantripAgent) -> None:
        self._agent = agent

    def get_repo_map(self) -> RepoMap | None:
        """The repo-map for the active charm, if one is configured.

        Built lazily on first access; subsequent calls reuse the cache.
        Returns ``None`` when no charm path is set or the path doesn't
        exist on disk — slash commands and tests rely on this to skip
        the section gracefully.
        """
        if self._agent.state.charm_path is None:
            return None
        if not self._agent.state.charm_path.exists():
            return None
        if self._agent._repo_map_cache is None:
            self._agent._repo_map_cache = RepoMap(self._agent.state.charm_path)
        return self._agent._repo_map_cache

    def refresh_repo_map(self) -> str:
        """Force a full rebuild of the repo-map.

        Used by ``/map-refresh``.  Returns the rendered map at the
        full configured budget, or the empty string when no charm is
        active.
        """
        rm = self._agent.repo_map
        if rm is None:
            return ""
        rm.build(force=True)
        return rm.render_full()

    def get_code_intel(self) -> CodeIntel | None:
        """Phase 72b read-only code-intelligence index for the active charm.

        Built lazily — same pattern as :attr:`repo_map`.  Returns
        ``None`` when no charm path is set or the path doesn't exist
        on disk; tools handle ``None`` by returning a clear error
        rather than failing silently.
        """
        if self._agent.state.charm_path is None:
            return None
        if not self._agent.state.charm_path.exists():
            return None
        if self._agent._code_intel_cache is None:
            self._agent._code_intel_cache = CodeIntel(self._agent.state.charm_path)
        return self._agent._code_intel_cache

    def code_intel_or_none(self) -> CodeIntel | None:
        """Bound getter handed to the codeintel tools.

        Lambdas would close over ``self._agent`` just as well, but a named
        method gives the tool layer a stable hook to monkey-patch in
        tests and a tidier ``repr`` if a tool ever logs its
        provenance.
        """
        return self._agent.code_intel

    def render_repo_map(self) -> str | None:
        """Build (incremental) and render the repo-map for prompt injection.

        Returns ``None`` when there's nothing to inject so the Jinja
        ``{% if repo_map %}`` block stays out of the prompt entirely.
        Failures are swallowed: the repo-map is a navigation aid; it
        must never break the conversation loop.  Anything more
        targeted than a bare ``Exception`` would risk a future
        regression where a new error type slips through and kills
        every turn.
        """
        rm = self._agent.repo_map
        if rm is None:
            return None
        try:
            rm.build()
            pressure = self._agent._context_manager.context_pressure(self._agent.state.messages)
            rendered = rm.render_for_prompt(context_pressure=pressure)
        except Exception as exc:  # noqa: BLE001 — best-effort; never block a turn.
            log.warning("repomap: render skipped (%s: %s)", type(exc).__name__, exc)
            return None
        return rendered or None
