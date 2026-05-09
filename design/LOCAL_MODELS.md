# Local Model Refresh — Research Findings

> Research note. Asks "what local model should Cantrip default to for
> on-device charm building, given what we learned from the qwen3-coder
> and gemma4 enhancement runs?". Captures the comparison work that
> motivates Phase 105. This is research, not a design.

## TL;DR

> **Status update (after Phase 105.1.5 smoke, 2026-05-09):**
> Qwen3-14B Run #3 produced a packable, well-structured ntfy
> charm autonomously in 5m 19s — first time any local model has
> matched improve-02 quality end-to-end without manual
> intervention.  This required Phases 102 (streaming reconnect),
> 103 (resume hallucination repair), 106 (BLOCKED-task deadlock
> fix), 107 (tool-call failure cap), *and* the planner refactor
> to all land first.  Qwen3-14B is now the candidate to beat for
> Phase 105.2 / 105.3.  qwen3-coder stays the documented default
> until 105.3 packages Qwen3-14B as a snap.

- **Qwen3-14B is the new front-runner** (§5.6.1).  Q4_K_M ~9 GB
  weights + 16 K KV cache fits in ~11.7 GB on the 12 GB GPU with
  full offload.  Run #3 walked the full sequence
  (read → write_file × 3 → charmcraft_pack), produced a 1.19 MB
  charm matching improve-02's size, no manual intervention.  Phase
  107's tool-call cap was dormant insurance — the model didn't
  loop — but Run #2 showed why it's load-bearing.
- **qwen3-coder remains the documented default** until 105.3
  packages Qwen3-14B as a snap.  The Unsloth-fixed GGUF the
  existing snap uses handles tool calling reliably; the gating
  issue for it is partial-offload speed (5–10 tok/s decode), not
  correctness.
- **Demoted: Qwen3-8B**.  Pre-flight checks pass but end-to-end is
  worse than qwen3-coder on this scenario (§5.1.1 / §5.1.2).
  ~30 % feature completeness in 20 min before deadlock; chained-p
  with the autonomous-loop confounds removed produced 0 successful
  edits in 8 min.  Keeps a place on the candidate list as the
  speed pick if the smoke server is already running, but not
  productionised.
- **Other candidates** that fit at the corrected ~12 GiB budget:
  - **DeepSeek-Coder-V2-Lite-Instruct** (16 B MoE, 2.4 B active) —
    not yet smoked.  Lower priority now that Qwen3-14B has
    cleared the bar; useful as a comparison data point.
  - **Mistral Nemo 12B** — native function calling, 128 K context;
    stays an option for long-context runs.
- **Ruled out (or demoted) outright.**
  - **gemma4** — 10 K context exhausts before a real conversation
    starts.
  - **Qwen2.5-Coder family (7 B, 14 B, 32 B)** — the
    [`--jinja` tool-call problems](https://github.com/ggml-org/llama.cpp/issues/12279)
    aren't 7 B-specific; the [32 B emits wrong XML tags](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md)
    too.  Not worth adopting until that family-wide template state
    closes.
- **Validation infrastructure that paid off.** The smoke shape
  (host `llama-server` + socat forwarder + per-model
  ``inference-snaps/<name>/`` scaffold + ``_TOOL_CAPABLE_SNAP_NAMES``
  allowlist entry) was sound and reusable.  Future candidate
  evaluations should follow it.

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
| VRAM in use at original capture | ~6.8 GiB (host `llama-server` processes) |
| ~~VRAM free, with gemma4 running~~ | ~~~5 GiB~~ — *misleading: gemma4 itself was ~5 GB of that.* |
| **VRAM free, with gemma4 + qwen3-coder both stopped** | **~12 GiB** (only ~15 MiB Xorg overhead, confirmed by `nvidia-smi` 2026-05-08) |
| Host RAM | 62 GiB |
| Host CPU | Intel Core Ultra 9 275HX (24 P+E cores, AVX2/AVX-VNNI, no AVX-512) |
| VM GPU passthrough | **None.** The cantrip multipass VM doesn't see the GPU; the agent reaches it via the host's inference-snap on `10.42.160.1`. |

The first iteration of this note pegged the budget at "~5 GiB
free" (with gemma4 running), then "~10–11 GiB" (with gemma4
stopped).  The *actual* budget when no model is loaded is **~12 GiB**:
``nvidia-smi`` after stopping both gemma4 and qwen3-coder showed
4 MiB used by Xorg and nothing else.  The numbers in the rest of
this note are correct for "Qwen3-8B + 32 K cache fits" framing,
but the headroom for *bigger* candidates is meaningfully larger
than I originally credited:

