"""Blind A/B arena mode — Phase 47.5.

A one-off preference-capture flow: two providers answer the same prompt,
the responses are shuffled and labelled ``A`` / ``B`` (no model names
shown), and the user picks a winner.  The outcome feeds the memory
subsystem as a global-scope ``fact`` so future turns can consult the
user's recorded preferences across charms.

Arena mode is deliberately separate from the race coordinator in
:mod:`cantrip.agent.race`: the race coordinator runs full subagent
loops with tools and objective scoring, whereas arena runs a single
provider completion per candidate and defers to the user for the
verdict.  The two mechanisms share a name and a goal but not an
implementation.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import random
import secrets
from typing import TYPE_CHECKING

from cantrip.agent.retry import complete_with_retry
from cantrip.llm.base import Message, Role

if TYPE_CHECKING:
    from cantrip.agent.memory import MemoryEntry, MemoryManager
    from cantrip.llm import base as llm

log = logging.getLogger(__name__)


# The ``/arena`` command passes the user's prompt straight through to
# both providers with no tools and no system-prompt injection — we want
# the models' default personalities, not a charm-builder persona.
# Temperature matches the conversation default so the responses feel
# like normal chat rather than deterministic canned answers.
_ARENA_TEMPERATURE = 0.7

# Hard cap on each candidate's response.  Arena is a quick compare, not
# a full work session; cap at 2 000 tokens so the A/B blocks stay
# readable side-by-side in the TUI chat.
_ARENA_MAX_TOKENS = 2000

# Memory-title prefix.  Titles are ``arena-preference-<8-hex>`` so the
# user can list or forget them by pattern.  The hex suffix keeps titles
# unique even when two arenas land in the same second.
_MEMORY_TITLE_PREFIX = "arena-preference-"

# Valid user picks.  Normalised to lowercase before comparison so the
# surface can pass the raw user reply straight in.
_PICKS_A = frozenset({"a", "pick a", "left"})
_PICKS_B = frozenset({"b", "pick b", "right"})
_PICKS_TIE = frozenset({"tie", "equal", "both", "neither", "t"})
_PICKS_SKIP = frozenset({"skip", "cancel", "abort", "never mind"})


class ArenaError(Exception):
    """Raised when arena mode cannot start (e.g. no second provider)."""


@dataclasses.dataclass(frozen=True)
class ArenaCandidate:
    """One side of a blind A/B arena run.

    ``label`` is the blinded identifier shown to the user (``"A"`` or
    ``"B"``); ``model_name`` and ``provider_name`` are stored so the
    reveal can unmask the winner and the memory can cite the model by
    its real name.
    """

    label: str
    provider_name: str
    model_name: str
    response: str


@dataclasses.dataclass(frozen=True)
class ArenaSession:
    """In-flight arena: two completed responses waiting on the user's pick.

    ``prompt`` is the user's arena prompt verbatim — stored so the
    memory can capture what the preference was actually about.  The
    session is frozen because mutation would invalidate the blinded
    label-to-model mapping.
    """

    prompt: str
    candidates: tuple[ArenaCandidate, ArenaCandidate]
    session_id: str

    @property
    def candidate_a(self) -> ArenaCandidate:
        for c in self.candidates:
            if c.label == "A":
                return c
        raise ValueError("arena session missing candidate A")

    @property
    def candidate_b(self) -> ArenaCandidate:
        for c in self.candidates:
            if c.label == "B":
                return c
        raise ValueError("arena session missing candidate B")


class ArenaOutcome:
    """Symbolic outcomes of an arena pick.

    Not a real enum because a plain class lets callers compare against
    string literals (``outcome == ArenaOutcome.PICKED_A``) without
    importing the enum type — which keeps the surface layers thinner.
    """

    PICKED_A = "picked_a"
    PICKED_B = "picked_b"
    TIE = "tie"
    SKIPPED = "skipped"
    UNRECOGNISED = "unrecognised"


def parse_pick(message: str) -> str:
    """Classify a user reply as A / B / tie / skip / unrecognised.

    Matching is case-insensitive and forgiving — ``a``, ``A``, ``pick A``,
    and ``left`` all map to :data:`ArenaOutcome.PICKED_A`.  Unrecognised
    replies return :data:`ArenaOutcome.UNRECOGNISED` so the caller can
    fall back to its normal message-handling path rather than forcing a
    pick or erroring out.
    """
    lower = message.strip().lower()
    if lower in _PICKS_A:
        return ArenaOutcome.PICKED_A
    if lower in _PICKS_B:
        return ArenaOutcome.PICKED_B
    if lower in _PICKS_TIE:
        return ArenaOutcome.TIE
    if lower in _PICKS_SKIP:
        return ArenaOutcome.SKIPPED
    return ArenaOutcome.UNRECOGNISED


def _shuffle_labels(
    first: ArenaCandidate,
    second: ArenaCandidate,
    *,
    rng: random.Random | None = None,
) -> tuple[ArenaCandidate, ArenaCandidate]:
    """Return the two candidates re-labelled A/B in a random order.

    ``rng`` is injected so tests can pin the shuffle; production callers
    pass ``None`` for a fresh ``random.Random`` seeded from the OS.
    """
    rng = rng or random.Random()
    ordered = [first, second]
    rng.shuffle(ordered)
    return (
        dataclasses.replace(ordered[0], label="A"),
        dataclasses.replace(ordered[1], label="B"),
    )


async def run_blind_arena(
    *,
    provider_a: llm.LLMProvider,
    provider_b: llm.LLMProvider,
    prompt: str,
    rng: random.Random | None = None,
) -> ArenaSession:
    """Run *prompt* against both providers in parallel and return a session.

    The two responses are shuffled and labelled A/B; the caller does not
    learn which provider answered which side.  Both providers are called
    with the same message, temperature, and token cap so differences in
    the output reflect model behaviour rather than prompt engineering.

    Raises :class:`ArenaError` when the two providers are indistinguishable
    (same ``model_name`` and ``name``) — a blind A/B against identical
    configurations produces no signal and wastes tokens.
    """
    if (provider_a.name, getattr(provider_a, "model_name", "")) == (
        provider_b.name,
        getattr(provider_b, "model_name", ""),
    ):
        raise ArenaError(
            "arena requires two distinct providers; "
            f"both sides resolved to {provider_a.name}:"
            f"{getattr(provider_a, 'model_name', '')}"
        )

    if not prompt.strip():
        raise ArenaError("arena prompt is empty; supply text after /arena")

    messages = [Message(role=Role.USER, content=prompt)]

    async def _one(provider: llm.LLMProvider) -> ArenaCandidate:
        response = await complete_with_retry(
            provider,
            messages,
            tools=None,
            temperature=_ARENA_TEMPERATURE,
            max_tokens=_ARENA_MAX_TOKENS,
        )
        return ArenaCandidate(
            label="?",
            provider_name=provider.name,
            model_name=getattr(provider, "model_name", "") or provider.name,
            response=response.content,
        )

    results = await asyncio.gather(_one(provider_a), _one(provider_b))
    labelled_a, labelled_b = _shuffle_labels(results[0], results[1], rng=rng)
    return ArenaSession(
        prompt=prompt,
        candidates=(labelled_a, labelled_b),
        session_id=secrets.token_hex(4),
    )


def format_blind_arena(session: ArenaSession) -> str:
    """Render an :class:`ArenaSession` as a blind A/B markdown block.

    No model or provider names appear in the output — that is the
    entire point of blind mode.  The trailer tells the user how to pick,
    including ``tie`` and ``skip`` so nobody is forced to invent
    preferences out of thin air.
    """
    return (
        "**Arena (blind A/B)**\n\n"
        f"**Prompt:** {session.prompt}\n\n"
        "---\n\n"
        "### Response A\n\n"
        f"{session.candidate_a.response.strip()}\n\n"
        "---\n\n"
        "### Response B\n\n"
        f"{session.candidate_b.response.strip()}\n\n"
        "---\n\n"
        "Reply **A**, **B**, **tie**, or **skip**."
    )


def record_preference(
    memory: MemoryManager,
    session: ArenaSession,
    outcome: str,
) -> MemoryEntry | None:
    """Write the arena outcome to global-scope memory.

    Skipped arenas and unrecognised outcomes return ``None`` without
    writing — there is no preference to capture.  Ties still write a
    memory (the observation that two models were indistinguishable on
    this prompt is useful), but picks get a directional ``preferred X
    over Y`` body.  All memories are ``kind="fact"`` and live in the
    ``global`` scope so preferences carry across charms.
    """
    if outcome in (ArenaOutcome.SKIPPED, ArenaOutcome.UNRECOGNISED):
        return None

    a = session.candidate_a
    b = session.candidate_b

    if outcome == ArenaOutcome.PICKED_A:
        winner, loser = a, b
        headline = (
            f"User preferred **{winner.model_name}** over **{loser.model_name}** "
            "on a blind arena comparison."
        )
    elif outcome == ArenaOutcome.PICKED_B:
        winner, loser = b, a
        headline = (
            f"User preferred **{winner.model_name}** over **{loser.model_name}** "
            "on a blind arena comparison."
        )
    else:
        # Tie — note both models were rated equally.
        winner = a  # arbitrary; not used beyond satisfying the type
        headline = (
            f"User rated **{a.model_name}** and **{b.model_name}** as "
            "equivalent on a blind arena comparison."
        )

    excerpt = session.prompt.strip().replace("\n", " ")
    if len(excerpt) > 200:
        excerpt = excerpt[:200] + "…"
    body = f"{headline}\n\n**Prompt excerpt:** {excerpt}"

    return memory.write(
        scope="global",
        title=f"{_MEMORY_TITLE_PREFIX}{session.session_id}",
        kind="fact",
        body=body,
        source="arena",
        tags=["arena", "model-preference"],
    )


def format_reveal(session: ArenaSession, outcome: str) -> str:
    """Render the reveal message shown after the user picks.

    The message unmasks the A/B mapping regardless of which outcome the
    user chose — a tie is just as informative as a pick, and a
    declined / skipped arena still benefits from the reveal because the
    user can learn which response came from which model post-hoc.
    """
    a = session.candidate_a
    b = session.candidate_b
    mapping = f"- **A** was {a.model_name} ({a.provider_name})\n- **B** was {b.model_name} ({b.provider_name})"

    if outcome == ArenaOutcome.PICKED_A:
        verdict = f"You picked **A** — {a.model_name}."
    elif outcome == ArenaOutcome.PICKED_B:
        verdict = f"You picked **B** — {b.model_name}."
    elif outcome == ArenaOutcome.TIE:
        verdict = f"You rated them equivalent — {a.model_name} vs {b.model_name}."
    elif outcome == ArenaOutcome.SKIPPED:
        verdict = "Arena skipped — no preference recorded."
    else:
        verdict = "Arena reply not recognised — no preference recorded."

    footer = (
        "\n\nRecorded as a global-scope memory."
        if outcome in (ArenaOutcome.PICKED_A, ArenaOutcome.PICKED_B, ArenaOutcome.TIE)
        else ""
    )
    return f"{verdict}\n\n{mapping}{footer}"


__all__ = [
    "ArenaCandidate",
    "ArenaError",
    "ArenaOutcome",
    "ArenaSession",
    "format_blind_arena",
    "format_reveal",
    "parse_pick",
    "record_preference",
    "run_blind_arena",
]
