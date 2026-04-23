# Agent Client Protocol (ACP) — Research Findings

> Output of Phase 39.  This is a research document, not a design.  It
> records what ACP is, how it maps onto Cantrip's existing
> abstractions, which shapes of integration are feasible, and when (if
> ever) any of them would be worth building.

## TL;DR

- **ACP is LSP-for-coding-agents.**  A JSON-RPC protocol
  ([spec](https://agentclientprotocol.com/)) that lets an *editor*
  (client) drive an *agent* (server subprocess) over stdio.  Zed,
  JetBrains, Neovim/CodeCompanion ship ACP clients; Claude Code,
  Gemini CLI, Codex CLI, Goose, Cline, Cursor, GitHub Copilot, and
  ~20 others ship ACP agents.
- **The pivotal finding: ACP agents execute their own tools.**  The
  client only brokers *permission* via `session/request_permission`
  and *optionally* provides file-system / terminal capabilities for
  the agent to call back into.  This breaks the naive "implement
  `LLMProvider` by delegating to an ACP agent" shape we sketched in
  §39.3 — the LLMProvider contract is "return tool calls for Cantrip
  to execute", but an ACP agent will have already executed them.
- **Three viable integration shapes, only one interesting**:
  1. **A. ACP-as-`LLMProvider`** — possible, but requires stripping
     the agent's tools to nothing, which defeats the purpose.  Not
     recommended.
  2. **B. ACP-as-subagent-backend** — replace a specific subagent's
     internal LLM loop with an ACP session.  The agent's tools run
     remote, Cantrip's tools stay local, Cantrip's planner/work-queue
     stays in charge.  Most promising shape; still a significant
     build.
  3. **C. Cantrip-as-ACP-agent** — expose Cantrip's charm-building
     expertise as an ACP agent that Zed/JetBrains users can drive.
     Different project; out of Phase 39 scope; worth naming so it
     isn't confused with A or B.
- **Verdict: interesting, not urgent.**  Nothing in ACP is broken; the
  Python SDK exists (async, Pydantic-based) and the ACP Registry
  gives distribution.  But every integration shape answers a
  hypothetical ("what if Claude Code's tool suite helped the
  *implement* subagent?") rather than a lived pain point.  **Defer
  to a follow-on phase, gated on a concrete trigger** — e.g. the
  *implement* or *debug* subagent consistently underperforms on
  real charms, or a Cantrip user asks to drive us from Zed.  Do
  not build speculatively.

The rest of this document walks through the evidence behind those
bullets.

## 1. What ACP is (Phase 39.1)

### 1.1 Goal and positioning

ACP ([agentclientprotocol.com](https://agentclientprotocol.com/))
standardises the communication between *code editors* and *coding
agents*.  It is explicitly framed as "LSP for AI coding agents" by
Zed, who authored it and continues to drive the working group.  The
protocol assumes the user lives in their editor and calls an agent
to do specific tasks — it does **not** try to be a general
inter-agent mesh.

The split is fixed:

| Role     | Examples                                              |
|----------|-------------------------------------------------------|
| Client   | Zed, JetBrains, Neovim (via CodeCompanion)            |
| Agent    | Claude Code, Gemini CLI, Codex CLI, Goose, Cline, …   |

A client *starts* the conversation.  The agent *does the work*.
Nothing in the protocol contemplates an agent talking to another
agent directly — an ACP-agent-of-agents would have to run a client
internally.

### 1.2 Transport

Two deployment shapes:

- **Local (stable).**  Client spawns the agent as a subprocess;
  JSON-RPC 2.0 frames over stdio.  This is how every current
  integration works.
- **Remote (WIP).**  HTTP or WebSocket.  Explicitly called out on
  the landing page as "a work in progress" — Anthropic and Zed are
  "collaborating with agentic platforms" to nail down the cloud
  shape.  Not safe to build against yet.

JSON-RPC 2.0 semantics apply: methods return a result or error,
notifications do not.  Each side owns its own ID space — client
IDs for client-initiated requests, agent IDs for agent-initiated
ones — so reply correlation is unambiguous.

### 1.3 Message model

Baseline methods (client → agent unless noted):

| Method                       | Dir | Purpose                                               |
|------------------------------|-----|-------------------------------------------------------|
| `initialize`                 | C→A | Version + capability handshake                        |
| `authenticate`               | C→A | Optional, if the agent requires credentials           |
| `session/new`                | C→A | Create a new conversation session                     |
| `session/load`               | C→A | Resume an existing session (capability-gated)         |
| `session/set_mode`           | C→A | Switch the agent's operating mode (capability-gated)  |
| `session/prompt`             | C→A | Send a user prompt; response carries a `stopReason`   |
| `session/cancel` *(notif.)*  | C→A | Abort an in-flight turn                               |
| `session/update` *(notif.)*  | A→C | Stream progress — chunks, tool calls, plans           |
| `session/request_permission` | A→C | Ask the user to approve/deny a tool call              |

Capability-gated callbacks (A→C, all optional):

- `fs/read_text_file`, `fs/write_text_file` — agent asks client to
  read/write files.  **Absolute paths only**, **1-based** line
  numbers.
- `terminal/create`, `terminal/output`, `terminal/release`,
  `terminal/wait_for_exit`, `terminal/kill` — interactive and
  background terminals hosted by the client.

### 1.4 The prompt turn

A turn is a single `session/prompt` request followed by a response
with a `stopReason`.  Between them the agent emits zero or more
`session/update` notifications whose `sessionUpdate` discriminator
takes one of:

| Update kind          | Payload                                                         |
|----------------------|-----------------------------------------------------------------|
| `agent_message_chunk`| Incremental assistant text/content block                        |
| `tool_call`          | Tool invocation declared (`toolCallId`, `title`, `kind`, `status`) |
| `tool_call_update`   | Status/content change for an existing tool call                 |
| `plan`               | Structured TODO list with `content` / `priority` / `status`     |

`stopReason` enum values on the turn response:

- `end_turn` — the model finished without needing more tools.
- `max_tokens` — response budget exceeded.
- `max_turn_requests` — too many model calls in one turn.
- `refusal` — agent refused to continue.
- `cancelled` — client cancelled.  The agent **MUST** translate any
  underlying exception into this stop reason rather than
  propagating; the client must not interpret a cancel as an error.

There is no "ask the user a question mid-turn" mechanism.  Every
user exchange is a fresh `session/prompt`.  Likewise, there is no
documented "thinking" channel distinct from `agent_message_chunk` —
reasoning either surfaces as prose or not at all.

### 1.5 Tool calls (the pivotal section)

This is the part that reshapes Phase 39.3.

- **The agent runs its own tools.**  When the model wants to call
  a tool, the agent executes it internally and streams
  `tool_call` / `tool_call_update` notifications with `status`
  progressing `pending → in_progress → completed | failed`.
- **The client brokers *permission*, not *execution*.**  The
  agent sends `session/request_permission` with `toolCall` and an
  `options` array; the client replies with
  `{"outcome": "selected", "optionId": …}` or
  `{"outcome": "cancelled"}`.
- **Optional capability-backed tools** (fs / terminals) run in the
  *client's* address space — but those are a fixed menu the
  *agent* reaches into, not a generic tool-execution protocol.

ACP defines structured wrappers for tool results: `{"type":
"content", …}`, `{"type": "diff", "path", "oldText", "newText"}`,
`{"type": "terminal", "terminalId"}`, plus freeform `rawInput` /
`rawOutput` fields.

### 1.6 Relationship to MCP

ACP and MCP are complementary.  A client can hand a set of MCP
server endpoints and credentials to the agent during
`session/new`; the agent then invokes those MCP tools from inside
its own model loop.  ACP's schema re-uses MCP JSON shapes where
practical.  Nothing in ACP *requires* MCP, but the two together
give the agent access to both "editor-side capabilities" (fs /
terminals via ACP) and "user-defined services" (databases / cloud
APIs via MCP).

### 1.7 Stable vs moving parts

Recent stabilisations announced on
[agentclientprotocol.com/announcements](https://agentclientprotocol.com/announcements/):

- `session/close` — stabilised
- `session/list` — stabilised
- `session/resume` — stabilised
- `session_config_options` — stabilised
- `session_info_update` — stabilised

A transports working group is separately iterating on the remote
(non-stdio) shape.  Stdio + local subprocess is the only
well-supported transport today.

## 2. Mapping to Cantrip (Phase 39.1 cont.)

Cantrip's integration-relevant abstractions live in four files:

| Concept             | Location                                        |
|---------------------|-------------------------------------------------|
| `LLMProvider`       | `src/cantrip/llm/base.py:152`                   |
| `AgentTask`, `WorkQueue` | `src/cantrip/agent/queue.py:42`, `:80`     |
| `BackgroundExecutor`| `src/cantrip/agent/executor.py:301`             |
| `Subagent`          | `src/cantrip/agent/subagent.py:720`             |
| Conversation loop   | `src/cantrip/agent/core.py:716`                 |

### 2.1 `LLMProvider` shape

Five methods, all owned by Cantrip:

```python
class LLMProvider(ABC):
    name: str
    context_window_tokens: int
    supports_vision: bool
    max_tools: int | None

    async def complete(self, messages, tools, temperature, max_tokens,
                       thinking_budget) -> Response: ...
    async def stream(self, messages, tools, …) -> AsyncIterator[Chunk]: ...
    def count_tokens(self, messages) -> int: ...
    async def count_tokens_accurate(self, messages) -> int: ...
```

`Response.tool_calls` is a list of `ToolCall` objects that the
caller — either the conversation loop or a subagent — is expected
to execute and then feed back on the next `complete()` call.

The important property: **the LLM provider is tool-*aware* but not
tool-*executing*.**  It receives schemas, returns calls, and stops.
Cantrip owns the registry, the execution, the veto hooks
(Phase 46.4a), and the result formatting.

### 2.2 Subagent dispatcher

A subagent is an isolated LLM context spawned per `AgentTask`:
category-filtered tool allowlist, task-specific system prompt,
limited max rounds (8 default, 12 for BUILD).  It re-uses the
same `LLMProvider` instances as the conversation loop but builds
its own message list from scratch.

Subagent exit states (`SubagentResult.exit_state`):

- `COMPLETED` — work done, queue transitions task to `DONE`
- `BLOCKED`  — needs user input, queue parks the task
- `FAILED`   — error, queue marks task `FAILED`
- `NOOP`     — the goal was already satisfied

### 2.3 The gap

ACP's turn is analogous to one `Subagent._run_iteration()` loop —
model round, tool calls, repeat — but at a much higher level of
abstraction.  Lining up the two:

| ACP concept                   | Cantrip analogue                                  |
|-------------------------------|---------------------------------------------------|
| Session                       | Per-subagent message list + tool inventory        |
| Prompt turn                   | A `Subagent.run()` call (one task end-to-end)     |
| `session/update: plan`        | No direct analogue (WorkQueue is global, not per-turn) |
| `session/update: tool_call`   | `ToolCall` in `Response`                          |
| `session/update: tool_call_update` | Internal log events during execution         |
| `session/update: agent_message_chunk` | `stream()` chunks                          |
| `session/request_permission`  | *no analogue* — Cantrip tools don't ask, they run |
| `fs/read_text_file`           | `read_file` tool                                  |
| `terminal/*`                  | `run_shell` tool + telemetry                      |
| `stopReason`                  | `SubagentExitState`                               |

The largest mismatches:

- **Tool execution ownership.**  ACP agent runs tools; Cantrip
  provider returns tool calls for Cantrip to run.  Inverted.
- **Permission model.**  ACP assumes an interactive human at the
  other end; Cantrip's autonomous loop rarely wants to block on
  user approval, and its permission story lives in hooks (Phase 46)
  rather than per-tool prompts.
- **Plan ownership.**  Both sides have a plan object, but
  Cantrip's `WorkQueue` is global across tasks while ACP's `plan`
  update is per-turn.  Nothing inherently clashes, but they can't
  trivially share state.

## 3. Candidate agents (Phase 39.2)

### 3.1 Claude Code via `claude-agent-acp`

Repository: https://github.com/zed-industries/claude-agent-acp
(Apache-licensed, TypeScript, Zed-maintained).

What it does: implements an ACP agent by wrapping the **Claude
Agent SDK**, not by shelling out to the Claude Code CLI.  So an
ACP client gets a fully-featured Anthropic agent — streaming,
tool use with permission prompts, @-mentions, image support, TODO
lists, terminals, client-side MCP servers, slash commands, edit
review — driven through ACP messages.

For Cantrip's evaluation: this is the single most useful agent to
wrap, because its tool suite (Bash, Edit, Read, Write, Grep,
TodoWrite, Task subagents, etc.) overlaps ~70% with what Cantrip's
*implement* and *debug* subagents already try to do, and it's
actively maintained by Zed + Anthropic.

Authentication: Claude API key (or Claude Code CLI's cached
session credentials, depending on how the SDK is initialised).

### 3.2 Other first-party agents

Named on Zed's site and the ACP "Agents" page:

| Agent        | Origin    | Relevance to Cantrip                              |
|--------------|-----------|---------------------------------------------------|
| Gemini CLI   | Google    | Cantrip already has a Gemini provider — overlap   |
| Codex CLI    | OpenAI    | Potential new-provider path, separate project     |
| GitHub Copilot | GitHub  | Commercial, auth-gated                            |
| Goose        | Square    | See also Phase 73 — recipes / MCP apps pattern    |

Goose is the interesting one: Phase 73 of the Cantrip roadmap
already calls out Goose-inspired workflow packaging.  If that
phase lands, an ACP bridge to Goose itself becomes a natural
experiment.

### 3.3 Community agents + registry

Cline, OpenCode, OpenHands, Cursor, Augment Code, Blackbox AI,
AgentPool, AutoDev, Tidewave, aizen, DeepChat, and others.  The
**ACP Agent Registry** went live January 2026 (per the JetBrains
announcement) and auto-updates agents installed from it.  That
gives any future Cantrip ACP bridge a zero-effort distribution
story *if* we publish Cantrip as an agent (Option C below).

### 3.4 Python SDK status

Package: `agent-client-protocol` on PyPI.  Async base classes,
Pydantic models, repo at
`github.com/agentclientprotocol/python-sdk`.  Examples directory
has agent, client, and dual-agent demos.

**Friction point for Cantrip:** the SDK is Pydantic-based and
Cantrip's CLAUDE.md forbids Pydantic in favour of stdlib
dataclasses.  Two honest ways to handle that:

- *Scoped dependency.*  Treat the SDK as a transport-layer
  adapter and confine Pydantic imports to one module (e.g.
  `src/cantrip/llm/acp.py` or `src/cantrip/acp/client.py`).
  Convert to Cantrip dataclasses at the boundary.  Acceptable per
  precedent — we already accept third-party Pydantic via MCP
  SDK.
- *Hand-roll JSON-RPC.*  Write our own frames against the ACP
  schema (`api-reference/openapi.json` is published).  Avoids
  Pydantic entirely but doubles the maintenance footprint and
  puts us off the upgrade path.

The scoped-dependency answer is almost certainly right if we ever
ship an ACP integration.  Flagged here so we don't discover it
three days into the build.

## 4. Integration sketches (Phase 39.3)

### 4.1 Option A — ACP-as-`LLMProvider`

The original 39.3 sketch.  An `ACPProvider(LLMProvider)` class
that implements `complete()` by opening an ACP session, sending a
`session/prompt`, and returning the accumulated response text as
a `Response`.

Why it doesn't work well:

- The ACP agent has its own tool inventory and will call tools
  *inside* the session.  `LLMProvider.complete()` needs to return
  `tool_calls` for Cantrip to execute.  Once the remote agent has
  already executed tools, those calls are results, not requests.
- To force the ACP agent to act as a pure text engine you'd have
  to answer every `session/request_permission` with "denied",
  reject all `fs/*` and `terminal/*` callbacks, and refuse any
  MCP server pass-through.  You end up with a very expensive
  pure-text completion.
- Cantrip's tool allowlist, prompt layering, skills, hooks, and
  race feature all still live in Cantrip — *nothing* interesting
  is offloaded.

Viable only as a curiosity demo.  Not recommended.

### 4.2 Option B — ACP-as-subagent-backend *(most promising)*

Instead of replacing `LLMProvider`, replace the *subagent loop*
for specific task categories.

```text
AgentTask (e.g. category=IMPLEMENT, description="scaffold …")
    │
    ▼
BackgroundExecutor picks task
    │
    ▼
ACPSubagent                           # new class, sibling of Subagent
    │
    ├── opens ACP session via python-sdk
    ├── passes task description as session/prompt
    ├── streams session/update → SubagentEvent bus
    ├── answers session/request_permission via hook system
    ├── forwards fs/* and terminal/* into the agent's worktree
    ├── waits for stopReason
    └── returns SubagentResult(exit_state = …)
```

What that buys us:

- Claude Code's tool suite runs on a charm task, end to end,
  inside Cantrip's worktree sandbox.
- Cantrip's planner (`AgentTask`, `WorkQueue`, dependencies,
  race, hooks) stays in charge of *what* to do.
- Existing local subagents (category-filtered, provider-specific)
  continue to handle other tasks unchanged — we route by
  `task.category` or `task.model_hint`.

What it costs:

- A real engineering project: ACP client, capability callbacks,
  permission bridging, event translation, worktree integration.
  Probably a full phase on its own (~a Phase-47-sized effort).
- Tool duality: Cantrip's tools (registered in `tools/base.py`)
  don't show up inside the ACP session.  So for ACP-driven tasks
  we lose charm-specific niceties (`jubilant_deploy`,
  `charmcraft_pack`, `run_scenario_test`, …) unless we re-expose
  them as MCP servers that the ACP agent can invoke.  MCP
  bridging is the natural path and ACP explicitly supports it,
  but it's another moving part.
- Race feature (Phase 49) doesn't compose cleanly — how do you
  race an ACP subagent against a local one?  Probably you don't,
  you let ACP-backed tasks opt out of racing.
- Cost model changes.  Claude Code via ACP is billed to the user's
  Anthropic account; Cantrip's provider router has a single
  budget dial today (Phase 48.6-ish) that would need extending.

**This is the shape that answers "what if someone else's agent is
better at X than our subagent?" without forcing Cantrip to become
a dumb wrapper.**

### 4.3 Option C — Cantrip-as-ACP-agent

The inverse: wrap Cantrip *itself* so an ACP client (Zed,
JetBrains, Neovim) can drive it.  The user types a charm prompt
in their editor; the editor opens an ACP session against
`cantrip --acp-agent`; Cantrip runs its planner + subagents as
usual and streams `session/update` back.

What it buys:

- Distribution.  Any ACP client user can pick up Cantrip from the
  Registry and use it in their preferred editor.
- Keeps Cantrip's stack intact — no Pydantic coupling, no tool
  duality, no race re-architecture.

What it costs:

- An ACP *server* implementation — new transport, new session
  lifecycle code, new permission UI (since ACP expects the user
  to be in an editor, not in Cantrip's TUI).
- Feature overlap with the existing TUI/Web UIs becomes a product
  question: do we deprecate them?  Keep all three?
- The target user is subtly different: "someone who already lives
  in Zed" vs "someone who wants to hand a charm goal to an
  autonomous system".  Unclear these overlap strongly.

This is a credible direction but it's a *different project from
Phase 39's framing* and would need its own phase and design doc.
Flagged so we don't confuse it with A or B.

### 4.4 Architectural questions worth naming

Any integration attempt (especially Option B) has to answer:

1. **Tool bridging.**  Do we expose Cantrip's charm tools as an MCP
   server so the ACP agent can call them, or do we accept that
   ACP-backed subagents only see the remote agent's built-ins?
2. **Permission policy.**  How does Cantrip's hook system
   (Phase 46) interact with `session/request_permission`?  The
   natural answer: each permission request runs through
   `pre_tool` hooks; approve if no hook vetoes.  Needs care
   around autonomous mode vs interactive mode.
3. **Worktree isolation.**  The ACP agent runs in a process; where
   does its working directory sit?  Presumably the task-allocated
   worktree — which means `fs/*` callbacks need to bind that
   directory, and `terminal/*` needs the same sandbox.  Phase 49's
   subprocess-sandboxing work is directly relevant.
4. **Telemetry.**  Cantrip's observability (`explanation-observability.html`,
   hook-stats in Phase 46.5) expects structured events.  ACP
   `session/update` streams will need translation into Cantrip's
   event bus so they appear in the TUI and session transcript
   alongside local subagent output.
5. **Cancellation.**  Cantrip's executor can cancel a task;
   translate to `session/cancel` and handle the `cancelled`
   stopReason cleanly.

## 5. Verdict and recommended next steps (Phase 39.4)

### 5.1 Feasibility summary

| Shape                         | Feasible? | Value | Effort | Recommend? |
|-------------------------------|-----------|-------|--------|------------|
| A — ACP as `LLMProvider`      | yes       | low   | small  | no         |
| B — ACP as subagent backend   | yes       | high  | big    | **later**  |
| C — Cantrip as ACP agent      | yes       | medium | big   | separate project |

### 5.2 Recommended trigger

Do not build speculatively.  Revisit Option B when **any one** of
these is true:

- A real Cantrip user asks for it (they want to drive Claude Code
  inside Cantrip's workflow).
- The *implement* or *debug* subagent evaluation scores (Phase 7
  test reports, Phase 5 research metrics) are consistently below
  expectations on real charm tasks and we believe a
  tool-heavier agent would close the gap.
- The ACP remote transport stabilises and we want to put
  Cantrip's planner in front of a farm of heterogeneous agents.

Revisit Option C when a non-trivial number of users ask to drive
Cantrip from an editor.

### 5.3 Cheap readiness steps we could take now

None are required, but each is small and non-committal:

- Add a `design/ACP_RESEARCH.md` entry to the references section
  of `CLAUDE.md` so future contributors find this write-up.
- Tag `src/cantrip/llm/base.py:LLMProvider` with a comment noting
  that tool execution stays in Cantrip — guards against future
  rewrites that inadvertently close off Option B.
- Keep an eye on the ACP Python SDK's 1.0 release; re-audit
  Pydantic-containment once it stabilises.

None of those count as "starting implementation" — they are just
hygiene.

## References

- ACP site: [agentclientprotocol.com](https://agentclientprotocol.com/)
- Protocol overview: https://agentclientprotocol.com/protocol/overview
- Prompt turn: https://agentclientprotocol.com/protocol/prompt-turn
- Tool calls: https://agentclientprotocol.com/protocol/tool-calls
- Python SDK: https://agentclientprotocol.com/libraries/python
  (GitHub: https://github.com/agentclientprotocol/python-sdk)
- Claude Agent ACP adapter: https://github.com/zed-industries/claude-agent-acp
- ACP Registry announcement:
  https://blog.jetbrains.com/ai/2026/01/acp-agent-registry/
- Zed's ACP page: https://zed.dev/acp

## Phase milestones mapped

- **39.1** — Protocol familiarisation.  §1 of this document
  (message model, turn flow, tool semantics, MCP crossover).  §2
  (mapping to Cantrip's abstractions, the gap).
- **39.2** — Candidate agents.  §3 (Claude Code adapter,
  first-party agents, registry, Python SDK status and Pydantic
  friction).
- **39.3** — Integration sketch.  §4 (three options evaluated,
  with Option B as the serious candidate).  §4.4 lists the
  architectural questions any future attempt must answer.
- **39.4** — Decision and write-up.  §5 (verdict, trigger, cheap
  readiness steps).
