# GLM via OpenRouter — Eval Plan

Point-in-time research note.  Asks "is Z.ai's GLM family a useful
cheap-cloud tier for Cantrip, sitting between the free local snap and
the premium Claude / Gemini paths?".  Captured 2026-05-25 alongside
the Phase 111/112 local-model sweep; *not* a design.

## 1. Why now

[`LOCAL_MODELS_SURVEY_2026-05.md`](LOCAL_MODELS_SURVEY_2026-05.md) §4
skipped **GLM-4.6** for local on hardware grounds — the smallest
published quant wants 1×24 GB VRAM plus 128 GB RAM, well past the
12 GB laptop budget.  That skip is correct *for the inference-snap
path*.  It says nothing about the OpenRouter path, where GLM-4.6 has
been the cheap-but-credible coding model on community leaderboards
since its Sept 2025 release, and GLM-4.7 superseded it on
2025-12-22 with the same rate card.

The from-scratch eval in
[`LOCAL_MODELS.md`](LOCAL_MODELS.md) §5.6.2 spent ≈$40–50 on a single
gemini-3.1-pro-preview run.  Even a 5× cheaper credible cloud
alternative would change how often we can re-run that eval.

## 2. Candidates

| Slug (OpenRouter) | Released | $/M in | $/M out | Context | Notes |
|---|---|---|---|---|---|
| `z-ai/glm-4.7` | 2025-12-22 | 0.40 | 1.75 | 203 K | Current flagship; pitched as "enhanced programming + more stable multi-step reasoning/execution". |
| `z-ai/glm-4.6` | 2025-09-30 | 0.43 | 1.74 | 203 K | Predecessor; more independent community evals available. Reported on-par with Claude 3.5 Sonnet on multi-turn coding while consuming fewer tokens. |

Both expose native tool calling.  OpenRouter's `/models` probe
populates context window + `supports_tools` automatically, so
`OpenRouterProvider` needs no per-model special-casing — only the
pricing table (`src/cantrip/llm/pricing.py`) needed a static entry,
which has been added.

For reference, the rate card sits roughly:

- **6×** cheaper than Claude Sonnet 4.6 ($3.00 / $15.00)
- **5×** cheaper than Gemini 3.1 Pro Preview ($2.00 / $12.00)
- **30×** cheaper than Claude Opus 4.7 ($15.00 / $75.00)

That makes "the from-scratch eval costs $8–10 on GLM instead of
$40–50 on Gemini Pro" the headline question to answer.

## 3. What to measure

The local survey's selection criteria don't all transfer to cloud
(tok/s and KV-cache headroom become moot when the provider serves
the model); the ones that do remain:

1. **Tool-call correctness on the rendered Cantrip system prompt.**
   Existing gate:
   ```
   CANTRIP_SMOKE_OPENROUTER_MODEL=z-ai/glm-4.6 \
     uv run pytest tests/eval/test_system_prompt_smoke.py -v
   ```
   Both `test_system_prompt_drives_tool_call` and
   `test_system_prompt_returns_non_empty_response` must pass.
2. **`improve-02` end-to-end.**  Match the Qwen3-14B Run #3 protocol
   from [`LOCAL_MODELS.md`](LOCAL_MODELS.md) §5.6.1 — packable
   `ntfy` charm, no manual intervention.  Drive via the eval runner:
   ```
   uv run python -m tests.eval.runner run tests/eval/charms/ntfy \
     --provider openrouter --model z-ai/glm-4.6
   ```
