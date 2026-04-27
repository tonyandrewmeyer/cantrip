---
title: "How to index the charm docs — Cantrip"
description: "Build a local index of Canonical's charm-ecosystem documentation so the agent retrieves cited passages instead of paraphrasing."
h1: "Index the charm docs"
subtitle: "Build a local index of Canonical&rsquo;s charm-ecosystem documentation so the agent answers from cited passages instead of plausible-sounding paraphrase."
section: howto
breadcrumb_label: "Index the charm docs"
see_also:
  - label: "CLI reference"
    href: "reference-cli.html"
  - label: "Configure embed and rerank"
    href: "howto-provider.html#retrieval-roles"
---

<p>
  Cantrip can index the canonical Canonical documentation
  surfaces (Juju, ops, charmcraft, rockcraft, jubilant,
  Charmhub).  Once indexed, the agent reaches for
  <code>docs_search</code> before answering &ldquo;how do
  I&hellip;&rdquo; questions, and you can pull cited passages
  mid-message via <code>@docs &lt;site&gt; &lt;query&gt;</code>.
  Both surfaces return canonical URLs &mdash; never paraphrased
  text &mdash; so the agent can no longer fall back to
  plausible-sounding hallucinations.
</p>

<h2 id="setup">One-time setup</h2>

<p>
  The index needs an embed provider.  Voyage is the
  Anthropic-ecosystem recommendation; OpenAI&rsquo;s
  <code>text-embedding-3-small</code> works too.  Configure
  either in your shell:
</p>

<pre><code><span class="prompt">$</span> export CANTRIP_EMBED_PROVIDER=voyage
<span class="prompt">$</span> export VOYAGE_API_KEY=&lt;your-key&gt;</code></pre>

<p>
  See <a href="howto-provider.html#retrieval-roles">Configure
  embed and rerank</a> for the OpenAI variant and the
  <code>OPENAI_EMBED_BASE_URL</code> override for self-hosted
  vLLM.
</p>

<h2 id="index">Index a site</h2>

<pre><code><span class="prompt">$</span> cantrip docs index --site ops
Indexing ops (https://ops.readthedocs.io/) &hellip;
  pages: 184  chunks: 612  embed-batches: 10  errors: 0</code></pre>

<p>
  Re-running the same command crawls fresh and replaces stored
  rows by stable <code>(url, ordinal)</code> hash &mdash; you
  do not need to clear the cache by hand.  Crawl errors
  (timeouts, 404s) are absorbed; the rest of the pages still
  index.
</p>

<p>
  <code>--all</code> indexes every registered site:
</p>

<pre><code><span class="prompt">$</span> cantrip docs index --all</code></pre>

<h2 id="list">See what&rsquo;s indexed</h2>

<pre><code><span class="prompt">$</span> cantrip docs list
Cache root: /home/&lt;you&gt;/.cache/cantrip/docs-index

Site         Indexed  Chunks   Description
------------ -------- -------- ----------------------------------------
juju         no       -        Juju documentation (operator framework + CLI)
ops          yes      612      ops library reference (charm authoring API)
charmcraft   no       -        charmcraft reference (charm packaging tooling)
rockcraft    no       -        rockcraft reference (OCI image packaging)
jubilant     no       -        Jubilant (integration-testing helpers)
charmhub     no       -        Charmhub charm-author guidelines</code></pre>

<h2 id="search">Search from a shell</h2>

<pre><code><span class="prompt">$</span> cantrip docs search ops "how do secrets work"
[0.842] https://ops.readthedocs.io/en/latest/howto/manage-secrets.html
    Manage charm secrets
    Charm secrets are content-addressed values that &hellip;

[0.781] https://ops.readthedocs.io/en/latest/reference/secrets.html
    Secret reference
    A secret is created with a label and content via the &hellip;</code></pre>

<p>Pipe the output into <code>fzf</code> or your editor for quick navigation.</p>

<h2 id="agent">Use it in chat</h2>

<p>
  Inside the TUI / Web chat, the agent calls
  <code>docs_search</code> automatically when answering
  ecosystem questions, and you can inject specific passages
  with the <code>@docs</code> mention:
</p>

<pre><code>How do I model a database relation? @docs ops relation</code></pre>

<p>
  The mention expands inline before the message reaches the
  LLM, attaching the top hits as a context block with their
  URLs.  See
  <a href="reference-cli.html#mentions">@-mention context
  providers</a> for the full mention catalogue.
</p>

<h2 id="costs">Costs</h2>

<p>
  Every batch of chunks goes through the embed provider, so
  costs are roughly the per-million-token rate of your
  embed model multiplied by the corpus size.  At
  <code>voyage-3</code>&rsquo;s $0.06/1M rate, indexing the
  ops reference (~600 chunks &times; 500 tokens) is well
  under a cent.  The <code>/cost</code> slash command shows a
  separate <strong>By role</strong> section once embed
  traffic exists, so retrieval spend is easy to spot.
</p>

<h2 id="caveats">Caveats</h2>

<ul>
  <li>
    The crawler is sitemap-driven only; sites that don&rsquo;t
    expose <code>sitemap.xml</code> are not currently
    supported.
  </li>
  <li>
    <code>cantrip docs index</code> re-crawls everything on
    each run.  Incremental refresh with
    <code>If-Modified-Since</code> is a planned follow-up.
  </li>
  <li>
    Indexing fails fast when the embed provider isn&rsquo;t
    configured &mdash; the error message names the env var to
    set.  Sessions without retrieval gracefully skip
    <code>@docs</code> registration so an unconfigured user
    sees the same experience they had before this feature
    landed.
  </li>
</ul>
