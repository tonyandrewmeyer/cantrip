# Framework Evaluation — Build vs. Adopt

**Date:** 2026-04-05
**Phase:** 18 (Agent Framework Evaluation)
**Author:** Cantrip development team

## Executive Summary

After evaluating eight agent frameworks against Cantrip's architecture, we
recommend **staying with the bespoke approach** with two targeted adoptions:

1. **Claude Agent SDK** for a potential future migration path — its subagent model
   is the closest match to Cantrip's architecture, but it is Claude-only and would
   eliminate multi-provider support (Gemini, local inference snaps).
2. **Pydantic AI** as a hybrid option — adopt its structured output parsing and
   tool schema generation, but keep our own orchestration.

The core finding is that Cantrip's two-loop architecture (conversation + autonomous
work queue) is unlike anything the frameworks provide.  Every framework assumes a
single conversation loop or a DAG of tasks; none have the concept of a persistent
work queue with dependency tracking, concurrent subagents, noop detection, and
graceful shutdown that Cantrip has built in Phases 4–21.

---

## 1. Landscape Survey

### 1.1 Candidates Evaluated

| Framework | Version | Stars | Licence | Async | Multi-LLM | Multi-Agent |
|-----------|---------|-------|---------|-------|-----------|-------------|
| **Claude Agent SDK** | 0.1.48 | — | Commercial | Yes | Claude only* | Yes (subagents) |
| **LangGraph** | 0.3.x | 8k+ | MIT | Yes | Yes (LangChain) | Yes (graph nodes) |
| **CrewAI** | 0.108+ | 46k+ | MIT | Yes (kickoff_async) | Yes (LiteLLM) | Yes (crews/flows) |
| **OpenAI Agents SDK** | 0.0.x | 18k+ | MIT | Yes | OpenAI only | Yes (handoffs) |
| **AutoGen / MS Agent Framework** | 1.0 | 40k+ | MIT | Yes (event-driven) | Yes | Yes (conversations) |
| **Pydantic AI** | 0.1.x | 10k+ | MIT | Yes | Yes (multi-provider) | Yes (delegation) |
| **smolagents** | 1.x | 26k+ | Apache-2.0 | Partial | Yes (LiteLLM) | Yes (multi-agent) |
| **DSPy** | 2.6+ | 22k+ | MIT | Limited | Yes | No (pipelines, not agents) |

\* Claude Agent SDK supports Claude via direct API, Bedrock, Vertex AI, and Azure — but only Claude models.

### 1.2 Early Disqualifications

| Framework | Reason | Impact |
|-----------|--------|--------|
| **OpenAI Agents SDK** | Locked to OpenAI models. Cantrip uses Gemini, Claude, and local inference snaps. | Fatal — multi-provider is a core requirement. |
| **DSPy** | Pipeline optimisation framework, not an agent orchestrator. No tool-calling loop, no multi-agent. | Wrong category entirely. |
| **smolagents** | Code-first execution model (agents write Python that runs). Cantrip uses structured tool calls. Partial async. | Architectural mismatch — would require rewriting all 40+ tools as executable code snippets. |
| **AutoGen / MS Agent Framework** | Heavy .NET lineage. Python SDK is young (v1.0 March 2026). Conversation-centric model doesn't map to work queues. Enterprise-oriented with middleware/telemetry layers Cantrip doesn't need. | Excessive complexity for our use case. |

### 1.3 Shortlisted Candidates

Three frameworks survived for detailed mapping:

1. **Claude Agent SDK** — closest subagent model, but single-provider.
2. **LangGraph** — most flexible orchestration, but heaviest abstraction cost.
3. **Pydantic AI** — lightest touch, best Python ergonomics, multi-provider.

**CrewAI** was borderline — its role-based model is elegant for "team of agents"
patterns, but Cantrip's subagents are task-scoped (one task, one subagent, one
category) rather than role-scoped.  The crew/task/agent model would require
restructuring how we think about work decomposition.  Kept as honourable mention.

---

## 2. Architecture Mapping

### 2.1 Cantrip's Core Components

