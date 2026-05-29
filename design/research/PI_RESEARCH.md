# pi.dev — Research Findings

> Sibling note to `ACP_RESEARCH.md`. Asks the same question — "could
> someone else's coding agent be a backend for Cantrip?" — but
> against [pi.dev](https://pi.dev) (the `@earendil-works/pi-coding-agent`
> toolkit) instead of the Agent Client Protocol. This is research,
> not a design.

## TL;DR

- **pi is a TypeScript coding-agent toolkit**, not a protocol. The
  monorepo at [github.com/earendil-works/pi](https://github.com/earendil-works/pi)
  ships three layers we could in principle hook into:
  - `@earendil-works/pi-ai` — a standalone unified LLM API across
    Anthropic / OpenAI / Google / Mistral / Bedrock with cost
    calculation. Equivalent in scope to our `LLMProvider`.
  - `@earendil-works/pi-agent-core` — agent runtime with tool calling
    and state management. Equivalent to our `Subagent`.
  - `@earendil-works/pi-coding-agent` — the full Claude-Code-shaped
    CLI built on top.
- **The SDK is Node-only.** Cross-language access is via *RPC mode*
  (JSONL over stdin/stdout) or *JSON event-stream mode* (read-only
  NDJSON). Cantrip integration would have to go through one of those.
- **The same A/B/C taxonomy from `ACP_RESEARCH.md` applies**, with
  the same pivotal property: pi-agent-core auto-executes its own
  tools, so we cannot use it as a pure `LLMProvider`. Option B
  (subagent backend) is again the only shape with real value.
- **pi has two genuine differentiators vs ACP:**
  1. A client-side `bash` RPC command that injects shell results
     into the next turn — cleaner than ACP's permission-only
     callback model.
  2. `fork` / `clone` session primitives at the protocol level —
     potentially compose with the Phase 49 race feature.
- **But pi loses on every other axis:** TypeScript-native tool
  bridging (no MCP), single-vendor protocol with no registry, no
  multi-agent ecosystem. Strictly more lock-in than ACP.
- **Verdict: interesting as a feature reference, not as an
  integration target.** If we ever build "external coding agent as
  subagent backend", ACP is the better target. Revisit pi only if
  the race feature specifically needs cheap session forking and we
  cannot get that elsewhere.

## 1. What pi.dev is

### 1.1 Positioning

pi describes itself as "a minimal terminal coding harness". The
monorepo README calls the project an "AI agent toolkit: coding
agent CLI, unified LLM API, TUI & web UI libraries, Slack bot,
vLLM pods." It is single-vendor (Earendil Works), Apache-licensed,
~96% TypeScript, and distributed via npm.

There is no protocol working group, no registry, no second
implementation. "pi.dev" and "the pi toolkit" are the same thing.

### 1.2 The three layers

| Package | Role | Cantrip analogue |
|---------|------|------------------|
| `pi-ai` | Unified multi-provider LLM API + cost calc | `src/cantrip/llm/` |
| `pi-agent-core` | Agent runtime — tool calling, state, sessions | `src/cantrip/agent/subagent.py` |
| `pi-coding-agent` | Full coding-agent CLI with built-in tools | The whole assistant surface |

Anything Cantrip might consume is at one of those layers.

### 1.3 Programmatic surfaces

Four operating modes are documented:

- **Interactive** — terminal TUI, slash commands.
- **JSON event-stream** — every session event written as NDJSON to
  stdout. Read-only; suitable for a Python parent process to tail.
  Events include `agent_start/end`, `turn_start/end`,
  `message_start/update/end`, `tool_execution_start/update/end`,
  `compaction_start/end`, `auto_retry_start/end`, `queue_update`.
- **RPC** — bidirectional JSONL over stdin/stdout. **Strict LF
  framing** — the docs explicitly call out that Node `readline`
  isn't protocol-compliant because it splits on `U+2028` /
  `U+2029`. Python `for line in stdin:` is fine if you pin the
  newline behaviour.
- **SDK** — `import { createAgentSession, SessionManager } from
  "@earendil-works/pi-coding-agent"`. Node only. Custom tools via
  `defineTool(...)` + `customTools: [myTool]`. Tools are
  auto-executed; the SDK exposes `tool_execution_*` events for
  observation but no documented interception point.

### 1.4 RPC method catalogue

Commands (client → agent):

| Group       | Methods                                                                             |
|-------------|-------------------------------------------------------------------------------------|
| Prompting   | `prompt`, `steer`, `follow_up`, `abort`                                             |
| State       | `get_state`, `get_messages`                                                         |
| Model       | `set_model`, `cycle_model`, `get_available_models`                                  |
| Thinking    | `set_thinking_level`, `cycle_thinking_level`                                        |
| Queue       | `set_steering_mode`, `set_follow_up_mode`                                           |
| Compaction  | `compact`, `set_auto_compaction`                                                    |
| Retry       | `set_auto_retry`, `abort_retry`                                                     |
| Bash        | `bash`, `abort_bash`                                                                |
| Session     | `get_session_stats`, `export_html`, `switch_session`, `fork`, `clone`, `get_fork_messages`, `get_last_assistant_text`, `set_session_name` |
| Utilities   | `get_commands`                                                                      |

Events (agent → client):

| Stream    | Notable updates                                                                     |
|-----------|-------------------------------------------------------------------------------------|
| Generation| `message_update` deltas: `text_delta`, `thinking_delta`, `toolcall_delta`           |
| Tools     | `tool_execution_start`, `tool_execution_update`, `tool_execution_end`               |
| UI        | `extension_ui_request` (with paired `extension_ui_response` command)                |
| Lifecycle | `agent_start/end`, `turn_start/end`, `message_start/end`, `queue_update`            |
| Context   | `compaction_start/end`, `auto_retry_start/end`                                      |

The hybrid `bash` command is interesting: the *client* runs the
shell command, pi stores the result as a `BashExecutionMessage`
that gets injected into the next LLM turn. This is a different
shape from ACP's `terminal/*` callbacks (where the agent asks the
client to host a terminal but still drives execution).

