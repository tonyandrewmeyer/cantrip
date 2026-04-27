---
title: "The repository map — Cantrip"
description: "How Cantrip builds a graph-ranked map of a charm's source code, why it's in the system prompt, and how /map exposes it for inspection."
h1: "The repository map"
subtitle: "A bird's-eye view of the active charm, ranked by reference importance, that the agent carries into every turn."
section: explanation
breadcrumb_label: "The repository map"
on_this_page:
  - { anchor: "why", label: "Why the agent needs a map" }
  - { anchor: "how", label: "How the map is built" }
  - { anchor: "injection", label: "When it reaches the LLM" }
  - { anchor: "inspect", label: "Inspecting it with /map" }
  - { anchor: "cache", label: "Caching and refresh" }
---

<h2 id="why">Why the agent needs a map</h2>

<p>
  A typical Juju charm is too big to paste into the LLM's
  context window in full, but small enough that the model
  benefits from knowing the rough shape rather than blindly
  grepping its way around.  Without any structural cue, the
  first move on every turn becomes &ldquo;list the directory,
  open three files, look at imports&rdquo; &mdash; tokens spent
  on navigation that could have been spent on the actual
  change.
</p>

<p>
  Cantrip mirrors the
  <a href="https://aider.chat/docs/repomap.html" target="_blank" rel="noopener">aider</a>-style
  &ldquo;repository map&rdquo; pattern: a compact summary of the
  charm's most important files and the symbols they define,
  injected into the system prompt on every turn.  When the
  agent reaches for code, it already knows where to look.
</p>

<h2 id="how">How the map is built</h2>

<p>
  Three layers of analysis combine into a single ranking:
</p>

<ol>
  <li>
    <strong>Symbol extraction.</strong>  Each source file is
    parsed for the symbols it defines &mdash; classes, functions,
    and module-level constants.  Charm YAML files contribute
    their declared interfaces (relations, configs, actions).
  </li>
  <li>
    <strong>Reference graph.</strong>  Within each file Cantrip
    records the symbols it <em>references</em> from elsewhere:
    callers point at callees, importers point at imports,
    charm-side YAML interface names link to the Python that
    handles them.  The result is a directed graph over
    files-by-symbol.
  </li>
  <li>
    <strong>PageRank.</strong>  Files are ranked by PageRank
    over the reference graph.  A small utility module that
    every other file imports rises in the ranking even if its
    own line count is modest; a long but unreferenced
    scaffolding file falls.
  </li>
</ol>

<p>
  The output is a per-file summary &mdash; the file's primary
  symbol with a <code>+N more</code> hint &mdash; ordered top to
  bottom by rank.
</p>

<h2 id="injection">When it reaches the LLM</h2>

<p>
  The map injects automatically into the system prompt under a
  configurable token budget (default 1500).  Two adaptive
  thresholds keep it from crowding out room to think:
</p>

<ul>
  <li>
    Past <strong>80%</strong> of the context window, the
    budget halves &mdash; the agent still gets a map, but a
    compressed one.
  </li>
  <li>
    Past <strong>95%</strong> of the context window, the map
    drops out entirely.  A near-full window cannot act on a
    bird's-eye view; the tokens are better spent on the
    immediate task.
  </li>
</ul>

<p>
  The map is regenerated incrementally: only files whose mtime
  changed get reparsed.  A working session that touches a
  handful of files per turn pays a few milliseconds for the
  map; a clean clone or a large rename triggers a full rebuild.
</p>

<h2 id="inspect">Inspecting it with /map</h2>

<p>
  Two slash commands expose the same map the agent sees:
</p>

<dl>
  <dt><code>/map</code></dt>
  <dd>
    Compact summary &mdash; one line per top-ranked file.  Useful
    before asking the agent to navigate, to confirm it has the
    right mental model of the codebase.
  </dd>
  <dt><code>/map full</code></dt>
  <dd>
    The wall-of-text version &mdash; every file with every symbol.
    Same view the agent receives.  Overwhelming as a chat-panel
    default, but invaluable when you want to understand
    precisely what's in scope.
  </dd>
</dl>

<p>
  <code>/map-refresh</code> (and <code>/map-refresh full</code>)
  discards the cache and reparses every source file from
  scratch.  Reach for it after a large rename or when the cache
  looks stale.
</p>

<h2 id="cache">Caching and refresh</h2>

<p>
  The map persists at <code>.cantrip-repomap.json</code> in
  the charm root, alongside the rest of Cantrip's per-charm
  state.  The file is intentionally a JSON document so that
  it can be inspected with standard tools and is small enough
  to gitignore without losing meaningful state &mdash; the cache
  rebuilds in seconds on a fresh clone.
</p>

<p>
  Because the map is keyed by file mtime, a
  <code>git checkout</code> that changes file timestamps
  invalidates the relevant entries automatically.  The full
  rebuild trigger (<code>/map-refresh</code>) exists for the
  cases where filesystem mtimes lie &mdash; a tarball extraction
  that preserves the original timestamps, for instance.
</p>

<h2 id="see-also">See also</h2>

<ul>
  <li><a href="reference-cli.html#repository-map">CLI reference &mdash; <code>/map</code></a></li>
  <li><a href="howto-mentions.html"><code>@file</code> and <code>@tree</code> mentions</a> &mdash; complementary surfaces for inline navigation</li>
  <li><a href="explanation-architecture.html">How Cantrip works</a> &mdash; where the map fits in the system-prompt assembly</li>
</ul>