| Component | Implementation | Lines | Key Characteristics |
|-----------|---------------|-------|-------------------|
| **Conversation loop** | `agent/core.py` | ~700 | User ↔ LLM ↔ tool calls, streaming, context compaction |
| **Work queue** | `agent/queue.py` | ~240 | AgentTask with status, deps, categories, model hints |
| **Background executor** | `agent/executor.py` | ~770 | Concurrent subagents, route() state machine, noop detection |
| **Subagent runner** | `agent/subagent.py` | ~500 | Isolated LLM context, category-scoped tools, exit contracts |
| **Tool system** | `agent/tools/` | ~6000 | 40+ tools, Tool ABC, JSON Schema params, async execute() |
| **LLM providers** | `llm/` | ~800 | Abstract interface, Gemini + Claude + inference snaps |
| **State persistence** | `agent/store.py` | ~400 | SQLite session store, tasks, messages, events, usage |
| **Routing** | `agent/routing.py` | ~210 | Pure route() function, WorkQueueState, deadlock-free |
| **Service protocols** | `agent/services.py` | ~100 | GitService, StateService, EnvironmentChecker, FollowupPlanner |
| **Watcher** | `agent/watcher.py` | ~600 | Status diffing, Loki polling, databag diffing, offer tracking |
| **Task planner** | `agent/planner.py` | ~400 | LLM decomposes intent into dependency-linked tasks |
| **TUI** | `tui/` | ~1500 | Textual app, status widget, task checklist, chat, screens |

### 2.2 Claude Agent SDK Mapping

| Cantrip Component | SDK Equivalent | Fit |
|-------------------|---------------|-----|
| Conversation loop | `query()` agent loop | **Good** — same pattern (prompt → tool calls → repeat) |
| Tool system | Built-in tools + custom tools | **Good** — SDK has Read/Write/Edit/Bash/Grep/Glob built-in |
| Subagent runner | `Agent` tool with `AgentDefinition` | **Good** — SDK supports subagents with scoped tools |
| Work queue | None | **No mapping** — SDK has no persistent task queue concept |
| Background executor | None | **No mapping** — SDK runs one query at a time, no concurrent background work |
| LLM providers | Claude only | **Blocker** — no Gemini, no inference snaps |
| State persistence | Sessions (resume by ID) | **Partial** — session resume exists, but no SQLite control |
| Routing | None | **No mapping** — SDK doesn't expose scheduling decisions |
| Watcher | None | **No mapping** — no event-driven model monitoring |
| Task planner | None | **No mapping** — no built-in task decomposition |
| TUI | None | **No mapping** — SDK is headless |

**Verdict:** The SDK is an excellent match for the *inner loop* (conversation + tool
calls + subagents) but has zero support for the *outer loop* (work queue, executor,
routing, planner, watcher) that makes Cantrip autonomous.  Adopting it would mean
rewriting 60%+ of the codebase while gaining little — Cantrip's inner loop already
works well.  The single-provider limitation is the fatal flaw.

### 2.3 LangGraph Mapping

| Cantrip Component | LangGraph Equivalent | Fit |
|-------------------|---------------------|-----|
| Conversation loop | Graph with tool-calling node | **Good** — standard LangGraph pattern |
| Tool system | LangChain tools / ToolNode | **Awkward** — would need to wrap all 40+ tools in LangChain format |
| Subagent runner | Sub-graph invocation | **OK** — sub-graphs can model subagents |
| Work queue | State with task list | **Partial** — state is just a TypedDict, not a queue with scheduling |
| Background executor | Concurrent node execution | **Partial** — LangGraph supports parallel branches but not open-ended concurrency |
| LLM providers | LangChain model registry | **Good** — supports all providers Cantrip uses |
| State persistence | Checkpointing | **Good** — robust, built-in |
| Routing | Conditional edges | **Partial** — graph edges model routing, but not a pure function |
| Watcher | None | **No mapping** — no event-driven external monitoring |
| Task planner | None | **No mapping** — manual graph construction |
| TUI | None | **No mapping** — headless |

**Verdict:** LangGraph is the most flexible option but requires the heaviest
buy-in.  Every tool would need a LangChain wrapper.  The graph model is powerful
for DAGs but awkward for Cantrip's open-ended work queue where tasks are
dynamically generated by the planner and dependencies form at runtime.  The
abstraction tax is significant: LangChain's model registry, tool protocol, message
types, and configuration system all have opinions that conflict with Cantrip's
deliberately simple stdlib-based approach.

### 2.4 Pydantic AI Mapping

| Cantrip Component | Pydantic AI Equivalent | Fit |
|-------------------|-----------------------|-----|
| Conversation loop | `agent.run()` | **Good** — clean async agent loop |
| Tool system | `@agent.tool` decorator | **Good** — auto schema from type hints |
| Subagent runner | Agent delegation via tools | **OK** — agents can call other agents |
| Work queue | None | **No mapping** |
| Background executor | None | **No mapping** |
| LLM providers | Multi-provider (OpenAI, Anthropic, Gemini, Ollama) | **Good** |
| State persistence | None built-in | **No mapping** — BYO persistence |
| Routing | Graph support (new) | **Partial** — type-hint-driven graphs |
| Watcher | None | **No mapping** |
| Task planner | None | **No mapping** |
| TUI | None | **No mapping** |

