# Research Spike: `canonical/-craft` and the Pi-Extension Alternative

> **Scope:** What is the `canonical/-craft` hackathon project? Could
> Cantrip be packaged as a Pi coding-agent extension — a lighter-weight
> alternative runner that forgoes the autonomous two-loop design but
> keeps the "build a charm very, very well" goal? What else is worth
> borrowing?
>
> **Companion reading:** `design/PI_RESEARCH.md` covers the reverse
> direction — using Pi *inside* Cantrip as a subagent backend. This
> document covers Cantrip's charm-building intelligence exposed *as* a
> Pi extension. As §3 concludes, `-craft` turns out to be a working
> instance of the `PI_RESEARCH.md` direction, not this one.
>
> **Sources:** read directly from the `canonical/-craft` repository
> (the `dashcraft` Python project; the repo is Canonical-internal —
> not visible to anonymous web requests but readable through the GitHub
> API with an authenticated session). Specific files cited inline.

---

## TL;DR

- **`canonical/-craft`** (the `dashcraft` project, aliased `-craft` on
  PATH) is **not** primarily a Pi extension. It is a **Python CLI**
  (`dashcraft pack`) that builds a Juju charm from an upstream repo in
  two stages: (1) a fully **deterministic** Python pipeline — clone the
  upstream, analyse it (`analysis.py`), and scaffold a charm with
  templates pre-filled from that analysis (`templates.py`), with no
  LLM involved; then (2) it launches **`pi` as a subprocess in RPC
  mode** to polish, lint, and unit-test the scaffold. It ships a
  TypeScript Pi extension *and* skills that it copies into each
  generated charm, but the extension is one component of the larger
  Python host, not the product itself.

- **`-craft`'s authors did not build the charm intelligence as a Pi
  extension that owns the run.** They built a Python host that owns
  the pipeline and uses pi only as a reactive coding loop, with a
  small TypeScript extension supplying pi's tools, skills, and system
  prompt. This is the `PI_RESEARCH.md` "pi as a subagent/coding
  backend" shape, *not* "Cantrip as a Pi extension".

- **Pi-extension-as-alternative-runner:** recommended against. The two
  blockers (language mismatch and architecture mismatch) hold, and
  `-craft`'s design choices illustrate how to sidestep both by *not*
  putting the orchestration inside a Pi extension.

- **Borrowable ideas:** the deterministic-scaffold-before-LLM pattern
  (the most valuable takeaway), the skills-as-`SKILL.md` distribution
  model, thin CLI-wrapping tools, and minimal system-prompt
  discipline. None require a hard Pi dependency.

- **Recommendation:** do not pursue a Pi extension as a Cantrip
  runner. If a lighter mode is wanted, add `--interactive` /
  `--no-loop` inside Cantrip. Separately, steal `-craft`'s
  deterministic-first pipeline idea for Cantrip's own charm
  scaffolding regardless of runner.

---

## 1. What is `canonical/-craft`?

### 1.1 What it is

`dashcraft` — aliased on PATH as `-craft` — is a fast, AI-driven charm
generator "in the spirit of Canonical's crafts (charmcraft, snapcraft,
…) but **not** built on the upstream craft framework — a small,
lightweight prototype" (`CLAUDE.md`). Given an upstream git repo and a
model name, `dashcraft pack` produces a fully-featured Juju charm
(observability, ingress, relations, config options, actions) and packs
it into a `.charm` file ready for `juju deploy`. The GitHub
description is *"What's faster than charming? Dashing. megademo.ai
hackathon project to generate charms on demand."*

### 1.2 Language and runtime

| Property | Fact | Source |
|----------|------|--------|
| Host language | **Python**, `requires-python >=3.14` | `pyproject.toml` |
| Runtime deps | exactly one: `pyyaml>=6.0` | `pyproject.toml` |
| Entry point | `dashcraft` console script (aliased `-craft`) | `pyproject.toml` `[project.scripts]` |
| Bundled extension | **TypeScript**, under `src/dashcraft/.pi/` | `.pi/extensions/dashcraft/index.ts` (~1190 lines) + `templates.ts` (~1390 lines) |
| External CLIs required | `git`, `uv` (>=3.14), `node`+npm, `quickpack`, `pi` | `CLAUDE.md` |
| Type checker | `ty` (Astral) — same as Cantrip | `pyproject.toml` |

