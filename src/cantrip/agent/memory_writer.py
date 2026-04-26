"""Auto-writer subagent for memory capture (Phase 43.2).

Given a trigger context (user correction, tool-failure-then-retry, task
complete), run a single LLM call that:

1. Decides whether the event is worth remembering (the "saves ≥5 minutes
   next time?" gate the spec calls out).
2. If so, emits a structured memory proposal — title, kind, scope, body,
   tags — in JSON.

The caller separately supplies the file paths the agent touched while the
event unfolded; the auto-writer computes current SHAs so the stored
citations can drive revalidation later (Phase 43.2a).
"""

from __future__ import annotations

import dataclasses
import enum
import json
import logging
import pathlib
import re
from typing import TYPE_CHECKING, Any

from cantrip.agent.memory import sha_for_range
from cantrip.agent.prompts.memory_writer import render_memory_writer_prompt
from cantrip.llm.base import Message, Role

if TYPE_CHECKING:
    from cantrip.agent.memory import MemoryEntry, MemoryManager
    from cantrip.llm.base import LLMProvider

log = logging.getLogger(__name__)


# Tool names whose arguments carry a file ``path``.  Used by
# ``collect_file_citations`` to harvest candidate citations from a
# subagent's tool-call log.  Added here rather than in the tools module
# to avoid a dependency cycle (memory_writer imports from memory, not
# from tools).
_FILE_TOOL_NAMES = frozenset({"read_file", "write_file", "edit_file", "multi_edit"})


# Temperature for the writer call.  Lower than conversation (0.7) so two
# similar triggers produce similar memories, but not zero — we want the
# model to phrase its rationale naturally.
_WRITER_TEMPERATURE = 0.3

# Hard cap on the writer's output.  A good memory is short; a 2k-token
# cap is generous and prevents a runaway model from drowning the pass.
_WRITER_MAX_TOKENS = 2000


class TriggerKind(enum.StrEnum):
    """What conversation-loop event prompted the auto-writer."""

    USER_CORRECTION = "user_correction"
    TOOL_FAILURE_RETRY = "tool_failure_retry"
    TASK_COMPLETE = "task_complete"


@dataclasses.dataclass(frozen=True)
class WriteMemoryContext:
    """Inputs the conversation loop passes to the writer.

    ``summary`` is a one-line human description of what happened (shown
    to the LLM verbatim); ``detail`` is optional longer context.  The
    writer uses these to decide whether to write and to compose the
    memory body — it never sees the full conversation history, which
    keeps the prompt small and the decision focused.

    ``cited_paths`` is the set of files the agent touched while the
    event unfolded.  The caller collects these from the tool-call log
    (usually via ``collect_file_citations``); the writer computes SHAs
    at call time so revalidation has a baseline.
    """

    trigger: TriggerKind
    summary: str
    detail: str = ""
    cited_paths: list[pathlib.Path] = dataclasses.field(default_factory=list)
    charm_name: str | None = None
    charm_path: pathlib.Path | None = None
    framework: str | None = None


@dataclasses.dataclass(frozen=True)
class WriteMemoryProposal:
    """Structured memory the LLM proposes to persist."""

    title: str
    kind: str
    scope: str
    body: str
    tags: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class AutoWriteDecision:
    """Outcome of a single auto-writer pass.

    ``entry`` is populated only when ``persisted`` is True — i.e. the
    LLM said "write", the proposal parsed cleanly, and the manager
    accepted it.  ``reasoning`` carries the LLM's explanation
    regardless, so callers can surface "skipped because …" in UI.
    """

    decision: str  # "write" or "skip"
    reasoning: str
    proposal: WriteMemoryProposal | None = None
    persisted: bool = False
    entry: MemoryEntry | None = None
    error: str | None = None


