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

  <a href="howto-light-models.html" class="doc-card">
    <span class="doc-card-label">How-to</span>
    <h3>Configure light models</h3>
    <p>
      Route internal tasks to cheaper models to reduce cost without
      sacrificing output quality.
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