So the project is bilingual by design: a Python CLI host plus a
TypeScript Pi extension that the host hands to pi at runtime.

### 1.3 The `pack` pipeline (`src/dashcraft/cli.py`)

`dashcraft pack` runs, in order:

1. parse `dashcraft.yaml` (`config.py`)
2. clone `upstream` into `.dashcraft-tmp/upstream/` (`upstream.py`)
3. **analyse** the cloned tree (`analysis.py`) → a `WorkloadAnalysis`
   dataclass (language, framework, start command, port, env vars,
   database/cache signals — all by inspecting `Dockerfile`,
   `docker-compose.yml`, `package.json`, `go.mod`, `requirements.txt`
   / `pyproject.toml`, `Cargo.toml`, `.env*`). **No LLM.**
4. **scaffold** a charm into `.dashcraft-tmp/charm/` with templates
   *pre-filled* from the analysis (`templates.py`
   `get_filled_files()`); run `uv lock`; copy the bundled `.pi/`
   extension + skills into the charm. **No LLM.**
5. check `pi` is installed and an API key is present, then **drive
   `pi` in RPC mode** (`pi.py` → `generate_charm()`) to validate,
   lint, and unit-test the scaffold. The prompt explicitly tells the
   agent the files are already filled and *not* to re-run the
   scaffolding tool; it iterates fixes up to five times each for lint
   and unit tests and then writes a `KNOWN_ISSUES.md` rather than
   giving up silently.
6. `quickpack pack` the result; move the `.charm` beside
   `dashcraft.yaml` and print a `juju deploy` hint (parsing
   `charmcraft.yaml` to add `--resource` flags).

The shape that matters: **steps 1–4 are deterministic Python; the LLM
only enters at step 5, as a polishing loop, and only via a subprocess
the Python host controls.**

### 1.4 How it talks to pi (`src/dashcraft/pi.py`)

`pi` is launched as a child process, not imported:

```python
cmd = [
    'pi', '--mode', 'rpc',
    '--no-session', '--no-context-files', '--no-themes',
    '--extension', self._extension,
    '--no-skills',                                 # default
    '--no-prompt-templates',                       # default
    '--system-prompt', '<charm-focused prompt>',   # custom, terse
    '--model', 'openrouter/<model>',               # always via OpenRouter
]
subprocess.Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE,
                 text=True, bufsize=1, cwd=self._work_dir)
```

Communication is **JSONL over stdin/stdout**: the host writes
`{"type":"prompt","message":...,"id":...}` lines and reads streamed
events back — `tool_execution_start/end/update`, `message_update`,
`agent_end`, `response`, `extension_error`. Generation is two-phase:
send the prompt and wait for acceptance (300 s default), then
`wait_for_agent_end()` reads events until `agent_end` (1800 s
default). The default model is `gemini/gemini-2.5-flash`; whatever
provider prefix the user supplies is preserved and OpenRouter is then
layered on top so pi routes every model through OpenRouter as the
gateway.

This is precisely the "drive pi as a coding-agent subprocess over
RPC" integration that `PI_RESEARCH.md` evaluated for Cantrip —
realised here in a shipping prototype.

### 1.5 The bundled Pi extension (`src/dashcraft/.pi/`)

```
.pi/
  extensions/dashcraft/
    index.ts       (~1190 lines) — commands + tools
    templates.ts   (~1390 lines) — TypeScript re-implementation of the analysis + templates
  skills/
    quick-charm-workflow/SKILL.md   relations/SKILL.md
    charm-testing/SKILL.md          observability/SKILL.md
    operational-patterns/SKILL.md   quality-review/SKILL.md
    debugging/SKILL.md
```

The TypeScript extension registers **one command** and **six tools**
for the agent:

| Surface | Name | What it does | How |
|---------|------|--------------|-----|
| command | `/dashcraft [name]` | scaffold & research a new charm interactively | TS |
| tool | `dashcraft` | research a workload clone, write `charmcraft.yaml` + `src/charm.py` | TS port of the Python analysis |
| tool | `charm_build` | `quickpack pack` | shells out to the CLI |
| tool | `charm_lint` | ruff / ruff-format / codespell / pyright | `uv run --group lint` |
| tool | `charm_test_unit` | pytest | `uv run --group unit` |
| tool | `charm_test_integration` | pytest (live Juju) | `uv run --group integration` |
| tool | `charm_help` | list skills + tools | — |

Two facts here are decisive for §3:

1. **The pi-facing tools are thin CLI wrappers.** `charm_build`,
   `charm_lint`, `charm_test_*` just shell out to `quickpack`, `uv`,
   `ruff`, `pyright` — and the wrappers stream output line by line
   (see `streamProcess` in `index.ts`) so the user sees live
   progress, but they do not bridge into a Python *library* API.
   Charm tooling happens to be CLI-shaped, so a TypeScript tool can
   drive it without a language bridge.
2. **The analysis logic is duplicated, not bridged.** The `dashcraft`
   tool re-implements `analysis.py` / `templates.py` in TypeScript
   (`templates.ts`, ~1390 lines) rather than calling the Python. The
   team paid for the language boundary with duplication — exactly the
   cost predicted in §3.3 — and chose it deliberately so the in-pi
   tool has no Python dependency at call time.

The extension and skills directory is also **copied into every
generated charm** by `cli.py`'s scaffolder, so a finished charm ships
with a self-contained `.pi/` for downstream pi-driven work.

### 1.6 Test harness

The repo's `tests/spread/` directory runs two end-to-end tracks:
`pack-*` / `dashcraft-*` suites that pack a charm with pi in the loop
and then unzip-and-verify, and `deploy-*` suites that additionally
deploy on a concierge-microk8s controller. Both share
`charm-helpers.sh`; new pack suites are a ~4-line `task.yaml`. This
matters for §4: `-craft` validates end-to-end on real Juju, not just
unit tests, which is why its skill set is trustworthy as a comparison
point.

---

## 2. The Pi Extension System (brief recap)

`PI_RESEARCH.md` documents Pi's RPC mode, SDK, and tool model in
detail. The points most relevant here, cross-checked against how
`-craft` actually uses them:

| Property | Detail | Confirmed by `-craft`? |
|----------|--------|------------------------|
| Language | TypeScript (Node/Bun); loaded at runtime, no build step | Yes — ships `.ts` directly |
| Built-in tools | `read`, `write`, `edit`, `bash` | Agent uses these to edit the charm |
| RPC mode | `pi --mode rpc`, JSONL on stdin/stdout | Yes — `pi.py` drives it exactly so |
| Extension API | `pi.registerTool()`, `pi.registerCommand()`, events, `ctx.ui.*` | Yes — six tools + one command |
| Skills | `SKILL.md` files, loadable via `/skill:<name>` | Yes — seven shipped skills |
| Flags | `--no-session`, `--no-context-files`, `--system-prompt`, `--model` | Yes — all used |
| Agent loop | single reactive loop; no built-in work queue/executor | `-craft` supplies its own loop in Python |
| MCP support | no documented pass-through | not used by `-craft` |

The notable confirmation: `-craft` runs pi with `--no-session`,
`--no-context-files`, `--no-themes`, `--no-skills`,
`--no-prompt-templates`, a custom `--system-prompt`, and its own
extension — i.e. it strips pi down to "a coding agent with my tools
and my prompt" and supplies all orchestration itself.

---

## 3. Pi Extension as Alternative Cantrip Runner

### 3.1 What the question is asking

The "lighter-weight mode" framing means: not replacing Cantrip's
codebase, but offering a different entry point for users who do not
want the full two-loop autonomous agent. A Pi extension would give
such users Pi's interactive loop plus charm-building tools, without
the Textual TUI, work queue, background executor, or Juju watcher.

### 3.2 What `-craft` actually chose — and why it matters

`-craft` faced the same fork in the road and answered it clearly:

