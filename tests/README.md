# Test Suite Layout

Cantrip's tests are organised in concentric rings of fidelity. Each ring picks up where the
inner one stops, so we don't pay the cost of a slower layer to assert something the faster
layer already covers.

```
tests/
├── conftest.py           # Project-wide fixtures and protocol fakes (see "Shared fakes")
├── support/              # Reusable test infrastructure shared across all layers
│   ├── providers.py      #   RecordingProvider, CallbackProvider, MultiRoleProvider
│   ├── tools.py          #   make_stub_tool — minimal Tool stand-in
│   ├── worktrees.py      #   FakeAllocator, AllocCall, ReleaseCall
│   ├── roles.py          #   StubEmbed, StubRerank
│   ├── mcp_fakes.py      #   FakeMCPClient/Registry + MCP-Apps content blocks
│   ├── git_fakes.py      #   FakeTask — minimal task shape for build_pr_body
│   ├── wait.py           #   wait_until / wait_for_task_status / wait_for_queue_state
│   └── transcript_seed.py#   Seeds a `.cantrip` session store for export tests
├── unit/                 # Pure unit tests — fast, no subprocesses, no real network
│   ├── conftest.py       #   (none — uses the project-wide one)
│   ├── agent/            #   Agent-internal modules (executor, planner, race, …)
│   ├── executor/         #   conftest with shared `_make_executor` helper
│   ├── subagent/         #   conftest with `_make_context` and `_make_tool` (mock execute)
│   ├── llm/              #   Provider adapters and role router
│   ├── planner/          #   Planner branches (design, day-2, replan)
│   └── …                 #   Additional feature-scoped suites
├── integration/          # In-process integration — real WorkQueue, real subagent loop
│   ├── conftest.py       #   Re-exports from tests.support.*; integration-only fixtures
│   └── …                 #   Wires the executor end-to-end with provider doubles
├── e2e/                  # Subprocess / Juju-driving suites (`make e2e`, manually invoked)
├── eval/                 # Provider-in-loop eval harness against gold-standard charms
├── live/                 # Live-network smoke tests (rarely run; require credentials)
└── spread/               # Spread-driven integration runs
```

## When to use which layer

* **`tests/unit/`** — anything you can exercise without spinning up a real subagent loop or
  reaching the filesystem in ways that aren't mocked. Most modules belong here.
* **`tests/integration/`** — when you need the work-queue, executor, and subagent assembled
  with real wiring but mocked LLM / network. Reach for `MultiRoleProvider` or
  `CallbackProvider` from `tests.support.providers`.
* **`tests/e2e/`** — when you need a real Juju controller, charmcraft pack, or Cantrip CLI
  subprocess. These are gated behind `make e2e` and do not run by default.
* **`tests/eval/`** — when measuring a real provider's behaviour against gold-standard
  outputs. Cost-bearing; opt-in.

## Shared fakes — "build on top of, don't fork"

Anything reusable across layers lives in `tests/support/` or — for the most pervasive
fakes — in `tests/conftest.py`. Reach for these before writing your own.

| Helper | Module | What it stands in for |
|--------|--------|-----------------------|
| `FakeProvider` | `tests.conftest` | `cantrip.llm.base.LLMProvider` — replays canned responses |
| `FakeGitService` | `tests.conftest` | `executor.GitService` protocol |
| `FakeStateService` | `tests.conftest` | `executor.StateService` protocol |
| `FakeEnvironmentChecker` | `tests.conftest` | `executor.EnvironmentChecker` protocol |
| `FakeFollowupPlanner` | `tests.conftest` | `executor.FollowupPlanner` protocol |
| `RecordingProvider` | `tests.support.providers` | `FakeProvider` that captures messages / temperature / thinking_budget |
| `CallbackProvider` | `tests.support.providers` | `FakeProvider` whose response is a callback over messages |
| `MultiRoleProvider` | `tests.support.providers` | `FakeProvider` with separate planner / subagent queues |
| `make_stub_tool` | `tests.support.tools` | `cantrip.agent.tools.base.Tool` — minimal placeholder |
| `FakeAllocator` | `tests.support.worktrees` | `cantrip.agent.worktree.WorktreeAllocator` |
| `StubEmbed` / `StubRerank` | `tests.support.roles` | `cantrip.llm.roles.EmbedProvider` / `RerankProvider` |
| `FakeMCPClient` / `FakeMCPRegistry` | `tests.support.mcp_fakes` | `cantrip.mcp.client.MCPClient` / registry — canned `call_tool` responses (set `key_arg` to key on an argument) |
| `FakeTextBlock` / `FakeUIBlock` / `FakeMetaResourceBlock` | `tests.support.mcp_fakes` | MCP SDK content blocks driving `_content_to_structured` |
| `FakeTask` | `tests.support.git_fakes` | Minimal task shape (`title`/`category`/`status`/`result`) for `build_pr_body` |
| `wait_until` / `wait_for_*` | `tests.support.wait` | Polling helpers — replace fixed `asyncio.sleep` waits |
| `seed_cli_export_session` | `tests.support.transcript_seed` | Populates a `.cantrip` store with messages, tasks, events |

