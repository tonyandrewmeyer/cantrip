# Transcript Export: Review and share agent sessions

*2026-04-18T10:07:49Z by Showboat 0.6.1*
<!-- showboat-id: c1b5b15d-59cf-4450-8cb0-41993b235859 -->

Every Cantrip session records a full transcript — every message, tool call, subagent hand-off, and status update — into a `.cantrip` directory inside the charm project. The `cantrip export-transcript` subcommand turns that store into a portable document for review, sharing, or auditing.

Three output formats are supported: **HTML** (paginated and styled, the default), **Markdown** (copy into a bug report or PR description), and **JSONL** (feed into another tool or eval pipeline).

## CLI

```bash
uv run cantrip export-transcript --help
```

```output
usage: cantrip export-transcript [-h] [--format {html,jsonl,markdown}]
                                 [--output OUTPUT] [--task FILTER_TASK]
                                 [--phase {research,build,deploy,test}]
                                 [--since FILTER_SINCE]
                                 [--page-size PAGE_SIZE]
                                 path

positional arguments:
  path                  Charm directory containing a .cantrip file

options:
  -h, --help            show this help message and exit
  --format {html,jsonl,markdown}
                        Output format (default: html)
  --output OUTPUT       Output file path (default: transcript.<ext> in charm
                        directory)
  --task FILTER_TASK    Export only a specific task and its subagent
                        conversation
  --phase {research,build,deploy,test}
                        Export only tasks in a phase (research, build, deploy,
                        test)
  --since FILTER_SINCE  Export only messages and events at or after an ISO
                        timestamp
  --page-size PAGE_SIZE
                        Split HTML output into pages of N conversation
                        messages each
```

## Filtering options

Big agent runs produce big transcripts. The filters let you zoom in:

| Flag | Effect |
|------|--------|
| `--task <name>` | Only include that task and its subagent's messages |
| `--phase research\|build\|deploy\|test` | Only tasks from a given phase of the agent's lifecycle |
| `--since <iso-timestamp>` | Only messages at or after a timestamp |
| `--page-size N` | Split the HTML into pages of N messages each (stops giant single-file exports) |

## Output formats

Implementations live in `src/cantrip/transcript/`:

```bash
ls src/cantrip/transcript/ | grep -v __ | grep -v templates
```

```output
export.py
html.py
jsonl.py
markdown.py
```

## Typical workflows

```bash
# After a session finishes, export the HTML with pagination
cantrip export-transcript ./my-charm --format html --page-size 50

# Just the build phase, for attaching to a bug report
cantrip export-transcript ./my-charm --format markdown --phase build --output build-transcript.md

# A single problematic task, as JSONL for an eval harness
cantrip export-transcript ./my-charm --format jsonl --task deploy-to-dev-model --output deploy.jsonl

# Everything since a recent point in time
cantrip export-transcript ./my-charm --since 2026-04-18T10:00:00Z
```

```bash
# The `.cantrip` directory in the charm project is the source of truth
ls ./my-charm/.cantrip/
#   events.jsonl    messages.jsonl    tasks.jsonl    state.json
```

```bash
# Nothing is uploaded — transcripts stay local unless you share them explicitly.
```
