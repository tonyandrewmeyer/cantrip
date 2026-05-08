---
title: "Documentation — Cantrip"
description: "Cantrip documentation: tutorials, how-to guides, reference, and explanations for the AI-powered Juju charm builder."
h1: "Cantrip Documentation"
subtitle: "Learn how to use Cantrip to build production-quality Juju charms with AI."
section: index
---

<p>
  This documentation follows the
  <a href="https://diataxis.fr/" target="_blank" rel="noopener">Diataxis</a> framework, organising
  content by what you need: learning, solving problems, looking things
  up, or understanding how the system works.
</p>

<h2 id="start-here">Start here</h2>

<ol>
  <li>
    <strong>Install Cantrip.</strong> The
    <a href="tutorial.html#install">tutorial starts with the end-user install flow</a>;
    if you still need to choose a provider, continue with
    <a href="howto-provider.html">Choose an LLM provider</a>.
  </li>
  <li>
    <strong>Pick your surface.</strong> Use
    <a href="howto-interface.html">Choose an interface</a> to decide between
    the TUI, Web UI, CLI REPL, and print mode.
  </li>
  <li>
    <strong>Decide whether you are building or improving.</strong> For a new
    charm, start with the <a href="tutorial.html">tutorial</a>. For an
    existing charm, jump to
    <a href="howto-improve.html">Improve an existing charm</a>.
  </li>
  <li>
    <strong>Need automation or tighter governance?</strong> Go straight to
    <a href="howto-print-mode.html">print mode</a>,
    <a href="howto-permissions.html">tool permissions</a>, and
    <a href="reference-cli.html#audit">audit trail inspection</a>.
  </li>
</ol>

