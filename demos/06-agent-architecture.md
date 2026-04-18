# Agent Architecture: Two loops, a work queue, and disposable subagents

*2026-04-18T10:08:16Z by Showboat 0.6.1*
<!-- showboat-id: fc998770-8309-45c4-a39b-6c39f994ffe6 -->

Cantrip's design is documented in `design/AGENT.md`. In short: there are **two concurrent loops** sharing a single work queue.

- A **conversation loop** handles the user — proposals, confirmations, status, steering.
- An **autonomous work loop** picks tasks off the queue and runs them in disposable subagents.

That split means the user can always steer mid-run without blocking the agent's progress, and the agent can keep working while it waits for a decision.

## The high-level diagram

From `design/AGENT.md`:

```bash
sed -n '18,40p' design/AGENT.md
```

````output
│                                                                         │
│  ┌───────────────────────┐              ┌────────────────────────────┐  │
│  │   Conversation Loop   │    steer/    │    Autonomous Work Loop    │  │
│  │                       │◄────────────►│                            │  │
│  │  process_message()    │    notify    │  Executor picks tasks      │  │
│  │  User chat, proposals │              │  Spawns subagents          │  │
│  │  Decision collection  │              │  Records results           │  │
│  └───────────┬───────────┘              └─────────────┬──────────────┘  │
│              │                                        │                 │
│              └───────────► WorkQueue ◄────────────────┘                 │
│                                ▲                                        │
│                                │                                        │
│                           Watcher events                                │
│                           User steering                                 │
│                           Adaptive replanning                           │
└─────────────────────────────────────────────────────────────────────────┘
```

## Main Agent (Conversation Loop)

The main agent handles the user-facing conversation. It:
- Talks to the user (design proposals, status updates, questions)
- Collects decisions and records them in `AgentState`
````

## Where each piece lives in the source

```bash
ls src/cantrip/agent/*.py | xargs -I {} basename {}
```

```output
__init__.py
autodeploy.py
context.py
core.py
design.py
emotions.py
executor.py
git_branch.py
github_issues.py
preflight.py
queue.py
retry.py
routing.py
services.py
skills.py
state.py
store.py
subagent.py
watcher.py
```

Selected responsibilities:

| File | Role |
|------|------|
| `core.py` | `CantripAgent` — top-level agent owning both loops |
| `queue.py` | `WorkQueue` — the shared channel between loops |
| `executor.py` | Autonomous work-loop driver that dequeues and dispatches tasks |
| `subagent.py` | Disposable task runner — one subagent per task, isolated context |
| `design.py` | Research → design proposal stage |
| `planner/` | Task planning (splits a design into an executable plan) |
| `skills.py` | `SkillsIndex` — load-on-demand skill library (see demo 04) |
| `state.py` | `AgentState` — durable decisions, status, transcript anchors |
| `watcher.py` | Dev-model event watcher that can trigger replanning |
| `emotions.py` | Experimental: Inner Parliament emotion subagents |

## The tool catalogue

Subagents act through tools. The agent ships a curated tool kit — this is what a subagent can call:

```bash
ls src/cantrip/agent/tools/*.py | xargs -I {} basename {} | grep -v __ | grep -v base.py
```

```output
acceptance.py
audit.py
benchmark.py
chaos.py
charm.py
charmhub.py
charmlint_tool.py
environment.py
files.py
fuzz.py
git.py
github.py
glob.py
grep.py
inference.py
juju.py
juju_subprocess.py
loadtest.py
multi_edit.py
observability.py
oci_registry.py
operational_readiness.py
planning.py
pr_review.py
publishing.py
report.py
rockcraft.py
rodney.py
run_command.py
scaling.py
showboat.py
skills.py
task_management.py
testing.py
upgrade.py
virtual_files.py
web.py
web_search.py
workflows.py
```

38+ tools, grouped roughly as:

- **Charm lifecycle** — `charm`, `rockcraft`, `publishing`, `operational_readiness`, `upgrade`
- **Testing** — `testing` (Scenario), `acceptance` (Jubilant), `chaos`, `fuzz`, `loadtest`, `benchmark`, `scaling`
- **Observability** — `observability`, dashboards, traces, metrics, logs
- **Environment** — `juju`, `juju_subprocess`, `environment` (Concierge), `oci_registry`
- **Code & files** — `files`, `glob`, `grep`, `multi_edit`, `virtual_files`, `git`, `github`, `pr_review`
- **Research** — `web`, `web_search`, `charmhub`, `audit`
- **Orchestration** — `planning`, `task_management`, `workflows`, `skills`
- **Demos & reporting** — `showboat` (yes, the tool generating *this* document), `report`, `rodney`

## Further reading

- `design/AGENT.md` — Full architecture write-up (work queue semantics, subagent lifecycle, adaptive replanning)
- `design/TOOLS.md` — Tool abstraction, registration pattern, how to add a new tool
- `design/PROMPTS.md` — Prompt layering and Jinja2 conventions
- `design/PLAN.md` — Higher-level design decisions and philosophy
- `ROADMAP.md` — Implementation phases
