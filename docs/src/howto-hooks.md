---
title: "How to configure hooks — Cantrip"
description: "Declare user hooks in YAML that run at lifecycle points — pre/post tool calls, compaction, subagent start/stop."
h1: "Configure hooks"
subtitle: "Run small scripts at lifecycle points without forking Cantrip."
section: howto
breadcrumb_label: "Configure hooks"
---

{#what}
## What hooks are for

A *hook* is a shell command Cantrip runs at a specific
event — every tool call, every compaction, every subagent
start — with a JSON payload piped to the hook’s
stdin. Use them for local policy (audit logs, Slack notifications,
custom linters you want to trigger before packing) without
changing Cantrip itself.

Hooks start in observer mode by default and can opt into
*veto* mode with `continue_on_error: false`
— see [Vetoing operations](#veto) below.  A `pre_tool_call`
hook can also *rewrite* the pending tool arguments before the
tool runs — see [Rewriting arguments](#mutate).

{#where}
## Where to configure

Cantrip reads two YAML files, in order:

1. **User scope:**
   `~/.config/cantrip/hooks.yaml` (override via
   `CANTRIP_HOOKS_USER_CONFIG`) — the right place
   for personal audits, experiments, or shared tooling you want
   on every charm.
2. **Repo scope:**
   `cantrip.hooks.yaml` next to your charm directory
   — for project-specific hooks that should be committed.
   Repo hooks with a matching `name` override
   user-scope hooks.

A malformed file is logged at WARNING and skipped rather than
crashing the agent, so a typo in one place never takes the other
down.

{#schema}
## Schema

```
hooks:
  - name: log-git-pushes
    event: pre_tool_call
    if: tool == "git_push"
    run: logger -t cantrip "pushing $(jq -r .arguments.branch)"
    timeout: 5
    continue_on_error: true
```

Fields:

- `name` (string, optional) — label used in
  logs and the future `/hooks` slash command.
  Defaults to the first word of `run`.
- `event` (string, required) — one of the
  event names below. (The field is named `event`
  rather than `on` because unquoted `on:`
  in YAML 1.1 parses as a boolean `True` key, which
  would silently break configs.)
- `run` (string, required) — the command line
  to invoke. Passed to `/bin/sh -c` so pipes,
  redirection, and env-var expansion all work.
- `if` (string, optional) — a boolean
  expression evaluated against the event payload. The hook
  only fires when the expression is truthy. See
  [Conditional filters](#filters) below.
- `timeout` (number, optional, default 30) —
  seconds before the hook is killed. A slow hook blocks the
  agent sequentially, so keep it short.
- `continue_on_error` (bool, optional, default
  `true`) — when `false`, a
  non-zero exit (or a timeout) *vetoes* the pending
  operation: the tool doesn’t run, compaction
  doesn’t happen, the subagent doesn’t start.
  See the [Vetoing operations](#veto) section.

{#filters}
## Conditional filters

The optional `if:` expression gates a hook on
payload shape so you don’t need to write shell guards in
every `run:`. Common patterns:

```
# Only audit git pushes, not every tool call.
- event: pre_tool_call
  if: tool == "git_push"
  run: ...

# Only react to builds the agent actually finished.
- event: post_subagent
  if: category == "BUILD" and exit_state == "completed"
  run: ...

# Don't notify for fast compactions.
- event: post_compact
  if: tokens_before > 100000
  run: ...

# Multiple values: set membership.
- event: pre_tool_call
  if: tool in ["git_push", "git_commit", "charmcraft_upload"]
  run: ...

# Nested fields walk through the payload.
- event: pre_tool_call
  if: tool == "juju_deploy" and arguments.channel == "edge"
  run: ...
```

**What the expression language supports:**
comparisons (`==`, `!=`, `<`,
`<=`, `>`, `>=`,
`in`, `not in`), boolean combinators
(`and`, `or`, `not`), nested
field access (`arguments.branch`,
`task.category`), subscripts
(`arguments["branch"]`), and string / number / list
literals.

**What it doesn’t support:** function calls,
method calls (`tool.startswith(…)`),
comprehensions, lambdas, imports — rejected at
config-load time with a clear error. Substring checks work via
`"git" in tool`.

**Missing fields are safe.** If a filter
references a payload key the event doesn’t carry (e.g.
`task.category` on a `pre_compact`
event), the comparison evaluates to `False` and the
hook is skipped. You can write one hook config that targets
fields from several event shapes without worrying about
KeyError crashes.

{#events}
## Events

The following events are fired today:

| Event | Fires when | Payload keys (in addition to `event` and `timestamp`) |
|---|---|---|
| `pre_tool_call` | Before every tool invocation (main agent or subagent). | `tool`, `arguments`, `source` (`main`, `main-stream`, or `subagent`), `task_category` (subagent only) |
| `post_tool_call` | After every tool invocation completes or errors. | `tool`, `arguments`, `success`, `error`, `source`, `task_category` |
| `pre_compact` | Just before context compaction runs. | `tokens_before`, `source` |
| `post_compact` | After compaction completes (even if it falls back to truncation). | `tokens_before`, `tokens_after`, `source` |
| `pre_subagent` | Before a subagent starts a task. | `task_id`, `title`, `category` |
| `post_subagent` | After the subagent returns (even on failure). | `task_id`, `title`, `category`, `exit_state` |

The following event names are reserved for future sub-phases:
`pre_pack`, `pre_push`, `pre_pr`,
`on_task_complete`, `on_session_end`.
You can register hooks for them today — they will just
never fire until the matching agent code lands.

{#payload}
## Payload shape

Every hook receives a JSON object on stdin with at least two
fields:

- `event` — the event name (mirrors the hook’s `event:` field).
- `timestamp` — ISO-8601 local time of the event.

The remaining fields vary by event, as listed above. Parse with
`jq`, or `python -c 'import json, sys;
d = json.load(sys.stdin)'`, or whatever your hook prefers.

{#examples}
## Examples

### Audit every tool call to a log file

```
hooks:
  - name: audit-tools
    event: post_tool_call
    run: |
      python3 -c 'import json, sys, datetime
      d = json.load(sys.stdin)
      with open("/tmp/cantrip-tools.log", "a") as f:
          f.write(f"{datetime.datetime.now().isoformat()} {d[\"tool\"]} ok={d[\"success\"]}\n")'
    timeout: 5
```

### Slack notification when compaction fires

```
hooks:
  - name: slack-compact
    event: post_compact
    run: |
      jq -c '{text: "Cantrip compacted: \(.tokens_before) -> \(.tokens_after) tokens"}' \
        | curl -s -X POST -H 'Content-Type: application/json' \
          -d @- https://hooks.slack.com/services/XXX/YYY/ZZZ
    timeout: 10
```

### Count how often each tool is called, per session

```
hooks:
  - name: tool-counter
    event: pre_tool_call
    run: |
      jq -r .tool | tee -a ~/.cache/cantrip/tool-counts
```

{#veto}
## Vetoing operations

A hook with `continue_on_error: false` can refuse
the pending operation by exiting non-zero (or by timing out).
Use it to enforce local policy:

```
# Refuse git pushes when the working tree has uncommitted changes.
- name: require-clean-tree
  event: pre_tool_call
  if: tool == "git_push"
  continue_on_error: false
  run: |
    if ! git diff --quiet; then
      echo "working tree dirty; refusing to push" >&2
      exit 1
    fi

# Block compaction while a user-pinned session is in progress.
- name: pin-context
  event: pre_compact
  continue_on_error: false
  run: test ! -f ~/.cache/cantrip/pinned
```

What happens when a pre-hook vetoes:

- `pre_tool_call`: the tool isn’t called. The
  LLM receives an error `ToolResult` naming the hook
  and its last stderr line, so its next turn can apologise,
  retry with different arguments, or ask the user for help.
  `post_tool_call` still fires with
  `success: false` and a `vetoed_by`
  field — observability hooks see the attempt.
- `pre_compact`: compaction is skipped and the
  context stays intact. The model gets no token-budget
  summary message. `post_compact` does *not*
  fire because compaction never ran.
- `pre_subagent`: the whole task returns a
  `BLOCKED` exit state without calling the LLM. The
  executor records the block like any other blocked task.
  `post_subagent` fires with the blocked exit
  state and a `vetoed_by` field.

Filter observability hooks on `if: vetoed_by != None`
to get a feed of blocked-only events.

The default (`continue_on_error: true`) is
unchanged from earlier releases — a failing lenient hook
logs at DEBUG and doesn’t block anything. Only
`continue_on_error: false` turns a hook into an
enforcer.

{#mutate}
## Rewriting arguments

A `pre_tool_call` hook can rewrite the arguments a tool is
about to receive by printing a JSON envelope to **stdout**:

```
{"mutate": {"arguments": {"branch": "main", "token": "[REDACTED]"}}}
```

The `mutate.arguments` object, when present, wholly replaces
the tool's arguments before the tool runs. Typical uses: strip
secrets from a `run_shell` command, canonicalise a filename,
normalise a branch name before `git_push`.

```
# Redact anything that looks like a token before it hits run_shell.
- name: redact-tokens
  event: pre_tool_call
  if: tool == "run_shell"
  run: |
    payload=$(cat)
    echo "$payload" | jq '
      .arguments as $args
      | {"mutate": {"arguments": ($args | .command |= gsub(
            "ghp_[A-Za-z0-9]+"; "[REDACTED]"
        ))}}
    '
```

Rules:

- Only `pre_tool_call` events honour the envelope. Other events
  parse and discard (so you can't accidentally rewrite things
  post-hoc).
- Hooks run sequentially for a given tool call, so a later hook
  in the chain sees the previous hook's mutation on stdin and
  can refine it further.
- A hook that *vetoes* (`continue_on_error: false` + non-zero
  exit) blocks the tool call outright; its envelope is ignored
  because the call will never run.
- Non-JSON stdout (e.g. a `logger` line or a `jq` error) is
  treated as a non-mutating log line. Existing hooks that print
  plain text keep working unchanged.
- Malformed envelopes (wrong types, unknown shape) log a
  WARNING and are ignored; they never break a tool call.

`post_tool_call` and the session transcript record the
**effective** arguments — the ones that actually ran — so the
audit trail reflects the mutated call.

{#inspecting}
## Inspecting hooks

Two debugging surfaces answer “is my hook wired right?”
without having to trigger a real agent operation:

{#slash}
### `/hooks` slash command

Available in the TUI, CLI REPL, and Web chat. Lists every
configured hook grouped by event with its `if:`
filter and (when `continue_on_error: false`) a
**veto-capable** badge; for hooks that have fired
this session, shows per-hook counts (invocations, successes,
failures, vetoes, timeouts), average duration, and last-seen
time:

```
/hooks
  Configured: 3 hook(s).

  pre_tool_call
    - `require-clean-tree`  if `tool == "git_push"`  veto-capable
        5 invocations (4 ok, 1 failed, 1 vetoed) · avg 23ms · last at 14:12:03
    - `audit-tools`
        147 invocations (147 ok, 0 failed) · avg 8ms · last at 14:12:04

  post_compact
    - `slack-compact`
        not invoked yet

  Transcript logging: on — hook_invocation events carry per-call detail
  in the session store.
```

{#cli-test}
### `cantrip hooks test <event>`

Fires a synthetic event against the current hook config and
prints results — great for authoring a new hook config before
letting it touch a live session. Exit code is 0 on success,
2 on argument / JSON errors:

```
$ cantrip hooks test pre_tool_call --payload '{"tool": "git_push"}'
Firing `pre_tool_call` against 2 matching hook(s).
  ✓ audit-tools — exit 0 in 5ms
      stdout: saw git_push at 14:12:09
  ∅ require-clean-tree — exit 1 in 12ms (VETO)
      stderr: working tree dirty; refusing to push
```

`--path DIR` overrides the repo root for
`cantrip.hooks.yaml` discovery
(defaults to CWD). `--payload` is merged into the
auto-added `event` + `timestamp` fields
so your `if:` filter evaluates against realistic
input.

{#transcript}
### Transcript events

Every executed hook records a
`hook_invocation` event in the session store with
`hook_name`, `event`,
`exit_code`, `duration_seconds`,
`vetoed`, `timed_out`,
`continue_on_error`, and (when stderr isn’t
empty) a 200-char `stderr_excerpt`. Skipped hooks
(rejected by their `if:` filter) do *not*
record events — the transcript is an audit log of real
executions, not an attempt log.

{#limits}
## Current limits

- Hooks run *sequentially* per event in declaration order.
  A slow hook blocks the next one and the agent itself. Keep
  `timeout` aggressive.
- Hook stdout is captured but not yet injected into the agent
  conversation. (A future sub-phase will let `pre_*`
  hooks mutate the pending payload via a JSON-patch envelope.)
- Stdout from a `pre_tool_call` hook is captured
  but not yet merged into the pending payload — a
  follow-up sub-phase will document a JSON envelope so a hook
  can redact a secret out of `arguments` before the
  tool runs.
