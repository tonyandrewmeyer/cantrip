# Agent Tools

This document covers the tool system under `src/cantrip/agent/tools/`:
the abstraction, the registration pattern, and how to add or remove
tools.  It is the companion to [AGENT.md](AGENT.md) (which describes
*when* the agent uses tools) and [PROMPTS.md](PROMPTS.md) (which
describes how tool schemas end up in the LLM call).

## The `Tool` abstraction

Every tool the agent can call is a subclass of `Tool`
(`src/cantrip/agent/tools/base.py`):

```python
class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]: ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult: ...
```

- **`name`** — the string the LLM uses to invoke the tool.  Convention:
  `snake_case`, namespaced by subsystem (`juju_status`, `git_commit`,
  `charmcraft_pack`).
- **`description`** — a short sentence the LLM reads to decide *when*
  to call the tool.  Keep it under ~200 characters.  Guidance about
  *how* to use the tool belongs in skills, not descriptions.
- **`parameters`** — a JSON Schema object (the same shape accepted by
  OpenAI / Anthropic / Gemini tool-use APIs).  `tool_to_schema()`
  bundles name + description + parameters into the payload the
  provider expects.
- **`execute()`** — `async def`, returns a `ToolResult`
  (`success: bool`, `output: str`, `data: dict`, `error: str | None`).
  `execute_tool()` in `base.py` wraps each call in a try/except that
  catches the standard exception set and converts them into
  `success=False` results so a tool crash never crashes the agent.

`PathAwareTool` (`tools/files.py`) is a base for tools that operate on
paths relative to the charm directory — it threads `base_path` through
so file tools work correctly when the charm lives in a worktree.

## The `build_tools()` factory

`src/cantrip/agent/tools/__init__.py` centralises construction.
`build_tools(base_path=..., skills_index=..., virtual_store=...,
provider=..., state=..., queue=...)` returns a `list[Tool]` — every
tool instance the agent will expose, in a stable order.  Call sites
pass this list to `CantripAgent`, which stores it as a `dict[name,
Tool]` for lookup.

Dependency injection is explicit: tools that need the skills index,
virtual-file store, or access to the executor queue take those as
constructor arguments.  There is no global registry, no auto-
discovery, no plugin mechanism — `build_tools()` is the single source
of truth.

## Adding a tool

1. **Create the module** under `src/cantrip/agent/tools/`.  Group by
   subsystem (`juju.py`, `git.py`, `charm.py`) rather than creating a
   one-class file per tool unless the tool is large (`audit.py`,
   `charmlint_tool.py`).  Name the class `<Action>Tool`
   (`JujuStatusTool`, `GitCommitTool`).
2. **Implement the four abstract members.**  Put JSON Schema for
   `parameters` as a class-level property returning a literal dict —
   no runtime generation.
3. **Import** the class in `tools/__init__.py`'s import block (tools
   are imported from per-subsystem modules, not individually).  Keep
   alphabetical ordering within a group — ruff will re-sort.
4. **Add to the `build_tools()` factory** under the appropriate
   section comment (`# File operations`, `# Juju operations`, etc.).
   Instantiate with any dependencies it needs.

That's it.  No settings to register, no hook to install, no test
boilerplate beyond the tool's own unit test.

## Removing a tool

1. Delete the class (or the whole module if it was the last tool
   there).
2. Remove the import and the `build_tools()` instantiation.
3. Remove the tool's unit test file if it existed.

Grep for the tool's `name` string to make sure no skill or subagent
prompt still references it — if so, update or remove those too.

## Naming conventions

| Concern | Convention | Example |
|---|---|---|
| Module | snake_case subsystem | `juju.py`, `charmhub.py` |
| Class | `<Action>Tool` PascalCase | `JujuStatusTool` |
| Tool name (LLM-facing) | `subsystem_verb` snake_case | `juju_status`, `git_commit` |
| One-tool-per-file | only for >200-line tools | `audit.py`, `rodney.py` |

`oci_registry.py` is the renamed-from-`registry.py` module holding
Docker Hub / OCI image search — the name was changed in Phase 53.4 to
avoid implying it was a tool registry.

## Tool categories currently in play

The `build_tools()` factory groups tools by section comment.  The
current list (not authoritative — read `tools/__init__.py` for the
source of truth):

- **File operations** — read, write, edit, list, grep, glob, multi-edit
- **Audit & lint** — charm_audit, charmlint, operational_readiness
- **Charm build** — charmcraft_init, charmcraft_pack, quick_pack,
  charm_validate, fetch_libs, analyse_framework
- **Terraform** — generate, validate
- **Publishing** — upload, release, generate_readme / icon / docs /
  diagram / load_test
