# Pause-and-Edit Interrupt — Research Findings

> Output of Phase 83.  This is a research document, not a design.  It
> records the question (should Cantrip soften its hard-cancel
> interrupt into a pausable, editable mid-turn affordance?), the
> peer-survey evidence, the design sketch under Cantrip's specific
> loop shape, and the verdict.

## TL;DR

- **Cancel today is hard but already preserves more state than the
  phase prompt suggests.**  ``CancelledError`` unwinds out of
  ``CantripAgent.process_message`` (``agent/core.py:1721``), but
  every completed round's user / assistant / tool messages are
  already appended to ``state.messages`` and recorded via
  ``self._record_message`` *before* the next LLM call.  A
  cancellation between rounds loses only the in-flight LLM call's
  output, not the prior reasoning trace.
- **Peer survey (§2) puts Cantrip closest to Aider** — a tool-heavy
  request/response loop where Esc cancels and the user retypes.
  Claude Code, Cursor, and Amp ship richer mid-turn affordances
  (queue-next-instruction in Claude Code, mid-stream edit in
  Cursor) but those products run interactive *coding-chat*
  workflows where a turn lasts seconds and the user wants to steer
  continuously; Cantrip's turns last *minutes* (charmcraft pack,
  juju wait, Ralph loops) and the user typically watches.
- **The single largest source of asymmetry is tool subprocess
  lifetime.**  Pausing between rounds is cheap (just stop
  dispatching the next round); pausing *during* a 5-minute
  ``charmcraft pack`` is hard (the subprocess keeps running unless
  killed, which gives the same result as Esc — the in-flight tool
  is gone).  Pause-and-edit's *real* value lives at the LLM-call
  seam, not the tool-call seam.
- **Three flavours of "I want to interrupt"** that pause-and-edit
  partially addresses (§3.4): redirect ("stop and do X instead"),
  augment ("add this clarification"), abort-tool ("this tool is
  going to take 10 min, do something else first").  Of these,
  *augment* is the highest-value and the cheapest to ship as a
  smaller pattern — see the queue-next-instruction sketch in §4.2.
- **Verdict: defer the full pause-and-edit interrupt.**  Cantrip's
  cancel already preserves committed work, the highest-value
  flavour (*augment*) admits a leaner shape (queue-next-
  instruction), and no real user complaint has surfaced.  Open
  Phase 83b — *Queue-Next Instruction* — only when a concrete
  pain point arrives; if it does, the queue-next shape is the
  cheaper first step before any mid-turn-pause work.

The rest of this document walks the evidence.

## 1. Cantrip's current interrupt path

### 1.1 What unwinds, what survives

The TUI bindings (``tui/app.py:81-82``) bind both ``ctrl+c`` and
``escape`` to ``action_cancel_agent`` (line 1907), which calls
``worker.cancel()`` on the running ``agent_response`` worker and
flips the status bar to ``"⏹ Cancelling..."``.  The Web UI's
``cancel_request`` payload (``web/server.py:608-612``) routes the
same ``asyncio.Task.cancel()`` to the wrapping
``_process_chat_turn`` task.

In both cases ``CancelledError`` propagates up through
``CantripAgent.process_message`` → ``_process_message_inner`` →
``_run_conversation_loop``.  What's already in ``state.messages``
when the exception fires:

- The user message of the cancelled turn (appended at line 1774).
- Every completed round's assistant + tool messages (appended at
  1805-1806 and 1901-1902 inside the ``while response.tool_calls``
  loop).

What's *not* there:

- The in-flight LLM call's response — ``_complete_with_retry``
  was awaiting it when the cancel arrived.
- Any partial reasoning / streaming output buffered inside the
  provider client.
- A ``final_msg`` for the turn (line 1955) — the loop never
  reaches it.

So a turn cancelled three rounds in retains the first two rounds
fully and loses only the third's LLM response.  Subsequent turns
see the same conversation history the model would have seen if
that third round had simply ended early.

### 1.2 What costs the user typing

The user re-types the redirection from scratch — there's no
queued / draft / prepended affordance.  The redirection becomes
the next ``USER`` message and the model picks up from where the
prior partial round left off in the recorded history.

What the user *does* lose: any context-dependent phrasing of the
original ask that they don't want to retype verbatim.  E.g. "fix
this charm bug" → cancel halfway → retype "fix this charm bug
*but skip the integration tests*" reproduces the original ask
with one addendum.  The verbatim retype is the friction.

### 1.3 What the executor does

``CantripAgent.process_message`` pauses the background executor
(``self._pause_executor()`` at line 1731) for the duration of the
turn, with a ``finally`` block resuming it (line 1735).  Cancel
hits the ``finally`` cleanly — the executor is never left paused.

