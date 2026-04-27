---
title: "How to branch a session — Cantrip"
description: "Fork a Cantrip session at any prior turn — explore alternatives, recover from a bad steering message, compare paths — without losing the work that came before."
h1: "Branch a session"
subtitle: "Fork at any prior turn so dead ends stay reachable, alternative paths run side by side, and a misdirected steering message no longer means losing the work it sat on top of."
section: howto
breadcrumb_label: "Branch a session"
see_also:
  - label: "Undo agent changes"
    href: "howto-undo.html"
  - label: "CLI reference &mdash; branch and tree"
    href: "reference-cli.html#branching"
  - label: "Export transcripts"
    href: "howto-export.html"
---

<h2 id="overview">/undo deletes, /branch rewinds</h2>

<p>
  Cantrip stores the conversation as a tree, not a flat list.
  Every assistant turn carries the id of the turn it replied to,
  and the active session is just &ldquo;which leaf is currently
  live.&rdquo;
</p>

<p>
  <a href="howto-undo.html"><code>/undo</code></a> walks back by
  <em>removing</em> rows: the messages disappear from history and
  the working tree restores from the snapshot before that turn.
  Use it when the last turn was wrong and you want the alternate
  reality where it never happened.
</p>

<p>
  <code>/branch</code> walks back without removing anything: the
  session pointer moves to a prior turn, but every turn that
  hung off the old leaf is still in the SQLite store and stays
  reachable. Use it when the last turn might have been wrong
  <em>or</em> might be salvageable, and you want both options
  available later.
</p>

<h2 id="quick">Quick reference</h2>

<table>
  <thead>
    <tr><th>Command</th><th>What it does</th></tr>
  </thead>
  <tbody>
    <tr>
      <td><code>/branch</code></td>
      <td>Fork before the most recent user turn. The typical recovery from a bad steering message.</td>
    </tr>
    <tr>
      <td><code>/branch &lt;turn-id&gt;</code></td>
      <td>Move the active head to a specific turn.  The turn id comes from <code>/tree</code>.</td>
    </tr>
    <tr>
      <td><code>/tree</code></td>
      <td>Render every turn in the session as an indented tree, with an asterisk on the active branch.  In the TUI this is an interactive picker; in the CLI it prints to chat.</td>
    </tr>
    <tr>
      <td><code>cantrip export-transcript &lt;charm&gt; --branch &lt;turn-id&gt;</code></td>
      <td>Export the conversation path leading to a specific leaf, even if that leaf is no longer the active branch.</td>
    </tr>
  </tbody>
</table>

<h2 id="recover">Recover from a bad steering message</h2>

<p>
  You typed &ldquo;use Path B for this Flask workload&rdquo; and
  the agent dutifully started scaffolding a Path B charm even
  though you meant Path A.  Three turns later you realise the
  mistake.
</p>

<pre><code><span class="prompt">cantrip&gt;</span> /branch
Forked before turn 14 (your last user message).
Active branch: turn 13 &mdash; &ldquo;Looks good, go ahead.&rdquo;</code></pre>

<p>
  The Path B work didn't disappear &mdash; it's still on the old
  branch.  Your next user message extends the active branch
  from turn 13.  If you ever want to inspect the abandoned
  Path B exploration, <code>/tree</code> will show it.
</p>

<h2 id="explore">Explore alternatives in parallel</h2>

<p>
  For a charm where the substrate or relation graph has more
  than one defensible answer, branching lets you walk both
  paths and compare them rather than picking blind.
</p>

<ol>
  <li>Drive the agent down option A as a normal session.</li>
  <li>Inspect the result, then <code>/branch &lt;id&gt;</code>
    back to the design-decision turn.</li>
  <li>Steer the agent down option B from the same starting
    point.</li>
  <li>Use <code>/tree</code> to see both branches.</li>
  <li>Pick one as the active branch; export the other for
    reference if it had useful artefacts.</li>
</ol>

<pre><code><span class="prompt">cantrip&gt;</span> /tree
Session 4f8a&hellip; (charm: my-flask)
* turn 18 &mdash; &ldquo;Run acceptance tests&rdquo; (Path B branch)
  turn 25 &mdash; &ldquo;Add ingress integration&rdquo; (Path A branch)</code></pre>

<p>
  Press Enter on a row in the TUI picker to dispatch
  <code>/branch &lt;id&gt;</code> for that turn.  Escape leaves
  the active branch alone.
</p>

<h2 id="export">Export an off-branch path</h2>

<p>
  Branching changes which turns are live, not which turns exist.
  Every leaf is exportable by id even after the head moves
  elsewhere:
</p>

<pre><code><span class="prompt">$</span> cantrip export-transcript ./my-flask --branch t-25 --format html
Wrote transcript_t-25.html (Path A exploration, 18 turns).</code></pre>

<p>
  Without <code>--branch</code>, exports follow the currently
  active branch, so a forked session exports only the active
  path by default.
</p>

<h2 id="snapshots">Snapshots, undo, and branches together</h2>

<p>
  Every user turn takes a working-tree snapshot before it
  executes (unless <code>--no-snapshots</code> /
  <code>CANTRIP_SNAPSHOTS=false</code> turns it off).  Those
  snapshots back <em>both</em> <code>/undo</code> and
  <code>/branch</code>:
</p>

<ul>
  <li><strong><code>/undo</code></strong> restores the snapshot
    and deletes the conversation row.</li>
  <li><strong><code>/branch</code></strong> restores the
    snapshot of the target turn and leaves every existing
    conversation row in place.</li>
</ul>

<p>
  The snapshot repo lives at
  <code>$XDG_STATE_HOME/cantrip/snapshots/&lt;hash&gt;/</code>,
  outside the charm tree, so <code>git clean -fdx</code> on the
  charm cannot wipe out your branch history.
</p>

<h2 id="caveats">Caveats</h2>

<ul>
  <li>
    Branching is a session-local feature.  Off-branch turns
    live in the session's SQLite file
    (<code>.cantrip</code>); a fresh charm clone won't see
    them until you copy the session over.
  </li>
  <li>
    Custom auto-commits (<a href="howto-auto-commit.html">per-turn
    commits</a>) sit in the charm's git history regardless of
    which branch is active.  After a <code>/branch</code> back,
    the working tree matches the older snapshot but
    <code>git log</code> still shows the commits from the
    abandoned branch.  Reconcile with
    <code>git reset --soft &lt;sha&gt;</code> if you want the
    repo history to follow the conversation.
  </li>
  <li>
    Long-lived sessions accumulate dead branches.
    <code>/tree</code> stays compact (one line per turn)
    regardless, but the SQLite file grows.  The session export
    format preserves branches; a fresh session simply starts
    empty.
  </li>
</ul>