> It did **not** build its charm intelligence *as* a Pi extension
> that owns the run. It built a Python host that owns the pipeline
> and uses pi as a polishing subprocess, exposing only a thin
> CLI-wrapping tool surface inside pi.

That is the strongest available evidence for this spike's
recommendation. A serious charm builder, given pi and a hackathon,
kept its real logic in its own process and treated pi as a
replaceable coding backend. The Pi extension carries prompts, skills,
and CLI shims — not the analysis, not the scaffolding, not the pack
orchestration.

### 3.3 The language-mismatch problem

Every Cantrip tool is Python; Pi extensions are TypeScript. There
are three bridging options — shell-out, full TS rewrite, or a TS
wrapper around a Python subprocess. `-craft` shows the real-world
resolution:

- For **CLI-shaped** capabilities (pack, lint, test), it wrote thin
  TypeScript tools that shell out to the CLI. Clean, because there is
  no Python *API* to bridge — just a command line.
- For **library-shaped** logic (workload analysis), it **re-implemented
  it in TypeScript**. That is the duplication tax, accepted on a few
  hundred lines of heuristics (the analysis is ~420 lines of Python
  matched by ~1390 lines of TypeScript in `templates.ts`).

Cantrip's ~50 tools are overwhelmingly library-shaped (they import
`ops`, `jubilant`, `craft-parts`, call Charmhub APIs, parse YAML with
Python models). Porting them the way `-craft` ported `analysis.py`
would mean re-implementing the lot in TypeScript — a multi-month
parallel codebase — or shelling out to `python3 -m cantrip.tools.*`
at every call site, which inverts Cantrip's no-shell policy. `-craft`
only got away with the TS port because its analysis surface is tiny.
Cantrip's is not.

### 3.4 The architecture-mismatch problem

Pi's single reactive loop is a poor container for Cantrip's value:

| Dimension | Pi extension | Full Cantrip | What `-craft` did |
|-----------|-------------|--------------|-------------------|
| Agent loop | single reactive | two-loop (conversation + autonomous executor) | kept its loop in Python; pi is one step |
| Task planning | LLM ad-hoc per turn | `WorkQueue` with typed deps, retry, replan | Python pipeline owns ordering |
| Background work | needs a community subagent ext | native executor | n/a — batch CLI, not interactive |
| No-shell policy | broken (`bash` is built-in) | enforced | irrelevant — `-craft` embraces shells |
| Determinism | none | tool-mediated | **deterministic scaffold before LLM** |

The two-loop design is the product's core value proposition. Removing
it to fit the Pi model yields something strictly weaker than
`cantrip --no-loop`. `-craft` did not even try to host orchestration
in pi — it kept pi for the one thing pi is good at (a reactive
code-editing loop with custom tools and prompt).

### 3.5 What a Pi extension would genuinely be good for

A Pi extension is the right shape for *charm-aware hints to existing
pi users* — inject a `SKILL.md`, register a few CLI-wrapping tools —
which is essentially what `.pi/extensions/dashcraft/` is when
considered on its own. That is "charm-aware prompting for pi", not "a
lighter Cantrip".

### 3.6 Recommendation

**Do not pursue a Pi extension as a Cantrip runner.** Two independent
lines point the same way: the language/architecture analysis above,
and `-craft`'s own design decisions.

If the goal is a lighter-weight Cantrip, add a mode flag inside
Cantrip:

```
cantrip --interactive   # or: cantrip --no-loop
```

Same Python codebase, same tool catalogue, same system prompt and
skills, single reactive loop instead of the two-loop executor. No
foreign runtime. Separate roadmap item, on its own merits — do not
couple it to Pi.

---

## 4. Ideas Worth Borrowing

### 4.1 Deterministic scaffold *before* the LLM (the headline takeaway)

`-craft`'s best idea is not a Pi idea at all: it does as much as
possible deterministically (clone → analyse → fill templates) and only
invokes the model to *polish and verify* a scaffold that already
compiles. This cuts LLM round-trips (no "what language is this?"
turn), makes the first pass reproducible, and shrinks the model's job
to the part that genuinely needs judgement. The prompt the agent
receives explicitly forbids re-running the scaffolder and orders the
lint / test / fix loop with a hard iteration cap (`_MAX_FIX_ITERATIONS
= 5`) — failure becomes a `KNOWN_ISSUES.md` rather than an endless
retry.

