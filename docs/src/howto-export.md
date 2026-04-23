---
title: "How to export transcripts — Cantrip"
description: "Export Cantrip session transcripts as HTML, Markdown, or JSONL."
h1: "Export transcripts"
subtitle: "Export a session's conversation history and task log for documentation, review, or analysis."
section: howto
breadcrumb_label: "Export transcripts"
see_also:
  - label: "CLI reference"
    href: "reference-cli.html"
---

{#mid-session}
## Export mid-session with `/export`

The `/export` slash command writes the current session's
transcript without leaving Cantrip. It works the same way in the TUI,
CLI REPL, and Web UI:

<pre><code><span class="prompt">›</span> /export
<span class="prompt">›</span> /export markdown
<span class="prompt">›</span> /export jsonl /tmp/session.jsonl</code></pre>

Syntax: `/export [html|jsonl|markdown] [path]`. Both
arguments are optional — without them Cantrip writes
`transcript.html` into the charm directory. The first
positional argument selects the format; a trailing token becomes the
output path. The command runs against the live `.cantrip`
store, so you can grab a snapshot at any point without pausing work.

{#basic}
## Export from the command line

Outside a session, export the full transcript as an HTML page:

<pre><code><span class="prompt">$</span> cantrip export-transcript /path/to/my-charm</code></pre>

This creates `transcript.html` in the charm directory.
Open it in a browser to see the complete conversation, tool calls,
and task results.

{#formats}
## Choose a format

Three output formats are available:

| Format | Flag | Use case |
|---|---|---|
| HTML | `--format html` (default) | Human-readable, shareable reports |
| Markdown | `--format markdown` | Documentation, wikis, READMEs |
| JSONL | `--format jsonl` | Programmatic analysis, data pipelines |

<pre><code><span class="prompt">$</span> cantrip export-transcript /path/to/my-charm --format markdown
<span class="prompt">$</span> cantrip export-transcript /path/to/my-charm --format jsonl</code></pre>

{#filter}
## Filter the transcript

For long sessions, filter the export to focus on what matters:

### By task

<pre><code><span class="prompt">$</span> cantrip export-transcript ./my-charm --task build_charm_code</code></pre>

### By phase

<pre><code><span class="prompt">$</span> cantrip export-transcript ./my-charm --phase research
<span class="comment"># Options: research, build, deploy, test</span></code></pre>

### By timestamp

<pre><code><span class="prompt">$</span> cantrip export-transcript ./my-charm --since 2026-04-15T10:00:00Z</code></pre>

{#pagination}
## Paginate HTML output

For very long sessions, split the HTML output into multiple pages:

<pre><code><span class="prompt">$</span> cantrip export-transcript ./my-charm --page-size 50</code></pre>

This creates `transcript_1.html`,
`transcript_2.html`, etc., each containing 50 conversation
messages. Navigation links connect the pages.

{#output-path}
## Custom output path

<pre><code><span class="prompt">$</span> cantrip export-transcript ./my-charm --output /tmp/my-report.html</code></pre>
