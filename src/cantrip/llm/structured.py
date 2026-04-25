"""Structured-output helpers for ``LLMProvider`` callers (Phase 73.3).

Provider-native enforcement (OpenAI ``response_format``, Gemini
``response_schema``) is an *optimisation* — Anthropic has no
equivalent today, and even providers that support the field
sometimes return text the validator should still re-check.  This
module wraps :meth:`LLMProvider.complete` so callers always get a
parsed, validated dict — and one corrective retry on schema-
violation failures, where the malformed output is fed back to the
model with the schema as a "please fix this" addendum.

Two public entry points:

- :func:`validate_against_schema` — pure parser/validator, takes a
  string and a schema, returns a dict or raises
  :class:`StructuredOutputError`.
- :func:`complete_structured` — calls a provider, validates the
  reply, retries once on failure.  This is the primary surface for
  recipes (Phase 73.1), the oracle (Phase 70.2), checks (Phase
  70.4), and any future caller that wants a typed reply.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

import jsonschema

from cantrip.llm import base as llm

if TYPE_CHECKING:
    from cantrip.llm.base import LLMProvider, Message, Tool

log = logging.getLogger(__name__)

# Maximum length of the malformed-output excerpt we feed back to the
# model on retry.  Long enough to keep the original failure visible
# without ballooning the corrective prompt.
_RETRY_EXCERPT_CHARS = 2000

# Patterns matched by :func:`_strip_markdown_fences`.  Both
# ```json …``` and bare ``` … ``` blocks survive; we strip the
# fences and keep the inner text.
_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON)?\s*\n?(?P<body>.*?)\n?\s*```\s*$",
    re.DOTALL,
)


class StructuredOutputError(ValueError):
    """Raised when a model reply fails JSON parse or schema validation.

    Carries the raw text, the schema it was checked against, and the
    underlying error so callers can surface the failure to the user
    without re-running the validator.  Subclass of :class:`ValueError`
    so existing ``except ValueError`` handlers still catch it.
    """

    def __init__(
        self,
        message: str,
        *,
        raw_text: str,
        schema: dict[str, Any],
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.schema = schema
        self.cause = cause


def _strip_markdown_fences(text: str) -> str:
    """Return *text* with any wrapping ```` ```json ```` fences removed.

    Idempotent — text without fences passes through unchanged.  Only
    the outermost fence is stripped; nested code blocks inside a JSON
    string survive (which is what JSON encodes them as anyway).
    """
    match = _FENCE_RE.match(text.strip())
    if match:
        return match.group("body").strip()
    return text.strip()


def validate_against_schema(text: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Parse *text* as JSON and validate it against *schema*.

    Returns the parsed object on success.  Raises
    :class:`StructuredOutputError` when the text is unparseable or
    the parsed object doesn't conform to the schema.  Markdown code
    fences are stripped before parsing so models that habitually
    wrap JSON in ```` ```json ```` blocks (Claude, some open-weights
    models) work without extra prompting.
    """
    payload = _strip_markdown_fences(text)
    if not payload:
        raise StructuredOutputError(
            "Empty response — model returned no content.",
            raw_text=text,
            schema=schema,
        )

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise StructuredOutputError(
            f"Response was not valid JSON: {exc.msg} at line {exc.lineno} col {exc.colno}",
            raw_text=text,
            schema=schema,
            cause=exc,
        ) from exc

    try:
        jsonschema.validate(instance=parsed, schema=schema)
    except jsonschema.ValidationError as exc:
        raise StructuredOutputError(
            f"Response did not match schema: {exc.message}",
            raw_text=text,
            schema=schema,
            cause=exc,
        ) from exc

    if not isinstance(parsed, dict):
        # JSON allows top-level arrays / scalars but the built-in
        # schemas all describe objects.  Surface the type mismatch
        # explicitly rather than letting downstream callers crash on
        # ``parsed["key"]``.
        raise StructuredOutputError(
            f"Schema expects an object at the top level; got {type(parsed).__name__}.",
            raw_text=text,
            schema=schema,
        )

    return parsed


async def complete_structured(
    provider: LLMProvider,
    messages: list[Message],
    schema: dict[str, Any],
    *,
    tools: list[Tool] | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    thinking_budget: int | None = None,
    retries: int = 1,
) -> dict[str, Any]:
    """Call *provider* and return a schema-validated dict.

    The provider receives *schema* through the ``response_schema``
    parameter so backends with native enforcement (Gemini, OpenAI-
    compatible) can constrain the reply.  The response is *always*
    validated by :func:`validate_against_schema` regardless — native
    enforcement is an optimisation, not a security boundary.

    On validation failure, up to *retries* corrective retries are
    issued: the malformed reply and the validation error are
    appended as a USER message asking the model to emit valid JSON
    matching the schema.  When all retries are exhausted, the final
    :class:`StructuredOutputError` is raised so the caller can
    surface it to the agent loop or the user.
    """
    if retries < 0:
        raise ValueError("retries must be non-negative")

    attempt_messages = list(messages)
    last_error: StructuredOutputError | None = None

    for attempt in range(retries + 1):
        response = await provider.complete(
            messages=attempt_messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
            response_schema=schema,
        )

        try:
            return validate_against_schema(response.content, schema)
        except StructuredOutputError as exc:
            last_error = exc
            if attempt >= retries:
                break
            log.info(
                "Structured response failed validation (attempt %d/%d): %s",
                attempt + 1,
                retries + 1,
                exc,
            )
            attempt_messages = _append_correction_turn(
                attempt_messages, response.content, exc, schema
            )

    assert last_error is not None  # only reachable on failure
    raise last_error


def _append_correction_turn(
    messages: list[Message],
    raw_reply: str,
    error: StructuredOutputError,
    schema: dict[str, Any],
) -> list[Message]:
    """Build the next attempt's message list with the failure folded in.

    Appends the model's malformed reply as an ASSISTANT turn and a
    USER turn that quotes the schema and the validation error.  The
    excerpt is bounded so a runaway response doesn't blow the
    context window on retry.
    """
    excerpt = raw_reply.strip()
    if len(excerpt) > _RETRY_EXCERPT_CHARS:
        excerpt = excerpt[: _RETRY_EXCERPT_CHARS - 1] + "…"

    correction = (
        "Your previous reply could not be parsed as JSON matching the requested "
        "schema:\n\n"
        f"Error: {error}\n\n"
        f"Schema:\n```json\n{json.dumps(schema, indent=2)}\n```\n\n"
        "Please reply again with **only** valid JSON conforming to the schema. "
        "No prose before or after, no markdown fences, no commentary."
    )

    return [
        *messages,
        llm.Message(role=llm.Role.ASSISTANT, content=excerpt),
        llm.Message(role=llm.Role.USER, content=correction),
    ]


__all__ = [
    "StructuredOutputError",
    "complete_structured",
    "validate_against_schema",
]