This matters because some peers don't have an executor concept
and their cancel is purely about the chat loop.  Cantrip's cancel
already coexists with autonomous background work without
deadlock.

## 2. Peer survey

### 2.1 Claude Code

- **Cancel:** ``Esc`` cancels the in-flight turn.
- **Mid-turn input:** typing in the input box while a turn is
  running queues the message; it folds into the *next* user
  turn after the current one finishes.  Effectively a queue-
  next-instruction pattern.
- **Edit prior message:** up-arrow in the input recalls the last
  message; editing and resending creates a new branch from that
  point (the on-disk session log records both).
- **State preserved on cancel:** rounds completed before the
  cancel land in the session.

The "queue while running" pattern is the closest match to what
this phase frames as pause-and-edit.  It is *not* a mid-turn
pause — it's an asynchronous append that runs at the next
natural seam.

### 2.2 Cursor

- **Cancel:** the chat panel's *Stop* button cancels the current
  generation.
- **Partial preservation:** the partial assistant message stays
  visible and editable; the user can re-prompt from it or
  branch.
- **Edit-and-rerun:** any prior user message in the chat is
  click-to-edit, which re-runs from that point (the rest of the
  chat downstream is dropped).
- **Resume:** no formal resume — the partial generation is
  treated as a finished-but-short turn.

Cursor's pattern works because its turns are short (seconds, not
minutes) and rendering the partial message is cheap.  Cantrip
doesn't have a "partial assistant message visible mid-stream"
state today — streaming is via ``process_message_streaming`` but
the UI renders an in-progress thinking indicator, not a building
text block.

### 2.3 Aider

- **Cancel:** ``Ctrl+C`` interrupts the in-flight LLM call.
- **State preserved on cancel:** any *applied* file edits stay
  on disk (Aider applies as it goes, against the user's git
  index); the in-flight response is lost.
- **No queue-next:** the input loop is line-based, blocked on
  the LLM call.
- **Pause-and-edit:** none.

Aider is the closest peer to Cantrip in interrupt model: hard
cancel, partial state preserved on disk and in conversation
history, retype to redirect.

### 2.4 Goose

- **Cancel:** ``Ctrl+C`` cancels the agent.
- **Mid-turn input:** none documented; the REPL is line-based.
- **Resume:** Goose persists session state and supports `/resume`
  but that's session-level, not turn-level.

### 2.5 Amp

- **Cancel:** ``Esc``.
- **Mid-turn input:** ``$$ <command>`` shell mode is *separate*
  from agent input — it runs synchronously without consuming
  tokens (this is what Phase 69.3 plans to copy).  Not a
  pause-and-edit mechanism.
- **Steering:** Amp's "interrupt and edit" affordance is a
  re-prompt rather than a true pause; the in-flight turn is
  cancelled and the new prompt starts fresh.

### 2.6 Summary table

| Tool | Cancel | Queue-next-instruction | Mid-turn pause | Edit prior message |
|---|---|---|---|---|
| Cantrip | Esc / Ctrl+C → hard cancel | None | None | None |
| Claude Code | Esc → hard cancel | **Yes** (typing while running) | None | Up-arrow recall + branch |
| Cursor | Stop button → hard cancel + preserve partial | None | None | Click-edit + re-run |
| Aider | Ctrl+C → hard cancel | None | None | None |
| Goose | Ctrl+C → hard cancel | None | None | None |
| Amp | Esc → hard cancel | None | None | None |

The only peer that ships a mid-turn affordance Cantrip doesn't
have is Claude Code's queue-next-instruction pattern.  No peer
ships true pause-and-edit (a paused turn that resumes with
modified context).

## 3. What "pause-and-edit" would mean for Cantrip

### 3.1 The resumable unit

The conversation loop has three natural seams:

1. **Between user-msg and first LLM call** — too early; the
   user hasn't seen anything yet.
2. **Between LLM-response and tool dispatch** — clean pause
   point.  The model has produced a tool plan, the user has
   seen it, the tools haven't run yet.
3. **Between tool result and next LLM call** — clean pause
   point.  Tools just finished, the model is about to react.

Pausing *during* an LLM call (mid-stream) requires the provider
client to support partial-buffer-keep semantics; Cantrip's current
``_complete_with_retry`` doesn't, and adding it varies per
provider.

Pausing *during* a tool call requires either killing the
subprocess (= same as cancel) or letting it complete and pausing
at the seam after — the latter only saves typing if the user
*also* wants the tool's output.

The product is therefore "pause at the next seam, not now."

### 3.2 TUI affordance options

