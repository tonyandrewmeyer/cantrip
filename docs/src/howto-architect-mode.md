---
title: "How to use architect mode — Cantrip"
description: "Split each agent turn into a propose-then-edit pair: a strong architect model designs the change, a cheap editor model emits the tool calls."
h1: "Use architect mode"
subtitle: "Spend on thinking once per turn, edit on a cheap model."
section: howto
breadcrumb_label: "Use architect mode"
see_also:
  - label: "CLI reference"
    href: "reference-cli.html"
  - label: "Light models"
    href: "howto-light-models.html"
  - label: "Multi-model patterns"
    href: "explanation-race.html"
---

<h2 id="when-to-use">When to use it</h2>

<p>Architect mode is the right fit when an architecture call has to
happen but the actual edits are mechanical. Three concrete
moments:</p>

<ul>
  <li><strong>Long BUILD sessions.</strong> The agent will spend a
lot of tool calls on file edits whose intent is already
clear. Splitting each turn into <em>propose</em> on the
expensive model and <em>edit</em> on a cheap one cuts the
bill without sacrificing the design call.</li>
  <li><strong>Diff-shaped refactors.</strong> Rename a class,
extract a helper, swap an event handler &mdash; the architect
explains where, the editor applies it.</li>
  <li><strong>Tight per-edit loops.</strong> Combined with
<a href="howto-ralph.html">Ralph Loop</a> and
<code>--print</code>, every iteration runs the architect
once and the editor as many times as the diff needs.</li>
</ul>

<h2 id="how-to-use">How to use it</h2>

<pre><code><span class="prompt">&gt;</span> /architect
**Architect mode on.**  Architect: `claude/claude-opus-4-7` &mdash;
Editor: `claude/claude-haiku-4-5-20251001`.  Each turn now runs as
*propose &rarr; edit*; both passes appear separately in `/cost`.

<span class="prompt">&gt;</span> Add ops-tracing to src/charm.py.

... agent's response is the editor's edits, not the architect
prose &mdash; the architect proposal is captured in the
transcript ...

<span class="prompt">&gt;</span> /cost
| Provider/Model                      | Requests | Prompt | Completion |
|-------------------------------------|----------|--------|------------|
| claude/claude-opus-4-7              | 1        | 2,400  | 410        |
| claude/claude-haiku-4-5-20251001    | 1        | 2,820  | 180        |

<span class="prompt">&gt;</span> /architect off
**Architect mode off.**  Single-model conversation resumed.</code></pre>

<p>Override the editor with a second token in the slash command:</p>

<pre><code><span class="prompt">&gt;</span> /architect on gemini/gemini-3-flash-preview
<span class="prompt">&gt;</span> /architect on gemini             # provider only; uses the default model
<span class="prompt">&gt;</span> /architect on claude/claude-haiku-4-5-20251001</code></pre>

<p>At session start, the same options live on the CLI:</p>

<pre><code>$ cantrip run --architect .
$ cantrip run --architect --editor-provider claude --editor-model claude-haiku-4-5-20251001 .
$ cantrip run --print --ralph 5 --architect "add ops-tracing to this charm"</code></pre>

<h2 id="how-it-works">How it works</h2>

<p>When architect mode is on, every LLM call inside the
conversation loop runs as two passes:</p>

<ol>
  <li><strong>Architect pass.</strong> The main provider runs
<em>without tools</em>. A short SYSTEM instruction asks for a
plain-prose proposal &mdash; which file(s), what to change,
why. The architect <em>cannot</em> emit tool calls because
it doesn't have any.</li>
  <li><strong>Editor pass.</strong> The editor provider runs
with the full tool list. The architect's proposal is
appended as a synthetic USER message wrapped in
<code>&lt;architect_proposal&gt; ... &lt;/architect_proposal&gt;</code>.
The editor's job is to translate the proposal into the
concrete <code>write_file</code> / <code>edit_file</code> /
<code>multi_edit</code> calls.</li>
</ol>

<p>Both passes write to the session's
<code>token_usage</code> table with their own provider/model
attribution, so <code>/cost</code> shows two rows per turn
&mdash; the architect's expensive prompt + the editor's smaller
one. Both passes also fire transcript events
(<code>architect_pass</code> / <code>editor_pass</code>) so
auditors can replay the design call when reviewing what the
agent did.</p>

