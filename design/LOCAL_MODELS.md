# Local Model Refresh — Research Findings

> Research note. Asks "what local model should Cantrip default to for
> on-device charm building, given what we learned from the qwen3-coder
> and gemma4 enhancement runs?". Captures the comparison work that
> motivates Phase 105. This is research, not a design.

## TL;DR

- **Primary recommendation:** Qwen3-8B (Q4_K_M GGUF, ~5.0 GB, 32 K
  native context) running with full GPU offload on the host. Native
  tool calling via `--jinja`, the same Qwen ergonomics we already
  debugged in `InferenceSnapProvider`, expected 40–50 tok/s on the
  RTX 5070 Ti Laptop GPU. Drops in behind the existing
  `--provider inference-snap --base-url http://10.42.160.1:<port>/v1`
  shape with no provider changes.
- **Long-context alternative:** Mistral Nemo 12B (Q4_K_M, ~7.5 GB,
  128 K native) for runs where we'd rather defer Phase 104 (short-
  session mode) than ship it. Slower (30–40 tok/s) but holds an
  entire multi-edit charm conversation without compaction.
- **Speed alternative:** Phi-4-Mini (3.8 B, ~2.4 GB, 128 K) when
  decode rate matters more than reasoning quality, e.g. running two
  models concurrently for planner + executor.
