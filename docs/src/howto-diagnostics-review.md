---
title: "How to run diagnostics and review — Cantrip"
description: "Use /diagnostics for deterministic linting and /review for prompt-based checks before asking the agent for the next round of changes."
h1: "Run diagnostics and review"
subtitle: "Two complementary inspectors: <code>/diagnostics</code> runs the deterministic linters, <code>/review</code> runs prompt-based checks for the &ldquo;an experienced human would notice this&rdquo; class of issues."
section: howto
breadcrumb_label: "Run diagnostics and review"
see_also:
  - label: "CLI reference &mdash; review checks"
    href: "reference-cli.html#review-checks"
  - label: "CLI reference &mdash; diagnostics"
    href: "reference-cli.html#project-diagnostics"
  - label: "Configure tool permissions"
    href: "howto-permissions.html"
---

<h2 id="overview">Two surfaces, two scopes</h2>

<table>
  <thead>
    <tr><th></th><th><code>/diagnostics</code></th><th><code>/review</code></th></tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>What runs</strong></td>
      <td><code>ruff</code>, <code>ty</code>, and (for charms) <code>charmlint</code></td>
      <td>Every loaded prompt-based Check, then linter diagnostics underneath</td>
    </tr>
    <tr>
      <td><strong>How it decides</strong></td>
      <td>AST/regex rules. Deterministic.</td>
      <td>One structured LLM call per Check (the <code>CHECK_RESULT</code> schema).</td>
    </tr>
    <tr>
      <td><strong>Cost</strong></td>
      <td>Local CPU only.</td>
      <td>One LLM call per loaded Check (typically 3&ndash;10).</td>
    </tr>
    <tr>
      <td><strong>When to reach for it</strong></td>
      <td>&ldquo;Is the code well-formed?&rdquo;</td>
      <td>&ldquo;Would a reviewer flag this charm's design?&rdquo;</td>
    </tr>
  </tbody>
</table>

<p>
  Both run against the active charm, not the whole repo.  Both
  cap their output so a noisy charm doesn't blow the chat
  panel.
</p>

<h2 id="diagnostics">/diagnostics</h2>

<pre><code><span class="prompt">cantrip&gt;</span> /diagnostics
charmlint:
  ERROR    metadata.yaml:5  unknown integration interface "promethus"
ruff:
  E501     src/charm.py:42  line too long (132 &gt; 120)
  F401     src/charm.py:1   unused import "ops.testing"
ty:
  &lt;clean&gt;</code></pre>

<p>
  Issues are grouped by tool and severity.  Output is capped at
  ~1500 tokens; over-budget charms get a
  &ldquo;<em>N more issues suppressed</em>&rdquo; footer.
  Results cache for 30 seconds, so a follow-up
  <code>/diagnostics</code> in the same chat turn is free.  Pass
  <code>--refresh</code> to bust the cache after editing files
  outside the agent.
</p>

<p>
  Tools that aren't installed are listed as
  <code>[skipped]</code> rather than treated as silent passes
  &mdash; a missing <code>ty</code> doesn't look the same as
  &ldquo;all clear.&rdquo;
</p>

<h3 id="pre-turn">Diagnostics also run pre-turn</h3>

<p>
  The same aggregator runs automatically when the autonomous
  loop starts a BUILD or DEBUG subagent, so the agent begins
  each task already knowing what's broken.  Result: the
  agent's first move on a debug task tends to be
  &ldquo;here are the four type errors I'll fix&rdquo;
  rather than &ldquo;let me run the linter.&rdquo;
</p>

<p>
  The <code>@problems</code>
  <a href="howto-mentions.html">mention</a> exposes the same
  cache, so you can drop current diagnostics into a steering
  message without re-running anything:
</p>

<pre><code><span class="prompt">cantrip&gt;</span> tighten the type errors first: @problems</code></pre>

<h2 id="review">/review</h2>

<p>
  <code>/review</code> runs every loaded prompt-based Check.
  Each Check is one structured LLM call &mdash; the
  <code>CHECK_RESULT</code> schema constrains the reply to
  <code>{status, severity, message, evidence?, suggested_fix?}</code>
  &mdash; so the report is uniform regardless of which model
  you're using.