**Verdict:** Pydantic AI is the lightest-touch option.  It would replace only the
innermost conversation/tool loop while leaving everything else intact.  The type-safe
tool definitions via decorators are genuinely better than Cantrip's manual JSON Schema.
Multi-provider support is strong.  But it offers almost nothing for the orchestration
layer that makes Cantrip distinctive.

---

## 3. Spike Assessment

Rather than building a full spike (which would take days for minimal signal), we
performed a *desk spike* — a detailed code comparison of how Cantrip's key patterns
would look in each framework.

### 3.1 Conversation Loop (Inner Loop)

All three shortlisted frameworks handle this well.  The relevant comparison:

**Cantrip today (~50 lines in core.py):**
```python
while True:
    response = await provider.complete(messages, tools=tool_descriptors)
    if not response.tool_calls:
        break
    for tc in response.tool_calls:
        result = await execute_tool(tc, tools)
        messages.append(tool_result_message(tc, result))
```

**Claude Agent SDK (~3 lines):**
```python
async for message in query(prompt=user_input, options=options):
    handle(message)
```

**Pydantic AI (~3 lines):**
```python
result = await agent.run(user_input, deps=deps)
```

The frameworks save ~50 lines but Cantrip's loop is well-tested, handles streaming,
context compaction, and integrates with the watcher.  Replacing it would require
re-implementing all integration points.

### 3.2 Work Queue + Executor (Outer Loop)

**No framework has an equivalent.**  This is Cantrip's most distinctive architecture:

- Dynamic task generation by the LLM planner
- Dependency-linked tasks with status tracking
- Concurrent subagent execution with semaphore-based throttling
- Pure `route()` function for scheduling decisions (Phase 21.1)
- Noop detection and escalation (Phase 21.3)
- Git snapshot/revert on failure (Phase 11.4)
- Protocol-based service injection for testability (Phase 21.2)
- Follow-up task creation (autodeploy, acceptance testing)

Adopting any framework would mean either:
- Abandoning this architecture (losing autonomy), or
- Building it on top of the framework (same code, more dependencies)

### 3.3 Tool System

Cantrip has 40+ tools with domain-specific logic (Juju, Charmcraft, Rockcraft,
git, web search, observability, acceptance testing, operational readiness).

| Aspect | Cantrip | Claude Agent SDK | Pydantic AI | LangGraph |
|--------|---------|-----------------|-------------|-----------|
| Tool definition | Tool ABC, JSON Schema | Custom tool functions | @agent.tool decorator | LangChain BaseTool |
| Schema | Manual dict | Auto from function sig | Auto from type hints | Manual or auto |
| Async | Yes | Yes | Yes | Yes |
| Error handling | ToolResult.error | Exception → tool error | Exception → retry | Varies |
| Migration effort | N/A | Low (thin wrapper) | Low (decorator) | Medium (LangChain format) |

Pydantic AI's decorator approach is the most Pythonic and would reduce boilerplate
for new tools.  But migrating 40+ existing tools for a cosmetic improvement is not
justified.

### 3.4 Overhead Estimate

| Framework | New dependencies | Migration effort | Ongoing abstraction tax |
|-----------|-----------------|-----------------|------------------------|
| Claude Agent SDK | claude-agent-sdk | 2-3 weeks (inner loop only) | Low, but Claude-locked |
| LangGraph | langchain-core, langgraph, langchain-anthropic, langchain-google-genai | 4-6 weeks | High (LangChain ecosystem) |
| Pydantic AI | pydantic-ai | 1-2 weeks (tool system only) | Low |

---

## 4. Gap and Gain Analysis

### 4.1 What We Would Gain

| Framework | Gain | Value to Cantrip |
|-----------|------|-----------------|
| Claude Agent SDK | Built-in file/bash/grep tools, MCP support, session management | **Low** — Cantrip already has all these |
| LangGraph | Checkpointing, conditional branching, LangSmith tracing | **Medium** — checkpointing is nice but we have SQLite |
| Pydantic AI | Type-safe tool schemas, structured output parsing, multi-provider | **Medium** — tool schemas would reduce boilerplate |
| Any framework | Community, bug fixes, upstream improvements | **Low** — Cantrip's agent infra is domain-specific |