- **8 B Q4_K_M + 32 K cache** ≈ 7.5 GB (~4.5 GB headroom)
- **12 B Q4_K_M + 32 K cache** ≈ 9.5 GB (~2.5 GB headroom)
- **14 B Q4_K_M + 32 K cache** ≈ 11–12 GB (just fits)
- **16 B MoE Q4_K_M + 32 K cache** ≈ 11–12 GB (just fits — but
  fast decode because only ~2.4 B active for MoE-Lite shapes)
- **30 B MoE Q4_K_M** ≈ 19 GB (still partial-offload, even at the
  full budget)

That keeps the sweet spot at "8 B class fits with comfort"
*and* opens a "14 B class just fits, with the trade of less KV-cache
headroom for bigger context".  The smoke evidence in §5.1.1 / 5.1.2
suggests bigger + code-tuned helps materially, so the latter tier
is worth taking seriously.

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

| Model | Q4_K_M weights | Native context | KV @ 32 K | Total VRAM | Tool calling | Decode est. | Coding | Smoked? |
|---|---|---|---|---|---|---|---|---|
| Qwen3-8B | 5.0 GB | 32 K (YaRN→128 K) | 2.5 GB | ~7.5 GB | native, well-tested | 40–50 tok/s | strong | ✗ underperformed (§5.1.1, 5.1.2) |
| **Qwen3-14B** | 9.0 GB | 32 K (YaRN→128 K) | 2.5 GB | **~11.5 GB** | proven Qwen3 family | 30–40 tok/s | strong, larger than 8 B | not yet — likely next target |
| **DeepSeek-Coder-V2-Lite** *(16 B MoE, 2.4 B active)* | 10 GB | 128 K | 2 GB | **~12 GB** (tight) | needs verification | ~40 tok/s (MoE) | code-tuned, GPT-4-Turbo-class per DS | not yet |
| **Mistral Nemo 12B** | 7.5 GB | 128 K | 2.0 GB | **~9.5 GB** | native function calling | 30–40 tok/s | very solid Python | not yet |
| Llama-3.1-8B-Instruct | 4.9 GB | 128 K | 3.0 GB | ~8.0 GB | native | 40–50 tok/s | solid | not yet |
| Phi-4-Mini (3.8 B) | 2.4 GB | 128 K | 1.5 GB | ~4.0 GB | native | 60–70 tok/s | weaker than 8 B | not yet |
| Qwen3-4B | 2.5 GB | 32 K | 1.5 GB | ~4.0 GB | native | ~60 tok/s | weaker than 8 B | not yet |
| Qwen2.5-Coder-7B / 14 B / 32 B | 4.7–18 GB | 32 K | 2.5 GB | varies | **family-wide `--jinja` issues** ([#12279](https://github.com/ggml-org/llama.cpp/issues/12279)) | varies | strong on benchmarks | ✗ ruled out |
| Qwen3-coder (30 B MoE, **current default**) | 18 GB | 32 K | 4 GB | ~22 GB *(partial offload — won't fully fit)* | native (Unsloth fix already in the snap's GGUF) | 5–10 tok/s decode | strongest reasoning we've measured | ✓ produced improve-02 |

Cells in **bold** are candidates that fit at the corrected ~12 GiB
budget *and* haven't been ruled out.  The earlier draft of this
table flagged Qwen3-8B / Llama-3.1-8B / Mistral Nemo 12B as
"comfortable" picks; after the smoke, the high-priority bold tier
shifts to **Qwen3-14B** + **DeepSeek-Coder-V2-Lite** + **Mistral
Nemo 12B** — bigger or more code-tuned models, which the smoke
evidence suggests matter more than raw decode speed.

## 5. Per-candidate notes

### 5.1 Qwen3-8B *(originally framed as primary pick — now demoted, see §5.1.1, §5.1.2)*

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

#### 5.1.1 Measured (Phase 105.1 smoke, 2026-05-08)

Smoke run results against
``inference-snaps/qwen3-8b/scripts/smoke-server.sh`` on the host
(RTX 5070 Ti Laptop, 12 GB VRAM, gemma4 + qwen3-coder both
stopped — full GPU available).  Server config: Q4_K_M GGUF,
``--ctx-size 32768``, ``--n-gpu-layers 99``, ``--jinja``,
llama.cpp build ``b8589`` (Canonical-published CUDA12 prebuild).

**Pre-flight checks (`smoke-check.sh`):**

| Check | Outcome |
|---|---|
| ``/v1/models`` reachable, model id ``Qwen3-8B-Q4_K_M.gguf``, ``n_ctx_train: 40960`` | pass |
| Plain hello (512-token budget) | pass — content "OK", finish=stop |
| Synthetic ``get_weather`` tool call | pass — clean ``tool_calls`` array, ``finish=tool_calls`` |

The hard test (synthetic tool call) round-trips correctly via
``--jinja``.  This is the failure shape that ruled out gemma4 and
Qwen2.5-Coder-7B; Qwen3-8B handles it cleanly.

**Notable observation:** Qwen3 is a *thinking* model.  Even the
plain "say OK" prompt produced 124 tokens of ``<think>...</think>``
reasoning before the 1-token visible reply (separated into the
``reasoning_content`` field by llama.cpp's default
``--reasoning-format deepseek``).  That overhead compounds across
an autonomous run.

**ntfy-improve scenario:** *partial — agent loop hung after 19m
43s of active work; ~30 % of the improve-02 target features
landed.*  Two attempts:

- **Run #1** (~9 min, exit code 1): hit the 300 s read-timeout in
  ``InferenceSnapProvider.client``.  After one successful
  ``edit_file`` round on charmcraft.yaml, the next LLM call was
  generating long enough that httpx timed out and ``ProviderError``
  fired.  Bumped the timeout to 1200 s as a stop-gap (the proper
  fix is Phase 102's streaming-reconnect work).
- **Run #2** (19m 43s active, then ~10 min hung before kill):
  - Followed the prompt's "read first" anchor: ``read_file``
    charmcraft.yaml + src/charm.py before any edits.
  - **32 tool invocations, 16 failures (50 % failure rate).**  The
    bulk of failures were ``edit_file`` ``old_string`` mismatches —
    Phase 103's hallucination pattern, now confirmed for Qwen3-8B
    too.  improve-02 with qwen3-coder ran at roughly a 5–10 %
    failure rate by comparison.
  - Despite an explicit "DO NOT call charmcraft_init" in the
    prompt, the model called it at minute 14 anyway, leaving a
    nested ``ntfy/`` scaffold to clean up.  Confirms: Qwen3-8B
    doesn't strictly honour negative instructions in long prompts
    (same shape we saw on gemma4).
  - **Output completeness vs improve-02:** 1 of 4 COS relations
    (only ``tracing``); 0 of 3 actions wired; ``ops_tracing.Tracing``
    *not* added; OCI image resource ✓; 2 unit tests started (vs
    target ≥ 7), never run successfully.  ``charmcraft.yaml`` was
    cleaner than ``src/charm.py`` — the model worked in YAML more
    reliably than Python.
  - Run hung after the work-queue task moved to status ``"blocked"``
    (10+ min of zero-CPU idle, no further LLM calls).  This is a
    *cantrip-side* bug — the autonomous loop should retry,
    escalate, or exit cleanly when all tasks are blocked, not park
    indefinitely.  Filed as Phase 106.

**Manual chained-p follow-up (Run #3):** to control for cantrip-
side confounds (planner mode pick, work-queue deadlock), repeated
the experiment as a series of single-feature ``cantrip run -p``
invocations with a fresh ``.cantrip`` between each.  First scope
("add the three remaining COS relations to charmcraft.yaml") was
allowed an 8-minute hard timeout.

  - Read the file twice.  Made **5 ``edit_file`` attempts, all
    failed** with ``old_string`` mismatches.  No fallback to
    ``write_file``.  Hit the timeout with **zero** net edits to
    charmcraft.yaml.
  - Confirms the ``edit_file`` accuracy issue isn't an artefact of
    the autonomous loop — it's the model.  When the autonomous run
    appeared to succeed at edits, it was largely because the model
    chose ``write_file`` (whole-file rewrite) when ``edit_file``
    kept failing; with a tighter scope and a small file, that
    fallback didn't fire.
  - Stopped the chained-p experiment after scope 1.  Running
    scopes 2–5 wouldn't change the conclusion — model-side
    accuracy is the binding constraint.

**Revised take-away.** Qwen3-8B is technically capable
(reachability + tool-call substrate work as advertised), but its
``edit_file`` accuracy on real charm files is poor enough that it
underperforms qwen3-coder on this task even after removing every
cantrip-side confound.  Code-tuning + size matter more than the
theoretical decode-rate advantage of full GPU offload.

**Recommendation revision.** Qwen3-8B should *not* be Cantrip's
documented local default.  Phase 105's "default switch" goal
should be reframed as "evaluate larger / more code-tuned candidates
on this hardware budget" — Qwen3-14B and DeepSeek-Coder-V2-Lite
are the obvious next smoke targets given the §1 / §3 framing now
holds at 12 GiB rather than 5 GiB.  Until one of those ships,
qwen3-coder stays the documented local pick.

Smoke artefacts retained at:

- ``cantrip-iter-runs/qwen3-8b-improve/run.ndjson`` — Run #1 +
  Run #2 event stream
- ``cantrip-iter-runs/qwen3-8b-improve/chained-logs/`` — Run #3
  chained-p NDJSON + stderr
- ``cantrip-iter-runs/qwen3-8b-improve/ntfy/`` — partial charm
  output (Run #2 final state)

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

### 5.5 Qwen3-coder *(current default — confirmed working, keep)*

- Strongest reasoning of any model that fits the hardware (in
  partial-offload form).  Q4_K_M GGUF is 18.6 GB so partial offload
  is unavoidable on the 12 GB GPU; that's the source of the
  5–10 tok/s decode rate.
- Tool calling: the [Unsloth fix](https://unsloth.ai/docs/models/tutorials/qwen3-coder-how-to-run-locally)
  for `--jinja` is *already integrated* into the GGUF the existing
  snap uses (``unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF``).  The
  ``conversation_temperature=0.2`` clamp we shipped pre-empted that
  bug; it's likely no longer load-bearing but doesn't hurt to keep.
- Phases 102 (streaming reconnect) and 103 (edit-hint remediation)
  are still necessary to make long runs reliable, but those are
  required for *any* local model — they're not specific to
  qwen3-coder.
- **Verdict after the Phase 105.1 smoke:** qwen3-coder produced
  improve-02's ~100 % feature target on the same hardware where
  Qwen3-8B produced ~30 %.  Until a different model demonstrates
  similar end-to-end completeness, qwen3-coder stays the documented
  default.

### 5.6 Qwen3-14B *(smoked — first local model to match improve-02 autonomously)*

- Same Qwen3 family as Qwen3-8B, so we know the ``--jinja``
  tool-call substrate works.  Roughly 1.75× the parameters at
  similar quantisation; turned out to be more accurate at
  ``write_file`` payload generation, which is the binding
  constraint (§5.1.2 saw an identical pattern at the smaller
  size).
- Q4_K_M ~9 GB ([bartowski/Qwen_Qwen3-14B-GGUF](https://huggingface.co/bartowski/Qwen_Qwen3-14B-GGUF));
  with a 16 K KV cache (KV is ~170 KB/token at fp16 for this
  geometry) total VRAM is ~11.7 GB — fits at the corrected 12 GiB
  budget with no headroom for a second model.  32 K context needs
  KV-cache quantisation (``CACHE_TYPE_K=q8_0``) to fit.
- Smoke server config under
  ``inference-snaps/qwen3-14b/scripts/smoke-server.sh``: port
  8340, ``--ctx-size 16384``, full GPU offload, llama.cpp ``b8589``
  CUDA12 prebuild (the same one the qwen3-coder snap uses).

#### 5.6.1 Measured (Phase 105.1.5 smoke, 2026-05-09)

Three runs against the smoke server, after Phases 102 (streaming
+ reconnect), 103 (resume hallucination repair), 106 (BLOCKED-task
deadlock fix), and the planner refactor all landed:

**Pre-flight checks** (`smoke-check.sh` from the VM):

| Check | Outcome |
|---|---|
| ``/v1/models`` reachable, model id ``Qwen_Qwen3-14B-Q4_K_M.gguf``, ``n_ctx_train: 32768`` | pass |
| Plain hello (512-token budget) | pass — content "OK", **97 tokens of reasoning** (vs Qwen3-8B's 124 — bigger model is *less* verbose in its thinking) |
| Synthetic ``get_weather`` tool call | pass — clean ``tool_calls`` array, ``finish=tool_calls`` |

**Run #1 — autonomous, original prompt (the same one used for
Qwen3-8B Run #2):**

- **Wall clock 7m 56s, exit code 0** (no deadlock, no kill — first
  time for any local-model smoke).
- 32 tool invocations, 8 successes / 1 failure on src/charm.py
  edits = **89 % success rate** (vs Qwen3-8B's 50 %).  Phase 103's
  did-you-mean hint helping.
- *No* ``plan_tasks`` call — the planner refactor (post-``db21d00``)
  evidently skipped sprint mode for this prompt shape, which
  avoided the sprint-mode hijack that wrecked the 8B run.
- ``charmcraft.yaml``: clean and complete (4 COS relations + 3
  actions + OCI image — single-shot ``write_file``).
- ``src/charm.py``: **broken**.  The model called ``edit_file``
  seven times to incrementally add things, each anchored on a
  stale read of the file.  End result: 3 stacked
  ``super().__init__(framework)`` calls, 14 cumulative
  ``framework.observe(...)`` lines (3-4 copies of each), wrong
  import (``import ops.tracing as ops_tracing``).
- ``charmcraft_pack`` not called — model went quiet after the last
  edit and the conversation loop returned.

**Run #2 — `write_file`-only directive added:**

- **Wall clock 14 min before manual kill, exit code 144.**
- The directive worked: ``charmcraft.yaml`` and ``src/charm.py``
  both written cleanly via single ``write_file`` calls — the
  duplicate-stacking pattern gone.  ``charm.py`` now passes
  ``ast.parse`` cleanly, has exactly 1 ``super().__init__``, 4
  ``framework.observe`` calls, 1 ``self._tracing`` block, and the
  correct ``import ops_tracing``.
- **New failure mode**: 8 consecutive ``write_file`` failures on
  ``tests/unit/test_charm.py``, each with ``duration_ms=0`` and
  caption ``"write_file()"`` (no path, no content) — the function-
  call envelope came back empty, almost certainly because the
  long test-file payload overflowed the model's tool-call
  generation budget mid-stream.  Each retry took ~80 s of
  reasoning.
- This wasn't covered by Phases 102 / 103 / 106 — those handle
  network timeouts, edit-hint mismatches, and
  already-blocked-task hangs respectively.  The retry loop ran
  for 11 minutes before manual SIGKILL.  **Filed as Phase 107**
  (tool-call failure cap).
- After Phase 107 and Phase 105.1.5 land, **Run #2's produced
  charm.py + charmcraft.yaml pack cleanly via manual
  ``charmcraft pack --destructive-mode``** (1.18 MB charm,
  matches improve-02's 1.19 MB).  So Run #2 was structurally
  one cap-bug away from end-to-end success.

**Run #3 — Phase 107 cap implemented + softened test-file prompt
(`3-5 simple tests, fall back to a single smoke test if the long
write fails`):**

- **Wall clock 5m 19s, exit code 0, autonomous ``charmcraft_pack``,
  charm packed at 1.19 MB.**
- Tool sequence (clean throughout):
  1. ``read_file`` charmcraft.yaml ✓
  2. ``write_file`` charmcraft.yaml (1213 bytes) ✓
  3. ``read_file`` src/charm.py ✓
  4. ``write_file`` src/charm.py (3255 bytes) ✓
  5. ``read_file`` tests/unit/test_charm.py ✓
  6. ``write_file`` tests/unit/test_charm.py (595 bytes) ✓ — *first
     attempt success*
  7. ``charmcraft_pack`` ✓ (3.087 s) → ``ntfy_amd64.charm`` (1.1 MB)
- The Phase 107 cap **didn't fire** — the model didn't loop.  The
  cap sits as dormant insurance against the failure shape Run #2
  exhibited.
- Test file is small (3 tests vs the prompt-asked 7) — the
  softened prompt explicitly invited that trade.  `improve-02`
  shipped 7 tests; for an honest comparison this is a
  half-way-there delta on the test surface, full match on the
  charm artefact.

**Take-away (revised after the smokes):**

Qwen3-14B is the **first local model to autonomously produce a
packable, well-structured ntfy charm** comparable in quality to
improve-02 — *but only after* Phases 102, 103, 106, 107, and the
planner refactor all landed.  The model itself is meaningfully
stronger than Qwen3-8B for tool-driven code-edit work; size +
code-tuning matter more than raw decode speed (§5.1.2 already
flagged this; §5.6.1 confirms it).

The Phase 107 cap is cheap insurance — only the second smoke
revealed the failure mode, and the third smoke didn't trigger it
— but skipping it would mean every operator hits a runaway loop
the first time the model can't generate a long ``write_file``
payload.  Worth keeping.

**Recommendation update:** Qwen3-14B becomes the candidate to
beat for Phase 105.2 / 105.3.  qwen3-coder stays the documented
default until the snap-packaging work in 105.3 lands; once it
does, Qwen3-14B should take that slot.  Re-running 105.1.6
(DeepSeek-Coder-V2-Lite) is still useful as a comparison data
point but is no longer urgent.

Smoke artefacts retained at:

- ``cantrip-iter-runs/qwen3-14b-improve/run.ndjson`` (Run #3) —
  full event stream
- ``cantrip-iter-runs/qwen3-14b-improve/ntfy/`` — packed charm
- Run #2 artefacts have been overwritten by Run #3's reset; the
  measurements above are reconstructed from the Phase 107 NDJSON
  and the doc-as-of-2026-05-10 snapshot of this section.

### 5.7 DeepSeek-Coder-V2-Lite-Instruct *(MoE candidate)*

- 16 B total parameters, **2.4 B active** per inference (MoE).
  Q4_K_M ~10 GB ([lmstudio-community GGUF](https://huggingface.co/lmstudio-community/DeepSeek-Coder-V2-Lite-Instruct-GGUF)).
  Total VRAM with a 32 K cache ~12 GB — fits, but tight.
- Code-tuned by DeepSeek; their reported benchmarks have it
  competitive with GPT-4-Turbo on code-specific tasks.
- 128 K native context — best long-context option in this tier.
- **Risk:** tool-calling reliability with llama.cpp's `--jinja`
  flag isn't documented as well as the Qwen family.  The smoke
  must include a tool-call round-trip check before any improve-
  scenario attempt.
- **Smoke shape:** same as §5.6, target port 8342.

## 6. Recommendation

> **Revised after Phase 105.1.5's Qwen3-14B Run #3 (§5.6.1,
> 2026-05-09):** Qwen3-14B produced a packable improve-02-quality
> charm autonomously in ~5 minutes.  The recommendation now reads:

**Adopt Qwen3-14B as the next documented local default**, gated on
Phase 105.3 packaging it as a snap.  Until that ships, qwen3-coder
stays the documented default — operators who want the new pick can
follow ``inference-snaps/qwen3-14b/README.md`` to run it from the
host directly.

**Next evaluations** (Phase 105.1 follow-ups, in priority order):

1. **Phase 105.2 — preset for ``--snap qwen3-14b``** (now active,
   see ROADMAP).  Wire ``InferenceSnapProvider``'s preset table,
   update the howto + reference-CLI docs.
2. **Phase 105.3 — package as a snap.**  Decide between custom
   snap and upstream contribution; ship recipe under
   ``inference-snaps/qwen3-14b/``.
3. **Phase 105.1.6 — DeepSeek-Coder-V2-Lite smoke** stays useful
   as a comparison data point but is no longer urgent.  The MoE
   shape might be faster than Qwen3-14B at similar quality;
   measure when convenient.
4. **Mistral Nemo 12B** — long-context fallback if Qwen3-14B's
   16 K runtime context turns out to be a binding constraint in
   practice.

Phi-4-Mini and Qwen3-8B remain documented as opt-in *speed* picks
for niche use cases (e.g. a planner-companion model running
alongside a heavier executor) but should not be the default.

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
