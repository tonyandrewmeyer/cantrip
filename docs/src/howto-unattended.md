---
title: "How to run Cantrip unattended — Cantrip"
description: "Use --yolo or /yolo to auto-approve every ask prompt so CI scripts never stall — deny rules still block."
h1: "Run Cantrip unattended"
subtitle: "Auto-approve every <em>ask</em> permission so CI scripts don't stall &mdash; with <code>deny</code> rules still enforced."
section: howto
breadcrumb_label: "Run Cantrip unattended"
see_also:
  - label: "CLI reference"
    href: "reference-cli.html"
  - label: "Tool permissions"
    href: "howto-permissions.html"
---

<h2 id="when-to-use">When to use it</h2>

<p>"Yolo" mode exists for one job: a non-interactive run where
stopping on a prompt means a hung build. Typical uses:</p>

<ul>
  <li><strong>CI charm-build jobs.</strong> The runner deploys a
charm, waits for active/idle, and exits &mdash; nobody is
watching for prompts.</li>
  <li><strong>Nightly regression sweeps.</strong> You want the
agent to iterate on a workload overnight without parking on
the first <code>git push</code> prompt.</li>
  <li><strong>Scripted demos.</strong> The flow has already been
reviewed once; subsequent replays should be frictionless.</li>
</ul>

<p>If you're working interactively, stay out of yolo mode. The
<em>ask</em> tier exists for a reason &mdash; you'll notice
moments where you want the prompt.</p>

<h2 id="how-to-enable">How to enable it</h2>

<p>Three ways in, one way out:</p>

<pre><code><span class="prompt">$</span> cantrip run --yolo /path/to/charm   # or ``-y``
<span class="prompt">$</span> cantrip run /path/to/charm
<span class="prompt">&gt;</span> /yolo on
<span class="prompt">&gt;</span> /yolo off</code></pre>

<p>Bare <code>/yolo</code> toggles; <code>/yolo on</code> and
<code>/yolo off</code> are unambiguous forms for scripts.
Anything else (<code>/yolo maybe</code>, <code>/yolo yes</code>)
is rejected with a usage line.</p>

<h2 id="what-changes">What changes under yolo</h2>

<p>Only the <em>ask</em> tier of the
<a href="howto-permissions.html">permission policy</a>
flips.  Concretely:</p>

<ul>
  <li>Every call whose ruleset lookup resolves to <code>ask</code>
auto-approves, with no CONFIRM task and no user prompt.</li>
  <li>Every call that resolves to <code>deny</code> still returns
a refused <code>ToolResult</code> with the matched-rule
message. Yolo does <em>not</em> escalate denies.</li>
  <li>Every auto-approval publishes a
<code>permission_auto_approved</code> event so the transcript
captures the rule that would otherwise have prompted &mdash;
audit trails stay honest.</li>
</ul>

<p>Plan mode, hooks, and the subprocess sandbox are unaffected.
Yolo layers on top of permissions, not around them.</p>

<h2 id="safety">The escape hatch matters</h2>

<p>Before you ship a CI script with <code>--yolo</code>, audit
<code>.cantrip/permissions.yaml</code> for the commands the run
will need. A call that you think is an <em>ask</em> today may
become a <em>deny</em> tomorrow when a built-in default tightens
&mdash; the run will fail loudly rather than silently skipping,
which is deliberate. Treat yolo as a convenience for known-good
flows, not as a blanket "trust everything" switch.</p>

<p>Two patterns work well:</p>

<ul>
  <li>Start in interactive mode, run the workload, and convert any
<em>ask</em> prompts you actually approve into explicit
<code>allow</code> rules in the repo's
<code>permissions.yaml</code>.  Then the CI run doesn't need
yolo at all &mdash; the policy itself is the contract.</li>
  <li>When you do need yolo, tighten
<code>bash: "rm -rf *"</code> and similar to <code>deny</code>
so a drift in the agent's plan can't do real damage. The
built-in defaults cover the obvious cases already.</li>
</ul>

<h2 id="status-indicator">Status indicator</h2>

<p>While yolo is on the TUI status bar tints via a
<code>-yolo-mode</code> CSS class backed by
<code>$error-darken-1</code> and renders a prominent
"YOLO MODE &mdash; confirmations off" badge. Every surface that
subscribes to <code>STATUS_BAR_CHANGED</code> with a
<code>mode</code> field sees the same signal, so the Web and CLI
UIs can render their own banner.</p>

<h2 id="reference">Related references</h2>

<ul>
  <li><a href="howto-permissions.html">Configure tool permissions</a>
&mdash; write <code>allow</code> / <code>ask</code> /
<code>deny</code> rules that yolo respects.</li>
  <li><a href="howto-plan-mode.html">Use plan mode</a> &mdash; the
complementary "tighten" switch. Plan mode and yolo are
mutually exclusive in spirit; enabling both is possible but
unusual (plan's narrow allow-list wins).</li>
  <li><a href="reference-cli.html#run">cantrip run</a> &mdash;
full list of flags on the <code>run</code> subcommand.</li>
</ul>