### 4.2 What We Would Lose

| Concern | Impact |
|---------|--------|
| **Multi-provider support** (Claude SDK) | Fatal — eliminates Gemini and inference snaps |
| **Direct prompt control** | Medium — frameworks abstract away system prompts |
| **Work queue architecture** | High — no framework supports it; we'd build it anyway |
| **Testability** (Phase 21.2 protocols) | Medium — framework internals are harder to fake |
| **Simplicity** | Medium — stdlib dataclasses → framework-specific types |
| **Juju domain tools** | Low — tools would need wrapping regardless |
| **TUI integration** | Low — frameworks are headless; TUI stays bespoke |

---

## 5. Recommendation

### Primary: Stay Bespoke

Cantrip's architecture is purpose-built for charm development with a two-loop
design that no framework replicates.  The autonomous work queue, concurrent
subagents, noop detection, pure routing state machine, and protocol-based service
injection are all unique to Cantrip and would need to be rebuilt on top of any
framework.  The migration cost exceeds the benefit.

**What we're giving up:** Community-maintained tool calling, upstream bug fixes,
potential future framework innovations (e.g., better memory systems, RAG
integration).  We accept this because Cantrip's domain is narrow (charm
development) and the agent infrastructure is now well-hardened (Phase 21).

### Hybrid: Selective Adoption

Two components are worth borrowing without full framework adoption:

1. **Pydantic AI's tool schema generation** — the `@agent.tool` decorator
   pattern that auto-generates JSON Schema from type hints is cleaner than
   our manual schema dicts.  We could adopt this pattern (not the library)
   by adding a `@tool` decorator to our `Tool` base class that introspects
   type hints.  Estimated effort: 1 day.  No new dependency.

2. **Claude Agent SDK awareness** — if Cantrip ever drops multi-provider
   support (i.e., Claude becomes the only supported model), the Agent SDK
   would be a natural migration target.  Its subagent model, session
   management, and built-in tools map well to Cantrip's inner loop.  We
   should keep the Agent SDK on our radar and revisit this evaluation if
   the provider landscape changes.

### Not Recommended

- **Full LangGraph adoption** — too heavy, too opinionated, LangChain ecosystem
  lock-in.
- **CrewAI adoption** — role-based model doesn't match task-scoped subagents.
- **Any framework for the outer loop** — none support persistent work queues
  with dynamic task generation.

---

## 6. Trade-Off Summary

| Dimension | Stay Bespoke | Adopt Framework |
|-----------|-------------|-----------------|
| **Control** | Full control over prompts, tools, scheduling | Reduced — framework has opinions |
| **Maintenance** | ~3000 lines of agent infra to maintain | Trade for framework dependency management |
| **Velocity** | Slower for generic features, faster for domain-specific | Faster for generic, slower for Juju-specific |
| **Lock-in** | None — stdlib Python | Framework-specific types, patterns, upgrade cycles |
| **Migration cost** | N/A | 2-6 weeks depending on framework, for partial benefit |
| **Testability** | Excellent (Phase 21.2 protocols, fake services) | Variable — framework internals are opaque |

---

## 7. Decision

**We stay bespoke.**  The bespoke agent infrastructure is Cantrip's competitive
advantage, not its technical debt.  The two-loop architecture, work queue, and
domain-specific tooling are what make Cantrip an autonomous charm builder rather
than a chatbot with tools.  No framework provides these primitives, so adopting
one would add complexity without reducing it.

We will revisit this decision if:

- A framework emerges that supports persistent work queues with concurrent agents.
- Cantrip drops multi-provider support (making Claude Agent SDK viable).
- The agent infrastructure becomes a maintenance burden (>25% of development time).

---

## Appendix: Sources

- [Claude Agent SDK overview](https://platform.claude.com/docs/en/agent-sdk/overview)
- [Claude Agent SDK Python](https://github.com/anthropics/claude-agent-sdk-python)
- [LangGraph documentation](https://www.langchain.com/langgraph)
- [CrewAI documentation](https://docs.crewai.com/)
- [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)
- [Pydantic AI documentation](https://ai.pydantic.dev/)
- [Pydantic AI multi-agent patterns](https://ai.pydantic.dev/multi-agent-applications/)
- [AutoGen / Microsoft Agent Framework](https://microsoft.github.io/autogen/stable/)
- [smolagents](https://huggingface.co/docs/smolagents/en/index)
- [Best Multi-Agent Frameworks in 2026](https://gurusup.com/blog/best-multi-agent-frameworks-2026)
