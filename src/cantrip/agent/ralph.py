"""Phase 69.1 — Ralph Loop: bounded iterate-until-green outer loop.

Wraps the existing autonomous loop with explicit refinement passes.
The pattern is Kimi Code CLI's: re-feed the same goal until the
agent emits a convergence signal (default ``STOP``) or a hard
iteration cap fires.  Particularly useful in non-interactive
``cantrip run --print`` (Phase 67.3) where there's no human to say
"keep going".

Stall detection guards against burning tokens on no-ops: if two
consecutive iterations produce the same final response and the
working tree didn't change, we exit early with a ``stalled`` outcome
rather than running the full cap.

The loop is *outer*: ``process_message`` still runs the work queue,
sub-agents, tool calls, the lot.  Ralph just decides whether to call
``process_message`` again.
"""

from __future__ import annotations

import asyncio
import dataclasses
import enum
import hashlib
import logging
import pathlib
import subprocess
from collections.abc import Awaitable, Callable

from cantrip.ui import events as ui_events

log = logging.getLogger(__name__)

# Default convergence sentinel — matches Kimi Code's ``STOP`` so a
# user transferring habits between tools doesn't have to relearn the
# token.  Override per-session via ``RalphConfig.convergence`` or
# (future) ``ralph.convergence`` config block.
DEFAULT_CONVERGENCE_SIGNAL = "STOP"

# How long to wait between iteration drains so the work queue has a
# chance to pick up newly-spawned tasks before we re-seed.  The same
# value the print-mode runner uses for its drain heartbeat.
_ITERATION_SETTLE_SECONDS = 0.5


class RalphOutcome(enum.StrEnum):
    """Why the Ralph loop exited."""

    CONVERGED = "converged"
    STALLED = "stalled"
    EXHAUSTED = "exhausted"


@dataclasses.dataclass(frozen=True)
class RalphConfig:
    """Per-run Ralph configuration.

    ``max_iterations`` mirrors Kimi semantics: ``0`` disables the
    loop entirely (single-shot; the wrapper falls through to one
    ``process_message``), ``-1`` means unlimited (run until the
    convergence signal fires or stall detection trips), positive
    integers cap the run.
    """

    max_iterations: int = 0
    convergence_signal: str = DEFAULT_CONVERGENCE_SIGNAL

    def is_enabled(self) -> bool:
        """Return whether the loop should engage at all."""
        return self.max_iterations != 0


@dataclasses.dataclass(frozen=True)
class RalphResult:
    """Outcome of a Ralph run.

    ``iterations`` is the number of refinement passes that actually
    executed (``1`` for "ran once and converged", ``N`` for
    "exhausted").  ``final_response`` is whatever the last
    iteration's ``process_message`` returned — typically the
    string fed back to the caller.  ``last_iteration_responses``
    keeps the per-iteration responses so the caller can render a
    summary.
    """

    outcome: RalphOutcome
    iterations: int
    final_response: str
    last_iteration_responses: list[str]


def _response_signature(response: str) -> str:
    """Return a short hash of the agent's reply for stall detection.

    Hashing the trimmed response means we treat semantically-
    identical replies as identical (whitespace and trailing
    punctuation drift won't fool the comparison).  We don't keep the
    full text — only the hash — so memory stays bounded across
    long runs.
    """
    return hashlib.sha256(response.strip().encode("utf-8")).hexdigest()[:16]