### 1.5 Tool execution ownership

Same defect as ACP: **the agent runs its own tools.** pi-agent-core
ships with built-ins (read, edit, bash, etc.); custom tools land
through `defineTool()` and are still executed inside the agent.
There is no "return tool calls for the host to dispatch" mode.

The closest escape hatch is the client-side `bash` RPC command in
§1.4 — but that is a parallel channel for *injecting* shell
output, not a way to intercept the model's tool decisions.

### 1.6 Extensions and tool bridging

pi extensions are TypeScript modules — see `examples/extensions/`
in the repo (`subagent`, `plan-mode`, `permission-gate`,
`protected-paths`, `ssh`, `sandbox`, `custom-compaction`). They
register tools, commands, events, and custom UI inside the running
pi process.

There is **no documented MCP pass-through.** This is the central
tool-bridging gap vs ACP, which explicitly accepts MCP server
endpoints during `session/new`. To expose Cantrip's charm tools
(`jubilant_deploy`, `charmcraft_pack`, `run_scenario_test`,
`scenario_test_runner`, …) inside a pi session we would have to
either:

- Write TypeScript extensions that shell out to a Cantrip helper —
  two language hops per call; or
- Add MCP support to pi ourselves — out of scope.

### 1.7 Permissions

pi exposes user-interaction surfaces via `extension_ui_request` /
`extension_ui_response` (dialog kinds: `select`, `confirm`,
`input`, `editor`; fire-and-forget kinds: `notify`, `setStatus`).
This is more general than ACP's `session/request_permission` but
also more loosely specified — there is no per-tool "approve / deny"
ceremony built into the protocol; it's a UI-callback channel that
extensions opt into.

Cantrip's hook system (Phase 46) would have to be wired in as the
default responder for any extension that requests confirmation.

## 2. Mapping to Cantrip

The relevant Cantrip abstractions are unchanged from
`ACP_RESEARCH.md` §2:

| pi concept                               | Cantrip analogue                                  |
|------------------------------------------|---------------------------------------------------|
| pi session                               | Per-subagent message list + tool inventory        |
| `prompt` command + turn                  | A `Subagent.run()` call                           |
| `message_update: text_delta`             | `stream()` chunks                                 |
| `message_update: toolcall_delta`         | `ToolCall` accumulation                           |
| `tool_execution_*`                       | Internal log events during execution              |
| `extension_ui_request`                   | Hook-veto callback (no direct analogue today)     |
| `bash` (client-side)                     | `run_shell` tool surface                          |
| `fork` / `clone`                         | *No analogue.* Phase 49 race feature is the closest match |
| `compact` / auto-compaction              | Subagent rounds budget + summariser               |
| `auto_retry_*`                           | Hook-driven retry pattern                         |
| Stop reasons (implicit in `agent_end`)   | `SubagentExitState`                               |

The mismatches are the same as ACP's:

- **Tool execution ownership.** pi runs tools; Cantrip's provider
  surface returns tool calls for Cantrip to run.
- **Permission model.** pi has UI dialogs; Cantrip has hook-driven
  vetoes that don't expect a human at the other end.
- **Plan ownership.** Cantrip's `WorkQueue` is global across
  tasks; pi's session is per-prompt.

## 3. Integration sketches

### 3.1 Option A — pi as `LLMProvider`

Same shape and same problems as ACP Option A. pi-agent-core
auto-executes tools, so `complete()` would have to suppress every
tool the agent has — and pi makes that *harder* than ACP because
there's no `MaxTokens=0` / `forbid all tools` knob in the
documented RPC surface. We'd be wrestling the runtime to turn it
back into a text generator we already have.

A *narrower* variant — wrapping `pi-ai` (the unified-provider
library) as Cantrip's provider — is cleaner conceptually but is
TypeScript-only, and Cantrip already covers the same provider
matrix in Python via `src/cantrip/llm/`. Two language hops to
reach providers we already reach natively. **No.**

### 3.2 Option B — pi as subagent backend *(most promising)*

Per task whose category we want to delegate, spawn `pi --rpc`
inside the worktree:

```text
AgentTask (e.g. category=IMPLEMENT)
    │
    ▼
BackgroundExecutor picks task
    │
    ▼
PiSubagent                            # new class, sibling of Subagent
    │
    ├── spawns `pi --rpc` subprocess (cwd = worktree)
    ├── sends `prompt` command with the task description
    ├── streams message_update / tool_execution_* → SubagentEvent bus
    ├── responds to extension_ui_request via hook system
    ├── (optionally) issues client-side `bash` for charm-specific shells
    ├── waits for agent_end
    └── returns SubagentResult(exit_state = …)
```

Genuine wins over Option B in `ACP_RESEARCH.md`:

- Client-side `bash` channel lets Cantrip splice in
  charm-specific shell-result context (charmcraft, juju status)
  without re-implementing them as pi tools. Useful where ACP
  would force a permission round-trip.
- `fork` / `clone` give us cheap "branch this session" semantics
  that *could* power the race feature (Phase 49) — racing two pi
  forks against the same partial state is a strictly nicer model
  than racing two independent agents from scratch.
- pi's auto-retry and auto-compaction are protocol-level, so we
  pay nothing to inherit them.

Costs and gaps:

- **Tool duality is worse than with ACP.** No MCP pass-through, so
  Cantrip's charm tool catalogue stays inaccessible to pi unless
  we write TypeScript extensions or hand-roll an MCP layer.
- **Permission policy via `extension_ui_request` is loose.** Each
  extension defines its own UI calls; Cantrip would need a
  default responder that does the right thing for unknown dialog
  kinds. Easy to get wrong.
- **TypeScript surface area.** Anything more sophisticated than
  RPC requires writing TS extensions, which is a runtime our team
  doesn't otherwise touch.
- **Cost model.** pi-agent-core uses pi-ai's cost calculation,
  which Cantrip doesn't read. Provider-router budget integration
  would need extending.
- **Single-vendor risk.** pi is one project's harness; we have no
  fallback if the protocol changes.

### 3.3 Option C — Cantrip as a pi provider / extension

Inverse of Option B: register Cantrip behind `pi.registerProvider()`
or wrap it as a pi extension so a pi user could drive Cantrip's
charm-building from inside pi.

Doesn't make conceptual sense. Cantrip is an autonomous planner
with subagents and a work queue; pi expects a *model* (or a
streaming LLM-shaped endpoint) at the provider boundary. The two
abstractions don't align — pi's provider contract is far below
Cantrip's planner.

If anyone ever wanted to *drive Cantrip from an editor*, ACP
Option C (cantrip-as-ACP-agent) is strictly the right path.

### 3.4 Architectural questions worth naming

The list mirrors ACP_RESEARCH §4.4, with pi-specific edges:

1. **Tool bridging.** No MCP. Either accept pi's built-ins only,
   or invest in TypeScript extensions. Bigger ask than ACP.
2. **Permission policy.** Map `extension_ui_request` to Cantrip
   hooks. Default-deny on unknown extensions to keep autonomous
   mode safe.
3. **Worktree isolation.** `pi --rpc` runs as a subprocess; cwd
   gives us file scoping but not process isolation. Phase 49's
   sandboxing work applies the same as for ACP.
4. **Telemetry.** Translate pi events into the Cantrip event bus
   so the TUI / session transcript stay coherent.