- **Demo** — showboat, rodney
- **Web** — fetch, search
- **Charmhub** — search, info
- **OCI registry** — search, image_info
- **Rockcraft** — init, pack, skopeo_push
- **Environment** — concierge_prepare, concierge_status
- **Git** — the full clone/init/status/diff/log/add/commit/push/
  branch/checkout/stash set
- **GitHub** — repo_create, pr_create / list / view, issue_list,
  pr_review, pr_review_reply
- **Juju** — the full status / deploy / refresh / relate / ssh /
  run_action / model / offer / consume / config / wait / sync /
  dispatch / secrets / relation_data / get_app_config / list_offers /
  remove_application / show_unit set
- **Observability** — debug_log, stream_logs, tempo_query, loki_query
- **Inference** — list_inference_snaps
- **Testing** — run_charm_tests, generate_tests, hook_benchmark,
  fuzz_test, chaos_test, acceptance (relation_smoke, action_exerciser,
  config_under_load, config_variation, workload_endpoint), scaling,
  upgrade
- **Publishing & reports** — test_report
- **Skills** — load_skill
- **Task management** — manage_tasks, plan_tasks

## Error handling contract

`execute_tool()` catches a deliberate, narrow set: `OSError`,
`ValueError`, `RuntimeError`, `KeyError`, `AttributeError`,
`UnicodeDecodeError`, `subprocess.SubprocessError`.  Anything else
propagates — a tool should not be silencing uncommon exceptions on
its own.  Tools should prefer returning `ToolResult(success=False,
error=...)` to raising when the failure is semantic
(a missing file, a Juju-side error) rather than structural.

## What a tool is *not*

- **Not a prompt.**  The `description` field is a decision aid, not a
  mini-prompt.  Guidance about methodology belongs in skills.
- **Not a god.**  A tool does one thing.  `juju.py` has 21 classes
  rather than one fat `JujuTool` with a `command` parameter because
  the LLM reasons better about explicit tool names than about string
  arguments.
- **Not a side-effect firehose.**  Tools report what they did via
  `ToolResult.output`.  They should not print, log at INFO, or write
  to stderr unless the operation genuinely benefits from it (the
  `log` call inside `execute_tool()` for caught exceptions is
  debugging affordance, not user-facing).

## Policy composition for tool access (Phase 55.4) — keep five, defer one, reject one

Cantrip's current tool-gating is `_filter_tools(tools, category)`
in `src/cantrip/agent/subagent.py` — a single-level allowlist
keyed off `TaskCategory`.  That's one layer where the
awesome-copilot [`agent-governance`][copilot-governance] skill
scopes six primitives across three layers (global / team /
agent) plus a rate limit, a trust score, and an audit trail.

### The six primitives — keep / defer / reject

| # | Primitive | Disposition | Why |
|---|-----------|-------------|-----|
| 1 | **`GovernancePolicy` + `compose_policies()`** — stacked allowlists with most-restrictive-wins semantics | **Keep** | Real value at the three Cantrip-relevant layers: global floor (``rm -rf`` always blocked), per-category (current `_CATEGORY_TOOLS` shape), and per-charm (operators can lock down a production charm directory). |
| 2 | **`max_calls_per_request`** — per-goal rate limit | **Keep** | Pairs with Phase 55.3's per-goal iteration + token budget as a cost safety valve. Three circuit breakers at goal > task > session-call granularity using the same bus event shape. |
| 3 | **JSONL audit trail** — append-only log of policy decisions | **Keep** | Streaming, grep-friendly export alongside the existing SQLite `events` table. Plays with `tail -f` and log aggregators in a way SQLite doesn't. |
| 4 | **Juju-aware destructive-command gate** inside `tools/juju.py` + `tools/run_command.py` | **Keep** | Covers a real gap: user hooks (Phase 46) fire at lifecycle events, sandboxing (Phase 49) isolates subprocesses *after* the decision to call. Neither catches a subagent autonomously firing `juju_destroy_model` through the native `tools/juju.py` path. The in-code gate is the third layer. |
| 5 | **Intent classification** — regex threat-signal scoring on prompt content | **Defer** | In a charm-building context the signal comes from the tool surface (`juju destroy-*`, `rm -rf`), not prompt content. Revisit if a real case emerges where a content regex catches something the tool-surface gate missed. |
| 6 | **Trust scoring with temporal decay** for multi-agent delegation | **Reject** | Cantrip's subagents all descend from one trusted operator — no mutually-untrusted delegation. The primitive assumes a threat model Cantrip doesn't have. |

### Mapping against Cantrip's current gating