Cantrip charm-building could adopt the same staging: run a
deterministic analysis + scaffold step (Cantrip already owns the
Python tools to do this well) and hand the agent a populated tree to
refine, rather than a blank directory. This is runner-agnostic and
worth a roadmap item.

### 4.2 Skills as portable `SKILL.md` (confirmed pattern)

`-craft`'s seven skills are plain `SKILL.md` files —
`quick-charm-workflow`, `relations`, `charm-testing`, `observability`,
`operational-patterns`, `quality-review`, `debugging`. They are
provider-agnostic text. Cantrip's skills are the same shape. Two
consequences:

- A community distribution model (`cantrip install-skill <url>`) is
  cheap and needs no Pi runtime.
- `-craft`'s charm-domain skills may overlap with or improve
  Cantrip's own; worth a direct diff of the two skill sets as a
  follow-up. (`quick-charm-workflow` already cross-references Cantrip's
  `twelve-factor` skill name, which suggests deliberate alignment.)

### 4.3 Thin CLI-wrapping tools

`-craft`'s `charm_build` / `charm_lint` / `charm_test_*` tools are a
reminder that when a capability is already a CLI, the cleanest tool
is a thin wrapper around it — with line-buffered streaming so the UI
shows live progress. Relevant when deciding whether a new Cantrip
tool needs a Python implementation or can shell a vetted binary.

### 4.4 Minimal system-prompt discipline

Pi's <1 000-token system prompt is deliberate, and `-craft` overrides
it with an even terser charm-specific one ("You are an assistant that
generates Juju charm code"). Cantrip's rendered prompt is hundreds of
lines. Pi's constraint is too strict for Cantrip's domain complexity,
but tracking rendered system-prompt token weight per session as a
metric (alert if it grows past ~3 000 tokens) remains a cheap audit.

### 4.5 Permission-gate / hook pattern (validation only)

Pi's `permission-gate` extension intercepts tool calls at a
`before_tool` event — the same pattern as Cantrip's Phase 46 hooks.
No change needed; the convergence validates the design.

### 4.6 Statusline data items & session forking

From `PI_RESEARCH.md`: adding the git branch of the charm under
development to Cantrip's status bar (not currently shown), and Pi's
session `fork`/`clone` as a reference model for the Phase 49 race
feature. Neither is a `-craft`-specific finding.

---

## 5. Concrete Next Steps

| Priority | Action |
|----------|--------|
| **Soon** | Prototype a deterministic analyse+scaffold step for Cantrip charm-building (§4.1) — the highest-value borrow. |
| **Soon** | Diff `-craft`'s seven skills against Cantrip's skills for overlapping or better charm guidance (§4.2). |
| **Backlog** | Add `--interactive` / `--no-loop` mode to Cantrip, independent of Pi (§3.6). |
| **Backlog** | Add `cantrip install-skill <url>` for community skill distribution (§4.2). |
| **Backlog** | Add git branch to the Cantrip status bar (§4.6). |
| **Closed** | Pi-extension-as-runner: evaluated and recommended against (§3); `-craft`'s own design confirms the call. |

---

## References

- `design/PI_RESEARCH.md` — Pi as subagent backend; full RPC/SDK
  analysis; pi vs ACP. `-craft` is a real instance of this direction.
- `design/ACP_RESEARCH.md` — Agent Client Protocol;
  Cantrip-as-ACP-agent.
- `canonical/-craft` source (the `dashcraft` project):
  `src/dashcraft/cli.py`, `pi.py`, `analysis.py`, `templates.py`,
  `.pi/extensions/dashcraft/index.ts`, `.pi/extensions/dashcraft/templates.ts`,
  `.pi/skills/*/SKILL.md`, `tests/spread/`.
- pi.dev: https://pi.dev — pi GitHub:
  https://github.com/earendil-works/pi
- pi extension docs:
  https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md
