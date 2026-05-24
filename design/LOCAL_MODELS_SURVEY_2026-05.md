# Local-Model Candidate Survey — Late May 2026

Point-in-time research note.  Refreshes [`LOCAL_MODELS.md`](LOCAL_MODELS.md)
with a fresh sweep of open-weight LLMs released since that document's
original survey (early–mid 2026).  Captured 2026-05-25 in the same
session that bumped the llama.cpp pin from ``b8589`` to ``b9050``
(Phase 111).

## 1. Why now

The original [`LOCAL_MODELS.md`](LOCAL_MODELS.md) survey crystallised
in early 2026 against llama.cpp ``b8589``.  Two things have shifted
since:

1. **Engine bump (Phase 111).**  We're now on ``b9050`` (CUDA12, ROCm,
   CPU prebuilds via ``canonical/llama.cpp-builds``), ~461 upstream
   commits and ~5 weeks of MoE / quant-kernel work past the previous
   pin.  In particular, the fused-kernel path that segfaulted on
   DeepSeek-Coder-V2-Lite in ``b8589`` is the headline-named fix in
   the ``b9000+`` range.
2. **New model releases.**  Granite 4.1, Ling-mini-2.0, Qwen3.5,
   Qwen3-Coder-Next, Devstral 2, and OmniCoder all landed after the
   original survey closed; some are directly relevant to the 12 GB
   VRAM / tool-calling-must-work corner we're optimising for.

The selection criteria from
[`LOCAL_MODELS.md`](LOCAL_MODELS.md) §3 are unchanged: ``--jinja``
tool calling, coding strength, ≥40 tok/s decode, ≥32 K context, fits
at Q4_K_M with KV cache headroom.

## 2. Hardware budget (unchanged)

Same RTX 5070 Ti Laptop / 12 GB VRAM / 62 GB host RAM / no GPU
passthrough into the multipass VM.  See
[`LOCAL_MODELS.md`](LOCAL_MODELS.md) §2 for the full capture.

The "8 B class fits with comfort / 14 B class just fits" framing
continues to hold.  The bigger discovery from the new releases is
that a *third* shape now fits comfortably: **small-active-parameter
MoE in the 16 B-total / 1–3 B-active range**, where decode rate is
governed by the active subset rather than the total weight size.

## 3. Ranked shortlist

Smoke-test in this order.  Each row links to GGUF weights, an
upstream model card, and (where available) a llama.cpp template
status.

### 3.1 IBM Granite 4.1-8B — top recommendation

| Property | Value |
|---|---|
| Arch | Dense, 8 B params, 40 layers |
| Native context | 128 K |
| Q4_K_M (Unsloth UD-Q4_K_M) | **5.35 GB** |
| Released | 2026-04-29 |
| ``--jinja`` template | **Confirmed.**  Unsloth ships fixes specifically for ``llama.cpp``'s template machinery; custom ``<\|start_of_role\|>`` markers. |
| Tool-calling benchmark | BFCL v3 = **68.27** (post-training objective, not bolt-on) |
| HumanEval / EvalPlus | **87.2** / **80.2** |
| GSM8K | 92.49 |
| GGUF | <https://huggingface.co/unsloth/granite-4.1-8b-GGUF> |
| Model card | <https://research.ibm.com/blog/granite-4-1-ai-foundation-models> |

**Why it goes first.**  It uniquely satisfies every hard criterion
in [`LOCAL_MODELS.md`](LOCAL_MODELS.md) §3, and the failure modes the
original survey hit — Mistral Nemo and Qwen2.5-Coder both
under-delivered on tool-call reliability — are exactly what IBM
optimised against: BFCL v3 is a published metric, not an afterthought.
The 5.35 GB Q4_K_M file leaves ~6 GB of GPU headroom even at 32 K
context, which is the opposite of the tight squeeze Mistral Nemo
exhibited.

Decode-rate prediction: dense 8 B on a 12 GB Blackwell at 70 W
typically delivers 50–70 tok/s at Q4_K_M; well above the 40 tok/s
floor.

### 3.2 IBM Granite 4.1-3B — speed/router companion

| Property | Value |
|---|---|
| Arch | Dense, 3 B params |
| Native context | 128 K |
| Q4_K_M | ~1.9 GB |
| Released | ~2026-05-04 |
| ``--jinja`` | Same template family as 4.1-8B; confirmed. |
| GGUF | <https://huggingface.co/unsloth/granite-4.1-3b-GGUF> |
| External coverage | <https://simonwillison.net/2026/May/4/granite-41-3b-svg-pelican-gallery/> |

Worth a smoke purely as a *low-latency planner/router companion* to
4.1-8B, not as a standalone charm-builder.  3 B dense at Q4_K_M will
fly on this hardware; if the tool-calling shape works the same as the
8 B sibling, this becomes a useful "fast path" for short-session and
plan-only roles.  Pin to the same template work.

### 3.3 Ling-mini-2.0 — speculative MoE candidate

| Property | Value |
|---|---|
| Arch | MoE (bailingmoe2), **16.26 B total / 1.43 B active per token** |
| Native context | 32 K (128 K with YaRN) |
| Q4_K_M (Bartowski) | **9.94 GB** |
| Released | 2025-07 (older, but the right shape) |
| ``--jinja`` template | **Unverified.**  Custom ``<role>...</role>`` markers, not in the llama.cpp function-calling docs' verified tier. |
| Coding benchmarks | Card claims "~7× equivalent dense performance" vs 7–8 B dense; no public BigCodeBench / Aider numbers found. |
| GGUF | <https://huggingface.co/bartowski/inclusionAI_Ling-mini-2.0-GGUF> |
| Model card | <https://huggingface.co/inclusionAI/Ling-mini-2.0> |