Today's picture:

```
user prompt → main agent → planner → AgentTask (with category)
                                       │
                                       ▼
          _filter_tools(tools, category)  ←── single layer: category allowlist
                                       │
                                       ▼
          Subagent runs — _tool_or_veto fires PRE_TOOL_CALL hooks
                                       │
                                       ▼
                              Tool.execute() → subprocess / juju / fs
```

Three gaps a stacked-policy design would close:

1. **No global floor.**  `juju destroy-model` is in
   `TaskCategory.INFRA`'s allowlist because *some* infra tasks
   legitimately destroy models.  There's no way to say "but not
   against the dev-model currently in use" short of Python code
   changes.  A global policy with
   `require_human_approval: [juju_destroy_model]` gives operators
   that switch declaratively.
2. **No per-charm scoping.**  Today's gates are identical across
   every charm Cantrip touches.  A Phase-6 publishing-ready charm
   and a fresh sprint experiment deserve different policies; a
   per-charm `<charm>/cantrip.policies.yaml` makes that
   difference explicit.
3. **No in-code destructive gate.**  `tools/juju.py::JujuDestroyModelTool`
   calls `subprocess.run` directly.  A user's PRE_TOOL_CALL hook
   wrapping `juju destroy-model` does nothing because the
   subagent never shells out through `run_command` — it calls
   `Tool.execute` on the Python-side wrapper.  Policy enforcement
   has to live inside Cantrip's code paths, not external hook
   scripts.

### Relation to Phases 46 / 49 / 55.3 / 55.5

Four adjacent phases cover related ground.  Policy composition
doesn't replace any of them — it's the layer they're missing:

| Phase | Layer | Fires when |
|-------|-------|-----------|
| 46 (user hooks) | Lifecycle events | `pre_subagent`, `post_subagent`, `pre_tool_call`, `post_tool_call`, `pre_compact` |
| 49 (sandboxing) | Subprocess isolation | A shelled-out command executes under PID/mount namespaces |
| 55.3 (goal budget) | Aggregate cost cap | Before the next task spawns; checks total iterations + tokens |
| 55.5 (safe-outputs) | Per-task side-effect cap | Inside the subagent's tool dispatcher, per-task counters |
| **55.4 → 80 (policy stack)** | **Tool eligibility** | **Before the tool even appears in the subagent's allowlist; policy check runs ahead of the pre-hook chain** |

The five phases nest: **global budget > task safe-outputs >
policy allowlist > user hook > sandbox**.  A single tool call
passes every gate; any one can stop it.  That's the
defence-in-depth story the charm-building context actually
needs, and Cantrip has four of the five layers shipped or
scoped.  Phase 55.4's output (this section) plus the new
Phase 80 fills the fifth.

### Output — Phase 80 filed

The recommendation lands as a new phase in the roadmap: Phase
80 — Stacked Tool-Access Policies.  Five subphases (80.1-80.5)
ship the *keep* primitives; the *defer* and *reject* ones are
called out in the Phase 80 "What this phase is not" block so a
future reviewer finds the rationale without re-reading this
write-up.  No tiny prototype of `compose_policies()` against an
existing task type — the investigation is complete as-is, and
the phase proposal is where the prototype would live anyway.

[copilot-governance]: https://github.com/github/awesome-copilot/blob/main/skills/agent-governance/SKILL.md

## Deterministic pre-scan for Path B (Phase 55.7) — port with a stub

Cantrip's `AnalyseFrameworkTool` (`tools/charm.py`) covers PaaS
detection (Flask / Django / FastAPI / Go / Express / Spring Boot)
and emits a `workload_hints` block for Path B.  For **custom
applications that don't match a PaaS framework**, the LLM still
has to go digging in the source tree manually to enumerate
manifests, entry points, CI/CD config, and container artefacts
— burning tokens on work that's entirely deterministic.

The upstream
[`awesome-copilot` `scan.py`][upstream-scan] (712 lines, MIT)
already does exactly this scan: 60-entry manifest table across 25+
languages, 10 CI/CD platforms, Docker / k8s / Vagrant detection,
SBOM and security-config scanning, lint-config detection, 40+
entry-point candidates, git churn, TODO search, code metrics.

### Comparison

