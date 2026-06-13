"""Provider selection and model switching for the agent.

This module hosts :class:`ProviderManager`, a service composed onto
:class:`~cantrip.agent.core.CantripAgent`. It resolves the provider for a given
purpose (routing light-model purposes to the configured light provider),
switches the active model and re-resolves the light provider while invalidating
the tool caches, and resolves the architect and editor role providers. All
provider and cache state stays on the agent; the service reads and writes it
through ``self._agent``.

``create_provider``, ``resolve_light_provider``, and ``_LIGHT_PURPOSES`` are
reached through :mod:`cantrip.agent.core` (lazily, to avoid an import cycle) so
that tests patching ``cantrip.agent.core.create_provider`` still take effect.
"""

from __future__ import annotations

import logging
import typing

from cantrip.agent.context.context import resolve_short_session_mode
from cantrip.llm.base import LLMProvider
from cantrip.ui import events as ui_events

if typing.TYPE_CHECKING:
    from cantrip.agent.core import CantripAgent

log = logging.getLogger("cantrip.agent.core")


class ProviderManager:
    """Provider resolution, model switching, and role-provider selection."""

    def __init__(self, agent: CantripAgent) -> None:
        self._agent = agent

    def get_provider(self, purpose: str) -> LLMProvider:
        """Select the appropriate provider for a given purpose.

        Purposes listed in ``core._LIGHT_PURPOSES`` are routed to the light
        provider when one is available; everything else uses the primary.
        """
        from cantrip.agent import core

        if self._agent._light_provider and purpose in core._LIGHT_PURPOSES:
            return self._agent._light_provider
        return self._agent.provider

    def switch_model(
        self,
        provider_name: str,
        model: str | None = None,
        *,
        base_url: str | None = None,
        snap_name: str = "gemma3",
    ) -> None:
        """Swap the active provider mid-session (Phase 67.2).

        Constructs a new provider via :func:`create_provider`, replaces
        ``self._agent.provider`` atomically, rebuilds the light provider using
        same-family rules, updates the context manager's window, and
        invalidates caches that captured the old provider (tool list,
        auto-writer).  Cost accumulators (``cache_creation_tokens`` /
        ``cache_read_tokens``) survive the swap — they're session
        totals, not per-provider.

        Raises:
            ProviderError / ValueError: Propagated from
                :func:`create_provider` when construction fails (bad
                name, missing API key, missing ``base_url`` for
                ``openai-compatible``).

        Emits a ``model_switched`` event so the status bar, cost
        tracker, and transcript listeners refresh.  Any CLI-configured
        hybrid light provider is dropped in favour of same-family
        routing — callers who relied on a specific light-provider
        combination should restart the session instead.
        """
        from cantrip.agent import core

        new_provider = core.create_provider(
            provider_name,
            model,
            snap_name=snap_name,
            base_url=base_url,
        )
        previous_provider = self._agent.provider
        self._agent.provider = new_provider
        self._agent._light_provider, _ = core.resolve_light_provider(
            new_provider,
            provider_name,
        )
        self._agent._context_manager.update_context_window(new_provider.context_window_tokens)
        # When the operator hasn't pinned --short-session, the mode tracks
        # whichever provider is now active (e.g. swapping to a tight-context
        # snap mid-session flips it on; swapping back off).
        self._agent._context_manager.set_short_session_mode(
            resolve_short_session_mode(new_provider, self._agent._short_session_override)
        )
        # Caches that captured the old provider need rebuilding on the
        # next access.  Memory manager is left alone: its provider is
        # used only inside the auto-writer path, which is itself cached
        # here and gets dropped.
        self._agent._tools_cache = None
        self._agent._tool_map_cache = None
        self._agent._auto_writer_cache = None

        if self._agent._store:
            self._agent._store.record_event(
                "model_switched",
                {
                    "provider": new_provider.name,
                    "model": new_provider.model_name,
                    "previous_provider": previous_provider.name,
                    "previous_model": previous_provider.model_name,
                },
            )

        try:
            self._agent._event_bus.publish(
                ui_events.model_switched(
                    provider=new_provider.name,
                    model=new_provider.model_name,
                    previous_provider=previous_provider.name,
                    previous_model=previous_provider.model_name,
                    context_window=new_provider.context_window_tokens,
                )
            )
            self._agent._publish_short_session_status()
        except Exception:  # noqa: BLE001
            log.debug("model_switched event publish failed", exc_info=True)

    def architect_provider(self) -> LLMProvider:
        """Provider for the architect pass.

        Always the main provider.  ``state.architect_consecutive_failures``
        beyond the threshold also routes the *editor* pass through the
        architect — see :meth:`editor_provider`.
        """
        return self._agent.provider

    def editor_provider(self) -> LLMProvider:
        """Provider for the editor pass.

        Resolution order:

        1. Per-session override (``state.editor_provider`` /
           ``editor_model``) — set explicitly via ``/architect on
           provider/model``.  Constructed on-demand via
           :func:`create_provider`; failures fall through to (2).
        2. The session's existing light provider (the one used for
           compaction etc.) when one is configured — same family,
           cheaper variant.
        3. Fallback to the main provider when no lighter variant is
           available.  No cost saving in that case but the dual-pass
           shape stays so the user sees the architect/editor split
           in the transcript.

        When the editor has failed too many turns in a row
        (``architect_consecutive_failures >= architect_failure_threshold``)
        the architect provider is used for both passes — the
        documented escape hatch from a weak editor.
        """
        from cantrip.agent import core

        if (
            self._agent.state.architect_consecutive_failures
            >= self._agent.state.architect_failure_threshold
        ):
            log.info(
                "Editor escalated to architect provider after %d consecutive failures",
                self._agent.state.architect_consecutive_failures,
            )
            return self._agent.provider
        if self._agent.state.editor_provider:
            try:
                return core.create_provider(
                    self._agent.state.editor_provider,
                    self._agent.state.editor_model,
                )
            except (ValueError, RuntimeError, OSError) as exc:
                log.warning(
                    "Editor provider override %s/%s failed (%s); falling back to light provider",
                    self._agent.state.editor_provider,
                    self._agent.state.editor_model,
                    exc,
                )
        if self._agent._light_provider is not None:
            return self._agent._light_provider
        return self._agent.provider