This is the "Qwen3-Coder-30B-A3B shape but actually fits at 12 GB"
candidate.  1.43 B active params per token implies *very* fast decode
even on partial offload; the 9.94 GB Q4_K_M leaves ~2 GB for KV at
32 K, which is tight but feasible.

**Risk:** the template is non-standard, and the ``--jinja`` story is
unverified.  Budget time for a template patch (or a Jinja override
file) before declaring it a candidate.  If the template works, this
likely beats Granite 4.1-8B on raw speed for the agent loop.

### 3.4 Phi-4-Mini — promote from backlog

[`LOCAL_MODELS.md`](LOCAL_MODELS.md) already lists it in the §3
"wins on ``--jinja``" tier and the [llama.cpp function-calling
docs](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md)
mark it as "no-config-needed".  Smoke-test as a baseline alongside
the Granite work.  Charm-specific Python strength is unknown; treat
it as a tool-call sanity baseline rather than a likely winner.

### 3.5 Llama-3.1-8B-Instruct — keep on backlog

Already in [`LOCAL_MODELS.md`](LOCAL_MODELS.md).  Reference model
in llama.cpp's function-calling docs; useful as a known-good
``--jinja`` baseline even if coding quality lags Granite.

## 4. Skip list

| Model | Reason |
|---|---|
| **Qwen3.5-9B** | Known ``--jinja`` bug at Q4_K_M ([llama.cpp #20837](https://github.com/ggml-org/llama.cpp/issues/20837)) — prints XML, stops mid-thinking-block.  Hard skip until a template fix lands. |
| **Qwen3-Coder-Next (80B-A3B)** | 48.5 GB at Q4_K_M (<https://huggingface.co/unsloth/Qwen3-Coder-Next-GGUF>).  Right shape, way over budget. |
| **Qwen3.6-27B / 35B-A3B** | Total weights overflow 12 GB at Q4_K_M (35B-A3B is still ~20 GB total). |
| **Devstral Small 2 24B** | 13.4 GB at Q4_K_M, over budget; Mistral's own quant guidance discourages Q3_K_M for code workloads. |
| **Devstral 2 (123B)** | Orders of magnitude too big. |
| **Codestral-22B** | ~13 GB Q4_K_M, over budget; community reports "GGUF doesn't support function calling yet". |
| **OmniCoder-9B** (Tesslate, Qwen3.5 base) | 8 K native context — fails the 32 K bar.  Also inherits the Qwen3.5 ``--jinja`` risk. |
| **Llama-4 Scout** | 109 B total MoE; doesn't fit even with aggressive quantisation. |
| **GLM-4.6** | 200 K context but smallest published quant assumes 1×24 GB + 128 GB RAM. |

## 5. Recommendation and sequencing

1. **First: Granite 4.1-8B at Q4_K_M.**  Scaffold
   ``inference-snaps/granite-4.1-8b/`` from the qwen3-8b template,
   pull from ``unsloth/granite-4.1-8b-GGUF``, run the same §5.1.1
   protocol (``/v1/models``, plain-hello, synthetic ``get_weather``,
   then ntfy-improve).  If it clears all four, this becomes the new
   default-recommended local model for cantrip on 12 GB hardware.
2. **Second, contingent on 1: Ling-mini-2.0** as the speculative
   speed candidate, after verifying its ``--jinja`` template (likely
   needs a custom Jinja override or a template-patch PR upstream).
3. **Third: Granite 4.1-3B** as a fast planner/router companion if
   we end up running cantrip with split planner / executor providers
   (Phase 105.2's provider-preset work).
4. **Backlog-elevated: Phi-4-Mini and Llama-3.1-8B** as
   tool-call-sanity baselines on the same b9050 engine, useful for
   isolating "model bug" vs "agent bug" when a future failure mode
   shows up.

## 6. Sources

- IBM Research — [Granite 4.1 blog](https://research.ibm.com/blog/granite-4-1-ai-foundation-models)
- Unsloth — [granite-4.1-8b-GGUF](https://huggingface.co/unsloth/granite-4.1-8b-GGUF), [granite-4.1-3b-GGUF](https://huggingface.co/unsloth/granite-4.1-3b-GGUF)
- Simon Willison — [Granite 4.1-3B](https://simonwillison.net/2026/May/4/granite-41-3b-svg-pelican-gallery/)
- Hacker News — [Granite 4.1 8B beats 32B MoE thread](https://news.ycombinator.com/item?id=47960507)
- Bartowski — [Ling-mini-2.0-GGUF](https://huggingface.co/bartowski/inclusionAI_Ling-mini-2.0-GGUF)
- inclusionAI — [Ling-mini-2.0 model card](https://huggingface.co/inclusionAI/Ling-mini-2.0)
- llama.cpp — [function-calling docs](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md), [Qwen3.5-9B --jinja bug #20837](https://github.com/ggml-org/llama.cpp/issues/20837)
- Tesslate — [OmniCoder-9B-GGUF](https://huggingface.co/Tesslate/OmniCoder-9B-GGUF)
- Mistral — [Devstral 2 announcement](https://mistral.ai/news/devstral-2-vibe-cli)
- Unsloth — [Qwen3-Coder-Next-GGUF](https://huggingface.co/unsloth/Qwen3-Coder-Next-GGUF)