def collect_file_citations(
    tool_calls: list[dict[str, Any]], *, base_path: pathlib.Path | None = None
) -> list[pathlib.Path]:
    """Extract candidate citation paths from a tool-call log.

    Scans for calls to the file-editing tools (``read_file``,
    ``write_file``, ``edit_file``, ``multi_edit``) and returns the
    deduplicated list of files they touched — resolved against
    ``base_path`` when the tool argument is relative.  Unresolvable
    or non-existent paths are dropped; the writer only cites real files.
    """
    seen: set[pathlib.Path] = set()
    ordered: list[pathlib.Path] = []
    for call in tool_calls:
        name = call.get("name")
        if name not in _FILE_TOOL_NAMES:
            continue
        args = call.get("arguments") or {}
        raw = args.get("path") or args.get("file_path")
        if not isinstance(raw, str) or not raw.strip():
            continue
        candidate = pathlib.Path(raw)
        if not candidate.is_absolute():
            if base_path is None:
                continue
            candidate = base_path / candidate
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(resolved)
    return ordered


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_BARE_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_writer_response(raw: str) -> dict[str, Any]:
    """Extract a JSON object from the LLM's response.

    Handles three common shapes: bare JSON, a fenced ``json`` block, and
    a fenced unlabelled block.  Raises :class:`ValueError` when nothing
    parses — the caller logs and treats it as a "skip".
    """
    stripped = raw.strip()
    fence_match = _JSON_FENCE_RE.match(stripped)
    if fence_match:
        stripped = fence_match.group(1).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        bare_match = _BARE_JSON_RE.search(raw)
        if bare_match is None:
            raise ValueError("no JSON object found in writer response") from None
        try:
            parsed = json.loads(bare_match.group(0))
        except json.JSONDecodeError as exc:
            raise ValueError(f"writer response is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("writer response must be a JSON object")
    return parsed


class AutoWriter:
    """Drive a single auto-writer LLM call and persist its proposal.

    Constructed once per agent; the same instance services every
    trigger.  The writer uses the agent's primary provider so it runs
    on whatever model is handling the conversation — the gating
    heuristic (worth ≥5 minutes?) works well on any capable model.
    """

    def __init__(self, provider: LLMProvider, manager: MemoryManager) -> None:
        self._provider = provider
        self._manager = manager

    async def propose(self, context: WriteMemoryContext) -> AutoWriteDecision:
        """Run the writer LLM call without persisting the result."""
        prompt = render_memory_writer_prompt(context)
        messages = [Message(role=Role.USER, content=prompt)]
        try:
            response = await self._provider.complete(
                messages,
                temperature=_WRITER_TEMPERATURE,
                max_tokens=_WRITER_MAX_TOKENS,
            )
        except Exception as exc:  # noqa: BLE001 - defensive: many providers raise different errors
            log.warning("AutoWriter LLM call failed: %s", exc)
            return AutoWriteDecision(
                decision="skip",
                reasoning="LLM call failed",
                error=str(exc),
            )
        return _decision_from_response(response.content)

    async def write(self, context: WriteMemoryContext) -> AutoWriteDecision:
        """Propose a memory and persist it when the LLM says to write."""
        decision = await self.propose(context)
        if decision.decision != "write" or decision.proposal is None:
            return decision
        proposal = decision.proposal
        citations = _build_citations(context.cited_paths)
        try:
            entry = self._manager.write(
                scope=proposal.scope,
                title=proposal.title,
                kind=proposal.kind,
                body=proposal.body,
                tags=list(proposal.tags),
                citations=citations,
                source="auto",
            )
        except Exception as exc:  # noqa: BLE001 - persistence surface varies by scope
            log.warning("AutoWriter persistence failed: %s", exc)
            return AutoWriteDecision(
                decision="write",
                reasoning=decision.reasoning,
                proposal=proposal,
                persisted=False,
                error=str(exc),
            )
        return AutoWriteDecision(
            decision="write",
            reasoning=decision.reasoning,
            proposal=proposal,
            persisted=True,
            entry=entry,
        )


def _decision_from_response(content: str) -> AutoWriteDecision:
    """Parse the raw LLM response into an :class:`AutoWriteDecision`.

    On any parse failure the decision collapses to "skip" with the
    error surfaced — we never persist a memory we don't understand.
    """
    try:
        payload = parse_writer_response(content)
    except ValueError as exc:
        return AutoWriteDecision(decision="skip", reasoning="parse failed", error=str(exc))
    raw_decision = str(payload.get("decision", "skip")).lower()
    reasoning = str(payload.get("reasoning", "")).strip()
    if raw_decision != "write":
        return AutoWriteDecision(decision="skip", reasoning=reasoning or "skip")
    memory = payload.get("memory")
    if not isinstance(memory, dict):
        return AutoWriteDecision(
            decision="skip",
            reasoning=reasoning or "malformed memory block",
            error="memory block missing",
        )
    title = str(memory.get("title", "")).strip()
    kind = str(memory.get("kind", "")).strip().lower()
    scope = str(memory.get("scope", "")).strip().lower()
    body = str(memory.get("body", "")).strip()
    tags_raw = memory.get("tags") or []
    tags = [str(t) for t in tags_raw if isinstance(t, str)]
    if not (title and kind and scope and body):
        return AutoWriteDecision(
            decision="skip",
            reasoning=reasoning or "required memory fields missing",
            error="missing required fields",
        )
    proposal = WriteMemoryProposal(title=title, kind=kind, scope=scope, body=body, tags=tags)
    return AutoWriteDecision(
        decision="write", reasoning=reasoning or "writer accepted", proposal=proposal
    )


def _build_citations(paths: list[pathlib.Path]) -> list[dict[str, Any]]:
    """Turn a list of resolved file paths into citation dicts with SHAs.

    Unreadable files are logged and skipped — a missing SHA is worse
    than a missing citation, since revalidation relies on it.
    """
    citations: list[dict[str, Any]] = []
    for path in paths:
        try:
            sha = sha_for_range(path, None, None)
        except OSError as exc:
            log.debug("Skipping unreadable citation path %s: %s", path, exc)
            continue
        citations.append({"path": str(path), "sha": sha})
    return citations


__all__ = [
    "AutoWriteDecision",
    "AutoWriter",
    "TriggerKind",
    "WriteMemoryContext",
    "WriteMemoryProposal",
    "collect_file_citations",
    "parse_writer_response",
]
