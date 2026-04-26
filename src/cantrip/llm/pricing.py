"""Per-model USD pricing for estimating inference cost.

Prices are listed per **million tokens** and are rough approximations —
providers adjust them without notice, and promotional rates (batch API,
long-context tiers, enterprise contracts) can shift them further.  The
numbers below are the published list prices as of early 2026 and are
good enough for a running-cost display.

The public entry point is :func:`estimate_cost`; callers pass the raw
token counts captured via :class:`cantrip.llm.base.Response.usage` and
receive a dollar figure back.  Unknown models return ``0.0`` — we
prefer an under-report to a scary, fabricated figure.
"""

import dataclasses


@dataclasses.dataclass(frozen=True)
class Price:
    """Per-million-token USD rates for one model.

    *prompt* and *completion* are the standard input/output rates.
    *cache_read* and *cache_write* are Anthropic's prompt-caching
    modifiers; providers that don't support caching leave both at zero,
    in which case callers should pass the cache counts as regular
    prompt tokens (Anthropic is the only provider that separates them
    in the usage payload today).
    """

    prompt: float
    completion: float
    cache_read: float = 0.0
    cache_write: float = 0.0


# Anthropic prompt caching: reads cost 10% of the base input rate,
# writes cost 125% of the base input rate.  Applying this ratio once
# in a helper avoids every Claude entry repeating the same constants.
def _claude(prompt: float, completion: float) -> Price:
    return Price(
        prompt=prompt,
        completion=completion,
        cache_read=prompt * 0.10,
        cache_write=prompt * 1.25,
    )


# Keys are substrings matched against ``model_name``.  The first match
# wins, so more specific patterns must come first.  Values are per
# **million** tokens.
_PRICES: dict[str, Price] = {
    # Claude 4 family — most specific versions first so substring
    # matching picks the right rate.  Unversioned fallbacks (``opus``,
    # ``sonnet``, ``haiku``) at the end catch variants like
    # ``claude-opus-4`` without a date stamp.
    "opus-4-7": _claude(prompt=15.00, completion=75.00),
    "opus-4-6": _claude(prompt=15.00, completion=75.00),
    "sonnet-4-6": _claude(prompt=3.00, completion=15.00),
    "sonnet-4-5": _claude(prompt=3.00, completion=15.00),
    "haiku-4-5": _claude(prompt=1.00, completion=5.00),
    "opus": _claude(prompt=15.00, completion=75.00),
    "sonnet": _claude(prompt=3.00, completion=15.00),
    "haiku": _claude(prompt=1.00, completion=5.00),
    # Gemini — Google publishes tiered pricing; the numbers below are
    # the low-context tier (<=200k tokens) for the text modality.
    "gemini-3-pro": Price(prompt=1.25, completion=10.00),
    "gemini-3-flash": Price(prompt=0.15, completion=0.60),
    "gemini-2.5-pro": Price(prompt=1.25, completion=10.00),
    "gemini-2.5-flash": Price(prompt=0.15, completion=0.60),
    "gemini-2.0-flash": Price(prompt=0.075, completion=0.30),
    # Local inference — the snap runs on the user's own hardware, so
    # there's no per-token charge.  Keeping it in the table makes the
    # "unknown model → $0" branch distinguishable from "known free".
    "inference-snap": Price(prompt=0.0, completion=0.0),
    "gemma3": Price(prompt=0.0, completion=0.0),
    # Phase 72.3: embedding and rerank models.  All are input-only —
    # there is no completion side — so ``completion`` stays at zero
    # and the input rate goes in ``prompt``.  Voyage publishes
    # context-tier breakdowns; the numbers below are the standard
    # single-tier rate as of early 2026.
    "voyage-3-lite": Price(prompt=0.02, completion=0.0),
    "voyage-3-large": Price(prompt=0.18, completion=0.0),
    "voyage-3": Price(prompt=0.06, completion=0.0),
    "voyage-code-3": Price(prompt=0.18, completion=0.0),
    "rerank-2-lite": Price(prompt=0.02, completion=0.0),
    "rerank-2": Price(prompt=0.05, completion=0.0),
    "text-embedding-3-small": Price(prompt=0.02, completion=0.0),
    "text-embedding-3-large": Price(prompt=0.13, completion=0.0),
}

# Sentinel price returned for unknown models.  Public so tests can
# assert on it without importing a private name.
ZERO_PRICE = Price(prompt=0.0, completion=0.0)


def lookup_price(model_name: str) -> Price:
    """Return the ``Price`` for *model_name*, or :data:`ZERO_PRICE`.

    Matching is a case-insensitive substring check against the keys of
    the internal pricing table.  The first matching key wins — the
    table is ordered most-specific-first, so ``claude-opus-4-7`` hits
    ``"opus-4-7"`` before the generic ``"opus"`` prefix would match.
    """
    if not model_name:
        return ZERO_PRICE
    needle = model_name.lower()
    for pattern, price in _PRICES.items():
        if pattern in needle:
            return price
    return ZERO_PRICE


def estimate_cost(
    model_name: str,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Return the estimated USD cost for the given usage.

    *prompt_tokens* should be the **non-cached** input tokens only —
    Anthropic's billing splits prompt tokens into three buckets (fresh,
    cache-read, cache-write) and each has a different rate.  Providers
    that don't separate them (Gemini, inference-snap) should pass all
    input tokens via *prompt_tokens* and leave the cache fields at
    zero.
    """
    price = lookup_price(model_name)
    cost_per_million = (
        prompt_tokens * price.prompt
        + completion_tokens * price.completion
        + cache_read_tokens * price.cache_read
        + cache_write_tokens * price.cache_write
    )
    return cost_per_million / 1_000_000


def format_cost(cost: float) -> str:
    """Format a dollar amount for compact display in the UI.

    Cost shown with two decimals above 1¢, four below — a session
    costing $0.0023 is more useful to see as ``$0.0023`` than
    ``$0.00``.  Zero cost returns ``$0.00`` (not a dash) so the
    free-local-model case is unambiguous.
    """
    if cost <= 0:
        return "$0.00"
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"
