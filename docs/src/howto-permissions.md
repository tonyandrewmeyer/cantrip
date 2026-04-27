---
title: "How to configure tool permissions — Cantrip"
description: "Write a .cantrip/permissions.yaml file to allow, ask before, or deny tool calls with glob patterns."
h1: "Configure tool permissions"
subtitle: "Declare which tool calls, shell commands, and file paths are allowed, require confirmation, or are forbidden."
section: howto
breadcrumb_label: "Configure tool permissions"
see_also:
  - label: "CLI reference"
    href: "reference-cli.html"
  - label: "How Cantrip works"
    href: "explanation-architecture.html"
---

<h2 id="overview">What permissions control</h2>

<p>Cantrip wraps every subagent tool call in a three-layer gate.
User hooks run first and can mutate or veto calls.
Governance policies come next &mdash; coarse, category-scoped
allow/deny/review. Permissions are the declarative
layer on top, matching the <em>post-hook</em> arguments so a command
your hook rewrote still sees the right pattern.</p>

<p>Each call resolves to one of three outcomes:</p>

<ul>
  <li><strong><code>allow</code></strong> &mdash; the call proceeds silently.</li>
  <li><strong><code>ask</code></strong> &mdash; the subagent pauses while a CONFIRM
task surfaces on the queue; the user types <code>yes</code> or
<code>no</code> to unblock it. A timeout auto-denies.</li>
  <li><strong><code>deny</code></strong> &mdash; the call is refused with a clear
error; the agent sees the denial and can course-correct.</li>
</ul>

<h2 id="file-locations">File locations</h2>

<p>Permissions are read from two files, composed in order so repo
rules override user rules when both match:</p>

<ol>
  <li><code>~/.config/cantrip/permissions.yaml</code> &mdash; your
personal defaults, applied to every charm.</li>
  <li><code>&lt;charm&gt;/.cantrip/permissions.yaml</code> &mdash; the
per-charm overlay, committed alongside the code.</li>
</ol>

<p>Both files are optional. When neither exists, the built-in
defaults (below) still apply.</p>

<h2 id="schema">Schema</h2>

<pre><code>tools:
  "&lt;tool-name-glob&gt;": "allow" | "ask" | "deny"

bash:
  "&lt;command-glob&gt;": "allow" | "ask" | "deny"

paths:
  "&lt;path-glob&gt;": "allow" | "ask" | "deny"

agents:
  &lt;category-name&gt;:
tools: { ... }
bash:  { ... }
paths: { ... }

bash_tools:
  - run_command</code></pre>

<p>The three sections match independently; the
<strong>most restrictive outcome wins</strong> when they disagree
(<code>deny</code> &gt; <code>ask</code> &gt; <code>allow</code>). Within a
section, <strong>last-match-wins</strong> &mdash; the later-written
glob takes effect. Globs use standard Unix shell syntax
(<code>*</code>, <code>?</code>, <code>[abc]</code>) and are
case-sensitive.</p>

<h2 id="sections">What each section matches</h2>

<ul>
  <li><strong><code>tools</code></strong> &mdash; globs on the tool name
(<code>fs_read</code>, <code>juju_deploy</code>, <code>git_*</code>).</li>
  <li><strong><code>bash</code></strong> &mdash; globs on the shell command
string passed to tools listed in <code>bash_tools</code>
(default: <code>run_command</code>). An <code>argv</code> list is
shell-joined before matching.</li>
  <li><strong><code>paths</code></strong> &mdash; globs on the <code>path</code>,
<code>file_path</code>, or <code>filename</code> argument of any
tool call.</li>
</ul>

<h2 id="example">A typical file</h2>

<pre><code>tools:
  # Shell wrappers always need a second look.
  "run_command": "ask"

bash:
  # Specific commands get more specific answers.  The later rule
  # for ``git push`` wins for those commands; everything else that
  # just hit "*" stays ``ask``.
  "*": "ask"
  "git status": "allow"
  "git log *": "allow"
  "git push *": "ask"
  "rm -rf *": "deny"
  "sudo *": "ask"

paths:
  # Credentials are never OK to read.
  "*.env": "deny"
  "**/secrets/**": "deny"

agents:
  # The research subagent is read-only &mdash; writes are out.
  research:
tools:
  "fs_write": "deny"
  "charmcraft_*": "deny"</code></pre>

<h2 id="defaults">Built-in defaults</h2>

<p>Even with no file present, Cantrip ships these safe defaults:</p>

<ul>
  <li><code>rm -rf *</code> and <code>rm -fr *</code> &mdash;
<code>deny</code>.</li>
  <li><code>sudo *</code> and <code>git push *</code> &mdash;
<code>ask</code>.</li>
  <li>Reads of <code>.env</code> (including <code>*.env</code> and
<code>*/.env</code>) &mdash; <code>deny</code>.</li>
  <li>Everything else &mdash; <code>allow</code>.</li>
</ul>

<p>Your rules override them because built-ins are composed first
and your file appends later.</p>

<h2 id="agents">Per-agent overrides</h2>

<p>The <code>agents:</code> block tightens or loosens rules for a
specific subagent category. Agent names match the task category
(<code>research</code>, <code>build</code>, <code>deploy</code>,
<code>test</code>, <code>debug</code>, <code>infra</code>). Per-agent
rules are evaluated <em>after</em> the top-level rules, so a
later-written <code>agents.research.tools</code> entry overrides
any earlier global rule.</p>

<h2 id="opencode-compat">Transferring from OpenCode</h2>

<p>The section / outcome shape is deliberately identical to
OpenCode's <code>opencode.json</code> <code>permission:</code> block,
so a rule like <code>{"bash": {"*": "ask", "git *": "allow", "rm *":
"deny"}}</code> carries over one-for-one. The only differences are:</p>

<ul>
  <li>Cantrip's file is YAML, not JSON.</li>
  <li>Cantrip adds a <code>paths</code> section with argument
globbing for file tools.</li>
  <li>Cantrip's per-agent key is <code>agents:</code> (matching
subagent categories) rather than a flat scope.</li>
</ul>

<h2 id="resolving-asks">Resolving an <code>ask</code></h2>

<p>When a subagent hits an <code>ask</code>, a CONFIRM task appears
in the work-queue widget with the tool name, the reason the rule
matched, and the command or path at issue. Respond in the chat
with <code>yes</code> to approve or <code>no</code> to refuse.
A <code>PERMISSION_DECIDED</code> event lands on the event bus each
time an <code>ask</code> opens or resolves, so the TUI and Web
transcripts record the full decision trail.</p>

<p>Approvals are scoped to that single call &mdash; approving
<code>git push origin main</code> does not approve a later
<code>git push --force</code>. Edit the rule to
<code>allow</code> if you want the decision to stick.</p>

<h2 id="what-it-does-not">What permissions do not do</h2>

<ul>
  <li>They do not bypass governance policy. A tool
category blocked by <code>cantrip.policies.yaml</code> stays
blocked even if <code>permissions.yaml</code> says
<code>allow</code>.</li>
  <li>They do not replace the subprocess sandbox.
A <code>bash: "*": "allow"</code> still runs inside the
namespace-isolated shell; permissions gate <em>whether</em> a
call fires, not how.</li>
  <li>They do not apply to MCP-provided tools &mdash; those are
gated by per-server <code>allowed_tools</code> in
<code>mcp.yaml</code>.</li>
</ul>