5. **Cancellation.** `abort` command on RPC + SIGTERM on the
   subprocess. pi documents `abort` semantics; verify before
   building.
6. **Race composition (pi-specific).** Investigate whether
   `fork`-based racing is genuinely cheaper than spawning two
   pi processes from scratch. If yes, this is pi's
   strongest-relative case.

## 4. pi vs ACP — head-to-head

| Axis                              | ACP                                       | pi.dev                                |
|-----------------------------------|-------------------------------------------|---------------------------------------|
| Cross-language transport          | JSON-RPC 2.0 stdio                        | JSONL over stdio + NDJSON event stream|
| Tool execution ownership          | Agent runs tools                          | Agent runs tools                      |
| Tool-bridging story for Cantrip   | MCP pass-through (native)                 | TypeScript extensions only            |
| Permission ceremony               | `session/request_permission` (per-tool)   | `extension_ui_request` (per-extension)|
| Session forking primitives        | None                                      | `fork`, `clone`, `switch_session`     |
| Client-side shell injection       | Permission-only                           | `bash` command injects results        |
| Cost calculation                  | Out of scope                              | Built-in via pi-ai                    |
| Auto-compaction / retry           | Agent-implementation-defined              | Protocol-level                        |
| Implementations / vendors         | ~20 agents, ~5 clients, registry          | Single project (Earendil Works)       |
| Distribution surface              | ACP Registry (live Jan 2026)              | npm + pi.dev/packages                 |
| Standardisation                   | Working group, stable methods enumerated  | Single-vendor versioning              |
| Pydantic-in-Cantrip pressure      | Yes (Python SDK is Pydantic)              | None (no Python SDK at all)           |

**Where pi wins:** session forking, client-side bash, built-in cost
calculation, auto-compaction at the protocol level, no Pydantic.

**Where ACP wins:** vendor neutrality, MCP-native tool bridging,
multi-agent ecosystem, registry distribution, formal stabilisation
process.

For Cantrip's "external coding agent as subagent backend" use
case, ACP's tool-bridging and vendor-neutrality wins outweigh pi's
nicer session primitives. Pi only pulls ahead if the race feature
specifically needs cheap forking and that becomes the load-bearing
requirement.

## 5. Verdict and recommended next steps

### 5.1 Feasibility summary

| Shape                              | Feasible? | Value | Effort | Recommend?       |
|------------------------------------|-----------|-------|--------|------------------|
| A — pi as `LLMProvider`            | yes       | ~zero | small  | no               |
| B — pi as subagent backend         | yes       | medium| big    | not over ACP     |
| C — Cantrip as pi provider/ext     | dubious   | low   | big    | no               |

### 5.2 Recommended trigger

Do not build speculatively. Revisit pi specifically when **all** of
these are true:

- We have already concluded that an external coding agent should
  back one of our subagents (i.e. ACP_RESEARCH §5.2 trigger has
  fired).
- The race feature (Phase 49) needs branching session state that
  ACP cannot provide cheaply.
- We are willing to accept single-vendor lock-in and a TypeScript
  extension surface for tool bridging.

If only the first is true, pick ACP. If only the second is true,
re-examine race-feature design before reaching for pi.

### 5.3 Cheap readiness steps

None required. Possible hygiene:

- Track the pi-ai package as a reference implementation for
  cross-provider cost calculation; if Cantrip's cost-tracking
  story (Phase 48-ish) ever needs an audit baseline, pi-ai is a
  decent reading.
- Watch `examples/extensions/sandbox/` and `subagent/` in the pi
  repo for technique-level inspiration on subprocess sandboxing
  and nested agent loops, even if we never integrate the runtime.
- Re-evaluate if pi adds MCP support — that single change would
  close the largest gap vs ACP.

## References

- pi.dev landing page: https://pi.dev
- pi documentation index: https://pi.dev/docs/latest
- pi RPC mode: https://pi.dev/docs/latest/rpc
- pi SDK: https://pi.dev/docs/latest/sdk
- pi JSON event stream: https://pi.dev/docs/latest/json
- pi custom providers: https://pi.dev/docs/latest/custom-provider
- pi GitHub monorepo: https://github.com/earendil-works/pi
- pi-coding-agent npm: https://www.npmjs.com/package/@earendil-works/pi-coding-agent
- Mario Zechner intro post: https://mariozechner.at/posts/2025-11-30-pi-coding-agent/
- Sibling note: `design/ACP_RESEARCH.md`