<h2 id="editor-resolution">Picking the editor</h2>

<p>Three resolution rules apply, top-to-bottom:</p>

<ol>
  <li><strong>Per-session override.</strong> When you set
<code>state.editor_provider</code> via
<code>/architect on &lt;provider&gt;[/&lt;model&gt;]</code> or
<code>--editor-provider</code> /
<code>--editor-model</code>, the editor is constructed on
demand from those values. A bad combination logs at WARNING
and falls through to the next rule.</li>
  <li><strong>The session's light provider.</strong> When you
started Cantrip with a configured light provider (see
<a href="howto-light-models.html">light models</a>), that
provider acts as the editor. This is the recommended
cheap-and-cheerful default.</li>
  <li><strong>Fallback to the main provider.</strong> When no
lighter variant exists, the editor runs on the architect's
provider. The dual-pass shape stays &mdash; you still get
the proposal-then-edit transcript &mdash; but there is no
cost saving.</li>
</ol>

<h2 id="fall-through">Fall-through after editor failures</h2>

<p>A weak editor can stall when the architect's proposal is
ambiguous. Cantrip tracks a per-turn counter
(<code>state.architect_consecutive_failures</code>) that ticks
every time an editor pass produces only failed tool calls and
resets on a successful round. When the counter reaches
<code>state.architect_failure_threshold</code> (default 2) the
<em>next</em> editor pass uses the architect provider as the
editor &mdash; the same model that wrote the proposal applies
it. Counter resets on the next user turn so a single sticky
problem doesn't escalate every subsequent round.</p>

<h2 id="status-indicator">Status indicator</h2>

<p>Every surface that shows a status bar repaints when architect
mode toggles. The TUI tints with the same
<code>STATUS_BAR_CHANGED</code> event the
<a href="howto-plan-mode.html">plan-mode</a> and
<a href="howto-unattended.html">yolo-mode</a> indicators use, so
a Web or CLI surface that already listens picks up the new
mode without extra wiring.</p>

<h2 id="interaction-with-other-guards">Interaction with other guards</h2>

<ul>
  <li><strong>Plan mode.</strong> The architect pass still
respects the plan-mode tool allow-list because the editor
is the one that picks up tools. Plan mode + architect mode
composes &mdash; the architect proposes, the editor's tool
calls hit the plan-mode gate just like any other tool call
would.</li>
  <li><strong>Permissions.</strong> The editor runs through the
<a href="howto-permissions.html">permission stack</a>
exactly like a single-model session. <code>deny</code>
rules block, <code>ask</code> rules park (or auto-approve
under <code>--yolo</code>).</li>
  <li><strong>Hooks.</strong> Pre-tool hooks fire on
the editor's tool calls, not the architect's prose &mdash;
the architect doesn't emit any.</li>
  <li><strong>/undo.</strong> Snapshots are taken at the
user-turn boundary, so <code>/undo</code> rolls back the
whole turn (architect proposal + editor edits) atomically.</li>
  <li><strong>Streaming.</strong> Architect mode runs the
dual-pass turn synchronously and yields the editor's
response as a single chunk. You lose token-by-token
streaming inside an architect-mode session in exchange for
the dual-pass cost split.</li>
</ul>

<h2 id="what-it-is-not">What architect mode is <em>not</em></h2>

<ul>
  <li>Not a multi-provider router. Picking and ranking across
many models is what
<a href="explanation-race.html">multi-model patterns</a>
(race, arena, oracle) cover. Architect mode is the simple
<em>two-model</em> case.</li>
  <li>Not a chain-of-thought wrapper. The architect's proposal
is recorded in the transcript but the editor sees only the
proposal text &mdash; no hidden reasoning trace.</li>
  <li>Not a quality gate. A weak editor that emits unapplyable
edits still emits unapplyable edits; the fall-through path
catches the obvious case but bad models stay bad.</li>
  <li>Not persistent. The mode is session-scoped. Restarting
Cantrip drops the flag back off.</li>
</ul>
