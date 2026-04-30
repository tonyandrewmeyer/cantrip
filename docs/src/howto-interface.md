---
title: "How to choose between the TUI, Web UI, CLI, and print mode — Cantrip"
description: "Pick the right Cantrip surface: terminal UI, browser UI, CLI REPL, or one-shot print mode."
h1: "Choose an interface"
subtitle: "Cantrip ships four ways to drive the same agent core. Pick the one that matches your terminal, browser, or automation workflow."
section: howto
breadcrumb_label: "Choose an interface"
on_this_page:
  - { anchor: "overview", label: "Overview" }
  - { anchor: "comparison", label: "Surface comparison" }
  - { anchor: "tui", label: "TUI" }
  - { anchor: "web", label: "Web UI" }
  - { anchor: "cli", label: "CLI REPL" }
  - { anchor: "print", label: "Print mode" }
  - { anchor: "caveats", label: "Feature-parity caveats" }
see_also:
  - label: "CLI reference"
    href: "reference-cli.html"
  - label: "TUI screens and shortcuts"
    href: "explanation-tui-screens.html"
  - label: "Run a single goal non-interactively"
    href: "howto-print-mode.html"
---

{#overview}
## Overview

Cantrip has four entry surfaces:

<ul>
  <li><strong>TUI</strong> (<code>cantrip</code>) &mdash; the default full-screen terminal experience.</li>
  <li><strong>Web UI</strong> (<code>cantrip --web</code>) &mdash; the same live agent loop in a browser tab.</li>
  <li><strong>CLI REPL</strong> (<code>cantrip --no-tui</code>) &mdash; a minimal interactive command-line session.</li>
  <li><strong>Print mode</strong> (<code>cantrip run --print "goal"</code>) &mdash; one-shot, non-interactive execution for scripts and CI.</li>
</ul>

<p>If you are unsure, start with the default TUI. It exposes the most
agent state at once and is the best fit for day-to-day charm work.</p>

{#comparison}
## Surface comparison

| Surface | Start with | Best for | Main caveat |
| --- | --- | --- | --- |
| TUI | `cantrip` | Rich interactive sessions with task pane, file tree, logs, traces, and model status visible together | Requires a full-screen terminal |
| Web UI | `cantrip --web` | Browser-based chat, easy scrolling/copying, keeping Cantrip beside docs or dashboards | `--improve` is not supported in Web mode |
| CLI REPL | `cantrip --no-tui` | SSH, tmux, minimal terminals, and interactive sessions where plain text is enough | No TUI panes or function-key screens |
| Print mode | `cantrip run --print "goal"` | CI, shell pipelines, scheduled jobs, and one-off unattended goals | No conversation or REPL; exits when the queue drains |

{#tui}
## TUI

<p>The default terminal UI is the richest interactive surface. Use it
when you want the chat, task list, Juju status, and file tree on screen
at once, or when you rely on the function-key screens for logs, traces,
the integration graph, transcript browsing, and file detail.</p>

<p>This is the best surface for "build a charm, watch it research,
inspect the logs, then confirm the next step" workflows. See
<a href="explanation-tui-screens.html">TUI screens and shortcuts</a>
for the modal screens and hotkeys.</p>

{#web}
## Web UI

<p>The Web UI runs the same live session in a browser tab:</p>

<pre><code><span class="prompt">$</span> cantrip --web
Cantrip Web UI running at http://127.0.0.1:8471</code></pre>

<p>Choose it when a browser is more comfortable than a full-screen
terminal: long chat transcripts are easier to scroll, links are easier
to follow, and it fits well beside web docs, Grafana, or GitHub in the
same window layout.</p>

<p>The important caveat is that <code>--improve</code> is not supported
here. Improvement mode relies on interactive confirmation flows that the
TUI and CLI REPL provide directly, so use one of those surfaces for
existing-charm upgrade work.</p>

{#cli}
## CLI REPL

<p>The CLI REPL keeps the session interactive but drops the full-screen
UI chrome:</p>

<pre><code><span class="prompt">$</span> cantrip --no-tui</code></pre>

<p>Use it when you are on a remote shell, inside tmux, or in any
terminal where a line-oriented interface is easier than a full TUI. The
REPL still supports normal chat plus slash commands, and it adds
Tab-completion for slash verbs when <code>readline</code> is available.</p>

<p>This is the best fit when you want an interactive session over SSH,
need plain-text logs in your terminal history, or prefer to drive the
agent with a small command-line footprint.</p>

{#print}
## Print mode

<p>Print mode is deliberately not another interactive surface. It runs
one goal to completion, streams progress to stdout, and exits:</p>

<pre><code><span class="prompt">$</span> cantrip run --print "Pack and test this charm"</code></pre>

<p>Use it for CI, shell pipelines, cron jobs, and one-off automation.
With <code>--json</code> it emits NDJSON events, which makes it easy to
pipe into <code>jq</code>, <code>tee</code>, or log collectors.</p>

<p>If you want back-and-forth conversation, do not use print mode; use
the TUI, Web UI, or CLI REPL instead. For the full automation workflow,
see <a href="howto-print-mode.html">Run a single goal non-interactively</a>.</p>

{#caveats}
## Feature-parity caveats

<ul>
  <li><strong>Only the TUI</strong> has the function-key screens, file tree,
  and modal inspectors described in
  <a href="explanation-tui-screens.html">TUI screens and shortcuts</a>.</li>
  <li><strong>Web UI</strong> and <strong>print mode</strong> are different:
  <code>--web</code> is interactive, <code>--print</code> is one-shot, and the
  two flags cannot be combined.</li>
  <li><strong>Web UI</strong> does not support <code>--improve</code>; use the
  TUI or CLI REPL for that workflow.</li>
  <li><strong>Print mode</strong> is unattended by default. Pending
  confirmation tasks stop the run unless you resolve them first or opt
  into <code>--yolo</code>.</li>
  <li><strong>Slash commands</strong> are for interactive surfaces. Use the
  TUI, Web UI, or CLI REPL when you need chat-native commands like
  <code>/memory</code> and <code>/mcp</code>; the CLI REPL also adds
  text-first helpers such as <code>/tasks</code> and
  <code>/status</code>.</li>
</ul>