def _tree_signature(charm_path: pathlib.Path | None) -> str | None:
    """Return a short hash of the working tree's tracked + dirty files.

    Used by stall detection to answer "did this iteration touch
    anything?" without depending on the snapshot store (Phase 68.1)
    which may be disabled.  ``git status --porcelain`` plus
    ``HEAD`` give us enough signal: identical porcelain output and
    HEAD between two iterations means *no observable file change*.

    Returns ``None`` if the path isn't a git repo or git itself
    isn't on ``$PATH``; callers fall back to response-only stall
    detection in that case.
    """
    if charm_path is None or not charm_path.exists():
        return None
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=charm_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        porcelain = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z"],
            cwd=charm_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None

    if head.returncode != 0:
        # Not a git repo (or HEAD doesn't exist yet).  Use
        # porcelain-only when it succeeded; otherwise no signal.
        if porcelain.returncode != 0:
            return None
        digest = hashlib.sha256(porcelain.stdout.encode()).hexdigest()
        return digest[:16]

    if porcelain.returncode != 0:
        return None
    combined = head.stdout + "\x00" + porcelain.stdout
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def has_converged(response: str, signal: str) -> bool:
    """Return whether *response* contains the convergence signal.

    Matched as a substring on a separate line *or* a standalone
    word.  The split-and-strip handles the common Kimi pattern of
    ``STOP`` on its own line at the end of the response.  We
    deliberately avoid a regex so users can pass an unusual signal
    string (e.g. ``"DONE WITH PROJECT"``) without escaping
    surprises.
    """
    if not signal:
        return False
    needle = signal.strip()
    if not needle:
        return False
    for line in response.splitlines():
        if line.strip() == needle:
            return True
    return needle in response.split()


def _build_reseed_prompt(
    original_goal: str,
    last_response: str,
    iteration: int,
    convergence_signal: str,
) -> str:
    """Compose the prompt fed back to the agent on iteration ``N+1``.

    The roadmap is explicit that the original user goal must be
    preserved verbatim across iterations — agents that re-summarise
    the goal often drift over iterations.  We bookend the goal with
    a short status header so the agent knows it's mid-Ralph (and
    not, say, being asked the same question fresh) and a tail line
    reminding it of the convergence signal.
    """
    summary = last_response.strip()
    if len(summary) > 1500:
        summary = summary[:1500].rstrip() + " …"

    parts = [
        f"This is Ralph iteration {iteration}.",
        "Original goal:",
        original_goal.strip(),
        "",
        "Last iteration's final response (for context):",
        summary or "(empty response)",
        "",
        (
            "Continue refining toward the original goal.  When the "
            f"goal is complete, emit `{convergence_signal}` on a "
            "line by itself to end the loop."
        ),
    ]
    return "\n".join(parts)


# Type alias for the message-processor callable Ralph drives.  Real
# callers pass ``agent.process_message``; tests pass a fake.
MessageProcessor = Callable[[str], Awaitable[str]]