| Option | Pro | Con |
|---|---|---|
| (a) ``Esc`` chord — first ``Esc`` pauses, second cancels | No new keybind | Surprises every user who relies on Esc-cancels-now today; Phase 65 already audited Esc behaviour for modals |
| (b) ``Ctrl+P`` for pause | No collision (Ctrl+L is ``clear_chat`` per Phase 67.2 deferral; Ctrl+X is reserved for Phase 69.3 shell mode) | New keybind to learn |
| (c) On-screen "Pause" button next to the thinking indicator | Discoverable | Mouse-y; the TUI is keyboard-first |
| (d) Use the existing input bar — typing while running enqueues | Matches Claude Code; zero new keys; visible affordance (the typed text) | Not a *pause* — runs at the next seam |

Option (d) is the queue-next-instruction shape.  The other three
add a new pause concept; (d) reuses the input bar that's already
there and gives the user something to do during a long turn
without learning a new key.

### 3.3 Message-flow shapes

When the paused turn resumes after a user edit, the model sees
*something* extra in the next request.  Three shapes:

| Shape | What the model sees | Effect |
|---|---|---|
| (1) Prepended next user turn | Existing history + new ``USER`` message with redirection | Model treats it as ordinary back-and-forth; cleanest |
| (2) Synthetic system note | Existing history + ``SYSTEM`` "user redirected: X" | Less natural; provider rules around mid-conversation system messages vary |
| (3) Replace in-flight context | Existing history minus the latest assistant turn + appended user redirection | Equivalent to "edit the last message" — different feature |

Shape (1) is the only one that doesn't require novel
provider-side semantics.  It's also exactly what Claude Code's
queue-next-instruction does.

### 3.4 The three "I want to interrupt" flavours

| Flavour | What the user wants | Today's path | Pause-and-edit answer | Queue-next answer |
|---|---|---|---|---|
| Redirect | "Stop and do X instead" | Esc, retype "do X instead" | Pause, type X, resume — model sees X as redirect | Queue X as next user turn — model sees both old work + X |
| Augment | "Add this clarification" | Esc, retype original + clarification | Pause, type clarification, resume — model continues with the addendum | Queue clarification — model continues at next seam with the addendum |
| Abort-tool | "This tool is wasting time, do something else" | Esc, retype | Doesn't help — the tool is already running | Doesn't help |

Pause-and-edit's wins over queue-next:
- *Faster* redirect — the user sees the model's plan, decides
  to redirect, and the model never runs the planned tool.
- *Surgical* edit — the user can change the in-flight context
  before any more compute fires.

Queue-next's wins over pause-and-edit:
- *Lower implementation cost* — no new keybind, no provider
  client changes, no message-flow ambiguity.
- *Composable* — the queued message folds into the next round
  whether the model paused or not.

