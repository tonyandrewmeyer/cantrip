"""Inner Parliament — emotion subagents that review a charm through distinct lenses.

A proof-of-concept feature. A small set of "emotions" (joy, fear, anger,
disgust, sadness) each review the current charm state through a distinct
personality, producing structured suggestions. They run in parallel on
the light model, don't use tools, and don't write to the work queue —
output is a markdown report shown to the user.

Invocation: ``/feelings`` in the TUI runs the default set; ``/feelings
joy fear`` runs only those two.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import pathlib
from importlib import resources

from cantrip.agent.retry import complete_with_retry
from cantrip.llm import base as llm

log = logging.getLogger(__name__)

# The full cast. Order here determines display order in the report.
EMOTIONS: tuple[str, ...] = ("joy", "fear", "anger", "disgust", "sadness")

# Default set when ``/feelings`` is invoked with no arguments. Joy and
# Fear are deliberately the most differentiated pair (delight vs risk),
# giving the user distinct signal without running the whole cast every time.
DEFAULT_ENABLED: tuple[str, ...] = ("joy", "fear")

_PROMPTS_PKG = "cantrip.agent.prompts.emotions"

# Cap per-emotion output. The prompts ask for 1–3; this is the hard ceiling.
_MAX_SUGGESTIONS_PER_EMOTION = 3

# Personality-driven lenses benefit from a slightly looser temperature
# than the subagents (0.5), but still below full chat (0.7).
_TEMPERATURE = 0.6

# Files we inline verbatim when sampling the charm, up to this size each.
# Small enough to keep the prompt cheap, large enough for real metadata.
_INLINE_FILE_BYTES = 8_000

# Files worth showing every emotion by default. Keep the list short —
# this is a quick review, not a full audit.
_SAMPLED_FILES: tuple[str, ...] = (
    "charmcraft.yaml",
    "metadata.yaml",
    "config.yaml",
    "actions.yaml",
    "README.md",
    "src/charm.py",
)


@dataclasses.dataclass(frozen=True)
class Suggestion:
    """A single suggestion from one emotion."""

    emotion: str
    severity: str  # "high" | "medium" | "low" (lower-cased; anything else kept as-is).
    title: str
    rationale: str
    suggested_change: str


@dataclasses.dataclass(frozen=True)
class ParliamentResult:
    """Aggregated output of a parliament run."""

    suggestions: list[Suggestion]
    failed_emotions: list[str]  # Emotions whose output could not be parsed.


def available_emotions() -> tuple[str, ...]:
    """The full list of known emotion names."""
    return EMOTIONS


def resolve_enabled(requested: list[str] | None) -> list[str]:
    """Resolve the list of emotions to run, applying defaults and de-duping.

    ``None`` means "caller did not specify" and yields the default set.
    An empty list is respected as "run nothing" — callers who want the
    defaults on empty input should substitute them before calling.

    Unknown names are dropped silently — callers that want strict
    validation should pre-check against ``EMOTIONS``.
    """
    names = list(DEFAULT_ENABLED) if requested is None else requested
    seen: set[str] = set()
    resolved: list[str] = []
    for name in names:
        low = name.lower()
        if low in EMOTIONS and low not in seen:
            seen.add(low)
            resolved.append(low)
    return resolved


def _load_prompt(emotion: str) -> str:
    """Load an emotion's system prompt from the package resources."""
    return (
        resources.files(_PROMPTS_PKG).joinpath(f"{emotion}.md").read_text(encoding="utf-8").strip()
    )


def build_context_message(
    *,
    charm_name: str | None,
    charm_type: str | None,
    framework: str | None,
    charm_path: pathlib.Path | None,
    decisions: list[dict[str, object]],
) -> str:
    """Construct the user message shown to every emotion.

    Kept minimal on purpose: emotions have no tools, so they can only
    react to what's in this string.
    """
    parts: list[str] = ["# Charm under review"]

    if charm_name:
        parts.append(f"- Name: {charm_name}")
    if charm_type:
        parts.append(f"- Type: {charm_type}")
    if framework:
        parts.append(f"- Framework: {framework}")

    if decisions:
        parts.append("\n## Recent decisions")
        for decision in decisions[-10:]:
            dtype = decision.get("type", "decision")
            choice = decision.get("choice", "?")
            line = f"- {dtype}: {choice}"
            reason = decision.get("reason")
            if reason:
                line += f" — {reason}"
            parts.append(line)

    if charm_path and charm_path.is_dir():
        parts.extend(_sample_charm_files(charm_path))

    if len(parts) == 1:
        # Nothing concrete yet — emotions still have a job: reacting to intent.
        parts.append(
            "\n(No charm has been created yet. Review the user's stated intent "
            "only, and suggest things they should plan for.)"
        )

    return "\n".join(parts)