| Dimension | upstream `scan.py` | Cantrip `analyse_framework` |
|-----------|---------------------|------------------------------|
| Manifest catalogue | 60 entries, 25+ languages | 4 manifests, 4 languages |
| CI/CD platform detection | 10 platforms | none |
| Container artefacts | Dockerfile / compose / k8s / Helm / Vagrant / podman | Dockerfile, docker-compose variants |
| Security configs | `.snyk`, `SECURITY.md`, SBOM, `.bandit.yaml`, etc. | none |
| Lint / formatter configs | ~15 files | none |
| Entry-point candidates | ~40 across 20 languages | none |
| Env templates | `.env.example` variants | binary flag only |
| Monorepo detection | yes | no |
| Git churn / recent commits | yes | no |
| Charm awareness | no | `charmcraft`/`rockcraft` profile map, substrate suggestion, `ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS` flagging |

The two scans are complementary — upstream is breadth,
`analyse_framework` is charm-specific depth.  The natural shape
is a single scan that unifies them.

### Vendor vs port vs subprocess

**Vendor as-is** into `src/cantrip/skills/acquire-codebase-knowledge/scripts/scan.py`
(MIT permits).  Matches the Phase 55.1 skill-as-folder pattern,
which would welcome exactly this script.  But: 55.1 explicitly
deferred the loader changes (`LoadSkillTool` returns body text,
`read_file` is sandboxed away from the skills tree), and the
upstream script has no charm awareness — a `charmcraft.yaml` in
the repo goes undetected.  Vendoring means forking the code to
add it.

**Subprocess-invoke** a system-installed or vendored script.
Lightest integration but worst output consumption: the script
prints section-headed plain text to stdout.  The LLM would parse
free-form text instead of reading a structured dict.  Loses the
checkpoint-friendly shape too — Phase 52.3 wraps tool calls with
`response_to_dict` / `tool_result_to_dict`, and opaque text
doesn't participate in hash-based invalidation as cleanly as a
typed dataclass.

**Port** the upstream tables + detection passes into a
Cantrip-native helper module `src/cantrip/agent/tools/_scan.py`
with charm-specific additions (`charmcraft.yaml`,
`rockcraft.yaml`, `metadata.yaml`, `.cantrip` detection; charm
markers signalling "this is an existing charm, route to
improvement path").  `AnalyseFrameworkTool.execute` calls into
the helper and layers charm-specific reasoning on top of the
structured result.  The port converges on one source of truth
for "what's in this codebase?" — current PaaS detection in
`charm.py` becomes a thin layer that reads from `ScanResult`.

**Verdict: port.**  The script is under MIT, so attribution in
the file header is the only licensing obligation; the Cantrip-
specific additions (charmcraft / rockcraft manifest awareness,
the `ScanResult.is_existing_charm` routing signal, the
`extras: dict[str, Any]` escape hatch) would fork upstream
anyway, so forking in the form of a port is the cleaner
long-term home.

### Implementation shipped

Phase 92.1 completes the port in
[`src/cantrip/agent/tools/_scan.py`](../src/cantrip/agent/tools/_scan.py).
The helper now provides:

- The data tables (`MANIFESTS`, `ENTRY_CANDIDATES`,
  `CI_CD_CONFIGS`, `CONTAINER_FILES`, `SECURITY_CONFIGS`,
  `LINT_FILES`, `ENV_TEMPLATES`, `EXCLUDE_DIRS`,
  `CHARM_MARKERS`) with upstream values plus Cantrip extensions.
- A frozen `ScanResult` dataclass describing the output shape —
  JSON-friendly so it slots into the Phase 52.3 checkpoint
  envelope if this scan later gets wrapped by `checkpoint()`.
- A bounded `scan(path)` implementation: one filesystem walk with
  excluded-directory pruning and stable ordering, then manifest /
  entry-point / CI/CD / container / security / lint / env-template
  / charm-marker detection plus recent-git-churn counting.
- Framework inference reused from
  `cantrip.agent.tools.framework_detection`, with the candidate
  list, web-app-fit signals, config-file hints, and systemd-unit
  hints carried in `ScanResult.extras`.
- `AnalyseFrameworkTool.execute()` wired to read from `scan(path)`
  rather than re-deriving deterministic facts ad hoc.
- Unit coverage in `tests/unit/test_scan.py` for manifests-only,
  CI-only, entry-point-only, existing-charm-marker, mixed
  Docker/systemd/config, excluded-directory, and git-churn cases.

Decision on future UI surfaces: **yes, use this helper as the
single source of truth for repo-shape summaries.**  Phase 92.1 only
wires the planner/tool path; the repo-stats sidebar, onboarding
summary, and print-mode preamble remain follow-on consumers and
should call `scan()` rather than growing their own tree walks.
Until then the stub anchors the shape decision and keeps the
port proposal honest (by forcing it into a concrete
`_scan.py`-lives-here layout rather than staying abstract).

[upstream-scan]: https://github.com/github/awesome-copilot/blob/main/skills/acquire-codebase-knowledge/scripts/scan.py
