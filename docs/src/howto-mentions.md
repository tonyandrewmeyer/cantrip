---
title: "How to use @-mention context — Cantrip"
description: "Pull file excerpts, git diffs, charm metadata, live Juju status, indexed docs, and URLs straight into a chat message with Tab-completable @ mentions."
h1: "Use @-mention context"
subtitle: "Inline a file, diff, charm spec, live Juju view, indexed docs passage, or URL straight into your message &mdash; before the LLM sees it &mdash; instead of asking the agent to fetch it."
section: howto
breadcrumb_label: "Use @-mention context"
see_also:
  - label: "CLI reference &mdash; @-mention providers"
    href: "reference-cli.html#mentions"
  - label: "Index the charm docs"
    href: "howto-docs-index.html"
  - label: "Configure MCP servers"
    href: "howto-mcp.html"
---

<h2 id="why">Why mention context inline</h2>

<p>
  The agent has tools for reading files, running
  <code>git diff</code>, fetching URLs, and so on.  When you
  already know what context the next reply needs, asking the
  agent to fetch it adds a tool round-trip (extra latency, extra
  tokens) that you can skip by pasting the content with a
  mention.
</p>

<p>
  Mentions are expanded <em>before</em> the message is sent to
  the LLM.  The substituted block is wrapped in a
  <code>[@name]&hellip;[/@name]</code> fence and recorded in the
  transcript so the intent (&ldquo;the user pulled
  <code>config.yaml</code> in&rdquo;) stays visible alongside the
  content.
</p>

<div class="callout">
  <p>
    Don't pre-fetch context for things the agent will discover
    on its own &mdash; the autonomous loop is good at that.  Use
    mentions when (a) you've spotted the file/section that
    matters and want to save the round-trip, or (b) you want a
    cited answer rather than the agent paraphrasing from
    memory.
  </p>
</div>

<h2 id="quickref">The provider catalogue</h2>

<table>
  <thead>
    <tr><th>Mention</th><th>Substitutes</th></tr>
  </thead>
  <tbody>
    <tr>
      <td><code>@file &lt;path&gt;</code></td>
      <td>Contents of a repo-relative file.  Absolute paths and <code>..</code> traversal are rejected.</td>
    </tr>
    <tr>
      <td><code>@diff</code></td>
      <td>Output of <code>git diff HEAD</code> in the active charm.</td>
    </tr>
    <tr>
      <td><code>@tree [path]</code></td>
      <td>Repo-tracked file listing via <code>git ls-files</code>.  Falls back to a plain walk outside a git checkout.</td>
    </tr>
    <tr>
      <td><code>@problems</code></td>
      <td>Current <code>ruff</code> / <code>ty</code> / <code>charmlint</code> diagnostics.  Shares the 30-second cache used by <code>/diagnostics</code>.</td>
    </tr>
    <tr>
      <td><code>@url &lt;url&gt;</code></td>
      <td>The fetched body of a URL, run through the same private-IP block, <code>llms.txt</code> probing, and HTML-to-text extraction the agent uses.</td>
    </tr>
    <tr>
      <td><code>@charm &lt;name&gt;</code></td>
      <td>Charmhub metadata for the named charm: relations, config, current revision.</td>
    </tr>
    <tr>
      <td><code>@juju &lt;subcmd&gt;</code></td>
      <td>Read-only Juju subcommand output.  Allowlisted: <code>status</code>, <code>show-unit</code>, <code>show-application</code>, <code>show-model</code>, <code>config</code>, <code>list-secrets</code>, <code>show-relation</code>, <code>list-models</code>.</td>
    </tr>
    <tr>
      <td><code>@docs &lt;site&gt; &lt;query&gt;</code></td>
      <td>Top hits from your indexed Canonical documentation.  Requires <code>cantrip docs index</code> to have run first &mdash; see <a href="howto-docs-index.html">Index the charm docs</a>.</td>
    </tr>
  </tbody>
</table>

<p>
  Each provider has a per-call character cap; over-budget output
  is truncated with a <code>[truncated N chars]</code> footer
  rather than silently elided.
</p>