If you find yourself defining a `_StubX` / `_FakeX` class inline inside a test file, check
this table first — and if your case is genuinely different, consider whether the shared
helper should grow a parameter rather than living as a parallel definition.

## conftest layering

* **`tests/conftest.py`** — auto-loaded by every test. Holds the project-wide fakes,
  the `--run-slow` CLI flag, and the `_disable_pypi_update_check` autouse fixture.
* **`tests/integration/conftest.py`** — adds `RESEARCH_PLAN_JSON`, `BUILD_PLAN_JSON`,
  `SAMPLE_DESIGN_MD` canned planner outputs and the `fast_executor` fixture; re-exports
  shared providers / wait helpers so existing tests keep working with their old
  import paths.
* **`tests/unit/executor/conftest.py`** — `_make_executor` helper assembling a
  `BackgroundExecutor` with sensible defaults.
* **`tests/unit/subagent/conftest.py`** — `_make_context` / `_make_tool` helpers,
  the latter wraps `tests.support.tools.make_stub_tool` with an `AsyncMock` so tests
  can assert on `tool.execute.await_args`.

When adding a new conftest fixture, prefer the closest scope that covers every test that
needs it. If two parallel directories want the same fixture, push it down to the parent
conftest or out to `tests/support/`.

## Running tests

```bash
make unit          # Full unit suite via pytest-xdist (~1 min vs ~4 min serial)
make check         # Lint + unit (the "is my branch ready" loop)
make all           # Format + check
make coverage      # Unit + coverage report
make e2e           # End-to-end runs (slow, requires a controller)

# Single-target runs
uv run pytest tests/unit/test_tools.py -v
uv run pytest tests/unit/test_tools.py::test_name -v
uv run pytest tests/unit/test_tools.py -v --run-slow   # Opt into @pytest.mark.slow
```

## Snapshot tests (syrupy)

Tests that freeze a large, deterministic text or structured output — rendered
prompts, parsed-design task lists — use [`syrupy`](https://github.com/syrupy-project/syrupy)
instead of hand-maintained SHA256 / length / substring assertions, so an
unintended change shows up as a readable diff. Ask for the `snapshot` fixture and
compare against it:

```python
def test_planning_prompt_snapshot(snapshot) -> None:
    assert _build_planning_prompt(_CANONICAL_CONTEXT) == snapshot
```

The on-disk snapshot lives in a `__snapshots__/` directory **next to the test
file**, in a `.ambr` file named after the module (e.g.
`tests/unit/agent/__snapshots__/test_planner_prompt_snapshots.ambr`). Commit the
`.ambr` alongside the test. After an *intentional* change, regenerate and review
the diff before committing:

```bash
uv run pytest path/to/test_file.py --snapshot-update   # rewrite this file's snapshots
```

Drop any non-deterministic fields (uuids, timestamps) from the value before
asserting — snapshot a normalised view, not the raw object. Snapshots are for
stable, high-volume output; a handful of field assertions stays a plain `assert`.

**Not** snapshotted: TUI rendering. Textual's pilot tests cover actions and
state; the render layer churns too much for golden files to pay off.

## Adding a new shared fake

1. Find the right home — `tests/conftest.py` for project-wide protocol fakes,
   `tests/support/<topic>.py` otherwise.
2. Keep the public surface small: name + docstring stating what protocol/contract it
   stands in for, and which assertions it supports (`.calls`, `.alloc_calls`, …).
3. Add a row to the table above.
4. If your new fake replaces an inline `_StubX` / `_FakeX`, port the call sites in the same
   change — leaving both alive defeats the point.