- **Ruled out:** qwen3-coder (current default — 30 B MoE, partial
  offload, slow decode, snap disconnects under long generations);
  gemma4 (10 K context exhausts on the system prompt + tool schemas
  alone); Qwen2.5-Coder-7B-Instruct (open `--jinja` tool-calling
  bug — see [llama.cpp #12279](https://github.com/ggml-org/llama.cpp/issues/12279)).
- **Validation path:** download Qwen3-8B-Instruct-GGUF directly,
  spin up a fresh host `llama-server` on a new port, retry the
  ntfy-improve scenario. ~1-hour smoke test versus ~1 day to package
  a custom inference-snap. If smoke passes, Phase 105.3 packages it
  for everyone.

## 1. Context: how we got here

Two recent enhancement runs against the same charm exposed
opposite failure modes:

- **qwen3-coder snap on port 8332** (30 B MoE, 32 K per slot,
  partial GPU offload). End-to-end works: a clean ntfy charm built
  in 16:53 from `mkdir`. But each enhancement round took 5–10 min
  per `edit_file` round; the snap dropped connections mid-stream
  on long generations (Phase 102's reconnect work covers this);
  resume from `load_state` produced hallucinated `old_string`
  mismatches (Phase 103).
- **gemma4 snap on port 8336** (~3 B, 10 K per slot, full GPU
  offload). Each scoped edit lands in ~10 s — fast enough — but the
  10 K context exhausts after ~5 messages with cantrip's full system
  prompt + tool schemas. The shape that worked was 7 chained
  `cantrip run -p` invocations with a fresh `.cantrip` per call,
  ~90 s of model time total (Phase 104's short-session mode lifts
  that pattern up into the agent).

Both phases are in flight, but the underlying constraint is the
same: **the gold-standard local model for this device shouldn't sit
at either extreme**. Qwen3-coder is too slow for an interactive
loop; gemma4 is too small to hold a charm-build conversation. We
want a model that's fast enough to keep the loop interactive *and*
big enough that compaction stops being load-bearing.

## 2. Hardware budget

Pulled from `tmp-hardware-info.md` (host capture 2026-05-08):

| Resource | Value |
|---|---|
| GPU | NVIDIA RTX 5070 Ti Laptop (Blackwell, 12 GB, 70 W cap) |
| VRAM total | 12 227 MiB |
| VRAM in use at capture | ~6.8 GiB (host `llama-server` processes) |
| **VRAM free, with gemma4 running** | **~5 GiB** |
| **VRAM free, with gemma4 stopped** | **~10–11 GiB** |
| Host RAM | 62 GiB |
| Host CPU | Intel Core Ultra 9 275HX (24 P+E cores, AVX2/AVX-VNNI, no AVX-512) |
| VM GPU passthrough | **None.** The cantrip multipass VM doesn't see the GPU; the agent reaches it via the host's inference-snap on `10.42.160.1`. |

The "5 GiB free" figure was misleading — it included gemma4 itself
(~5 GB at Q4_K_M with its KV cache). If we're picking a *replacement*
for gemma4, that 5 GB comes back. The real budget is **~10–11 GiB
usable for one model + KV cache**.

That moves the sweet spot from "4 B class" to "**7–8 B class with
full GPU offload**". A 12 B with 32 K cache is borderline; 14 B+ is
out unless we accept partial-offload-style decode penalties (which
is exactly what we're trying to escape from qwen3-coder).

## 3. Selection criteria

Ranked, with the model that wins on each axis:

1. **Tool calling reliability under llama.cpp `--jinja`.** Non-
   negotiable. Cantrip is a tool-calling agent; a model that emits
   `<tool_code>...` text or stale function-call tokens (the
   qwen3-coder failure) is unusable. Wins: Qwen3-8B, Llama-3.1-8B,
   Mistral Nemo 12B, Phi-4-Mini all have well-tested `--jinja`
   chat templates per [llama.cpp's function-calling guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md).
2. **Coding strength.** Cantrip is specifically writing Python
   charms, charmcraft.yaml, pytest. Wins: Qwen2.5-Coder family is
   strongest on the small set; Qwen3-8B and Llama-3.1-8B are solid
   generalists; Mistral Nemo 12B is competitive on Python tasks.
3. **Decode rate ≥ ~40 tok/s.** Below that the loop feels unusable
   even on small edits. Wins: anything 8 B and below with full GPU
   offload at Q4_K_M on this hardware.
4. **Native context ≥ 32 K.** Below that we *need* short-session
   mode (Phase 104) to ship before a default switch is sane. Wins:
   everything except Qwen3-4B's 32 K (just at the line) and
   Phi-4-Mini's 128 K (well over). Llama-3.1 and Mistral Nemo are
   the long-context tier at 128 K native.
5. **Fits with KV cache headroom.** Q4_K_M weights + 32 K KV cache
   should leave ≥ 1 GB spare for activations and the host's other
   GPU work. Pushes us away from 12 B + 128 K cache (~13 GB) and
   towards 8 B + 32 K cache (~7.5 GB).
6. **Already familiar to cantrip's prompt machinery.** Soft signal
   but real: the qwen3-coder run got us our chat-template debt for
   the Qwen family; reusing that work with Qwen3-8B is nearly free.

## 4. Comparison

VRAM totals are weights at Q4_K_M plus a 32 K-token KV cache,
unless noted. Decode rates are estimates for full-GPU-offload on
RTX 5070 Ti Laptop, scaled from public benchmarks of comparable-
size models on Ada/Hopper/Blackwell mobile parts; treat them as
shape, not as a contract.

| Model | Q4_K_M weights | Native context | KV @ 32 K | Total VRAM | Tool calling | Decode est. | Coding |
|---|---|---|---|---|---|---|---|
| **Qwen3-8B** | 5.0 GB | 32 K (YaRN→128 K) | 2.5 GB | **~7.5 GB** | native, well-tested | 40–50 tok/s | strong |
| **Llama-3.1-8B-Instruct** | 4.9 GB | 128 K | 3.0 GB | **~8.0 GB** | native | 40–50 tok/s | solid |
| **Mistral Nemo 12B** | 7.5 GB | 128 K | 2.0 GB | **~9.5 GB** | native (function calling) | 30–40 tok/s | very solid |
| Qwen2.5-Coder-7B-Instruct | 4.7 GB | 32 K | 2.5 GB | ~7.2 GB | **flaky w/ `--jinja`** | 45–55 tok/s | strongest at 7 B |
| Phi-4-Mini (3.8 B) | 2.4 GB | 128 K | 1.5 GB | ~4.0 GB | native | 60–70 tok/s | weaker than 8 B |
| Qwen3-4B | 2.5 GB | 32 K | 1.5 GB | ~4.0 GB | native | ~60 tok/s | weaker than 8 B |
| Qwen2.5-Coder-14B | 8.5 GB | 32 K | 2.5 GB | ~11 GB | native | 25–35 tok/s | strongest of all listed |
| Qwen3-coder (30 B MoE, current) | 18 GB | 32 K | 4 GB | ~22 GB *(partial offload)* | native | **5–10 tok/s** decode (CPU fallback) | strongest reasoning, but unusable speed |

Cells in **bold** are the ones the budget admits comfortably with
gemma4 stopped.

## 5. Per-candidate notes

### 5.1 Qwen3-8B *(primary pick)*

- [Hugging Face card](https://huggingface.co/Qwen/Qwen3-8B) confirms
  native tool calling, 32 K window with YaRN extension to 128 K,
  and explicit `--jinja` support in the published GGUF.
- Reuses our existing Qwen-family debugging from the qwen3-coder
  work: same chat-template tokenisation, same `<think>` handling.
- Expected to clear the budget at ~7.5 GB total with a 32 K cache,
  leaving ~3 GiB headroom on the 11 GiB usable pool.
- 32 K context is plenty for cantrip's normal long-form
  conversation — the qwen3-coder runs (also 32 K) only hit
  compaction on the heaviest enhancement passes.
- **Risk:** instruction-tuning quality on niche library API
  knowledge (e.g. modern `ops-tracing.Tracing` constructor) is
  unknown. We've already got Phase 101 closing that hole through
  the system prompt; the model just has to follow the recipe.

### 5.2 Mistral Nemo 12B *(long-context alternative)*

- 128 K native context, native function-calling, very solid Python
  performance per public benchmarks.
- ~9.5 GB total with a 32 K cache — fits, but tight. With a
  128 K cache it'd be ~13 GB and we'd be partial-offloading again.
  We'd ship it with a default 32 K cache and document the bigger
  cache as an opt-in.
- ~30–40 tok/s decode is a meaningful step down from 8 B. On the
  ntfy-improve scenario that translates to ~25 % longer wall clock.
  Trade is "no compaction needed" against "every edit takes longer".
- This is the model to pick if Phase 104 (short-session mode) gets
  deferred.

### 5.3 Phi-4-Mini *(speed alternative)*

- 3.8 B parameters, 128 K context, native tool calling.
- The fastest credible pick — 60+ tok/s — and small enough that
  *both* it and an 8 B model could be co-resident on the 11 GiB
  pool. That opens up "small fast model for the planner, larger
  model for the executor" as a future shape.
- Reasoning is meaningfully weaker than 8 B class on coding
  benchmarks. Probably not the *primary* default but a useful
  secondary.

### 5.4 Qwen2.5-Coder-7B-Instruct *(ruled out)*

- On paper the natural successor to qwen3-coder: code-tuned, Qwen
  family, 7 B fits comfortably, fastest among the strong-coder
  picks.
- **Open tool-calling bug** in [llama.cpp issue #12279](https://github.com/ggml-org/llama.cpp/issues/12279):
  multiple frameworks fail to get successful `tool_calls` out of
  this model with the `--jinja` flag. Given how much pain we just
  spent chasing the qwen3-coder template tokens, picking another
  Qwen-family model with an open template bug isn't worth the risk
  for a default. Worth re-evaluating once that issue closes.

### 5.5 Qwen3-coder *(current default — keep as opt-in)*

- Strongest reasoning of any model that fits the hardware, but the
  decode-rate cost is severe: partial-offload at the 30 B-MoE level
  produces 5–10 tok/s in our measurements. A 5-min `edit_file`
  round at this rate is unavoidable.
- Phases 102 and 103 are necessary just to make this model finish
  long runs reliably. Phase 105 doesn't replace it — it just stops
  *defaulting* to it. Operators who want it explicitly keep it.

## 6. Recommendation

Switch the documented "default local model" away from qwen3-coder
to **Qwen3-8B**, validated by a smoke test on the existing host
inference-snap infrastructure first (so we don't pay the snap-
packaging cost until we're sure). See Phase 105 in ROADMAP for the
work breakdown.

Keep Mistral Nemo 12B documented as the long-context alternative
and Phi-4-Mini as the speed alternative; they're not mutually
exclusive with the default and operators should be free to swap.

## 7. Open questions

- **Custom inference-snap or host llama-server?** The fastest path
  to validation is host `llama-server` directly (an hour of work).
  Long-term, we want a snap so the rest of the team gets the same
  experience without manual setup. Phase 105.3 covers the snap
  packaging once 105.1 confirms the model is the right pick.
- **Does Qwen3-8B's tool calling survive long tool schemas?**
  qwen3-coder leaks `<function=...>` tokens into `content` at
  temperature > 0.2 — we already clamp `conversation_temperature`
  to 0.2 for inference-snap. An open question is whether Qwen3-8B
  shares that quirk; the smoke test will tell us, and the existing
  clamp covers us either way.
- **Can we run two models concurrently?** Phi-4-Mini (~4 GB) +
  Qwen3-8B (~7.5 GB) ≈ 11.5 GB, on the edge. Useful if cantrip
  ever wants a tiny "router" model that decides whether the heavy
  model is needed. Out of scope for Phase 105 but worth tracking.
- **Does VM GPU passthrough become worth setting up?** If we
  always reach the model via `http://10.42.160.1:<port>` from
  inside the VM, the model selection here is independent of the VM
  topology. Passthrough only matters if we want the agent to spawn
  its own model instances, which we don't today.

## 8. Sources

- [llama.cpp function-calling docs](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md) — `--jinja` support matrix and template guidance.
- [Qwen3-8B model card](https://huggingface.co/Qwen/Qwen3-8B) — tool calling, context, GGUF availability.
- [Qwen2.5-Coder-7B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF) — quantisation list.
- [llama.cpp issue #12279](https://github.com/ggml-org/llama.cpp/issues/12279) — open tool-call bug for Qwen2.5-Coder-7B-Instruct.
- [Qwen llama.cpp guide](https://qwen.readthedocs.io/en/latest/run_locally/llama.cpp.html) — Qwen-specific running notes.
- `tmp-hardware-info.md` — host hardware capture.
- Local enhancement runs: `cantrip-iter-runs/run-final2`, `improve-02`, `gemma-improve` — measured wall-clock and failure modes.