<h2 id="tab">Tab-complete in the TUI</h2>

<p>
  Type <code>@</code> mid-message and a popup lists every
  registered provider.  Keep typing to filter:
</p>

<pre><code><span class="prompt">cantrip&gt;</span> look at @fi<span class="cursor">|</span>
            @file
            @file &lt;path&gt;</code></pre>

<p>
  <kbd>Tab</kbd> completes the highlighted suggestion without
  disturbing the surrounding prose.  <kbd>Up</kbd> /
  <kbd>Down</kbd> moves the highlight; <kbd>Esc</kbd> dismisses
  the popup so a literal <code>@x</code> stays a literal
  <code>@x</code>.
</p>

<h2 id="examples">Realistic examples</h2>

<h3>Pull in a config file before steering</h3>

<pre><code><span class="prompt">cantrip&gt;</span> the existing config is @file config/app.yaml &mdash;
keep the same shape but split the database connection into its
own section.</code></pre>

<p>
  The agent receives the file contents inline and can reason
  about the change without calling <code>read_file</code>
  first.
</p>

<h3>Cite indexed docs in a question</h3>

<pre><code><span class="prompt">cantrip&gt;</span> how do I model a database relation? @docs ops relation</code></pre>

<p>
  The top retrieved passages from the indexed
  <code>ops</code> documentation are pasted in with their
  canonical URLs, so the answer is grounded in cited text
  rather than the model's recollection of the API.
</p>

<h3>Compare a live Juju model against expectations</h3>

<pre><code><span class="prompt">cantrip&gt;</span> the deploy looked off &mdash; here's status now: @juju status
why is the relation showing as pending?</code></pre>

<p>
  <code>@juju</code> runs only the read-only allowlisted
  subcommand; a typo cannot reach a destructive verb.
</p>

<h3>Forward a remote document for review</h3>

<pre><code><span class="prompt">cantrip&gt;</span> here's the spec the team agreed on:
@url https://internal.example.com/specs/charm.html
does our current design match?</code></pre>

<h2 id="slash">Mentions inside slash commands</h2>

<p>
  Slash commands run before mention expansion, so a literal
  <code>@x</code> inside a slash argument is not substituted:
</p>

<pre><code><span class="prompt">cantrip&gt;</span> /remember user wants @-mentions tested before merging</code></pre>

<p>
  The memory captures the literal text including the
  <code>@</code>.  Combined with
  <a href="howto-custom-commands.html">user-defined slash
  commands</a>, this means a custom command's argument text is
  itself a clean string &mdash; mention expansion only fires on the
  raw chat input.
</p>

<h2 id="extending">Add your own provider</h2>

<p>
  The mention catalogue is extensible:
</p>

<ul>
  <li>
    An <a href="howto-mcp.html">MCP server</a> can register a
    prompt-style entry that surfaces as
    <code>@&lt;server&gt;.&lt;name&gt;</code>.
  </li>
  <li>
    A <a href="howto-hooks.html">hook</a> can intercept the
    outbound user message and inject context the same way the
    built-in providers do.
  </li>
</ul>

<p>
  The protocol and registration shape are documented in
  <a href="https://github.com/tonyandrewmeyer/cantrip/blob/main/design/CONTEXT_PROVIDERS.md" target="_blank" rel="noopener">design/CONTEXT_PROVIDERS.md</a>.
</p>

<h2 id="caveats">Caveats</h2>

<ul>
  <li>
    Mentions are local-only context.  Pasting
    <code>@file</code> content does not commit it &mdash; it
    only reaches the LLM.
  </li>
  <li>
    Large mentions count against the LLM's context window.
    Per-call truncation prevents accidental overflows, but
    five <code>@file</code>s in one message can still crowd
    out room for the agent's response.
  </li>
  <li>
    <code>@docs</code> needs an embed provider configured (see
    <a href="howto-provider.html#retrieval-roles">Configure
    embed and rerank</a>) and at least one
    <code>cantrip docs index</code> run to have stored
    chunks.  Without those, the mention reports the missing
    configuration rather than failing silently.
  </li>
</ul>
