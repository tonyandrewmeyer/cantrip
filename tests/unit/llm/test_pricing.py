"""Tests for the per-model pricing helper."""

import pytest

from cantrip.llm import pricing


class TestLookupPrice:
    def test_claude_opus_matches_opus_entry(self):
        price = pricing.lookup_price("claude-opus-4-7")
        assert price.prompt == 15.00
        assert price.completion == 75.00
        # Cache-read is 10% of input.
        assert price.cache_read == pytest.approx(1.50)
        # Cache-write is 125% of input.
        assert price.cache_write == pytest.approx(18.75)

    def test_claude_sonnet_matches_sonnet_entry(self):
        price = pricing.lookup_price("claude-sonnet-4-6")
        assert price.prompt == 3.00
        assert price.completion == 15.00

    def test_claude_haiku_matches_haiku_entry(self):
        price = pricing.lookup_price("claude-haiku-4-5-20251001")
        assert price.prompt == 1.00
        assert price.completion == 5.00

    def test_gemini_flash_matches_flash_tier(self):
        price = pricing.lookup_price("gemini-3-flash-preview")
        assert price.prompt == 0.50
        assert price.completion == 3.00

    def test_gemini_pro_matches_pro_tier(self):
        price = pricing.lookup_price("gemini-3-pro")
        assert price.prompt == 2.00
        assert price.completion == 12.00

    def test_gemini_3_1_pro_preview_matches_pro_tier(self):
        # The default Gemini model uses a dotted version string; the
        # pricing key needs an explicit dotted variant or substring
        # matching falls through to ZERO_PRICE.
        price = pricing.lookup_price("gemini-3.1-pro-preview")
        assert price.prompt == 2.00
        assert price.completion == 12.00

    def test_glm_4_6_matches_openrouter_slug(self):
        # Slug as served by OpenRouter is ``z-ai/glm-4.6``; substring
        # match on ``glm-4.6`` carries the per-million rates.
        price = pricing.lookup_price("z-ai/glm-4.6")
        assert price.prompt == 0.43
        assert price.completion == 1.74

    def test_glm_4_7_matches_openrouter_slug(self):
        price = pricing.lookup_price("z-ai/glm-4.7")
        assert price.prompt == 0.40
        assert price.completion == 1.75

    def test_inference_snap_is_free(self):
        price = pricing.lookup_price("gemma3")
        assert price.prompt == 0.0
        assert price.completion == 0.0

    def test_gemma4_is_free(self):
        price = pricing.lookup_price("gemma4")
        assert price.prompt == 0.0
        assert price.completion == 0.0

    def test_case_insensitive(self):
        # Any case variant should match the same entry.
        upper = pricing.lookup_price("CLAUDE-SONNET-4-6")
        lower = pricing.lookup_price("claude-sonnet-4-6")
        assert upper == lower

    def test_unknown_model_returns_zero(self):
        assert pricing.lookup_price("hypothetical-model-v42") is pricing.ZERO_PRICE

    def test_empty_model_returns_zero(self):
        assert pricing.lookup_price("") is pricing.ZERO_PRICE


class TestEstimateCost:
    def test_sonnet_full_rate_no_cache(self):
        # 1M input + 500k output on Sonnet 4.6 → $3.00 + $7.50 = $10.50.
        cost = pricing.estimate_cost(
            "claude-sonnet-4-6",
            prompt_tokens=1_000_000,
            completion_tokens=500_000,
        )
        assert cost == pytest.approx(10.50)

    def test_claude_cache_discount_applied(self):
        # 100k cache-read tokens on Sonnet: 100k * $0.30 per M = $0.03.
        cost = pricing.estimate_cost(
            "claude-sonnet-4-6",
            cache_read_tokens=100_000,
        )
        assert cost == pytest.approx(0.03)

    def test_claude_cache_write_premium(self):
        # 100k cache-write tokens on Sonnet: 100k * $3.75 per M = $0.375.
        cost = pricing.estimate_cost(
            "claude-sonnet-4-6",
            cache_write_tokens=100_000,
        )
        assert cost == pytest.approx(0.375)

    def test_unknown_model_free(self):
        cost = pricing.estimate_cost(
            "hypothetical-v42",
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
        )
        assert cost == 0.0

    def test_inference_snap_free(self):
        cost = pricing.estimate_cost(
            "gemma3",
            prompt_tokens=10_000_000,
            completion_tokens=10_000_000,
        )
        assert cost == 0.0

    def test_gemini_flash_realistic_turn(self):
        # A 10k-in / 2k-out turn on Gemini 3 Flash.
        cost = pricing.estimate_cost(
            "gemini-3-flash-preview",
            prompt_tokens=10_000,
            completion_tokens=2_000,
        )
        # 10k * $0.50/M = $0.005; 2k * $3.00/M = $0.006; total $0.011.
        assert cost == pytest.approx(0.011)


class TestFormatCost:
    def test_zero(self):
        assert pricing.format_cost(0.0) == "$0.00"

    def test_negative_treated_as_zero(self):
        assert pricing.format_cost(-1.23) == "$0.00"

    def test_sub_cent_uses_four_decimals(self):
        assert pricing.format_cost(0.0027) == "$0.0027"

    def test_above_cent_uses_two_decimals(self):
        assert pricing.format_cost(1.2345) == "$1.23"

    def test_exactly_one_cent(self):
        assert pricing.format_cost(0.01) == "$0.01"