The augment flavour is the most common pattern in long Cantrip
sessions (charm builds with "oh and also handle the case
where…").  The redirect flavour is rare because the user is
typically watching the agent run autonomous tasks and reacts to
*outcomes*, not in-flight plans.

## 4. Implementation cost sketch

### 4.1 Full pause-and-edit

Estimated work to ship:

- Agent loop seam: a ``self._pause_event`` checked at the seams
  in §3.1; the ``while response.tool_calls`` loop awaits it
  before dispatching the next round.  ~40 lines in
  ``agent/core.py``.
- TUI: new ``Ctrl+P`` binding, ``action_pause_agent``, a
  ``"Paused — type a redirection"`` status state, ``Enter``
  resume / second-``Ctrl+P`` cancel.  ~80 lines in
  ``tui/app.py`` plus a screen variation.
- Web UI: ``pause_request`` / ``resume_request`` WS message
  shapes, the matching client-side button state, the message
  composer that builds the resumed prompt.  ~120 lines across
  ``web/server.py`` and the front-end.
- Event bus: ``TURN_PAUSED`` / ``TURN_RESUMED`` events for the
  shared event-bus contract (``design/UI.md``).
- Tests: pause→edit→resume preserves history; pause→cancel is
  equivalent to today's cancel; pause-during-tool resolves at
  the next seam not immediately; paused-state-persistence-on-
  reload behaviour decided.
- Docs: ``docs/docs/explanation-tui-screens.html`` and
  ``docs/docs/reference-cli.html`` plus an entry in ``UI.md``.

Conservative range: 400-600 LOC + tests, 2-3 days of work, 1-2
days of integration polish across TUI / Web parity.

### 4.2 Queue-next-instruction (the smaller alternative)

Estimated work to ship:

- TUI: while the agent worker is running, ``Enter`` in the input
  bar appends the typed text to a *queued* list (visible as a
  ``"Queued: <preview>"`` line above the thinking indicator)
  rather than starting a new turn.  At the natural seam (start
  of next ``process_message`` call), the queue is drained into
  the user message.  ~60 lines in ``tui/app.py``.
- Web UI: same shape — chat input accepts text while
  ``thinking: true``, broadcasts a ``queue_input`` event, the
  WS server appends to the queue.  ~50 lines in
  ``web/server.py`` + small front-end change.
- Agent: ``CantripAgent`` grows a ``_pending_user_input: list[str]``
  attribute; ``process_message`` prepends drained queue
  contents (newline-joined) to the user message before the
  first LLM call.  ~20 lines.
- Tests: queue persists across turns when not drained; queue
  drains in order; cancel does not lose the queue.
- Docs: a paragraph in ``docs/docs/explanation-tui-screens.html``
  + the help shortcut catalogue.

Conservative range: 130-180 LOC + tests, half a day to a day of
work.

The smaller shape pays for itself if the *augment* flavour shows
up regularly.

## 5. Verdict

**Defer the full pause-and-edit interrupt.**

Reasons, in order of weight:

1. **Cancel already preserves committed work.**  The phase
   prompt's "agent forgets what it was doing past the last
   persisted event" is partly true — the in-flight LLM call's
   response is lost — but every completed round survives.  The
   real loss is one round and the verbatim user prompt.
2. **No real user complaint.**  The phase opened on the
   observation that Claude Code has a fuller interrupt; nothing
   in the Cantrip transcripts surveyed showed a user pining for
   pause-and-edit.
3. **The cheaper shape is queue-next-instruction.**  Of the
   three interrupt flavours (§3.4), *augment* is the most
   common in charm sessions and is fully served by queue-next.
   *Redirect* is rarer and *abort-tool* isn't addressed by
   either pattern.
4. **Charm work is tool-heavy and outcome-driven.**  Long Ralph
   loops, ``charmcraft pack`` minutes, ``juju wait`` polls — the
   user typically watches outcomes (tests pass / fail) and
   reacts at *those* gates, not mid-LLM-call.  The product
   shape pause-and-edit was built for (interactive coding chat
   with seconds-long turns) doesn't match.

What does **not** land in this phase:

- No ``Ctrl+P`` keybind.
- No ``self._pause_event`` in the agent loop.
- No ``pause_request`` / ``resume_request`` WS shapes.
- No documentation of pause-and-edit in ``docs/docs/``.

What lands:

- This document (``design/PAUSE_AND_EDIT.md``).
- Reference link in ``AGENTS.md`` so future contributors find
  the analysis before re-litigating the question.
- Phase 83 marked ✓ in ``ROADMAP.md`` with the verdict and the
  revisit triggers for Phase 83b.

## 6. Revisit triggers

Open Phase 83b — *Queue-Next Instruction* — when **any** of the
following fire:

1. **Repeated augment-flavour friction.**  A user reports
   verbatim-retyping the original ask plus a clarification
   after Esc more than once in a transcript audit, or names it
   as a pain point.  This is the highest-probability trigger.
2. **Long-Ralph-loop steering.**  Phase 69.1's bounded Ralph
   loop runs unattended for many iterations; if a user wants
   to *steer* an in-flight Ralph loop without aborting it, the
   queue-next pattern is the natural seam (next iteration
   reads the queued text).
3. **Web-UI accessibility request.**  The Phase 60 WCAG audit
   flagged keyboard-only navigation; if the Stop+retype flow
   surfaces as an accessibility blocker for low-vision users,
   queue-next is more accessible than a chord keybind.

Open Phase 83c — *Full pause-and-edit* — only after Phase 83b
ships and **either**:

4. Queue-next demonstrably doesn't cover the *redirect* flavour
   in real sessions (users keep cancelling rather than
   queueing because they don't want the tool to run at all).
5. A peer ships a clearly better pattern worth copying — e.g.
   Cursor-style mid-stream edit becomes standard across the
   coding-agent ecosystem.

When 1-3 fire, the implementation phase opens with §4.2's
sketch as the deliverable scope and the message-flow shape (1)
from §3.3 as the architecture.  When 4 or 5 fire, the design
note revisits §3.1's seam choice and §3.2's keybind options
with whatever new evidence the trigger surfaced.

## 7. What this phase is *not*

- **Not a commitment to ship pause-and-edit or queue-next.**
  Both are deferred against named triggers; either may stay
  deferred indefinitely.
- **Not a rework of the existing cancel path.**  Esc / Ctrl+C
  / the Web *Cancel* button stay as hard cancel.
- **Not a redesign of session resume / undo / branch.**  Those
  are separate surfaces (Phase 67.1 session tree, Phase 68.1
  snapshot undo) with their own contracts; mid-turn pause is
  a third axis.
- **Not an edit-prior-message story.**  Cantrip doesn't ship
  click-to-edit-history.  That's a different feature; this
  doc neither pre-empts nor scopes it.