def _sample_charm_files(charm_path: pathlib.Path) -> list[str]:
    """Inline a small set of files from the charm directory, if present."""
    sections: list[str] = []
    for relpath in _SAMPLED_FILES:
        full = charm_path / relpath
        if not full.is_file():
            continue
        try:
            size = full.stat().st_size
        except OSError:
            continue
        if size > _INLINE_FILE_BYTES:
            sections.append(
                f"\n## {relpath}\n\n(skipped — file is {size} bytes, above the inline limit)"
            )
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.debug("Could not read %s for parliament: %s", full, exc)
            continue
        sections.append(f"\n## {relpath}\n\n```\n{text}\n```")
    return sections


def parse_suggestions(emotion: str, text: str) -> list[Suggestion]:
    """Extract a JSON array of suggestions from a single emotion's response.

    The prompt enforces a pure JSON response, but LLMs occasionally add
    prose anyway. We locate the outermost ``[...]`` and parse that.
    Raises ``ValueError`` if nothing parseable is found.
    """
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON array found in {emotion} response")

    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"{emotion} response was not valid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError(f"{emotion} response was not a JSON array")

    out: list[Suggestion] = []
    for item in data[:_MAX_SUGGESTIONS_PER_EMOTION]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        out.append(
            Suggestion(
                emotion=emotion,
                severity=str(item.get("severity") or "medium").strip().lower(),
                title=title,
                rationale=str(item.get("rationale") or "").strip(),
                suggested_change=str(item.get("suggested_change") or "").strip(),
            )
        )
    return out


async def _run_one_emotion(
    emotion: str,
    provider: llm.LLMProvider,
    context_message: str,
) -> tuple[str, list[Suggestion] | None]:
    """Run a single emotion and return its parsed suggestions.

    Returns ``(emotion, None)`` when the provider call fails or the output
    can't be parsed — failure of one emotion must not kill the parliament.
    """
    system_prompt = _load_prompt(emotion)
    messages = [
        llm.Message(role=llm.Role.SYSTEM, content=system_prompt),
        llm.Message(role=llm.Role.USER, content=context_message),
    ]
    try:
        response = await complete_with_retry(
            provider,
            messages,
            tools=None,
            temperature=_TEMPERATURE,
        )
    except llm.ProviderError as exc:
        log.warning("Emotion %s provider error: %s", emotion, exc)
        return emotion, None

    try:
        return emotion, parse_suggestions(emotion, response.content)
    except ValueError as exc:
        log.warning("Emotion %s produced unparseable output: %s", emotion, exc)
        return emotion, None


async def run_parliament(
    *,
    enabled: list[str],
    provider: llm.LLMProvider,
    charm_name: str | None = None,
    charm_type: str | None = None,
    framework: str | None = None,
    charm_path: pathlib.Path | None = None,
    decisions: list[dict[str, object]] | None = None,
) -> ParliamentResult:
    """Run the enabled emotions in parallel and aggregate their suggestions."""
    run_list = resolve_enabled(enabled)
    if not run_list:
        return ParliamentResult(suggestions=[], failed_emotions=[])

    context = build_context_message(
        charm_name=charm_name,
        charm_type=charm_type,
        framework=framework,
        charm_path=charm_path,
        decisions=decisions or [],
    )

    results = await asyncio.gather(
        *(_run_one_emotion(emotion, provider, context) for emotion in run_list)
    )

    suggestions: list[Suggestion] = []
    failed: list[str] = []
    for emotion, suggs in results:
        if suggs is None:
            failed.append(emotion)
        else:
            suggestions.extend(suggs)

    return ParliamentResult(suggestions=suggestions, failed_emotions=failed)


def format_report(result: ParliamentResult, enabled: list[str]) -> str:
    """Render a parliament result as a human-readable markdown report."""
    if not result.suggestions and not result.failed_emotions:
        return "_The parliament has no opinions — no emotions ran._"

    lines: list[str] = ["# Inner Parliament"]

    by_emotion: dict[str, list[Suggestion]] = {}
    for suggestion in result.suggestions:
        by_emotion.setdefault(suggestion.emotion, []).append(suggestion)

    # Preserve the user-requested order when emitting sections.
    for emotion in resolve_enabled(enabled):
        section_suggs = by_emotion.get(emotion, [])
        if not section_suggs:
            continue
        lines.append(f"\n## {emotion.title()}")
        for suggestion in section_suggs:
            severity = suggestion.severity or "medium"
            lines.append(f"\n**{suggestion.title}** _({severity})_")
            if suggestion.rationale:
                lines.append(f"\n{suggestion.rationale}")
            if suggestion.suggested_change:
                lines.append(f"\n_Suggested change:_ {suggestion.suggested_change}")

    if result.failed_emotions:
        names = ", ".join(sorted(result.failed_emotions))
        lines.append(f"\n_({names} did not produce a parseable response)_")

    return "\n".join(lines).strip()