<div class="doc-cards">

  <a href="tutorial.html" class="doc-card">
    <span class="doc-card-label">Tutorial</span>
    <h3>Build your first charm</h3>
    <p>
      A guided walkthrough from installation to a deployed, tested charm.
      No prior Cantrip experience required.
    </p>
  </a>

  <a href="howto-provider.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Choose an LLM provider</h3>
    <p>
      Pick the right provider and model for your situation &mdash; cloud
      API, local inference, or hybrid.
    </p>
  </a>

  <a href="howto-interface.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Choose an interface</h3>
    <p>
      Decide between the TUI, Web UI, CLI REPL, and print mode based on
      your terminal, browser, or automation workflow.
    </p>
  </a>

  <a href="howto-improve.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Improve an existing charm</h3>
    <p>
      Audit and upgrade an existing charm: add tests, fill observability
      gaps, modernise deprecated APIs.
    </p>
  </a>

  <a href="howto-export.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Export transcripts</h3>
    <p>
      Export session transcripts as HTML, Markdown, or JSONL for
      documentation or review.
    </p>
  </a>

  <a href="howto-print-mode.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Run a single goal non-interactively</h3>
    <p>
      Drive one goal end to end in CI, shell pipelines, or scheduled jobs
      with <code>cantrip run --print</code>.
    </p>
  </a>

  <a href="howto-light-models.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Configure light models</h3>
    <p>
      Route internal tasks to cheaper models to reduce cost without
      sacrificing output quality.
    </p>
  </a>

  <a href="howto-docs-index.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Index the charm docs</h3>
    <p>
      Crawl Canonical's documentation surfaces (Juju, ops,
      charmcraft, rockcraft, jubilant, Charmhub) and let the agent
      cite passages via <code>docs_search</code> and
      <code>@docs &lt;site&gt; &lt;query&gt;</code> instead of
      paraphrasing from memory.
    </p>
  </a>

  <a href="howto-memory.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Use durable memory</h3>
    <p>
      Record lessons with <code>/remember</code>, let the
      auto-writer capture corrections, export shareable
      <code>SKILL.md</code> bundles, and keep the index fresh via
      revalidation and TTL.
    </p>
  </a>

  <a href="howto-team-sync.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Share with teammates</h3>
    <p>
      Three opt-in toggles &mdash; shared memory, shared decisions
      log, human co-author trailer &mdash; turn Cantrip into a
      small-team tool by committing
      <code>.cantrip-shared/</code> to git. No server, no live
      collab, just files alongside the charm.
    </p>
  </a>

  <a href="howto-skills.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Add a custom skill</h3>
    <p>
      Drop a standard-format skill into
      <code>~/.claude/skills/</code> or
      <code>~/.config/cantrip/skills/</code> and Cantrip picks it
      up at startup &mdash; vendor-neutral format, optional
      <code>tools:</code> list, bundled skills can be overridden.
    </p>
  </a>

  <a href="howto-recipes.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Run a recipe</h3>
    <p>
      Parameterised, retryable workflows committed alongside the
      charm: <code>/recipe charm-cos-add</code> or
      <code>/recipe charm-reactive-to-ops</code> ship the same
      prompt, the same parameter shapes, and the same convergence
      checks every time.
    </p>
  </a>

  <a href="howto-flows.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Walk a flow</h3>
    <p>
      Mermaid decision trees the agent walks step by step:
      <code>/flow charm-cos-enable</code>,
      <code>/flow charm-reactive-to-ops</code>, or
      <code>/flow charm-upgrade-ladder</code>. The agent
      announces branch decisions inline so you can follow its
      reasoning.
    </p>
  </a>

  <a href="howto-mcp.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Configure MCP servers</h3>
    <p>
      Attach third-party tools via <code>cantrip.mcp.yaml</code>
      &mdash; stdio and HTTP transports, OAuth 2.1, mid-task
      elicitation, and marketplace discovery.
    </p>
  </a>

  <a href="howto-charm-library.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Search the charm library</h3>
    <p>
      Use the Librarian subagent and <code>/search-charms</code> to
      find existing Charmhub and Launchpad charms before reinventing
      them &mdash; quality flags surface stale or borderline hits.
    </p>
  </a>

  <a href="howto-charm-icon.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Generate a charm icon</h3>
    <p>
      Paint a Charmhub-style <code>icon.svg</code> for a charm via
      <code>/icon</code> &mdash; LLM-driven, square, designer-polish
      recommended; bounded by a per-session USD cap.
    </p>
  </a>

  <a href="howto-hooks.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Configure hooks</h3>
    <p>
      Run shell commands at lifecycle events via
      <code>cantrip.hooks.yaml</code> &mdash; pre/post tool
      calls, compaction, subagent start/stop; JSON payload piped
      to stdin.
    </p>
  </a>

  <a href="howto-permissions.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Configure tool permissions</h3>
    <p>
      Control which tool calls auto-run, ask for confirmation, or are
      denied outright with repository and user-level policy files.
    </p>
  </a>

  <a href="howto-feelings.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Convene the inner parliament</h3>
    <p>
      Run emotion subagents over your charm for a multi-lens review
      &mdash; delight, risk, friction, taste, empathy.
    </p>
  </a>

  <a href="reference-cli.html" class="doc-card">
    <span class="doc-card-label">Reference</span>
    <h3>CLI reference</h3>
    <p>
      Complete listing of all commands, flags, and environment variables.
    </p>
  </a>

  <a href="reference-cli.html#audit" class="doc-card">
    <span class="doc-card-label">Reference</span>
    <h3>Audit policy decisions</h3>
    <p>
      Inspect <code>.cantrip-audit.jsonl</code> after unattended runs or
      export it as JSONL or CSV for review and CI artefacts.
    </p>
  </a>

  <a href="reference-tools.html" class="doc-card">
    <span class="doc-card-label">Reference</span>
    <h3>Agent tools</h3>
    <p>
      Every tool the agent can use, grouped by category, with
      descriptions and parameters.
    </p>
  </a>

  <a href="explanation-architecture.html" class="doc-card">
    <span class="doc-card-label">Explanation</span>
    <h3>How Cantrip works</h3>
    <p>
      The two-loop architecture, work queue, subagents, and why
      autonomous operation matters.
    </p>
  </a>

  <a href="explanation-charm-paths.html" class="doc-card">
    <span class="doc-card-label">Explanation</span>
    <h3>The three charm paths</h3>
    <p>
      Why there are three approaches to charm building and how
      the agent selects the right one.
    </p>
  </a>

  <a href="explanation-observability.html" class="doc-card">
    <span class="doc-card-label">Explanation</span>
    <h3>Observability and debugging</h3>
    <p>
      How Cantrip uses COS, Tempo, and Loki to debug charms
      autonomously.
    </p>
  </a>

  <a href="explanation-quickpack-rs.html" class="doc-card">
    <span class="doc-card-label">Explanation</span>
    <h3>Quickpack Rust backend</h3>
    <p>
      Why quickpack has a Rust implementation, how Cantrip selects it,
      and measured performance.
    </p>
  </a>

  <a href="explanation-charmlint-rs.html" class="doc-card">
    <span class="doc-card-label">Explanation</span>
    <h3>Charmlint Rust backend</h3>
    <p>
      Why charmlint has a Rust implementation, how Cantrip selects it,
      and measured performance.
    </p>
  </a>

  <a href="explanation-emotions.html" class="doc-card">
    <span class="doc-card-label">Explanation</span>
    <h3>Emotion subagents</h3>
    <p>
      Why there are five personality-driven review lenses, how
      they&apos;re scoped to avoid overlap, and the tradeoffs.
    </p>
  </a>

  <a href="explanation-race.html" class="doc-card">
    <span class="doc-card-label">Explanation</span>
    <h3>Racing and Arena</h3>
    <p>
      How Cantrip ranks Best-of-N candidates by charm quality and
      how blind A/B <code>/arena</code> captures your model
      preferences.
    </p>
  </a>

  <a href="explanation-tui-screens.html" class="doc-card">
    <span class="doc-card-label">Explanation</span>
    <h3>TUI screens and shortcuts</h3>
    <p>
      The function-key modals &mdash; Logs, Traces, Graph, File
      detail &mdash; and the Dev and COS status panes.
    </p>
  </a>

</div>
