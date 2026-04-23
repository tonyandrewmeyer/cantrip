---
title: "How Cantrip works — Cantrip"
description: "The two-loop architecture, work queue, subagents, and autonomous operation in Cantrip."
h1: "How Cantrip works"
subtitle: "Understanding the architecture helps you use Cantrip more effectively and interpret its behaviour when things go wrong."
section: explanation
breadcrumb_label: "How Cantrip works"
on_this_page:
  - { anchor: "two-loops", label: "Two concurrent loops" }
  - { anchor: "work-queue", label: "The work queue" }
  - { anchor: "subagents", label: "Subagents" }
  - { anchor: "context", label: "Context management" }
  - { anchor: "sessions", label: "Session persistence" }
---

{#two-loops}
## Two concurrent loops

Most AI coding tools operate as chatbots: you send a message, the
tool responds, you send another. Cantrip is different. It runs two
loops concurrently:

- **The conversation loop** handles your messages. When
  you type something, the agent processes it, may call tools, and
  responds. This is the familiar chat pattern.
- **The autonomous work loop** picks tasks from a work
  queue and executes them in the background without waiting for your
  input. It runs concurrently with the conversation loop.

This means the agent keeps working while you are reading its output,
thinking, or not interacting at all. You steer; the agent drives.

### Why two loops?

Building a charm involves many steps that do not require human input:
reading documentation, scaffolding files, running tests, diagnosing
failures. Waiting for the user between each step would waste time.
The two-loop design lets the agent be autonomous where it can and
interactive where it must (design confirmation, domain questions,
steering).

{#work-queue}
## The work queue

The work queue is the coordination layer between the two loops. It
holds **AgentTask** objects, each with:

- **Status** — pending, active, done, failed, or
  blocked.
- **Category** — research, build, deploy, test,
  debug, infrastructure, or confirm.
- **Dependencies** — tasks that must complete
  before this one can start.

The executor picks the next ready task (one whose dependencies are
all satisfied), spawns a subagent to handle it, and records the
result. When a task completes, it unblocks any tasks that depend on
it.

Tasks are created by the **planner**, which uses the LLM
to decompose a high-level intent ("build a Redis charm") into
concrete tasks with dependencies. The user's conversation loop can
also create tasks — for example, when you say "add backup
support", the agent plans new tasks and adds them to the queue.

### Concurrency

By default, up to three subagents run concurrently
(`--concurrency` flag). This means the agent can research
documentation while scaffolding files while running tests, as long
as there are no dependency conflicts.

{#subagents}
## Subagents

Each background task runs in a **subagent** — an
isolated LLM conversation with its own context and a focused set
of tools. Subagents are important for two reasons:

1. **Context isolation.** A research subagent reading
   hundreds of lines of documentation does not pollute the main
   conversation's context window. The subagent summarises its findings
   into a compact result.
2. **Focused tools.** A research subagent does not need
   Juju deployment tools. A deploy subagent does not need web search.
   Limiting the tool set reduces confusion and cost.

Subagents have a limited number of rounds (typically 8–12 tool
calls) and category-specific timeouts. If a subagent exceeds its
budget, it is terminated and the task is marked as failed, which can
trigger a retry or diagnostic task.

### Cost routing

Tasks are routed to different models based on their category.
Research and log analysis go to the light model (cheaper, faster).
Code generation and design go to the primary model (more capable).
See [Configure light models](howto-light-models.html).

{#context}
## Context management

Long sessions accumulate a lot of context: conversation messages,
tool results, research findings. Cantrip manages this in two ways:

- **Context compaction** — when the conversation
  approaches the model's context window limit, older messages are
  summarised into a compact form by the LLM. Recent messages are
  preserved verbatim.
- **Virtual files** — large bodies of text (code
  files, documentation pages, research summaries) are stored in a
  virtual file store and referenced by name. The agent can read
  them on demand without keeping them in the active context.

{#sessions}
## Session persistence

All state is saved to a `.cantrip` SQLite file in the
charm directory. This includes conversation history, task queue,
design decisions, and token usage metrics. If Cantrip crashes or
you stop it, you can resume by running `cantrip` in the
same directory. The agent picks up where it left off, with the work
queue intact.

See also:

- [The three charm paths](explanation-charm-paths.html)
- [Observability and debugging](explanation-observability.html)
- [Agent tools](reference-tools.html)