</p>

<pre><code><span class="prompt">cantrip&gt;</span> /review
FAILED  charm-readme-coherence  warning
  README claims a `prometheus` relation but metadata.yaml only
  declares `loki`. Suggested fix: align README with metadata.

PASSED  action-ergonomics
PASSED  relation-data-hygiene

Deterministic checks
charmlint: 1 error in metadata.yaml
ruff:      2 issues across 1 file
ty:        clean</code></pre>

<p>
  Failures appear first, then errors (couldn't reach a
  verdict), then skipped (no matching files), then passes.
  The linter pass underneath is the same <code>/diagnostics</code>
  output, so one combined run answers both
  &ldquo;is the code well-formed?&rdquo; and &ldquo;does it
  hang together?&rdquo;
</p>

<h3 id="default-checks">What ships by default</h3>

<p>
  Three Checks are bundled:
</p>

<dl>
  <dt><code>charm-readme-coherence</code></dt>
  <dd>
    README claims align with the actual charm shape: relation
    interfaces, config options, supported actions, listed
    endpoints.
  </dd>
  <dt><code>action-ergonomics</code></dt>
  <dd>
    Action names follow the verb-noun convention; descriptions
    are non-empty and not just restate the name; required
    parameters carry sensible defaults where possible.
  </dd>
  <dt><code>relation-data-hygiene</code></dt>
  <dd>
    Relation data writes use stable keys, validate on read,
    and don't leak secrets that should live in
    <code>juju secrets</code>.
  </dd>
</dl>

<h3 id="custom-checks">Add your own Check</h3>

<p>
  Checks are loaded from three layered locations (later wins
  on name conflict):
</p>

<ol>
  <li>Bundled defaults shipped with Cantrip.</li>
  <li><code>~/.config/cantrip/checks/*.md</code> &mdash; user scope.</li>
  <li><code>&lt;charm&gt;/.cantrip/checks/*.md</code> &mdash; repo scope.</li>
</ol>

<p>
  Each Check is YAML frontmatter plus a markdown body.  See
  <a href="https://github.com/tonyandrewmeyer/cantrip/blob/main/design/CHECKS.md" target="_blank" rel="noopener">design/CHECKS.md</a>
  for the schema.  Rough boundary against the linters:
  <code>charmlint</code> is the right home for AST/regex rules;
  <code>/review</code> is the right home for &ldquo;an
  experienced human would notice this is off but you can't
  write it as a regex.&rdquo;
</p>

<h2 id="workflow">A typical workflow</h2>

<ol>
  <li>
    <strong>Mid-build</strong> &mdash; let the autonomous loop's
    pre-turn diagnostics carry the linters.  You don't run
    anything by hand.
  </li>
  <li>
    <strong>Before asking for next-step changes</strong> &mdash;
    run <code>/diagnostics</code> if you've been editing files
    outside the agent (use <code>--refresh</code> to bust the
    30-second cache).
  </li>
  <li>
    <strong>Before pushing or opening a PR</strong> &mdash; run
    <code>/review</code>.  This is the one that catches the
    cross-cutting issues a linter cannot: README drift,
    action ergonomics, relation-data hygiene, plus any
    repo-scoped Checks you've added.
  </li>
</ol>

<h2 id="caveats">Caveats</h2>

<ul>
  <li>
    <code>/review</code> calls the LLM once per loaded Check.
    Costs scale with the number of Checks; a small repo with
    the three defaults is a few cents per run, but a
    ten-Check setup adds up across a session.  The
    <code>/cost</code> command makes the spend visible.
  </li>
  <li>
    Prompt-based Checks are non-deterministic.  Treat a
    <code>FAILED</code> verdict as &ldquo;a competent reviewer
    flagged this&rdquo; &mdash; worth investigating, not always
    worth acting on.  The <code>evidence</code> field tells
    you which lines drove the verdict.
  </li>
  <li>
    Diagnostics caches for 30 seconds.  In an agent loop that
    edits files repeatedly within a single turn, the second
    <code>/diagnostics</code> may be stale by milliseconds.
    Use <code>--refresh</code> when correctness matters more
    than latency.
  </li>
</ul>