async def run_ralph(
    *,
    process_message: MessageProcessor,
    goal: str,
    config: RalphConfig,
    event_bus: ui_events.EventBus | None = None,
    charm_path: pathlib.Path | None = None,
    on_iteration: Callable[[int, str], Awaitable[None]] | None = None,
) -> RalphResult:
    """Drive a Ralph loop and return the eventual outcome.

    *process_message* is the agent-layer entry point — typically
    ``agent.process_message`` — that runs one full conversation
    turn (plus any subagent work) for the given prompt and
    returns the final assistant response.

    *config* controls the iteration cap and convergence signal.
    With ``max_iterations == 0`` the loop is a no-op pass-through:
    one call to ``process_message`` and we return whatever it
    produced.  ``-1`` means "no cap"; we rely on convergence or
    stall detection to terminate, with a hard safety ceiling
    (``_UNLIMITED_SAFETY_CAP``) so a misbehaving agent can't loop
    forever without manual intervention.

    *event_bus* receives the ``ralph_*`` lifecycle events; pass
    ``None`` to silently run.  *charm_path* is used for tree-hash
    stall detection — pass the agent's working directory.
    *on_iteration* is an optional async callback fired between
    iterations for callers that need to drain a queue (the print
    mode runner does this).
    """
    if not config.is_enabled():
        # Disabled config — fall through to a single pass without
        # the iteration framing.  The caller gets the response
        # exactly as they would without Ralph at all.
        response = await process_message(goal)
        return RalphResult(
            outcome=RalphOutcome.CONVERGED,
            iterations=1,
            final_response=response,
            last_iteration_responses=[response],
        )

    # Hard ceiling on "unlimited" runs so a stuck convergence loop
    # can't swallow an entire CI budget.  Picked generously: most
    # real Ralph runs converge inside a dozen iterations, so 200 is
    # both well above the practical maximum and below any plausible
    # token budget for a single charm goal.
    _UNLIMITED_SAFETY_CAP = 200
    cap = _UNLIMITED_SAFETY_CAP if config.max_iterations < 0 else config.max_iterations

    responses: list[str] = []
    response_sigs: list[str] = []
    tree_sigs: list[str | None] = []

    final_response = ""
    iteration = 0

    for iteration in range(1, cap + 1):
        if event_bus is not None:
            event_bus.publish(
                ui_events.ralph_iteration_started(
                    iteration=iteration,
                    max_iterations=(config.max_iterations if config.max_iterations > 0 else None),
                    goal=goal,
                )
            )

        if iteration == 1:
            prompt = goal
        else:
            prompt = _build_reseed_prompt(
                original_goal=goal,
                last_response=responses[-1],
                iteration=iteration,
                convergence_signal=config.convergence_signal,
            )

        response = await process_message(prompt)
        responses.append(response)
        response_sigs.append(_response_signature(response))
        tree_sigs.append(_tree_signature(charm_path))
        final_response = response

        if on_iteration is not None:
            await on_iteration(iteration, response)

        if has_converged(response, config.convergence_signal):
            if event_bus is not None:
                event_bus.publish(
                    ui_events.ralph_converged(
                        iteration=iteration,
                        signal=config.convergence_signal,
                    )
                )
            return RalphResult(
                outcome=RalphOutcome.CONVERGED,
                iterations=iteration,
                final_response=response,
                last_iteration_responses=responses,
            )

        # Stall detection needs at least two iterations of history.
        if iteration >= 2 and _is_stalled(response_sigs, tree_sigs):
            if event_bus is not None:
                event_bus.publish(
                    ui_events.ralph_stalled(
                        iteration=iteration,
                        reason="response and working tree unchanged",
                    )
                )
            return RalphResult(
                outcome=RalphOutcome.STALLED,
                iterations=iteration,
                final_response=response,
                last_iteration_responses=responses,
            )

        # Brief settle so any async event-bus delivery has a chance
        # to land before the next iteration begins.  Low-cost in the
        # general case; matters only for tests that assert on
        # event ordering.
        await asyncio.sleep(_ITERATION_SETTLE_SECONDS)

    # Fell off the end — exhausted the iteration cap.
    if event_bus is not None:
        event_bus.publish(
            ui_events.ralph_exhausted(
                iteration=iteration,
                cap=config.max_iterations,
            )
        )
    return RalphResult(
        outcome=RalphOutcome.EXHAUSTED,
        iterations=iteration,
        final_response=final_response,
        last_iteration_responses=responses,
    )


def _is_stalled(
    response_sigs: list[str],
    tree_sigs: list[str | None],
) -> bool:
    """Return whether the last two iterations are indistinguishable.

    Stall = identical response signature AND identical (or both
    ``None``) tree signature.  When tree signatures are unavailable
    (no git repo, no charm path) we fall back to response-only
    detection — better than nothing, and the agent's reply usually
    drifts even when files don't change because it summarises the
    iteration differently.  If responses also match, that's a real
    stall regardless of tree state.
    """
    if len(response_sigs) < 2:
        return False
    last_two_responses = response_sigs[-2:] == [response_sigs[-1]] * 2
    if not last_two_responses:
        return False
    last_two_trees = tree_sigs[-2:]
    # Two ``None``s compare equal — that's the "git not available"
    # path falling back to response-only detection.
    return last_two_trees[0] == last_two_trees[1]