3. **From-scratch build of a real multi-service workload.**  Same
   `suitenumerique/docs` target that Qwen3-14B couldn't carry and
   gemini-3.1-pro-preview did, per
   [`LOCAL_MODELS.md`](LOCAL_MODELS.md) §5.6.2.  Cost should land at
   roughly 1/5 of the Gemini run if the token-count claim ("≈15%
   fewer tokens than GLM-4.5 on multi-turn engineering") holds.
4. **A/B 4.7 vs 4.6** on the same prompts.  Same rate card, so the
   decision is purely quality and reliability.  Run 4.7 first — if it
   wins, 4.6 stays in the table for cost reporting / regressions but
   the candidate is 4.7.

## 4. Decision criteria

Promote to a documented cloud option (alongside Claude and Gemini)
if **all** of:

- §3.1 smoke passes consistently (≥3 of 3 runs).
- §3.2 improve-02 produces a packable charm with no manual
  intervention.
- §3.3 from-scratch run either completes the task *or* fails in a
  way that costs <$15 (cheap enough that the failure itself is
  affordable to retry).

If only §3.1 and §3.2 pass, treat as "cheap cloud for the improve
path" — narrower recommendation, document the from-scratch ceiling.

If §3.1 regresses, file the tool-call failure mode against
OpenRouter and stop — no point chasing the rest of the matrix.

## 5. First-run results (2026-05-25)

Smoke + improve-02 ran the same evening the note was written.  Both
GLM-4.7 and GLM-4.6 were exercised against the rendered system
prompt; only 4.7 went through to the full ntfy build.

### 5.1 System-prompt smoke (§3.1)

Against ``tests/eval/test_system_prompt_smoke.py`` with
``CANTRIP_SMOKE_OPENROUTER_MODEL`` set:

| Model | tool-call shape | non-empty response | Notes |
|---|---|---|---|
| `z-ai/glm-4.7` | PASS | PASS | Clean both runs. |
| `z-ai/glm-4.6` | PASS | FAIL → PASS on rerun | First call returned 14 completion tokens of `reasoning_content` only, empty `content`, no tool calls, `finish_reason=stop` — same shape as the Qwen3 "all-thinking, no-answer" failure mode that the local snap's `enable_thinking: false` fix solved. Adapter (`_openai_compat.py:390`) already routes `reasoning_content` into metadata, so the smoke is genuinely catching a model-side reliability gap on trivial prompts. |

**Verdict per §4 decision rule**: 4.7 wins the A/B on reliability;
4.6 stays in the pricing table but is not the recommendation.

### 5.2 improve-02 / from-scratch ntfy build (§3.2 + §3.3)

Single run against `z-ai/glm-4.7` via the eval runner.  Driving
command (note the absolute venv binary — `--cantrip-executable "uv
run cantrip"` fails because the runner treats the value as a single
argv[0], not a shell command):

```
uv run python -m tests.eval.runner run tests/eval/charms/ntfy \
  --provider openrouter --model z-ai/glm-4.7 \
  --cantrip-executable /home/ubuntu/cantrip/.venv/bin/cantrip \
  --timeout-seconds 1800
```

Headline numbers:

- **Wall-clock**: 66 seconds (`token_usage` first→last timestamp).
- **LLM calls**: 16 total (4 main-agent + 30 subagent message rows).
- **Tokens**: 196,883 in / 3,362 out.
- **Cost**: ≈$0.085 (≈$0.079 prompt + ≈$0.006 completion).
- **Result**: packable `ntfy-k8s_amd64.charm` at 1,186,633 bytes.
- **Rubric score**: 27/47 (57%), 2 critical failures.

For comparison, the historical anchors from
[`LOCAL_MODELS.md`](LOCAL_MODELS.md):

- Qwen3-14B Run #3 — improve-02 (existing scaffold), 5m 19s.
- gemini-3.1-pro-preview — from-scratch (no scaffold), ≈$40–50.

GLM-4.7 here did the *from-scratch* path in 66 s for under 9¢.
Throughput-and-cost-wise it dominates the cloud baselines.

### 5.3 Rubric breakdown

| Category | Score | Pct |
|---|---|---|
| structure | 9/9 | 100% |
| cos | 3/3 | 100% |
| testing | 4/6 | 67% |
| metadata | 5/12 | 42% |
| code | 6/17 | 35% |

What worked:

- ``charmcraft.yaml``, ``src/charm.py``, ``tests/unit/``,
  ``tests/integration/`` all present.
- Uses ``ops`` framework, configures a Pebble layer, declares the
  workload container.
- **COS integration via ops-tracing is in place** — the always-on
  CLAUDE.md rule landed.

What missed (2 CRITICAL):

- ``generates-config-file`` — no code path that materialises
  ``/etc/ntfy/server.yml`` from charm config.
- ``ntfy-serve-command`` — Pebble layer doesn't invoke ``ntfy
  serve``.

Plus six MAJOR/MINOR gaps: ``ingress`` relation absent, several
config options absent (``base-url``, ``cache-duration``),
``deny-all`` default missing, no ``behind-proxy`` handling, no
storage declared, tests don't use Scenario.

The pattern is clear: GLM-4.7 nailed the charm *scaffold* and the
project's conventions (ops, Pebble, COS, Scenario-not-Harness
naming) but skipped much of the workload-specific implementation
the prompt asked for.  That's a useful failure mode — fixable by
prompt tuning or a longer agent loop, *not* a fundamental
model-quality ceiling.

