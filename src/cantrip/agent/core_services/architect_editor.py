"""Architect / editor two-model turn split for the agent.

``ArchitectEditorMixin`` holds the Phase 71.2 dual-pass machinery: an
*architect* pass that proposes the change in prose, an *editor* pass that
realises it as tool calls, the fall-through predicate, transcript-event
recording, and the pre-/post-turn auto-commit hooks that bracket a turn.
Mixed into :class:`~cantrip.agent.core.CantripAgent`; provider selection
(``_providers``), the retry helpers (``_complete_with_retry``), and all
state are reached through ``self``.
"""

from __future__ import annotations

import logging
import sqlite3

from cantrip.agent.git import auto_commit
from cantrip.llm import base as llm
from cantrip.llm.base import LLMProvider, Message, Response, Role
from cantrip.ui import events as ui_events

log = logging.getLogger("cantrip.agent.core")


class ArchitectEditorMixin:
    """Architect/editor dual-pass turn execution and commit hooks."""

    # ─── Phase 71.2: Architect / Editor two-model split ──────────────

    _ARCHITECT_INSTRUCTION = (
        "You are operating in *architect* mode for this turn.  Describe "
        "the change you would make in plain prose: which file(s), what "
        "to change, why.  Be specific about line ranges or symbols.  "
        "Do NOT emit tool calls and do NOT write code blocks larger "
        "than a few lines for illustration — a separate *editor* pass "
        "will translate your proposal into the actual edits."
    )

    _EDITOR_INSTRUCTION_TEMPLATE = (
        "Apply the architect's proposal below as concrete tool calls "
        "(``write_file``, ``edit_file``, ``multi_edit``, …).  Edit "
        "exactly the files the architect named; if the proposal is "
        "ambiguous, read the relevant files first.  Do not redesign "
        "the change.\n\n"
        "<architect_proposal>\n{proposal}\n</architect_proposal>"
    )

    def _architect_provider(self) -> LLMProvider:
        return self._providers.architect_provider()

    def _editor_provider(self) -> LLMProvider:
        return self._providers.editor_provider()

    @staticmethod
    def _all_tool_calls_failed(tool_results: list[llm.ToolResult]) -> bool:
        """Predicate driving Phase 71.2 fall-through.

        Returns ``True`` when *every* tool result in the list reports
        ``is_error=True``, ``False`` for an empty list (no calls means
        nothing to fail) or when at least one call succeeded.
        """
        if not tool_results:
            return False
        return all(r.is_error for r in tool_results)

    def _record_architect_editor_event(
        self,
        kind: str,
        response: Response,
        provider: LLMProvider,
    ) -> None:
        """Persist an ``architect_pass`` / ``editor_pass`` transcript event.

        Captures the provider/model attribution so downstream auditors
        can reconstruct who-said-what without joining against the
        ``token_usage`` table.  Best-effort: store errors are logged
        and swallowed so a misconfigured store can't tear down the
        agent loop.
        """
        self._ensure_store()
        if not self._store:
            return
        usage = response.usage or {}
        try:
            self._store.record_event(
                kind,
                {
                    "provider": provider.name,
                    "model": provider.model_name,
                    "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                    "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                    "tool_calls": len(response.tool_calls),
                    "content_excerpt": (response.content or "")[:400],
                },
            )
        except sqlite3.Error:
            log.debug("record_event(%s) failed", kind, exc_info=True)

    # ─── Phase 71.3: Auto-commit-per-turn ─────────────────────────────

    def _maybe_pre_turn_commit_dirty(self) -> None:
        """Commit pre-existing dirty work before the agent runs.

        Gated by ``state.git_auto_commit``; the actual git work
        lives in :mod:`cantrip.agent.git.auto_commit` so the
        conversation loop stays focused on its own concerns.
        Failures inside the helper are non-fatal (logged at
        DEBUG); we never want a broken auto-commit setup to break
        the agent loop.
        """
        if not self.state.git_auto_commit:
            return
        try:
            auto_commit.pre_turn_commit_dirty(self.state.charm_path)
        except Exception:  # noqa: BLE001 — never break the loop.
            log.debug("auto_commit pre-turn failed", exc_info=True)

    async def _summarise_for_commit(
        self,
        user_message: str,
        files: list[str],
    ) -> str | None:
        """Generate a one-line commit subject via the light provider.

        Returns ``None`` when no light provider is configured or
        when generation fails — :func:`auto_commit.build_commit_message`
        falls back to a user-message-derived subject.  The prompt
        is short to keep latency bounded; the subject is the only
        thing we need (the body is composed by
        :func:`auto_commit.build_commit_message` from raw inputs).
        """
        provider = self._light_provider or self.provider
        prompt = (
            "Write a single-line conventional-commit subject (≤72 "
            "characters, imperative mood, no trailing period) for the "
            "agent's edits below.  Return only the subject line — no "
            "preamble, no markdown.\n\n"
            f"User request: {user_message[:400]}\n"
            f"Files touched: {', '.join(files[:10])}"
        )
        try:
            response = await provider.complete(
                messages=[Message(role=Role.USER, content=prompt)],
                tools=None,
                temperature=0.3,
                max_tokens=80,
            )
        except Exception:  # noqa: BLE001 — fall back to derived subject.
            log.debug("auto_commit summary generation failed", exc_info=True)
            return None
        if response and response.content:
            self._record_usage(response, provider=provider)
            return response.content
        return None

    async def _maybe_post_turn_commit_agent_edits(
        self,
        user_message: str,
        turn_start_idx: int,
    ) -> None:
        """Commit files the agent touched in the just-finished turn.

        Walks ``state.messages[turn_start_idx:]`` to pick out
        file-mutating tool calls; if any fired, generates a commit
        subject via the light provider and lands the commit on
        ``state.charm_path`` with a Cantrip co-author trailer.
        Stamps the resulting SHA on
        ``state.last_cantrip_commit_sha`` for future audit.
        """
        if not self.state.git_auto_commit:
            return
        try:
            turn_slice = self.state.messages[turn_start_idx:]
            touched = auto_commit.collect_touched_files(turn_slice)
            if not touched:
                return
            summary = await self._summarise_for_commit(user_message, touched)
            sha = auto_commit.post_turn_commit_agent_edits(
                self.state.charm_path,
                turn_slice,
                user_message,
                summary=summary,
            )
            if sha:
                self.state.last_cantrip_commit_sha = sha
                self._ensure_store()
                if self._store:
                    try:
                        self._store.record_event(
                            "auto_commit",
                            {
                                "sha": sha,
                                "files": touched[:50],
                                "file_count": len(touched),
                            },
                        )
                    except sqlite3.Error:
                        log.debug("auto_commit event record failed", exc_info=True)
        except Exception:  # noqa: BLE001 — never break the loop.
            log.debug("auto_commit post-turn failed", exc_info=True)

    async def _run_architect_editor_turn(
        self,
        messages: list[Message],
        llm_tools: list[llm.Tool] | None,
    ) -> Response:
        """Run a single conversation-loop step as architect → editor.

        Returns a single :class:`Response` whose ``content`` is the
        editor's text and whose ``tool_calls`` are what the editor
        emitted.  Both passes get their usage recorded individually
        (so ``/cost`` shows two model lines per turn) and a
        transcript event each.

        The architect pass passes ``tools=None`` so a strict
        provider can't sneak a tool call in; the editor pass passes
        the full ``llm_tools`` list and is the source of any actual
        edits.

        Used in place of a single ``_complete_with_retry`` call from
        ``_run_conversation_loop`` and
        ``_run_conversation_loop_streaming`` whenever
        ``state.architect_mode`` is True.
        """
        architect_provider = self._architect_provider()
        # Architect: prepend the architect instruction as a SYSTEM
        # message so it's clear the request is "propose, don't act".
        # Don't mutate the caller's list.
        architect_msgs: list[Message] = list(messages) + [
            Message(role=Role.SYSTEM, content=self._ARCHITECT_INSTRUCTION),
        ]
        architect_resp = await self._complete_with_retry(
            architect_msgs,
            tools=None,
            provider=architect_provider,
        )
        self._record_usage(architect_resp, provider=architect_provider)
        self._record_architect_editor_event("architect_pass", architect_resp, architect_provider)
        try:
            self._event_bus.publish(
                ui_events.chat_message(
                    role="system",
                    content=(
                        f"_Architect ({architect_provider.name}/"
                        f"{architect_provider.model_name}) proposed_."
                    ),
                )
            )
        except Exception:  # noqa: BLE001 — UI hook must not break the loop.
            log.debug("architect_pass UI publish failed", exc_info=True)

        editor_provider = self._editor_provider()
        proposal = architect_resp.content or "(no proposal text)"
        # Editor: append the proposal as a synthetic USER message so
        # the conversation alternates cleanly (the prior message ends
        # ASSISTANT or TOOL — never USER — when this method is called).
        editor_msgs: list[Message] = list(messages) + [
            Message(
                role=Role.USER,
                content=self._EDITOR_INSTRUCTION_TEMPLATE.format(proposal=proposal),
            )
        ]
        editor_resp = await self._complete_with_retry(
            editor_msgs,
            tools=llm_tools,
            provider=editor_provider,
        )
        self._record_usage(editor_resp, provider=editor_provider)
        self._record_architect_editor_event("editor_pass", editor_resp, editor_provider)
        return editor_resp
