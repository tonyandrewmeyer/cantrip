---
title: "Tutorial: Build your first charm — Cantrip"
description: "A step-by-step tutorial to build and deploy your first Juju charm with Cantrip."
h1: "Build your first charm"
subtitle: "Go from zero to a deployed, tested Juju charm in a single sitting. This tutorial takes about 15 minutes."
section: tutorial
breadcrumb_label: ""
primary_list: on_this_page
on_this_page:
  - { anchor: "overview", label: "Overview" }
  - { anchor: "prerequisites", label: "Prerequisites" }
  - { anchor: "install", label: "Install Cantrip" }
  - { anchor: "api-key", label: "Set up your API key" }
  - { anchor: "create-project", label: "Create a project" }
  - { anchor: "launch", label: "Launch Cantrip" }
  - { anchor: "describe", label: "Describe your workload" }
  - { anchor: "review-design", label: "Review the design" }
  - { anchor: "watch-build", label: "Watch the build" }
  - { anchor: "verify", label: "Verify the deployment" }
  - { anchor: "next-steps", label: "Next steps" }
see_also:
  - label: "CLI reference"
    href: "reference-cli.html"
  - label: "How Cantrip works"
    href: "explanation-architecture.html"
---

{#overview}
## What you will learn

By the end of this tutorial you will have:

- Installed Cantrip and connected it to an LLM provider.
- Described a workload and reviewed the agent's design proposal.
- Watched the agent build, deploy, and test a charm autonomously.
- Verified that the charm is running and observable.

<div class="callout">
  <p>
    This tutorial uses a simple Flask application as the example workload.
    Cantrip handles it via <strong>Path A</strong> (12-factor PaaS), which
    is the fastest charm path. The same workflow applies to more complex
    workloads &mdash; only the design proposal and build time differ.
  </p>
</div>

{#prerequisites}
## Prerequisites

Before you begin, make sure you have:

- **Ubuntu 22.04+** (or another Linux distribution with
  snap support).
- **Juju 3.x** installed and bootstrapped with at least
  one controller. If you need to set up Juju, see the
  [Juju getting started guide](https://juju.is/docs/juju/get-started-with-juju).
- **Python 3.12+** and **uv** installed.
  Install uv with: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- A **Gemini API key** (free tier is sufficient). Get one
  at [Google AI Studio](https://aistudio.google.com/app/apikey).
  You can also use Claude or a local inference snap — see
  [Choose an LLM provider](howto-provider.html).

{#install}
## 1. Install Cantrip

Install Cantrip as a standalone tool using `uv`:

<pre><code><span class="prompt">$</span> uv tool install cantrip</code></pre>

Verify the installation:

<pre><code><span class="prompt">$</span> cantrip --version
<span class="dim">cantrip 0.x.y</span></code></pre>

{#api-key}
## 2. Set up your API key

Export your Gemini API key so Cantrip can access the model:

<pre><code><span class="prompt">$</span> export GEMINI_API_KEY="your-key-here"</code></pre>

Add this to your shell profile (`~/.bashrc` or
`~/.zshrc`) so it persists across sessions.

{#create-project}
## 3. Create a project directory

Cantrip works inside a charm project directory. Create one and move
into it:

<pre><code><span class="prompt">$</span> mkdir my-flask-charm &amp;&amp; cd my-flask-charm</code></pre>

{#launch}
## 4. Launch Cantrip

Start Cantrip in the default TUI mode:

<pre><code><span class="prompt">$</span> cantrip</code></pre>

The terminal UI opens with three panels: a task checklist on the left,
Juju status in the centre, and a chat panel on the right. Your cursor
is in the chat input area, ready for your first message.

<div class="callout">
  <p>
    If you prefer a browser interface, launch with
    <code>cantrip --web</code> instead. For a minimal command-line REPL,
    use <code>cantrip --no-tui</code>.
  </p>
</div>

{#describe}
## 5. Describe your workload

In the chat panel, type a description of what you want to charm:

```
Build a charm for a Flask hello-world application
```

Press Enter. The agent begins its research phase — you will see
tasks appearing in the checklist on the left as it searches the web,
checks Charmhub for existing charms, and analyses the workload.

{#review-design}
## 6. Review the design proposal

After a few moments the agent presents a structured design proposal
in the chat. It looks something like this:

<pre><code><span class="comment">Substrate:</span>      Kubernetes
<span class="comment">Charm path:</span>     A (12-Factor PaaS)
<span class="comment">Base:</span>           paas-charm (Flask)
<span class="comment">Integrations:</span>   ingress, COS
<span class="comment">Config:</span>         app-port (default 8080)
<span class="comment">Observability:</span>  ops-tracing, Prometheus metrics</code></pre>

The agent waits for your confirmation. Read through the proposal. If
it looks right, reply:

```
Looks good, go ahead
```

If you want changes, tell the agent what to adjust — for example,
"add a database integration" or "use machine substrate instead".

{#watch-build}
## 7. Watch the build

Once confirmed, the agent enters the autonomous work loop. Watch the
task checklist update as subagents work through the plan:

- Scaffolding the charm project with `charmcraft init`
- Generating a `rockcraft.yaml` for the OCI image
- Writing integration tests
- Writing the charm code
- Packing and deploying
- Running acceptance tests

You do not need to type anything during this phase. The agent handles
errors automatically — if a build fails, it diagnoses the issue
using traces and logs and creates a fix task.

<div class="callout">
  <p>
    For a simple Flask charm, the build typically completes in under
    two minutes. More complex workloads (Path B or C) take longer.
  </p>
</div>

{#verify}
## 8. Verify the deployment

When all tasks show a tick in the checklist, your charm is deployed
and tested. Verify it with Juju:

<pre><code><span class="prompt">$</span> juju status
<span class="dim">Model    Controller  Cloud/Region        Version  ...
default  lxd         localhost/localhost  3.x.y    ...

App              Version  Status  Scale  Charm            Channel  Rev
my-flask-charm            active      1  my-flask-charm              0

Unit                  Workload  Agent  Machine  ...
my-flask-charm/0*     active    idle   0        ...</span></code></pre>

The charm should be in `active/idle` status. Observability
is automatically wired up via COS — traces and metrics are
flowing.

{#next-steps}
## Next steps

You have built and deployed your first charm with Cantrip. From here:

- [Improve an existing charm](howto-improve.html) —
  point Cantrip at a charm you have already written.
- [Choose an LLM provider](howto-provider.html) —
  try Claude or local inference snaps.
- [The three charm paths](explanation-charm-paths.html) —
  understand how Cantrip handles different workload types.
- [How Cantrip works](explanation-architecture.html) —
  learn about the two-loop architecture and subagents.
- [CLI reference](reference-cli.html) —
  explore all available flags and commands.
