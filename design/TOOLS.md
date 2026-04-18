# Agent Tools

This document covers the tool system under `src/cantrip/agent/tools/`:
the abstraction, the registration pattern, and how to add or remove
tools.  It is the companion to [AGENT.md](AGENT.md) (which describes
*when* the agent uses tools) and [PROMPTS.md](PROMPTS.md) (which
describes how tool schemas end up in the LLM call).

## The `Tool` abstraction

Every tool the agent can call is a subclass of `Tool`
(`src/cantrip/agent/tools/base.py`):

```python
class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]: ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult: ...
```

- **`name`** — the string the LLM uses to invoke the tool.  Convention:
  `snake_case`, namespaced by subsystem (`juju_status`, `git_commit`,
  `charmcraft_pack`).
- **`description`** — a short sentence the LLM reads to decide *when*
  to call the tool.  Keep it under ~200 characters.  Guidance about
  *how* to use the tool belongs in skills, not descriptions.
- **`parameters`** — a JSON Schema object (the same shape accepted by
  OpenAI / Anthropic / Gemini tool-use APIs).  `tool_to_schema()`
  bundles name + description + parameters into the payload the
  provider expects.
- **`execute()`** — `async def`, returns a `ToolResult`
  (`success: bool`, `output: str`, `data: dict`, `error: str | None`).
  `execute_tool()` in `base.py` wraps each call in a try/except that
  catches the standard exception set and converts them into
  `success=False` results so a tool crash never crashes the agent.

`PathAwareTool` (`tools/files.py`) is a base for tools that operate on
paths relative to the charm directory — it threads `base_path` through
so file tools work correctly when the charm lives in a worktree.

## The `build_tools()` factory

`src/cantrip/agent/tools/__init__.py` centralises construction.
`build_tools(base_path=..., skills_index=..., virtual_store=...,
provider=..., state=..., queue=...)` returns a `list[Tool]` — every
tool instance the agent will expose, in a stable order.  Call sites
pass this list to `CantripAgent`, which stores it as a `dict[name,
Tool]` for lookup.

Dependency injection is explicit: tools that need the skills index,
virtual-file store, or access to the executor queue take those as
constructor arguments.  There is no global registry, no auto-
discovery, no plugin mechanism — `build_tools()` is the single source
of truth.

## Adding a tool

1. **Create the module** under `src/cantrip/agent/tools/`.  Group by
   subsystem (`juju.py`, `git.py`, `charm.py`) rather than creating a
   one-class file per tool unless the tool is large (`audit.py`,
   `charmlint_tool.py`).  Name the class `<Action>Tool`
   (`JujuStatusTool`, `GitCommitTool`).
2. **Implement the four abstract members.**  Put JSON Schema for
   `parameters` as a class-level property returning a literal dict —
   no runtime generation.
3. **Import** the class in `tools/__init__.py`'s import block (tools
   are imported from per-subsystem modules, not individually).  Keep
   alphabetical ordering within a group — ruff will re-sort.
4. **Add to the `build_tools()` factory** under the appropriate
   section comment (`# File operations`, `# Juju operations`, etc.).
   Instantiate with any dependencies it needs.

That's it.  No settings to register, no hook to install, no test
boilerplate beyond the tool's own unit test.

## Removing a tool

1. Delete the class (or the whole module if it was the last tool
   there).
2. Remove the import and the `build_tools()` instantiation.
3. Remove the tool's unit test file if it existed.

Grep for the tool's `name` string to make sure no skill or subagent
prompt still references it — if so, update or remove those too.

## Naming conventions

| Concern | Convention | Example |
|---|---|---|
| Module | snake_case subsystem | `juju.py`, `charmhub.py` |
| Class | `<Action>Tool` PascalCase | `JujuStatusTool` |
| Tool name (LLM-facing) | `subsystem_verb` snake_case | `juju_status`, `git_commit` |
| One-tool-per-file | only for >200-line tools | `audit.py`, `rodney.py` |

`oci_registry.py` is the renamed-from-`registry.py` module holding
Docker Hub / OCI image search — the name was changed in Phase 53.4 to
avoid implying it was a tool registry.

## Tool categories currently in play

The `build_tools()` factory groups tools by section comment.  The
current list (not authoritative — read `tools/__init__.py` for the
source of truth):

- **File operations** — read, write, edit, list, grep, glob, multi-edit
- **Audit & lint** — charm_audit, charmlint, operational_readiness
- **Charm build** — charmcraft_init, charmcraft_pack, quick_pack,
  charm_validate, fetch_libs, analyse_framework
- **Terraform** — generate, validate
- **Publishing** — upload, release, generate_readme / icon / docs /
  diagram / load_test
- **Demo** — showboat, rodney
- **Web** — fetch, search
- **Charmhub** — search, info
- **OCI registry** — search, image_info
- **Rockcraft** — init, pack, skopeo_push
- **Environment** — concierge_prepare, concierge_status
- **Git** — the full clone/init/status/diff/log/add/commit/push/
  branch/checkout/stash set
- **GitHub** — repo_create, pr_create / list / view, issue_list,
  pr_review, pr_review_reply
- **Juju** — the full status / deploy / refresh / relate / ssh /
  run_action / model / offer / consume / config / wait / sync /
  dispatch / secrets / relation_data / get_app_config / list_offers /
  remove_application / show_unit set
- **Observability** — debug_log, stream_logs, tempo_query, loki_query
- **Inference** — list_inference_snaps
- **Testing** — run_charm_tests, generate_tests, hook_benchmark,
  fuzz_test, chaos_test, acceptance (relation_smoke, action_exerciser,
  config_under_load, config_variation, workload_endpoint), scaling,
  upgrade
- **Publishing & reports** — test_report
- **Skills** — load_skill
- **Task management** — manage_tasks, plan_tasks

## Error handling contract

`execute_tool()` catches a deliberate, narrow set: `OSError`,
`ValueError`, `RuntimeError`, `KeyError`, `AttributeError`,
`UnicodeDecodeError`, `subprocess.SubprocessError`.  Anything else
propagates — a tool should not be silencing uncommon exceptions on
its own.  Tools should prefer returning `ToolResult(success=False,
error=...)` to raising when the failure is semantic
(a missing file, a Juju-side error) rather than structural.

## What a tool is *not*

- **Not a prompt.**  The `description` field is a decision aid, not a
  mini-prompt.  Guidance about methodology belongs in skills.
- **Not a god.**  A tool does one thing.  `juju.py` has 21 classes
  rather than one fat `JujuTool` with a `command` parameter because
  the LLM reasons better about explicit tool names than about string
  arguments.
- **Not a side-effect firehose.**  Tools report what they did via
  `ToolResult.output`.  They should not print, log at INFO, or write
  to stderr unless the operation genuinely benefits from it (the
  `log` call inside `execute_tool()` for caught exceptions is
  debugging affordance, not user-facing).