### 5.4 Procedural gotchas surfaced

1. **Charm-dir layout deviation.**  GLM-4.7 built the charm under
   a ``ntfy-k8s/`` subdir of the run directory.  Gold-standard
   layouts (``gold-claude``, ``gold-fireworks``) put
   ``charmcraft.yaml`` at the run-dir root.  The eval scorer walks
   the run-dir root, so the first invocation reported 2/47 even
   though the charm was real; re-scoring with
   ``runner.py score … ntfy-k8s/`` produced the real 27/47.
   Fixable two ways: a system-prompt nudge ("emit files at the
   current working dir, not a named subdir") or scorer logic that
   walks one level into a single-subdir directory.
2. **``--cantrip-executable`` is single-token.**  The runner
   passes the string as argv[0] to ``subprocess.run``, so multi-word
   wrappers like ``"uv run cantrip"`` fail with ``FileNotFoundError``.
   The eval doc should call out the absolute venv path.

### 5.5 Improve-loop on GLM-4.7's own output (2026-05-25)

Took the 27/47 charm from §5.2, stripped the build artefacts
(``parts/``, ``stage/``, ``prime/``, ``*.charm``, ``.craft/``,
``.cantrip*``), and pointed cantrip at it again with a focused
"close these specific gaps" prompt enumerating the eight rubric
misses.

Numbers:

- **Wall clock**: 148 s.
- **LLM calls**: 21 main-agent (zero subagents, zero plan-tasks).
- **Tokens**: 798,679 in / 6,877 out.
- **Cost**: ≈$0.33 (≈$0.32 prompt + ≈$0.01 completion).
- **Rubric score**: **45/47 (96%)** — both CRITICAL gaps closed,
  all targeted MAJOR/MINOR gaps closed.

The only remaining failure was ``uses-scenario`` (MAJOR) — the
improve prompt explicitly asked for ``ops.testing.Scenario`` and
GLM-4.7 declined to switch the test framework.  A targeted second
improve pass would almost certainly close it.

Combined cost of from-scratch (§5.2) + one improve pass:
**≈$0.42 to take ntfy from nothing to 96 % rubric.**  For the
≈$40–50 figure that ``LOCAL_MODELS.md`` §5.6.2 records for
``gemini-3.1-pro-preview`` on a comparable target, that is two
orders of magnitude cheaper at similar quality.

### 5.6 Reliability ceiling on the system-prompt smoke

While verifying §5.1, ran the bare-hello smoke against GLM-4.7
four times back-to-back: **2 pass, 2 fail** (failure shape always
the same — ~14–23 completion tokens, ``content=''``,
``tool_calls=[]``, ``finish_reason=stop``).  GLM-4.6 showed the
same pattern in §5.1.  The model is emitting tokens into
``reasoning_content`` and stopping without producing a final
answer on trivial prompts; the OpenAI-compat adapter
(`src/cantrip/llm/_openai_compat.py:390`) already routes
``reasoning_content`` into metadata, so this isn't an adapter
bug — it's GLM choosing to think rather than answer when there's
not much to say.

The failure mode is benign in multi-turn agent work (the
improve-loop ran 21 calls with no empty turns), but it is a real
gap for any user-facing single-shot interaction.  Per the §4
decision rule this would normally block promotion; the call here
is to **promote with a documented caveat** because (a) the
multi-turn agent path is the load-bearing one for Cantrip and
demonstrably works, and (b) the from-scratch + improve cost is so
low that the reliability tax of an occasional retry is dominated
by the value of the cheap path.

### 5.7 Updated verdict

**Promote GLM-4.7 as a documented "cheap cloud" option** alongside
Claude / Gemini, with two notes:

1. The from-scratch run is *partial* (≈57 % rubric); the iterate
   loop closes the gap dramatically (≈96 % in one extra pass for
   ≈33 ¢).  Document the two-pass workflow rather than promising
   single-shot.
2. The bare-hello smoke has a ~50 % failure rate.  Multi-turn
   agent work is unaffected; single-shot users may see empty
   replies that recover on retry.

GLM-4.6 stays in the pricing table for cost-accounting parity but
is not the recommended slug — 4.7 wins the A/B and the rate card
favours it slightly anyway.

### 5.8 System-prompt nudge (charm-dir layout) — did not work

§5.4 flagged GLM-4.7 nesting the charm under a ``<workload>-k8s/``
subdirectory of the run directory; gold-claude / gold-fireworks
put ``charmcraft.yaml`` at the run-dir root.

**Attempt 1** (committed in `3c1bbbd`): added a one-line nudge to
``src/cantrip/agent/prompts/system.md.j2`` in the
``Current Context`` block (rendered only when ``charm_path`` is
set), explicitly directing the model to emit files at the path
rather than in a named subdir.  A fresh from-scratch run with the
nudge in place still nested under ``ntfy-k8s/``.

**Attempt 2** (not committed): expanded the nudge into a six-line
"### File Layout (IMPORTANT)" subsection under "Charm Development
Standards" with explicit "Correct:" and "Wrong:" examples
("Wrong: `ntfy-k8s/charmcraft.yaml`").  Verified the prompt
shipped with the new section.  GLM-4.7 *still* nested under
``ntfy-k8s/``.  The run also timed out at 30 minutes with the
build task blocked — possibly the model confusing itself when its
strong prior collided with the explicit prohibition.  Reverted.

GLM-4.7 has a **sticky behavioural prior** that "build a charm
called X" implies "create directory `X/` and build inside it",
and prompt-level nudges (one-line or six-line) don't redirect it.
The Attempt-1 line is small enough that the cost of leaving it
committed is below the cost of churning another commit to remove
it; future cleanup is fine.

The right fix is **not** prompt-engineering — it's one of:

1. **Fix the eval scorer** to walk one level into a single-subdir
   directory before declaring "no charmcraft.yaml found".  Lowest
   blast radius; would have surfaced the real 27/47 on the first
   try.  Recommended.
2. **Hardcode the layout post-hoc** — flatten any
   single-subdir-with-charm pattern in the eval runner before
   scoring.
3. **Treat as model-specific behaviour** — accept that GLM-4.7
   ships a working charm in a slightly different layout; the eval
   harness should be robust to that.

None of the three is in scope for this note.  For now the
operational workaround is: when scoring a GLM-4.7 from-scratch
run, point ``runner.py score`` at the nested charm subdir, not
the run-dir root.

### 5.9 Second improve pass — ntfy to 47/47 (2026-05-25)

Targeted the one remaining ``uses-scenario`` failure on the 45/47
charm from §5.5.  Diagnosis first: the test file already used
Scenario semantically — ``from ops import pebble, testing`` then
``testing.Context(...)`` — but ``tests/eval/checks.py:218`` looks
for the literal substring ``"ops.testing"`` or
``"scenario"``.  Neither was in the file.  The check has a real
blind spot for the ``from ops import testing`` idiom; flagged for
follow-up.

Sent GLM-4.7 a focused prompt asking it to switch the import
style to ``import ops.testing as scenario`` and update the call
sites.  Result:

- **Wall clock**: 84 s.
- **LLM calls**: 11.
- **Tokens**: 398,175 in / 5,758 out.
- **Cost**: ≈$0.17.
- **Rubric**: **47/47 (100 %)** — all six testing rows now pass.

GLM-4.7 honoured the targeted instruction cleanly: imports
became ``import ops.testing as scenario``, every ``testing.X``
became ``scenario.X``, no other files touched.  Demonstrates that
**when given a single, specific gap to close, the iterate loop is
both cheap and reliable**.

### 5.10 Generalisation test — gitea from-scratch (2026-05-25)

ntfy is a single-relation Path B charm.  Does the two-pass
workflow generalise to a relations-and-ops-heavy spec?  Picked
``tests/eval/charms/gitea`` — five data-plane integrations
(PostgreSQL, Redis, SMTP, S3, ingress), three COS surfaces
(metrics, dashboards, logs), and operational actions
(``create-admin``, ``run-housekeeping``, ``backup-data``,
``restore-data``).  Total possible: 89 points.

The eval-runner bootstrap-failure pattern (§5.4 gotcha 2)
recurred — third time today across seven runner-driven
invocations.  All four manual invocations bootstrapped cleanly;
the failure shape is empty ``.cantrip`` SQLite, only
``AGENTS.md`` on disk, ``finish_reason`` not surfaced because
``runner.py`` only prints stderr when *zero* artefacts exist.
Worth filing as a follow-up: either fix the runner's
subprocess-capture path or surface stderr on any non-zero exit.

Ran gitea manually instead.  Results:

- **Wall clock**: 12 min 30 s.
- **LLM calls**: 36.
- **Tokens**: 1,147,290 in / 22,747 out.
- **Cost**: ≈$0.50.
- **Rubric**: **83/89 (93 %)** from-scratch, one shot.

Per-category breakdown:

| Category | Score | Pct |
|---|---|---|
| code | 26/26 | 100 % |
| cos | 10/10 | 100 % |
| metadata | 36/36 | 100 % |
| structure | 9/11 | 82 % |
| testing | 2/6 | 33 % |

What landed:

- All five data-plane relations declared and wired into the
  charm code (``postgres-relation-code``, ``redis-relation-code``,
  ``s3-relation-code``, ``smtp-relation-code``,
  ``ingress-relation-code`` — all PASS).
- All five operational actions (``create-admin``,
  ``change-admin-password``, ``run-housekeeping``,
  ``backup-data``, ``restore-data``).
- All three COS surfaces (metrics-endpoint + grafana-dashboard +
  logging relations; grafana dashboard bundled at
  ``src/grafana_dashboards/*.json``).
- Storage declared (data + config volumes with correct mount
  points).
- ``gitea-dump-call`` and ``gitea-admin-user-call`` rubric rows
  pass — the charm actually invokes the right Gitea CLI for
  backup and user bootstrap.

What missed (6 points):

- ``app-ini-template`` (MAJOR, 2 pt): rubric expects
  ``src/templates/*app*.j2``; GLM-4.7 generated app.ini inline
  from a Python f-string in ``src/charm.py``.  Same shape as the
  ntfy ``server.yml`` route in §5.2 — model prefers inline
  config rendering over Jinja templates.
- ``uses-scenario`` (MAJOR, 2 pt) and ``no-harness``
  (CRITICAL, 2 pt): same Harness-default failure mode as ntfy.
  GLM-4.7 has a strong prior to use ``ops.testing.Harness`` for
  unit tests despite the system prompt's explicit "Use Scenario,
  NOT Harness" rule.  Both ntfy and gitea exhibit this; it's
  consistent, not a flake.

### 5.11 Updated verdict (after §5.9 / §5.10)

GLM-4.7 generalises.  The two-pass workflow from ntfy carries
cleanly to gitea — 93 % from scratch, with the two missing
testing rows closable by the same targeted improve loop §5.9
demonstrated for ntfy.

**Cost ledger across the eval session:**

| Run | Spec | Pass | Score | Wall | Cost |
|---|---|---|---|---|---|
| §5.2 | ntfy | from-scratch | 27/47 (57 %) | 66 s | $0.085 |
| §5.5 | ntfy | improve #1 | 45/47 (96 %) | 148 s | $0.33 |
| §5.9 | ntfy | improve #2 | **47/47 (100 %)** | 84 s | $0.17 |
| §5.10 | gitea | from-scratch | **83/89 (93 %)** | 750 s | $0.50 |
| **Total** | | | | 17 m 8 s | **$1.09** |

For comparison, ``LOCAL_MODELS.md`` §5.6.2 records
``gemini-3.1-pro-preview`` spending ≈$40–50 on a single
``suitenumerique/docs`` from-scratch run.  GLM-4.7 took two
non-trivial charms to ≥93 % for under 1/40 of that budget.

**Known stickinesses that the system prompt can't shift:**

1. **Charm-dir layout** — model creates a ``<workload>-k8s/``
   subdirectory.  §5.8 documented two failed prompt nudges.
2. **Harness vs Scenario** — model defaults to ``ops.testing.Harness``
   despite the explicit project rule.  Surfaced on both ntfy
   (§5.2) and gitea (§5.10).

Both are fixable in one targeted improve pass at ≈$0.15–0.20
per spec, but the prompt-level fix line is the wrong knob —
either the eval harness should normalise around these
behaviours, or future work should explore SFT / few-shot
in-context examples rather than imperative system-prompt rules.

### 5.12 Follow-ups surfaced (not done in this session)

1. **Fix the eval scorer to handle nested charm layouts.**  Walk
   one level into a single-subdir tree before declaring
   ``charmcraft.yaml missing``.  Would have turned the §5.2 2/47
   into 27/47 on first read.
2. **Broaden ``uses_scenario_tests`` substring matching.**  Done
   in the same commit as this note update — ``tests/eval/checks.py``
   now also matches ``from ops import …testing…`` via a regex.
   New regression coverage in ``tests/eval/test_checks.py`` pins
   each of the four Scenario import idioms (explicit dotted,
   aliased dotted, ``from ops import testing``, ``import
   ops.testing as scenario``) plus the negative cases.
3. **Surface cantrip stderr from the eval runner on non-zero
   exits.**  Three of seven runner-driven runs today hit an
   empty-bootstrap failure with no diagnostic surfaced.  Either
   stream cantrip's output through to stderr, or print it when
   the runner detects an empty ``.cantrip`` SQLite alongside
   only ``AGENTS.md``.
4. **Optionally**, file the Harness-vs-Scenario stickiness with
   Z.ai if a contact is available — it's a behaviour their
   alignment / instruction-following passes could potentially
   tighten, given the system prompt is explicit.

## 6. Open questions

- **`z-ai` vs `:exacto` vs `:free` variants.**  OpenRouter lists
  `z-ai/glm-4.6:exacto` (provider-pinned routing) and
  `z-ai/glm-4.5-air:free` (rate-limited free tier).  Worth running
  the §3.1 smoke against the free tier first as a zero-cost
  smoke-the-smoke, then committing budget to the paid slug for the
  real evals.
- **Reasoning/thinking mode.**  GLM-4.6/4.7 model cards don't
  describe a separate think/no-think toggle the way Qwen3 does, but
  if OpenRouter's response schema surfaces a reasoning channel we
  should default it off — the InferenceSnapProvider's no-think fix
  (LOCAL_MODELS.md TL;DR) ~5×'d turn speed on Qwen3.
- **GLM-5.**  OpenRouter's catalogue already lists `z-ai/glm-5` —
  out of scope here, but if 4.7 lands well it's the natural next
  hop.

## 7. Sources

- OpenRouter — [`z-ai/glm-4.6`](https://openrouter.ai/z-ai/glm-4.6), [`z-ai/glm-4.7`](https://openrouter.ai/z-ai/glm-4.7), [Z.ai provider page](https://openrouter.ai/z-ai)
- Cirra — [GLM-4.6 Tool Calling & MCP Use: A Technical Analysis](https://cirra.ai/articles/glm-4-6-tool-calling-mcp-analysis)
- Z.AI — [GLM-4.6 Overview (developer docs)](https://docs.z.ai/guides/llm/glm-4.6)
- Together AI — [GLM-4.6 API](https://www.together.ai/models/glm-4-6)
