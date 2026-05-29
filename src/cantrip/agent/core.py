"""Core agent logic."""

import asyncio
import logging
import os
import pathlib
import re
import sqlite3
import subprocess
import time
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any

from cantrip.agent import (
    auto_commit,
    context_providers,
    context_providers_builtin,
    sandbox,
)
from cantrip.agent import flows as flows_module
from cantrip.agent import recipes as recipes_module
from cantrip.agent.arena_controller import ArenaController
from cantrip.agent.cache_monitor import CacheCascadeDetector
from cantrip.agent.commands import custom as custom_commands
from cantrip.agent.confirmations import ConfirmationsController
from cantrip.agent.context import (
    SHORT_SESSION_INTURN_FOLD_AFTER,
    ContextManager,
    VirtualFileStore,
    resolve_short_session_mode,
)
from cantrip.agent.design import parse_design_from_result
from cantrip.agent.emotions import ParliamentResult, run_parliament
from cantrip.agent.executor_controller import ExecutorController
from cantrip.agent.git_branch import (
    PUSH_CONFIRM_PREFIX,
    PrFeedback,
    create_branch,
    gh_pr_view,
)
from cantrip.agent.mcp_controller import MCPController
from cantrip.agent.memory import (
    AutoWriter,
    MemoryEntry,
    MemoryManager,
    TriggerKind,
    WriteMemoryContext,
    collect_file_citations,
)
from cantrip.agent.permissions import (
    PLAN_MODE_ALLOWED_TOOLS,
    PermissionDecision,
    plan_mode_message,
)
from cantrip.agent.persistence import PersistenceController
from cantrip.agent.planner import (
    PlanningContext,
    TaskPlanner,
    find_day2_anchor,
    is_one_shot_build,
    plan_day2_ops_phase,
    plan_improvement_fixes,
    plan_one_shot_build,
)
from cantrip.agent.preflight import (
    DEFAULT_PRESET,
    PreflightCallback,
    PreflightResult,
    PreflightRunner,
)
from cantrip.agent.prompts import agents_md, build_dynamic_context, build_system_prompt
from cantrip.agent.queue import (
    AgentTask,
    TaskCategory,
    TaskStatus,
    WorkflowPhase,
    WorkQueue,
)
from cantrip.agent.repo_map_service import RepoMapService
from cantrip.agent.retry import RetryEvent, complete_with_retry, stream_with_retry
from cantrip.agent.session_preview import SessionPreview
from cantrip.agent.skills import SkillsIndex
from cantrip.agent.snapshots import SnapshotManager
from cantrip.agent.state import AgentState, Decision, TestResults
from cantrip.agent.store import SessionStore
from cantrip.agent.tool_builder import ToolBuilder
from cantrip.agent.tools import (
    Tool,
    ToolResult,
    expand_leaves,
    resolve_subcommand,
)
from cantrip.agent.triage_controller import TriageController
from cantrip.agent.usage_tracker import UsageTracker
from cantrip.agent.watcher import WatcherConfig, WatcherEvent
from cantrip.agent.watcher_controller import WatcherController
from cantrip.codeintel import CodeIntel
from cantrip.hooks import (
    HookEvent,
    HookResult,
    HookRunner,
    HookStats,
    final_arguments,
    first_veto,
)
from cantrip.llm import base as llm
from cantrip.llm import create_provider, resolve_light_provider, roles
from cantrip.llm.base import Chunk, LLMProvider, Message, Response, Role
from cantrip.repomap import RepoMap

if TYPE_CHECKING:
    from cantrip.mcp import MarketplaceLoader, MarketplaceSource, MCPRegistry
from cantrip.ui import events as ui_events
from cantrip.ui import flavour

log = logging.getLogger(__name__)

# Re-export for backwards compatibility.
__all__ = ["AgentState", "CantripAgent", "Decision"]

# Maximum tool-call rounds before we force the model to respond with text.
MAX_TOOL_ROUNDS = 20

# Tools whose results may contain a test summary to surface in the TUI.
_TEST_RESULT_TOOLS = frozenset({"run_charm_tests", "charm_validate"})

# Maximum characters of a failed tool's combined error + output to
# forward on the ``TOOL_INVOKED`` event so the chat surfaces can offer
# a failure drill-down — long enough for a traceback or a pytest tail,
# short enough that a runaway log doesn't bloat the event bus.  The
# per-tool truncation already trims most outputs well below this.
_TOOL_FAILURE_DETAIL_MAX_CHARS = 8_000

# Purposes that can use the light model.
_LIGHT_PURPOSES = frozenset({"compaction"})

# Pattern for GitHub HTTPS and SSH remote URLs.
_GITHUB_HTTPS_RE = re.compile(r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?$")
_GITHUB_SSH_RE = re.compile(r"git@github\.com:([^/]+/[^/]+?)(?:\.git)?$")

# User-correction phrases that trigger the auto-writer.  Reasonably
# specific to avoid false positives ("don't" appears in plenty of
# conversational text); the auto-writer's own gating heuristic provides
# the second filter so a borderline match still costs only one LLM call.
_USER_CORRECTION_RE = re.compile(
    r"(?:^\s*(?:no|actually|wait|stop)[,.!\s]"
    r"|\b(?:don'?t|do not)\s+(?:do|use|run|call|invoke|create|edit|push|commit|delete|change|modify|add|use)"
    r"|\b(?:that(?:'s| is)) (?:wrong|not right|incorrect)\b"
    r"|\bnot what i\b"
    r"|\bnot (?:like|how) (?:that|i)\b"
    r"|^\s*(?:always|never)\b"
    r"|\bplease (?:always|never|stop|don'?t)\b"
    r"|\binstead\b)",
    re.IGNORECASE,
)


def _is_user_correction(message: str) -> bool:
    """Return True when *message* looks like a correction worth recording.

    Conservative match — the auto-writer's gating decides whether to
    actually persist anything.  False negatives are fine (the agent can
    always be asked again); false positives waste an LLM call.
    """
    if not message or not message.strip():
        return False
    return bool(_USER_CORRECTION_RE.search(message))


#: Guidance appended to the system prompt when :attr:`AgentState.plan_mode` is
#: on.  Asks the agent to produce a "Proposed changes" section at the end of
#: each turn so ``/build`` can resume from a concrete list instead of
#: re-planning from scratch.  Kept short so it doesn't crowd the real system
#: prompt — the permission gate refusal message already tells the LLM what it
#: can and can't do when it tries.
_PLAN_MODE_GUIDANCE = (
    "## Plan mode (read-only)\n\n"
    "The user has put this session into **plan mode**.  You may read the "
    "code, inspect Juju state, read git history, and fetch web content, "
    "but you cannot edit files, run shell commands, deploy, or mutate the "
    "model in any way.  Every non-read-only tool will return a refused "
    "``ToolResult`` — do not retry the same call hoping it will go through.\n"
    "\n"
    "Your job in plan mode is to *think through* the change with the user.  "
    "End every response with a section titled **Proposed changes** listing "
    "concrete edits (``path/to/file`` — what to change and why) and "
    "commands (``$ cmd``) you would run.  Leave any work queue tasks you "
    "create marked as pending so they do not execute.  The user will flip "
    "to ``/build`` when they are satisfied, and that summary will be re-"
    "fed as context so you can execute without re-planning."
)


#: Phase 103.1: one-shot directive prepended to the system prompt while
#: ``state.was_resumed`` is True.  A resumed session has been
#: serialised+rehydrated through the SQLite store, so the model's
#: in-conversation memory of file bytes is unreliable — calling
#: ``edit_file`` against an ``old_string`` synthesised from that memory
#: lands a ``String not found`` error and burns a round on rediscovery.
#: The directive forces a ``read_file`` first; ``_execute_tool`` clears
#: the flag after the first successful ``read_file`` so the directive
#: stops bloating subsequent turns.
_RESUMED_MUST_READ_GUIDANCE = (
    "## Resumed session — re-read before editing\n\n"
    "This conversation was loaded from a prior session.  File contents "
    "you remember from earlier turns may have drifted on disk, and "
    "post-rehydrate ``edit_file`` calls that trust in-conversation memory "
    "of bytes commonly fail with ``String not found``.\n"
    "\n"
    "Before any ``edit_file`` / ``write_file`` / ``multi_edit`` call, you "
    "**must** first ``read_file`` to confirm the current bytes.  This "
    "directive is one-shot — it goes away as soon as you read a file, "
    "and from then on you can edit normally."
)


#: Regex that captures the body of a ``## Proposed changes`` (or similar)
#: section at the end of an assistant response.  Intentionally flexible on
#: heading depth and capitalisation so the LLM doesn't have to emit a
#: specific shape.  We stop at the next same-or-higher-level heading or
#: the end of the string — whichever comes first.
_PROPOSED_CHANGES_RE = re.compile(
    r"(?im)^\s*#{2,6}\s*Proposed\s+Changes\s*\n(.+?)(?:\n\s*#{1,6}\s|\Z)",
    re.DOTALL,
)


#: File extensions worth picking up from user messages when scanning
#: for path-shaped tokens (Phase 70.3 conditional guidance).  Anchored
#: to charm-relevant types — Python, charm metadata YAML, the charm
#: rock/snap manifests, docs, and the standard Python project files.
#: Lower-case match; we coerce the extracted token before comparison.
_PATH_LIKE_EXTENSIONS = frozenset(
    {
        "py",
        "yaml",
        "yml",
        "toml",
        "md",
        "json",
        "txt",
        "j2",
        "cfg",
        "ini",
        "sh",
        "svg",
        "rock",
        "rst",
    }
)

#: Bare filenames worth matching even without an extension match — these
#: are charm-canonical files an author refers to by name in plain
#: prose ("look at metadata.yaml", "actions are wrong").  Kept narrow so
#: a stray "README" in conversation doesn't trigger every skill.
_PATH_LIKE_BARENAMES = frozenset(
    {
        "Makefile",
        "Dockerfile",
        "Justfile",
        "Procfile",
        "Rockfile",
    }
)

#: Captures path-shaped tokens in user messages.  Conservative: the
#: token must contain a slash or end in a known extension, and must
#: not start or end on a separator-like character.  Backticks and
#: quotes around paths (``a markdown ``conventional`` shape``) are
#: stripped by the caller before this regex runs.
_PATH_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_/.-])"
    r"(?P<path>[A-Za-z0-9_./-]*[A-Za-z0-9_-]\.[A-Za-z0-9]{1,8}"
    r"|(?:[A-Za-z0-9_-]+/)+[A-Za-z0-9_.-]+)"
    r"(?![A-Za-z0-9_/.-])"
)


def _extract_user_mentioned_files(
    text: str, charm_path: pathlib.Path | None
) -> list[pathlib.Path]:
    """Pick file-path-shaped tokens out of *text*.

    Powers Phase 70.3 conditional guidance: a user message naming
    ``metadata.yaml`` should pull the metadata-authoring skill into
    the prompt even if the agent has not yet touched that file on
    disk.  Returns ``Path`` objects resolved against ``charm_path``
    when relative; existence on disk is *not* required because the
    user might be asking for a file that does not exist yet.

    Tokens are filtered to a charm-relevant extension set
    (:data:`_PATH_LIKE_EXTENSIONS`) plus a small list of
    extensionless filenames (:data:`_PATH_LIKE_BARENAMES`) so
    arbitrary words like ``today.is`` or version strings like
    ``1.2.3`` don't pull skills in.
    """
    if not text:
        return []

    # Strip backticks and surrounding quotes so ``"src/charm.py"`` and
    # ``\`metadata.yaml\``` tokens land cleanly in the matcher.
    cleaned = text.replace("`", " ").replace('"', " ").replace("'", " ")

    seen: set[pathlib.Path] = set()
    ordered: list[pathlib.Path] = []
    for match in _PATH_TOKEN_RE.finditer(cleaned):
        raw = match.group("path").strip(".")
        if not raw:
            continue
        suffix = raw.rsplit(".", 1)[-1].lower() if "." in raw else ""
        basename = raw.rsplit("/", 1)[-1]
        if suffix not in _PATH_LIKE_EXTENSIONS and basename not in _PATH_LIKE_BARENAMES:
            continue
        candidate = pathlib.Path(raw)
        if not candidate.is_absolute() and charm_path is not None:
            candidate = charm_path / candidate
        if candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)
    return ordered


def _extract_proposed_changes(content: str) -> str | None:
    """Return the body of a ``## Proposed changes`` section or ``None``.

    Cantrip asks for the section by name in :data:`_PLAN_MODE_GUIDANCE`, so
    the extractor is conservative: it only recognises the canonical heading.
    An absent section returns ``None`` and the caller leaves
    :attr:`AgentState.plan_summary` unchanged.
    """
    match = _PROPOSED_CHANGES_RE.search(content)
    if match is None:
        return None
    body = match.group(1).strip()
    return body or None


def _plan_mode_refusal(state: AgentState, tool_name: str) -> ToolResult | None:
    """Return a synthetic refused :class:`ToolResult` when plan mode blocks *tool_name*.

    Phase 68.4: plan mode lets the main agent use only the read-only
    toolset defined by :data:`PLAN_MODE_ALLOWED_TOOLS`.  MCP-provided
    tools bypass the check (mirroring the Phase 80 policy enforcer's
    MCP exemption) because those are gated per-server in
    ``mcp.yaml`` and aren't inherently destructive.  Returns
    ``None`` when the call is permitted so the caller can proceed
    normally.
    """
    if not state.plan_mode:
        return None
    if tool_name.startswith("mcp__"):
        return None
    if tool_name in PLAN_MODE_ALLOWED_TOOLS:
        return None
    return ToolResult(
        success=False,
        output="",
        error=plan_mode_message(tool_name),
    )


def _tool_failure_detail(result: ToolResult) -> str | None:
    """Assemble the failure drill-down text for a failed :class:`ToolResult`.

    Combines the tool's short ``error`` summary with its captured
    ``output`` (stderr, test logs, tracebacks) — skipping the output
    when it merely repeats the error — and caps the total length so a
    runaway log can't bloat the event bus.  Returns ``None`` when the
    result is successful or carries no usable text.
    """
    if result.success:
        return None
    error = (result.error or "").strip()
    output = (result.output or "").strip()
    parts = [error] if error else []
    if output and output != error:
        parts.append(output)
    detail = "\n\n".join(parts)
    if not detail:
        return None
    if len(detail) > _TOOL_FAILURE_DETAIL_MAX_CHARS:
        detail = "…(truncated)\n" + detail[-_TOOL_FAILURE_DETAIL_MAX_CHARS:]
    return detail


def detect_github_repo(charm_path: pathlib.Path | None) -> str | None:
    """Detect a GitHub owner/repo from the git remote origin URL.

    Parses both HTTPS (``https://github.com/owner/repo``) and SSH
    (``git@github.com:owner/repo``) remote URLs.  Returns a string
    like ``"canonical/grafana-k8s"`` or *None* if the remote is not a
    GitHub URL or git is unavailable.
    """
    if charm_path is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["git", "remote", "get-url", "origin"],
            cwd=str(charm_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    for pattern in (_GITHUB_HTTPS_RE, _GITHUB_SSH_RE):
        m = pattern.match(url)
        if m:
            return m.group(1)
    return None


class CantripAgent:
    """Main Cantrip agent."""

    def __init__(
        self,
        provider: LLMProvider,
        charm_path: pathlib.Path | None = None,
        light_provider: LLMProvider | None = None,
        hook_runner: HookRunner | None = None,
        role_router: "roles.RoleRouter | None" = None,
        short_session: str | None = None,
    ):
        """Initialise the agent.

        Heavy work (skills discovery, tool creation, session store) is
        deferred until first use so that startup stays fast.

        When *light_provider* is given it is used for internal tasks
        like context compaction, saving cost on the primary model.

        When *hook_runner* is given, its registered hooks are fired
        at the lifecycle events documented on :class:`HookEvent`.
        Callers that want config-driven hooks should build the
        runner with ``HookRunner.from_disk(charm_path)``; tests and
        internal callers can pass a custom runner or let this default
        to an empty runner (a no-op).

        Phase 72.3: *role_router* registers the providers that serve
        the ``embed`` and ``rerank`` roles for retrieval features.
        Defaults to an empty router; retrieval-using callers raise
        :class:`~cantrip.llm.roles.RoleNotConfigured` until a
        provider is registered.

        Phase 104: *short_session* is the ``--short-session`` override
        (``"on"`` / ``"off"`` / ``"auto"``).  ``None`` falls back to
        ``CANTRIP_SHORT_SESSION`` and finally to ``"auto"``, which
        defers to :attr:`LLMProvider.short_session_mode` — tight-context
        local snaps then run the aggressive-compaction, ledger-and-drop,
        per-turn-ephemeral flow; frontier APIs keep rich history.
        """
        self.provider = provider
        self._light_provider = light_provider
        self.role_router = role_router if role_router is not None else roles.RoleRouter()
        if charm_path is not None and not isinstance(charm_path, pathlib.Path):
            charm_path = pathlib.Path(charm_path)
        self.state = AgentState(charm_path=charm_path)
        # Phase 107: tool-call failure cap is tunable via env var so
        # operators on slow / unreliable local models can loosen it,
        # while CI runs that need fast-fail can tighten it.  Anything
        # outside [1, 50] is silently ignored — runaway loops are the
        # whole point of the cap so a 500-fail budget would defeat it.
        cap_raw = os.environ.get("CANTRIP_TOOL_FAILURE_CAP")
        if cap_raw is not None:
            try:
                cap_value = int(cap_raw)
            except ValueError:
                log.warning(
                    "Ignoring CANTRIP_TOOL_FAILURE_CAP=%r — expected an integer",
                    cap_raw,
                )
            else:
                if 1 <= cap_value <= 50:
                    self.state.tool_failure_cap = cap_value
                else:
                    log.warning(
                        "Ignoring CANTRIP_TOOL_FAILURE_CAP=%r — must be in [1, 50]",
                        cap_raw,
                    )
        self.state.github_repo = detect_github_repo(charm_path)
        if self.state.github_repo:
            log.info("Detected GitHub remote: %s", self.state.github_repo)
        self._work_queue = WorkQueue()
        self._event_bus = ui_events.EventBus()
        self._preflight = PreflightRunner(self.state)
        self._hook_runner = hook_runner if hook_runner is not None else HookRunner()
        self._hook_stats = HookStats()
        # Every hook execution flows through ``_on_hook_result`` so
        # the stats accumulator and the transcript stay in sync;
        # listener exceptions are swallowed inside the runner so a
        # misconfigured session store can never break the agent.
        self._hook_runner.set_listener(self._on_hook_result)

        # Context window management.
        self._virtual_store = VirtualFileStore()
        self._short_session_override = short_session
        self._context_manager = ContextManager(
            virtual_store=self._virtual_store,
            context_window_tokens=provider.context_window_tokens,
            short_session_mode=resolve_short_session_mode(provider, short_session),
        )

        # Lazy-initialised on first access via properties.
        self._skills_index_cache: SkillsIndex | None = None
        self._tools_cache: list[Tool] | None = None
        self._tool_map_cache: dict[str, Tool] | None = None
        self._store: SessionStore | None = None
        self._store_initialised = False
        self._memory_manager_cache: MemoryManager | None = None
        self._auto_writer_cache: AutoWriter | None = None
        self._memory_background_tasks: set[asyncio.Task[Any]] = set()
        # Phase 70.3: dedupe transcript events for glob-conditional skill
        # filtering.  ``_build_system_prompt`` is hot — re-emitting an
        # identical decision every turn would drown the transcript.  We
        # remember the last (loaded, skipped) signature and only record
        # when the set actually changes.
        self._last_skill_filter_signature: tuple[tuple[str, ...], tuple[str, ...]] | None = None
        self._mcp = MCPController(
            state=self.state,
            event_bus=self._event_bus,
            invalidate_tools_cache=self._invalidate_tools_cache,
        )

        self._watcher_ctl = WatcherController(
            state=self.state,
            event_bus=self._event_bus,
            work_queue=self._work_queue,
            ensure_store=self._ensure_store,
            get_store=lambda: self._store,
        )
        self._executor_ctl = ExecutorController(
            state=self.state,
            event_bus=self._event_bus,
            publish_tool_invoked=self._publish_tool_invoked,
            publish_tool_invoked_pending=self._publish_tool_invoked_pending,
            on_cache_usage=self._accumulate_subagent_cache,
        )
        self._triage_ctl = TriageController(
            state=self.state,
            event_bus=self._event_bus,
            work_queue=self._work_queue,
            ensure_store=self._ensure_store,
            get_store=lambda: self._store,
        )

        # Session-level prompt cache accumulators (Claude-specific).
        self.cache_creation_tokens: int = 0
        self.cache_read_tokens: int = 0
        # Phase 78.1: watches per-turn cache deltas for the "was reading,
        # now only creating" pattern that flagged Anthropic's April 23
        # incident.  Observes response usage in ``_record_usage``.
        self._cache_monitor = CacheCascadeDetector()

        self._arena_ctl = ArenaController(
            provider=self.provider,
            get_light_provider=lambda: self._light_provider,
            get_memory_manager=lambda: self._memory_manager,
            ensure_store=self._ensure_store,
            get_store=lambda: self._store,
        )

        self._confirmations = ConfirmationsController(
            state=self.state,
            work_queue=self._work_queue,
            ensure_store=self._ensure_store,
            get_store=lambda: self._store,
            create_feature_branch=self._create_feature_branch,
            build_push_confirm_task=self._build_push_confirm_task,
            detect_github_repo=lambda p: detect_github_repo(p),
        )

        self._persistence = PersistenceController(
            state=self.state,
            work_queue=self._work_queue,
            ensure_store=self._ensure_store,
            get_store=lambda: self._store,
            reset_store=self._reset_store,
            restore_safety_state=self._context_manager.restore_safety_state,
            restore_cache_tokens=self._restore_cache_tokens,
            rebuild_messages=self._rebuild_messages_from_active_branch,
        )

        # Phase 68.1: per-turn working-tree snapshots feed ``/undo``.
        # Built lazily so sessions that never touch a charm path or
        # opt out via ``--no-snapshots`` pay no init cost.  Lives on
        # the agent so the slash-command dispatcher can reach it.
        self._snapshot_manager_cache: SnapshotManager | None = None

        # Phase 71.1: graph-ranked symbol map of the active charm repo.
        # Lazy — sessions without a charm path skip it entirely; the
        # first ``_build_system_prompt`` call kicks off the parse.
        self._repo_map_cache: RepoMap | None = None

        # Phase 97.3: substrate summary (controllers, active cloud,
        # MicroCloud detection).  Cached for the agent's lifetime; the
        # first ``_build_system_prompt`` call shells out, subsequent
        # calls reuse the result.  Set to a sentinel ``False`` after a
        # failed probe so we don't retry on every turn.
        self._substrate_cache: Any = None

        # Phase 72b: read-only code-intelligence index.  Built lazily
        # via :pyattr:`code_intel`; the codeintel tools call into it
        # through ``self._code_intel_or_none`` so a session without a
        # charm path returns a clean error rather than crashing on the
        # missing index.
        self._code_intel_cache: CodeIntel | None = None

        # Phase 68.3: load user-defined slash commands from
        # ``.cantrip/commands/*.md`` + ``~/.config/cantrip/commands/*.md``
        # once at startup.  The dispatcher reads
        # ``agent.custom_commands`` and surfaces each command in
        # ``/help``, autocomplete, and the verb fall-through path.
        # Malformed files log a warning and are skipped inside the
        # loader so a single bad file can't prevent the agent booting.
        self.custom_commands: custom_commands.CustomCommandRegistry = (
            custom_commands.CustomCommandRegistry(
                commands=tuple(custom_commands.discover_custom_commands(charm_path=charm_path))
            )
        )

        # Phase 73.1: load parameterised recipes from
        # ``.cantrip-recipes/*.yaml`` (repo) and
        # ``~/.config/cantrip/recipes/*.yaml`` (user).  Sibling-of-SQLite
        # path matches Phase 51b's ``.cantrip-shared/`` precedent.  The
        # ``/recipe`` dispatcher reads ``agent.recipes`` for the catalogue
        # and the per-name lookup; malformed files log + skip.
        self.recipes: recipes_module.RecipeRegistry = recipes_module.RecipeRegistry(
            recipes=tuple(recipes_module.discover_recipes(charm_path=charm_path))
        )

        # Phase 69.4: load flow skills from the bundled
        # ``cantrip/flows/`` root, ``~/.config/cantrip/flows/``, and
        # ``<charm>/.cantrip-flows/``.  Same precedence rules as recipes;
        # ``/flow`` reads ``agent.flows`` for the catalogue and per-flow
        # render.  Malformed files log + skip in the loader.
        self.flows: flows_module.FlowRegistry = flows_module.FlowRegistry(
            flows=tuple(flows_module.discover_flows(charm_path=charm_path))
        )

        # Phase 72.2: ``@``-mention context providers.  Built once at
        # startup with the baseline set; third-party MCP/hook
        # registrations append via ``self.context_providers.register``.
        # The TUI and Web input layers read this registry to expand
        # mentions before the message reaches the LLM.
        self.context_providers: context_providers.ProviderRegistry = (
            context_providers_builtin.build_default_registry(
                role_router=self.role_router if self.role_router.has_embed() else None,
                code_intel_getter=self._code_intel_or_none,
                # Phase 72.2 follow-up: lazy getter so ``@terminal`` reads
                # ``self._store`` at expansion time — sessions that swap
                # stores mid-run (resume + branch) still get the right
                # backing store.
                store_getter=lambda: getattr(self, "_store", None),
            )
        )

        if charm_path:
            self._ensure_agents_md(charm_path)
        self._usage = UsageTracker(self)
        self._tool_builder = ToolBuilder(self)
        self._repo = RepoMapService(self)

    @property
    def event_bus(self) -> ui_events.EventBus:
        """The shared UI event bus."""
        return self._event_bus

    @property
    def snapshot_manager(self) -> SnapshotManager | None:
        """Phase 68.1: lazy-built snapshot manager backing ``/undo`` and ``/redo``.

        Returns ``None`` when the session has no charm path or
        ``state.snapshot_enabled`` is false.  Callers that want to
        snapshot must check for ``None`` and skip silently — the
        agent must keep running even when undo history is unavailable.
        """
        if not self.state.snapshot_enabled:
            return None
        if self.state.charm_path is None:
            return None
        if self._snapshot_manager_cache is None:
            self._snapshot_manager_cache = SnapshotManager(
                self.state.charm_path,
                event_bus=self._event_bus,
            )
        return self._snapshot_manager_cache

    @property
    def work_queue(self) -> WorkQueue:
        """The agent's work queue, for TUI and executor access."""
        return self._work_queue

    def lifecycle_label(self) -> str:
        """Phase 99.4: project current state into a Codex-style lifecycle label.

        Returns one of ``running`` / ``paused`` / ``done`` / ``blocked`` /
        ``budget-limited`` per :func:`cantrip.agent.lifecycle.lifecycle_label`.
        Read-only — every input lives on existing fields, so callers can
        invoke this on every task / pause / budget event without worrying
        about mutating state.  The TUI status bar and the Web UI status
        indicator both call this so the two surfaces never disagree.
        """
        from cantrip.agent.lifecycle import lifecycle_label

        return lifecycle_label(
            user_paused=self._executor_ctl.user_paused,
            tasks=self._work_queue.all_tasks(),
        )

    @property
    def context_manager(self) -> ContextManager:
        """The agent's context manager, for TUI status display."""
        return self._context_manager

    @property
    def hook_runner(self) -> HookRunner:
        """The agent's hook runner, for slash commands and tests."""
        return self._hook_runner

    @property
    def hook_stats(self) -> HookStats:
        """Per-hook telemetry aggregator feeding the ``/hooks`` command."""
        return self._hook_stats

    def _on_hook_result(self, result: HookResult) -> None:
        """Listener fired by :class:`HookRunner` after each hook run.

        Feeds the result into :class:`HookStats` and writes a
        ``hook_invocation`` transcript event so the ``/hooks``
        slash command can show running totals and ``cantrip hooks
        test`` debugging matches what the agent actually did.
        """
        self._hook_stats.record(result)
        if self._store is None:
            return
        detail = {
            "hook_name": result.name,
            "event": result.event.value,
            "exit_code": result.exit_code,
            "duration_seconds": round(result.duration_seconds, 4),
            "vetoed": result.vetoed,
            "timed_out": result.timed_out,
            "continue_on_error": result.continue_on_error,
        }
        # Only the first 200 chars of stderr — a failing hook's
        # backtrace can be arbitrarily long and we don't want to
        # balloon the transcript database.
        if result.stderr:
            detail["stderr_excerpt"] = result.stderr.strip()[:200]
        try:
            self._store.record_event("hook_invocation", detail)
        except sqlite3.Error:
            log.debug("Failed to record hook_invocation transcript event", exc_info=True)

    @property
    def _skills_index(self) -> SkillsIndex:
        """Skills index, discovered lazily on first access.

        Passes the charm path as ``project_root`` so project-scope
        ``gh skill install`` destinations (``<charm>/.agents/skills/``,
        ``<charm>/.claude/skills/``) are discovered alongside the
        user-scope directories.
        """
        if self._skills_index_cache is None:
            self._skills_index_cache = SkillsIndex(project_root=self.state.charm_path)
            self._skills_index_cache.discover()
        return self._skills_index_cache

    @property
    def _tools(self) -> list[Tool]:
        """Tool instances, built lazily on first access."""
        if self._tools_cache is None:
            self._tools_cache = self._build_tools()
            # Expand leaves so the dispatch map can find a bundle's
            # leaf by its canonical name (``juju_deploy``) — that's the
            # name the executor uses after rewriting a bundled call,
            # and it matches what permission rules and audit logs are
            # written against.
            self._tool_map_cache = {t.name: t for t in expand_leaves(self._tools_cache)}
        return self._tools_cache

    @property
    def _tool_map(self) -> dict[str, Tool]:
        return self._tool_builder.tool_map()

    @property
    def store(self) -> SessionStore | None:
        """Return the session store, initialising lazily if needed."""
        self._ensure_store()
        return self._store

    @property
    def _memory_manager(self) -> MemoryManager:
        """Memory manager over charm-scope (if any) and global-scope memory."""
        if self._memory_manager_cache is None:
            self._ensure_store()
            manager = MemoryManager(
                session_store=self._store,
                charm_path=self.state.charm_path,
            )
            manager.set_write_callback(self._on_memory_written)
            manager.set_recall_callback(self._on_memory_recalled)
            self._memory_manager_cache = manager
        return self._memory_manager_cache

    @property
    def _auto_writer(self) -> AutoWriter:
        """Auto-writer subagent for opportunistic memory capture."""
        if self._auto_writer_cache is None:
            self._auto_writer_cache = AutoWriter(
                provider=self.provider, manager=self._memory_manager
            )
        return self._auto_writer_cache

    def _on_memory_written(self, entry: MemoryEntry) -> None:
        """Forward MemoryManager write callbacks to the UI event bus."""
        try:
            self._event_bus.publish(
                ui_events.memory_written(
                    title=entry.title,
                    scope=entry.scope,
                    kind=entry.kind,
                    source=entry.source,
                )
            )
        except Exception:  # noqa: BLE001 - UI hook must not break memory writes.
            log.debug("memory_written event publish failed", exc_info=True)

    def _on_memory_recalled(self, entry: MemoryEntry) -> None:
        """Forward MemoryManager recall callbacks to the UI event bus."""
        try:
            self._event_bus.publish(
                ui_events.memory_recalled(title=entry.title, scope=entry.scope, kind=entry.kind)
            )
        except Exception:  # noqa: BLE001 - UI hook must not break recall.
            log.debug("memory_recalled event publish failed", exc_info=True)

    def _maybe_schedule_correction_writer(self, user_message: str) -> None:
        """Schedule the auto-writer when the user message looks like a correction.

        Runs as a background task so the conversation loop's response is
        not blocked on a second LLM call.  The task reference is held in
        ``_memory_background_tasks`` until completion to satisfy
        asyncio's "task may be garbage-collected" warning.
        """
        if not _is_user_correction(user_message):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        prior_assistant = self._latest_assistant_text()
        cited_paths = self._collect_recent_file_citations()
        context = WriteMemoryContext(
            trigger=TriggerKind.USER_CORRECTION,
            summary=user_message[:200],
            detail=(f"Agent's prior action: {prior_assistant[:500]}" if prior_assistant else ""),
            cited_paths=cited_paths,
            charm_name=self.state.charm_name,
            charm_path=self.state.charm_path,
            framework=self.state.framework,
        )
        task = loop.create_task(self._auto_writer.write(context))
        self._memory_background_tasks.add(task)
        task.add_done_callback(self._memory_background_tasks.discard)

    def _latest_assistant_text(self) -> str:
        """Return the text content of the most recent assistant message."""
        for msg in reversed(self.state.messages):
            if msg.role == Role.ASSISTANT and msg.content:
                return msg.content
        return ""

    def _collect_recent_file_citations(self, max_messages: int = 20) -> list[pathlib.Path]:
        """Scan the most recent assistant tool calls for file-citation candidates."""
        tool_calls: list[dict[str, Any]] = []
        for msg in self.state.messages[-max_messages:]:
            if msg.role != Role.ASSISTANT:
                continue
            for tc in msg.tool_calls:
                tool_calls.append({"name": tc.name, "arguments": tc.arguments})
        return collect_file_citations(tool_calls, base_path=self.state.charm_path)

    def _current_turn_files(self, *, max_messages: int = 6) -> list[pathlib.Path]:
        """Collect file paths in the active conversational context.

        Used by Phase 70.3 glob-conditional skill loading: the result
        is fed to :meth:`SkillsIndex.format_for_prompt` so skills with
        ``globs:`` frontmatter only enter the prompt when something
        the agent is currently looking at matches.

        The set is the union of three sources, in priority order:

        1. Files cited by recent ``read_file`` / ``write_file`` /
           ``edit_file`` / ``multi_edit`` tool calls (existing
           :meth:`_collect_recent_file_citations`, capped to the same
           20-message window the memory writer uses).
        2. File-path-shaped tokens in the most recent user messages,
           extracted by :func:`_extract_user_mentioned_files`.  These
           need not exist on disk yet — a user asking "edit
           ``metadata.yaml`` to add an interface" should pull the
           metadata skill *before* the file is created.
        3. The active task's title, scanned by the same regex —
           planner-emitted tasks often name the file in scope.

        Duplicates are removed while preserving first-seen order.
        """
        seen: set[pathlib.Path] = set()
        ordered: list[pathlib.Path] = []

        for path in self._collect_recent_file_citations():
            if path not in seen:
                seen.add(path)
                ordered.append(path)

        message_texts: list[str] = []
        for msg in reversed(self.state.messages):
            if len(message_texts) >= max_messages:
                break
            if msg.role == Role.USER and msg.content:
                message_texts.append(msg.content)

        active_task = next(
            (t for t in self._work_queue.all_tasks() if t.status == TaskStatus.ACTIVE),
            None,
        )
        if active_task is None:
            active_task = self._work_queue.next_ready()
        if active_task is not None:
            message_texts.append(active_task.title)
            if active_task.description:
                message_texts.append(active_task.description)

        for text in message_texts:
            for path in _extract_user_mentioned_files(text, self.state.charm_path):
                if path not in seen:
                    seen.add(path)
                    ordered.append(path)

        return ordered

    def _record_skill_filtering(self, current_files: list[pathlib.Path]) -> None:
        """Record which globbed skills loaded vs. were skipped this turn.

        Phase 70.3 observability: writes a ``skill_filter`` side event
        to the session store so a user can audit "why did this skill
        fire?".  Deduplicated against the previous turn — if the same
        set of skills loads and the same set is skipped, no event is
        emitted (the transcript stays focused on actual changes).
        Skills without ``globs:`` frontmatter are unconditional and
        intentionally absent from this report.
        """
        if not any(s.globs for s in self._skills_index.list_skills()):
            return
        report = self._skills_index.filtering_report(
            current_files=current_files,
            charm_path=self.state.charm_path,
        )
        signature = (tuple(report["loaded"]), tuple(report["skipped"]))
        if signature == self._last_skill_filter_signature:
            return
        self._last_skill_filter_signature = signature
        store = self._store
        if store is None:
            return
        try:
            store.record_event("skill_filter", report)
        except sqlite3.Error:
            log.debug("skill_filter event recording failed", exc_info=True)

    def _ensure_store(self) -> None:
        """Initialise the session store on first need."""
        if self._store_initialised:
            return
        self._store_initialised = True
        if self.state.charm_path:
            self._init_store(self.state.charm_path)

    def _reset_store(self) -> None:
        """Clear the store reference and lazy-init flag.

        Called by the persistence controller when archiving or recovering
        from a corrupt database.
        """
        self._store = None
        self._store_initialised = False

    def _init_store(self, charm_path: pathlib.Path) -> None:
        """Initialise the session store, migrating from JSON if necessary."""
        db_path = charm_path / ".cantrip"

        # Migrate from the old directory-based layout.
        old_dir = charm_path / ".cantrip"
        if old_dir.is_dir():
            json_file = old_dir / "session.json"
            backup = charm_path / ".cantrip.bak"
            try:
                if json_file.exists():
                    temp_db = charm_path / ".cantrip.tmp"
                    try:
                        SessionStore.migrate_from_json(json_file, temp_db)
                    except ValueError as exc:
                        # Corrupt or non-UTF-8 ``session.json`` — preserve the
                        # original directory under ``.cantrip.corrupt`` so the
                        # user can inspect it, but don't block startup.
                        log.warning(
                            "Skipping .cantrip/ migration (%s); "
                            "preserving original at .cantrip.corrupt",
                            exc,
                        )
                        temp_db.unlink(missing_ok=True)
                        old_dir.rename(charm_path / ".cantrip.corrupt")
                    else:
                        old_dir.rename(backup)
                        temp_db.rename(db_path)
                        log.info(
                            "Migrated .cantrip/ to SQLite (old directory saved as .cantrip.bak)"
                        )
                else:
                    old_dir.rename(backup)
            except OSError as exc:
                # Read-only filesystem or permission error.  Fall back to an
                # in-memory session rather than crashing the agent at startup.
                log.warning(
                    "Cannot migrate .cantrip/ at %s (%s); using a fresh session",
                    charm_path,
                    exc,
                )
                self._store = None
                return

        self._store = SessionStore(db_path)

        # Route sandbox policy decisions into the transcript so reviewers
        # can audit which bind mounts and network settings every
        # subprocess actually saw (Phase 49.5).  Safe to install even if
        # this agent later shuts down — the sink drops writes when the
        # store is None, and it's replaced per-init so there's at most
        # one live sink.
        def _sandbox_event_sink(name: str, data: dict[str, object]) -> None:
            store = self._store
            if store is not None:
                store.record_event(name, data)

        sandbox.set_event_sink(_sandbox_event_sink)

    def _ensure_agents_md(self, charm_path: pathlib.Path) -> None:
        """Write AGENTS.md and a CLAUDE.md → AGENTS.md symlink into the charm directory.

        AGENTS.md is the cross-tool convention (https://agents.md) read
        by Claude Code, Cursor, Codex, Aider, and others. The CLAUDE.md
        symlink keeps Claude Code's primary discovery path working
        without a duplicate file. Skips if either name already exists.
        """
        if not charm_path.is_dir():
            return
        agents_path = charm_path / "AGENTS.md"
        claude_path = charm_path / "CLAUDE.md"
        if agents_path.exists() or claude_path.exists() or claude_path.is_symlink():
            return
        charm_name = self.state.charm_name or charm_path.name
        content = agents_md.render_agents_md(charm_name, charm_type=self.state.charm_type)
        agents_path.write_text(content)
        claude_path.symlink_to("AGENTS.md")
        log.info("Wrote AGENTS.md to %s (with CLAUDE.md symlink)", charm_path)

    def _record_usage(
        self,
        response: Response,
        provider: LLMProvider | None = None,
    ) -> int | None:
        return self._usage.record_usage(response, provider)

    def _restore_cache_tokens(self, cache_creation_tokens: int, cache_read_tokens: int) -> None:
        """Seed the in-memory prompt-cache accumulators from persisted totals.

        Called on session resume so cache cost and hit-rate pick up where
        the prior session left off — the ``/cost`` block and the
        end-of-session summary both read these in-memory counters, so
        rehydrating them keeps those surfaces accurate across a restart
        without any change to the display code.
        """
        self.cache_creation_tokens = max(0, cache_creation_tokens)
        self.cache_read_tokens = max(0, cache_read_tokens)

    def _accumulate_subagent_cache(
        self, cache_creation_tokens: int, cache_read_tokens: int
    ) -> None:
        """Fold a subagent turn's prompt-cache tokens into the session totals.

        Subagents bill against the same session as the main loop, so their
        cache reads and writes belong in the session-level accumulators
        that ``/cost`` and the end-of-session summary read.  Persisted by
        the executor's ``_record_usage`` too, so resume rehydration (which
        sums every stored row) stays in step with the live counters.

        The cascade detector is deliberately *not* fed here — it watches
        the main conversation's prompt prefix, which subagents don't share.
        """
        if not cache_creation_tokens and not cache_read_tokens:
            return
        self.cache_creation_tokens += cache_creation_tokens
        self.cache_read_tokens += cache_read_tokens
        self._event_bus.publish(
            ui_events.cache_metrics_updated(
                cache_creation_tokens=self.cache_creation_tokens,
                cache_read_tokens=self.cache_read_tokens,
            )
        )

    def _check_cache_cascade(self, usage: dict[str, int]) -> None:
        return self._usage.check_cache_cascade(usage)

    async def _run_compaction(self, *, tokens_before: int, source: str) -> None:
        """Run compaction (with emergency-truncate fallback), bracketed by UI events.

        Publishes ``COMPACTION_STARTED`` / ``COMPACTION_COMPLETED`` around
        the work so the chat pane can show an inline indicator — without
        it users see a multi-second pause with no explanation (the lesson
        from Anthropic's April 23 incident was that silent state changes
        are expensive to diagnose later).  Complements the existing
        ``pre_compact`` / ``post_compact`` hooks which fire but don't
        reach the UI event bus.

        On failure falls back to ``emergency_truncate`` so the loop can
        continue; the ``kind`` field in the completed event
        disambiguates the two paths for downstream listeners.
        """
        strategy = self._context_manager.compaction_strategy
        self._event_bus.publish(
            ui_events.compaction_started(
                tokens_before=tokens_before, source=source, strategy=str(strategy)
            )
        )
        kind = "compact"
        try:
            self.state.messages = await self._context_manager.compact(
                self.state.messages,
                system_prompt=self._build_system_prompt(),
                provider=self._get_provider("compaction"),
                ledger=self.state.ledger,
            )
        except Exception:  # noqa: BLE001 — any compaction failure must fall through to emergency truncation; the loop has to keep running.
            log.warning(
                "Compaction failed, falling back to emergency truncation",
                exc_info=True,
            )
            self.state.messages = self._context_manager.emergency_truncate(self.state.messages)
            kind = "emergency"
        tokens_after = self._context_manager.estimate_tokens(self.state.messages)
        self._persist_compaction_state()
        self._event_bus.publish(
            ui_events.compaction_completed(
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                source=source,
                kind=kind,
                strategy=str(strategy),
            )
        )

    def _persist_compaction_state(self) -> None:
        """Persist compaction counters and surface any pending safety warning.

        Called after each compact/emergency_truncate so budgets (and as
        of Phase 78.3 the ``cycle_detected`` / ``budget_exhausted`` stop
        flags) survive session resume and the user sees cycle/budget
        warnings promptly.
        """
        compactions, emergencies, cycle, exhausted = self._context_manager.safety_state()
        if self._store:
            try:
                self._store.save_compaction_counters(
                    compactions,
                    emergencies,
                    cycle_detected=cycle,
                    budget_exhausted=exhausted,
                )
            except sqlite3.Error:
                log.warning("Failed to persist compaction counters", exc_info=True)
        warning = self._context_manager.consume_safety_warning()
        if warning:
            self.state.messages.append(Message(role=Role.SYSTEM, content=warning))
            log.warning("Compaction safety warning: %s", warning)

    def _snapshot_before_user_turn(self, user_msg: Message) -> None:
        """Phase 68.1: snapshot the working tree before *user_msg* lands.

        Stamps the resulting commit SHA onto :attr:`Message.metadata`
        so ``/undo`` can map the turn back to its pre-state, and
        clears the redo stack — a fresh user turn invalidates any
        previously-undone history.  All failure modes (no charm path,
        snapshots disabled, git missing, repo init failed) leave
        ``user_msg`` untouched and the agent runs uncrippled.
        """
        mgr = self.snapshot_manager
        if mgr is None:
            return
        mgr.clear_redo()
        # ``turn_id`` is the 1-based count of user turns so far —
        # the one being snapshotted is the next one, hence the +1.
        existing_user_turns = sum(1 for m in self.state.messages if m.role == Role.USER)
        turn_id = str(existing_user_turns + 1)
        sha = mgr.snapshot_turn(turn_id)
        if sha is not None:
            user_msg.metadata["snapshot_sha"] = sha

    def _record_message(self, msg: Message) -> int | None:
        """Persist a conversation message to the session store.

        Returns the SQLite row ID of the inserted record, or ``None``
        when the store is not yet initialised.  User-role messages
        also get the row ID stamped onto :attr:`Message.metadata` so
        Phase 68.1 ``/undo`` can map a sliced message back to the
        rows it needs to delete.
        """
        self._ensure_store()
        if not self._store:
            return None
        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in msg.tool_calls
            ]
        tool_results = None
        if msg.tool_results:
            tool_results = [
                {
                    "tool_call_id": tr.tool_call_id,
                    "content": tr.content,
                    "is_error": tr.is_error,
                }
                for tr in msg.tool_results
            ]
        row_id = self._store.record_message(
            role=msg.role.value,
            content=msg.content,
            tool_calls=tool_calls,
            tool_results=tool_results,
            metadata=msg.metadata or None,
        )
        if msg.role == Role.USER:
            msg.metadata["db_message_id"] = row_id
        return row_id

    def _rebuild_messages_from_active_branch(self) -> int:
        """Reload ``state.messages`` from the store's currently active branch.

        Phase 67.1 hook used by both resume (``load_state``) and
        ``/branch`` (which moves the head pointer and then re-reads
        the path).  Clears ``state.messages`` first so a partial
        rehydration leaves nothing stale; rolls forward through the
        branch ordering tool calls / results aren't restored
        (the LLM only needs role + content to keep context, and
        re-running tools on resume would double-pay).  Returns the
        number of messages rehydrated.
        """
        self._ensure_store()
        if self._store is None:
            return 0
        raw_messages = self._store.load_active_branch()
        self.state.messages.clear()
        for msg in raw_messages:
            role_str = msg.get("role", "")
            try:
                role = Role(role_str)
            except ValueError:
                continue
            content = msg.get("content", "")
            if not content:
                continue
            restored = Message(role=role, content=str(content))
            if role == Role.USER and msg.get("id") is not None:
                restored.metadata["db_message_id"] = msg["id"]
            self.state.messages.append(restored)
        return len(self.state.messages)

    def _get_provider(self, purpose: str) -> LLMProvider:
        """Select the appropriate provider for a given purpose.

        Purposes listed in ``_LIGHT_PURPOSES`` are routed to the light
        provider when one is available; everything else uses the primary.
        """
        if self._light_provider and purpose in _LIGHT_PURPOSES:
            return self._light_provider
        return self.provider

    def switch_model(
        self,
        provider_name: str,
        model: str | None = None,
        *,
        base_url: str | None = None,
        snap_name: str = "gemma3",
    ) -> None:
        """Swap the active provider mid-session (Phase 67.2).

        Constructs a new provider via :func:`create_provider`, replaces
        ``self.provider`` atomically, rebuilds the light provider using
        same-family rules, updates the context manager's window, and
        invalidates caches that captured the old provider (tool list,
        auto-writer).  Cost accumulators (``cache_creation_tokens`` /
        ``cache_read_tokens``) survive the swap — they're session
        totals, not per-provider.

        Raises:
            ProviderError / ValueError: Propagated from
                :func:`create_provider` when construction fails (bad
                name, missing API key, missing ``base_url`` for
                ``openai-compatible``).

        Emits a ``model_switched`` event so the status bar, cost
        tracker, and transcript listeners refresh.  Any CLI-configured
        hybrid light provider is dropped in favour of same-family
        routing — callers who relied on a specific light-provider
        combination should restart the session instead.
        """
        new_provider = create_provider(
            provider_name,
            model,
            snap_name=snap_name,
            base_url=base_url,
        )
        previous_provider = self.provider
        self.provider = new_provider
        self._light_provider, _ = resolve_light_provider(
            new_provider,
            provider_name,
        )
        self._context_manager.update_context_window(new_provider.context_window_tokens)
        # When the operator hasn't pinned --short-session, the mode tracks
        # whichever provider is now active (e.g. swapping to a tight-context
        # snap mid-session flips it on; swapping back off).
        self._context_manager.set_short_session_mode(
            resolve_short_session_mode(new_provider, self._short_session_override)
        )
        # Caches that captured the old provider need rebuilding on the
        # next access.  Memory manager is left alone: its provider is
        # used only inside the auto-writer path, which is itself cached
        # here and gets dropped.
        self._tools_cache = None
        self._tool_map_cache = None
        self._auto_writer_cache = None

        if self._store:
            self._store.record_event(
                "model_switched",
                {
                    "provider": new_provider.name,
                    "model": new_provider.model_name,
                    "previous_provider": previous_provider.name,
                    "previous_model": previous_provider.model_name,
                },
            )

        try:
            self._event_bus.publish(
                ui_events.model_switched(
                    provider=new_provider.name,
                    model=new_provider.model_name,
                    previous_provider=previous_provider.name,
                    previous_model=previous_provider.model_name,
                    context_window=new_provider.context_window_tokens,
                )
            )
            self._publish_short_session_status()
        except Exception:  # noqa: BLE001 - UI hook must not break the swap.
            log.debug("model_switched event publish failed", exc_info=True)

    def _publish_short_session_status(self) -> None:
        """Publish the ``[short-session]`` status-bar chip (empty when inactive).

        Fired on a runtime ``/model`` swap so the bar tracks whichever
        provider is now active; the UI also primes the chip directly from
        :attr:`context_manager` at startup.
        """
        chip = "[short-session]" if self._context_manager.short_session_mode else ""
        self._event_bus.publish(ui_events.status_bar_changed(short_session=chip))

    def _invalidate_tools_cache(self) -> None:
        return self._tool_builder.invalidate_tools_cache()

    def _build_tools(self) -> list[Tool]:
        return self._tool_builder.build_tools()

    def _build_system_prompt(self) -> str:
        """Build the current system prompt.

        Uses a compact prompt for providers with limited context windows
        to avoid exceeding the model's capacity.  When plan mode is
        active (Phase 68.4) an appendix explains the read-only stance
        and asks for a *Proposed changes* summary so ``/build`` can
        pick up where the plan left off.

        Per-turn-volatile context (the skills index and repo map) is
        *not* built here — it lives in :meth:`_build_dynamic_context_message`
        and rides along as a trailing ephemeral message so this prompt
        stays byte-stable across turns and the provider's prompt cache
        keeps hitting.
        """
        compact = self.provider.max_tools is not None
        memory_index = self._memory_manager.render_prompt_index() or None
        prompt = build_system_prompt(
            charm_name=self.state.charm_name,
            charm_path=str(self.state.charm_path) if self.state.charm_path else None,
            charm_type=self.state.charm_type,
            framework=self.state.framework,
            dev_model=self.state.dev_model,
            cos_model=self.state.cos_model,
            recent_decisions=[d.to_dict() for d in self.state.decisions],
            memory_index=memory_index,
            environment_ready=self.state.environment_ready,
            watcher_enabled=self.state.watcher_enabled and self.state.watcher_reacting,
            substrate=self._get_substrate_cached(),
            compact=compact,
        )
        if self.state.plan_mode:
            prompt = f"{prompt}\n\n{_PLAN_MODE_GUIDANCE}"
        if self.state.was_resumed:
            prompt = f"{prompt}\n\n{_RESUMED_MUST_READ_GUIDANCE}"
        return prompt

    def _build_dynamic_context_message(self) -> Message | None:
        """Render the per-turn-volatile context as a trailing ephemeral message.

        The skills index (filtered by the files in play this turn) and the
        repo map (scaled by live context pressure) are recomputed every
        turn, so they cannot live in the cached system prompt without
        invalidating the whole prefix on each call.  They ride along as a
        ``USER`` message flagged :attr:`Message.ephemeral` so the provider
        keeps its cache breakpoint on the stable history before it and only
        this small tail is re-sent at full input price.

        Returns ``None`` when there is nothing to inject (no skills, no
        repo map) so :meth:`_build_llm_messages` can skip it entirely.
        """
        compact = self.provider.max_tools is not None
        current_files = self._current_turn_files()
        skills_index = self._skills_index.format_for_prompt(
            current_files=current_files,
            charm_path=self.state.charm_path,
        )
        self._record_skill_filtering(current_files)
        repo_map = None if compact else self._render_repo_map()
        body = build_dynamic_context(skills_index=skills_index, repo_map=repo_map)
        if not body:
            return None
        framed = (
            "<system_note>\n"
            "Current working context (skills you can load, repo map) — reference "
            "material for your own planning, not a user message.  Do not echo it.\n\n"
            f"{body}\n"
            "</system_note>"
        )
        return Message(role=Role.USER, content=framed, ephemeral=True)

    def _get_substrate_cached(self) -> Any:
        """Return the cached :class:`preflight.SubstrateSummary` or ``None``.

        Phase 97.3: substrate detection (controllers, active cloud,
        MicroCloud presence) shells out to ``juju`` and ``snap``.  We
        compute it once on the first ``_build_system_prompt`` call and
        reuse the result for the agent's lifetime.  Probe failures are
        treated as "no substrate info" — the prompt section degrades
        cleanly when the summary is ``None`` or has no fields set.

        Callers wanting to force a refresh (e.g. after a fresh
        ``concierge`` run) clear ``self._substrate_cache`` directly.
        """
        if self._substrate_cache is not None:
            return self._substrate_cache or None
        try:
            from cantrip.agent.preflight import substrate_summary

            self._substrate_cache = substrate_summary()
        except Exception:  # noqa: BLE001 - never block the prompt on a probe error.
            log.debug("substrate_summary probe failed", exc_info=True)
            self._substrate_cache = False  # cache the failure so we don't retry
            return None
        # Mirror the active cloud onto AgentState so the autodeploy hook
        # (which only sees state, not the agent) can pick up the
        # OpenStack acceptance task.  Empty string = "unknown".
        self.state.active_cloud = self._substrate_cache.active_cloud or ""
        return self._substrate_cache

    @property
    def repo_map(self) -> RepoMap | None:
        """The repo-map for the active charm, if one is configured.

        Built lazily on first access; subsequent calls reuse the cache.
        Returns ``None`` when no charm path is set or the path doesn't
        exist on disk — slash commands and tests rely on this to skip
        the section gracefully.
        """
        return self._repo.get_repo_map()

    def refresh_repo_map(self) -> str:
        """Force a full rebuild of the repo-map.

        Used by ``/map-refresh``.  Returns the rendered map at the
        full configured budget, or the empty string when no charm is
        active.
        """
        return self._repo.refresh_repo_map()

    @property
    def code_intel(self) -> CodeIntel | None:
        """Phase 72b read-only code-intelligence index for the active charm.

        Built lazily — same pattern as :attr:`repo_map`.  Returns
        ``None`` when no charm path is set or the path doesn't exist
        on disk; tools handle ``None`` by returning a clear error
        rather than failing silently.
        """
        return self._repo.get_code_intel()

    def _code_intel_or_none(self) -> CodeIntel | None:
        """Bound getter handed to the codeintel tools.

        Lambdas would close over ``self`` just as well, but a named
        method gives the tool layer a stable hook to monkey-patch in
        tests and a tidier ``repr`` if a tool ever logs its
        provenance.
        """
        return self._repo.code_intel_or_none()

    def _render_repo_map(self) -> str | None:
        """Build (incremental) and render the repo-map for prompt injection.

        Returns ``None`` when there's nothing to inject so the Jinja
        ``{% if repo_map %}`` block stays out of the prompt entirely.
        Failures are swallowed: the repo-map is a navigation aid; it
        must never break the conversation loop.  Anything more
        targeted than a bare ``Exception`` would risk a future
        regression where a new error type slips through and kills
        every turn.
        """
        return self._repo.render_repo_map()

    # Phase 110: phase-aware tool curation.  Each :class:`WorkflowPhase`
    # gets a hand-curated ≤11-name set so an inference-snap provider's
    # 12-tool cap can still fit one MCP tool / extension on top.  The
    # active phase is derived from the work-queue task category (or the
    # ``CANTRIP_TOOL_PHASE`` override); see :meth:`workflow_phase`.
    # Names match LLM-facing entries — Juju leaves are bundled behind the
    # single ``juju`` tool, so the sets reference the bundle name; the
    # leaf still dispatches via the subcommand rewrite at the executor.
    _CORE_TOOLS_BY_PHASE: dict[WorkflowPhase, set[str]] = {
        WorkflowPhase.BUILD: {
            "read_file",
            "write_file",
            "edit_file",
            "list_directory",
            "charmcraft_init",
            "quick_pack",
            "charmcraft_pack",
            "charmlint",
            "plan_tasks",
            "run_charm_tests",
            "run_command",
        },
        WorkflowPhase.DEBUG: {
            "read_file",
            "edit_file",
            "list_directory",
            "juju",
            "charmlint",
            "juju_debug_log",
            "juju_status_render",
            "run_command",
            "plan_tasks",
            "run_charm_tests",
            "web_fetch",
        },
        WorkflowPhase.DEPLOY: {
            "juju",
            "concierge_prepare",
            "juju_status_render",
            "juju_debug_log",
            "wait_for",
            "relation_smoke_test",
            "charmcraft_pack",
            "run_command",
            "list_directory",
            "plan_tasks",
        },
        WorkflowPhase.RESEARCH: {
            "read_file",
            "list_directory",
            "web_fetch",
            "web_search",
            "analyse_framework",
            "code_definition",
            "code_references",
            "oracle_consult",
            "plan_tasks",
            "extract_design_decisions",
        },
        WorkflowPhase.DEMO: {
            "read_file",
            "write_file",
            "edit_file",
            "list_directory",
            "charmcraft_init",
            "quick_pack",
            "charmcraft_pack",
            "manage_tasks",
            "plan_tasks",
            "run_charm_tests",
            "run_command",
        },
    }

    #: ``CANTRIP_TOOL_PHASE={research|build|debug|deploy|demo}`` pins the
    #: curated tool slice regardless of work-queue state — useful for
    #: operators driving cantrip through an unusual flow (e.g. a
    #: documentation pass that wants research-tier tools throughout).
    _TOOL_PHASE_ENV = "CANTRIP_TOOL_PHASE"

    def _active_task_category(self) -> TaskCategory | None:
        """Category of the currently-running queue task, or ``None``.

        Falls back to the next ready task so an interactive turn between
        executor picks still gets a sensible scope.
        """
        active = next(
            (t for t in self._work_queue.all_tasks() if t.status == TaskStatus.ACTIVE),
            None,
        )
        if active is None:
            active = self._work_queue.next_ready()
        return active.category if active is not None else None

    @property
    def workflow_phase(self) -> WorkflowPhase:
        """Active workflow phase used to curate the LLM tool slice.

        ``CANTRIP_TOOL_PHASE`` wins if set to a recognised value;
        otherwise the active (or next-ready) work-queue task's category
        maps onto a phase, defaulting to :attr:`WorkflowPhase.BUILD`
        when the conversation is idle.
        """
        override = os.environ.get(self._TOOL_PHASE_ENV, "").strip().lower()
        if override:
            try:
                return WorkflowPhase(override)
            except ValueError:
                log.warning(
                    "%s=%r is not a valid workflow phase; ignoring",
                    self._TOOL_PHASE_ENV,
                    override,
                )
        return WorkflowPhase.from_category(self._active_task_category())

    def _curated_tool_names(self) -> set[str]:
        return self._tool_builder.curated_tool_names()

    def tool_phase_badge(self) -> str:
        """Short badge text for status surfaces, or ``""`` when uncurated.

        Returns e.g. ``"build · 11"`` when the LLM tool slice has been
        narrowed to the active phase's curated set; empty when the full
        toolset is offered (roomy providers), so the badge stays quiet in
        the common case.
        """
        full = len(self._tools)
        offered = len(self._tools_for_llm())
        return f"{self.workflow_phase.value} · {offered}" if offered < full else ""

    def _tools_for_llm(self) -> list[llm.Tool]:
        return self._tool_builder.tools_for_llm()

    async def _execute_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool by name.

        Forwards the per-edit lint flag (Phase 71.4) and the active
        charm directory so :func:`execute_tool` can append ruff /
        ty / charmlint diagnostics to file-edit results.  Subagent
        callers go through :mod:`cantrip.agent.subagent`, which
        uses ``execute_tool`` directly without these arguments.
        """
        from cantrip.agent.tools.base import execute_tool

        result = await execute_tool(
            self._tool_map,
            name,
            arguments,
            auto_lint=self.state.auto_lint,
            charm_path=self.state.charm_path,
        )
        # Phase 103.1: a successful ``read_file`` clears the resume
        # must-read directive — the model has now seen the on-disk
        # bytes, so the next edit doesn't need the prompt nudge.
        if name == "read_file" and result.success and self.state.was_resumed:
            self.state.was_resumed = False
        # Phase 103.4: tick the post-resume hallucination counter from
        # the structured signals the edit tools emit.  ``edit_miss_path``
        # increments the per-file count; ``edit_success_paths`` (or the
        # singular ``edit_success_path`` from ``edit_file``) decrements
        # for each file the agent successfully resolved.
        if name in ("edit_file", "multi_edit") and result.data:
            self._update_edit_string_misses(result.data)
        return result

    def _update_edit_string_misses(self, data: dict[str, Any]) -> None:
        """Apply the Phase 103.4 hallucination-counter signals from *data*."""
        miss_path = data.get("edit_miss_path")
        if isinstance(miss_path, str):
            current = self.state.edit_string_misses.get(miss_path, 0)
            self.state.edit_string_misses[miss_path] = current + 1

        success_path = data.get("edit_success_path")
        success_paths = data.get("edit_success_paths") or []
        candidates: list[str] = []
        if isinstance(success_path, str):
            candidates.append(success_path)
        if isinstance(success_paths, list):
            candidates.extend(p for p in success_paths if isinstance(p, str))
        for path in candidates:
            current = self.state.edit_string_misses.get(path, 0)
            if current <= 1:
                self.state.edit_string_misses.pop(path, None)
            else:
                self.state.edit_string_misses[path] = current - 1

    def _publish_activity(self, label: str) -> None:
        """Publish a status-bar activity update (e.g. "running: charmcraft_pack").

        Used by the main conversation loop so slow tools like
        ``charmcraft_pack`` and ``juju_deploy`` produce visible feedback
        between LLM rounds — without this the bar stuck on a single
        flavour label and the user had no idea a long-running command
        was in flight.
        """
        self._event_bus.publish(ui_events.status_bar_changed(task_label=label))

    def _publish_tool_invoked(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: ToolResult,
        *,
        source: str,
        duration_ms: int | None = None,
        tool_call_id: str | None = None,
    ) -> None:
        """Emit a ``TOOL_INVOKED`` event for the chat surfaces (Phase 75).

        Builds a caption via :func:`build_tool_caption` — the tool's
        own ``ToolResult.caption`` when present, a formulaic
        ``tool_name(key=value)`` fallback otherwise.  Published on the
        shared event bus; the TUI chat widget and the Web UI each
        render a compact tool block when they receive it.

        ``tool_call_id`` (Phase 82) round-trips with the matching
        :meth:`_publish_tool_invoked_pending` event so the renderers can
        update the existing block in place rather than appending a new
        line.  On a failed call the event also carries a ``detail``
        string (error summary + captured output) so the chat surfaces
        can offer a "what went wrong" drill-down.
        """
        from cantrip.agent.tools.base import build_tool_caption

        caption = build_tool_caption(tool_name, arguments, result)
        self._event_bus.publish(
            ui_events.tool_invoked(
                tool_name=tool_name,
                caption=caption,
                success=result.success,
                duration_ms=duration_ms,
                source=source,
                tool_call_id=tool_call_id,
                detail=_tool_failure_detail(result),
            )
        )

    def _publish_tool_invoked_pending(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        source: str,
        tool_call_id: str,
    ) -> None:
        """Emit a ``TOOL_INVOKED_PENDING`` event before tool dispatch (Phase 82).

        Renders the chat-surface "running now" block immediately so
        slow tools (``charmcraft_pack``, ``juju_wait``, ``web_fetch``)
        produce visible feedback the moment they're dispatched rather
        than after they return.  The matching ``TOOL_INVOKED`` event,
        carrying the same ``tool_call_id``, replaces the pending block
        with the post-call caption when the tool finishes.
        """
        from cantrip.agent.tools.base import build_tool_intro_caption

        tool = self._tool_map.get(tool_name) if self._tool_map else None
        caption = build_tool_intro_caption(tool, tool_name, arguments)
        self._event_bus.publish(
            ui_events.tool_invoked_pending(
                tool_name=tool_name,
                caption=caption,
                tool_call_id=tool_call_id,
                source=source,
            )
        )

    def _capture_test_results(self, tool_name: str, result: ToolResult) -> None:
        """Update state with test results if the tool produced a test summary."""
        if tool_name not in _TEST_RESULT_TOOLS:
            return
        data = result.data if hasattr(result, "data") else {}
        if tool_name == "charm_validate":
            summary = data.get("tests", {}).get("summary", {})
        else:
            summary = data.get("summary", {})
        if not summary:
            return
        self.state.test_results = TestResults(
            test_type="unit",
            passed=summary.get("passed", 0),
            failed=summary.get("failed", 0),
            error=summary.get("error", 0),
            skipped=summary.get("skipped", 0),
        )

    def _build_llm_messages(self, include_budget: bool = False) -> list[Message]:
        """Build the full message list for the LLM including system prompt.

        When *include_budget* is True, a transient context budget message
        is appended (not stored in state.messages).

        In short-session mode the accumulated history ledger
        (:attr:`AgentState.ledger`) is rendered into a SYSTEM message
        right after the prompt so a tight-context model retains a thread
        of past actions even though the raw transcript has been dropped.
        Like the budget message, it is built fresh each turn and never
        stored in ``state.messages``.

        The per-turn-volatile dynamic context (skills index, repo map) and
        the budget note are appended *after* the conversation as ephemeral
        messages.  The provider keeps its history cache breakpoint on the
        last non-ephemeral message, so this tail is re-sent at full price
        but never invalidates the cached system + history prefix.
        """
        messages = [Message(role=Role.SYSTEM, content=self._build_system_prompt())]
        if self._context_manager.short_session_mode and self.state.ledger:
            messages.append(self._context_manager.build_ledger_message(self.state.ledger))
        messages.extend(self.state.messages)
        dynamic = self._build_dynamic_context_message()
        if dynamic is not None:
            messages.append(dynamic)
        if include_budget:
            messages.append(self._context_manager.build_budget_message(messages))
        return messages

    def _collapse_messages_for_short_session(self) -> None:
        """Fold the prior conversation into the ledger and reset the working set.

        Called at the start of every user turn in short-session mode (and
        only when there is something to fold).  Conceptually each turn
        becomes a near-fresh session: ``state.messages`` collapses to
        empty here, the new user message is appended by the caller, and
        :meth:`_build_llm_messages` re-renders ``state.ledger`` into the
        prompt.  This also covers resume — the next turn after a restored
        transcript re-derives the ledger from it, so nothing about the
        ledger needs persisting.
        """
        if not self._context_manager.short_session_mode or not self.state.messages:
            return
        carried = len(self.state.messages)
        new_entries = self._context_manager.build_ledger_entries(self.state.messages)
        ContextManager.extend_ledger(self.state.ledger, new_entries)
        self.state.messages = []
        log.info(
            "Short-session: collapsed %d messages into %d new ledger entries at turn start",
            carried,
            len(new_entries),
        )

    def _maybe_fold_oldest_round_into_ledger(self, turn_start_idx: int) -> None:
        """Eagerly fold the oldest completed tool round of this turn into the ledger.

        Once a turn has accumulated more than
        :data:`SHORT_SESSION_INTURN_FOLD_AFTER` completed tool rounds,
        the oldest is distilled into ledger entries and its raw messages
        dropped — keeping the in-conversation working set small without
        waiting for the compaction threshold.  No-op outside
        short-session mode.
        """
        if not self._context_manager.short_session_mode:
            return
        msgs = self.state.messages

        def _round_starts() -> list[int]:
            return [
                i
                for i in range(turn_start_idx + 1, len(msgs))
                if msgs[i].role == Role.ASSISTANT and msgs[i].tool_calls
            ]

        starts = _round_starts()
        while len(starts) > SHORT_SESSION_INTURN_FOLD_AFTER:
            start, nxt = starts[0], starts[1]
            # Only fold a round whose tool results have actually landed.
            if not any(msgs[j].role == Role.TOOL for j in range(start + 1, nxt)):
                break
            folded = msgs[start:nxt]
            new_entries = self._context_manager.build_ledger_entries(folded)
            ContextManager.extend_ledger(self.state.ledger, new_entries)
            del msgs[start:nxt]
            log.info(
                "Short-session: folded oldest in-turn round (%d msgs, %d entries) into ledger",
                len(folded),
                len(new_entries),
            )
            starts = _round_starts()

    async def _complete_with_retry(
        self,
        messages: list[Message],
        tools: list[llm.Tool] | None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        provider: LLMProvider | None = None,
    ) -> Response:
        """Call ``provider.complete()`` with retry and linear backoff for transient errors.

        ``provider`` overrides the default :attr:`self.provider`; used
        by the Phase 71.2 architect/editor split to route the architect
        pass through the main provider and the editor pass through a
        cheaper one.

        ``temperature`` defaults to the active provider's
        :attr:`LLMProvider.conversation_temperature` — frontier APIs
        keep that at 0.7, local quantised snaps clamp it down to
        steady tool-call formatting.

        Phase 102.2: when the chosen provider's
        ``conversation_temperature`` is below 0.7 (i.e. an inference
        snap or any other slow local backend), route through
        :func:`stream_with_retry` instead of
        :func:`complete_with_retry`.  Streaming keeps a TCP heartbeat
        alive so a long single-turn generation doesn't trip the
        backend's keep-alive, and partial assistant text persists to
        the session store as it arrives so a mid-stream disconnect
        leaves a recoverable transcript instead of an empty turn.

        Phase 102.4: a transient retry (rate limit, mid-stream drop)
        publishes a ``[provider reconnect]`` system message on the
        chat surface so the operator sees what's happening rather
        than staring at a frozen UI.
        """
        chosen_provider = provider or self.provider
        if temperature is None:
            temperature = chosen_provider.conversation_temperature

        if chosen_provider.conversation_temperature < 0.7:
            return await self._stream_with_retry_and_writeback(
                chosen_provider,
                messages,
                tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        return await complete_with_retry(
            chosen_provider,
            messages,
            tools,
            temperature=temperature,
            max_tokens=max_tokens,
            on_retry=self._publish_provider_retry,
        )

    async def _stream_with_retry_and_writeback(
        self,
        chosen_provider: LLMProvider,
        messages: list[Message],
        tools: list[llm.Tool] | None,
        *,
        temperature: float,
        max_tokens: int | None,
    ) -> Response:
        """Slow-path streaming wrapper with partial-message persistence.

        Pre-records an empty assistant row, runs
        :func:`stream_with_retry` with a closure that updates that row
        as chunks arrive, then deletes the placeholder on success — so
        the conversation loop's existing canonical-record step writes
        the final row unchanged.  On exception (retries exhausted) the
        partial row is left in place so resume can recover the
        in-flight transcript instead of regenerating from scratch.

        The placeholder is metadata-flagged ``partial: True`` so a
        future inspector tool (or migration) can identify rows left
        behind by an aborted slow-path turn.
        """
        partial_id: int | None = None
        if self._store is not None:
            partial_msg = Message(
                role=Role.ASSISTANT,
                content="",
                metadata={"partial": True},
            )
            partial_id = self._record_message(partial_msg)

        on_partial: Callable[[str], None] | None = None
        if partial_id is not None and self._store is not None:
            store = self._store
            row_id = partial_id

            def _writeback(text: str) -> None:
                try:
                    store.update_message_content(row_id, text)
                except sqlite3.Error:
                    log.debug("partial writeback failed", exc_info=True)

            on_partial = _writeback

        response = await stream_with_retry(
            chosen_provider,
            messages,
            tools,
            temperature=temperature,
            max_tokens=max_tokens,
            on_retry=self._publish_provider_retry,
            on_partial=on_partial,
        )

        # Successful generation — clean up the placeholder so the
        # conversation loop's canonical ``_record_message`` writes the
        # final row without leaving a duplicate behind.  An exception
        # above skips this, leaving the partial content on disk for
        # resume to find.
        if partial_id is not None and self._store is not None:
            try:
                self._store.delete_messages_from(partial_id)
            except sqlite3.Error:
                log.debug("partial-row cleanup failed", exc_info=True)
        return response

    def _publish_provider_retry(self, event: RetryEvent) -> None:
        """Publish a ``[provider reconnect]`` chat row for a retry event.

        Phase 102.4: a slow local snap dropping mid-stream used to
        surface only as a stack trace.  This handler converts the
        retry-layer signal into an inline system message so the user
        sees the reconnect attempt and the wait time before the loop
        resumes.
        """
        kind = (
            "rate-limited"
            if isinstance(event.exception, llm.ProviderRateLimitError)
            else (
                "overloaded"
                if isinstance(event.exception, llm.ProviderOverloadedError)
                else "disconnected"
            )
        )
        delay_str = f"{event.delay:.0f}s" if event.delay >= 1 else f"{event.delay:.1f}s"
        message = (
            f"[provider reconnect] {event.provider_name} {kind} "
            f"(attempt {event.attempt}/{event.max_retries}); "
            f"retrying in {delay_str}…"
        )
        self._event_bus.publish(ui_events.chat_message(role="system", content=message))
        self._event_bus.publish(
            ui_events.status_bar_changed(task_label=f"reconnecting ({delay_str})")
        )

    # ─── Phase 107: Tool-call failure cap ────────────────────────────

    def _track_tool_failure_streak(
        self, tool_name: str, arguments: dict[str, Any], success: bool
    ) -> None:
        return self._usage.track_tool_failure_streak(tool_name, arguments, success)

    def _maybe_warn_before_failure_cap(self) -> None:
        return self._usage.maybe_warn_before_failure_cap()

    def _consecutive_failure_cap_exceeded(self) -> str | None:
        return self._usage.consecutive_failure_cap_exceeded()

    def _mark_active_task_blocked(self, reason: str) -> None:
        """Flip the currently-active work-queue task to ``BLOCKED``.

        Used by Phase 107 to escalate a runaway tool-failure streak so
        Phase 106's exit/escalation paths fire downstream.  No-op when
        no task is active — that case is logged but doesn't unwind the
        loop because the caller is already breaking out of it.
        """
        for task in self._work_queue.all_tasks():
            if task.status == TaskStatus.ACTIVE:
                self._work_queue.set_blocked(task.id, reason=reason)
                log.info("Marked task %r BLOCKED (Phase 107): %s", task.id, reason)
                return
        log.info("Phase 107 cap fired with no active task (reason: %s)", reason)

    # ─── Phase 71.2: Architect / Editor two-model split ──────────────

    _ARCHITECT_INSTRUCTION = (
        "You are operating in *architect* mode for this turn.  Describe "
        "the change you would make in plain prose: which file(s), what "
        "to change, why.  Be specific about line ranges or symbols.  "
        "Do NOT emit tool calls and do NOT write code blocks larger "
        "than a few lines for illustration — a separate *editor* pass "
        "will translate your proposal into the actual edits."
    )

    _EDITOR_INSTRUCTION_TEMPLATE = (
        "Apply the architect's proposal below as concrete tool calls "
        "(``write_file``, ``edit_file``, ``multi_edit``, …).  Edit "
        "exactly the files the architect named; if the proposal is "
        "ambiguous, read the relevant files first.  Do not redesign "
        "the change.\n\n"
        "<architect_proposal>\n{proposal}\n</architect_proposal>"
    )

    def _architect_provider(self) -> LLMProvider:
        """Provider for the architect pass.

        Always the main provider.  ``state.architect_consecutive_failures``
        beyond the threshold also routes the *editor* pass through the
        architect — see :meth:`_editor_provider`.
        """
        return self.provider

    def _editor_provider(self) -> LLMProvider:
        """Provider for the editor pass.

        Resolution order:

        1. Per-session override (``state.editor_provider`` /
           ``editor_model``) — set explicitly via ``/architect on
           provider/model``.  Constructed on-demand via
           :func:`create_provider`; failures fall through to (2).
        2. The session's existing light provider (the one used for
           compaction etc.) when one is configured — same family,
           cheaper variant.
        3. Fallback to the main provider when no lighter variant is
           available.  No cost saving in that case but the dual-pass
           shape stays so the user sees the architect/editor split
           in the transcript.

        When the editor has failed too many turns in a row
        (``architect_consecutive_failures >= architect_failure_threshold``)
        the architect provider is used for both passes — the
        documented escape hatch from a weak editor.
        """
        if self.state.architect_consecutive_failures >= self.state.architect_failure_threshold:
            log.info(
                "Editor escalated to architect provider after %d consecutive failures",
                self.state.architect_consecutive_failures,
            )
            return self.provider
        if self.state.editor_provider:
            try:
                return create_provider(
                    self.state.editor_provider,
                    self.state.editor_model,
                )
            except (ValueError, RuntimeError, OSError) as exc:
                log.warning(
                    "Editor provider override %s/%s failed (%s); falling back to light provider",
                    self.state.editor_provider,
                    self.state.editor_model,
                    exc,
                )
        if self._light_provider is not None:
            return self._light_provider
        return self.provider

    @staticmethod
    def _all_tool_calls_failed(tool_results: list[llm.ToolResult]) -> bool:
        """Predicate driving Phase 71.2 fall-through.

        Returns ``True`` when *every* tool result in the list reports
        ``is_error=True``, ``False`` for an empty list (no calls means
        nothing to fail) or when at least one call succeeded.
        """
        if not tool_results:
            return False
        return all(r.is_error for r in tool_results)

    def _record_architect_editor_event(
        self,
        kind: str,
        response: Response,
        provider: LLMProvider,
    ) -> None:
        """Persist an ``architect_pass`` / ``editor_pass`` transcript event.

        Captures the provider/model attribution so downstream auditors
        can reconstruct who-said-what without joining against the
        ``token_usage`` table.  Best-effort: store errors are logged
        and swallowed so a misconfigured store can't tear down the
        agent loop.
        """
        self._ensure_store()
        if not self._store:
            return
        usage = response.usage or {}
        try:
            self._store.record_event(
                kind,
                {
                    "provider": provider.name,
                    "model": provider.model_name,
                    "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                    "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                    "tool_calls": len(response.tool_calls),
                    "content_excerpt": (response.content or "")[:400],
                },
            )
        except sqlite3.Error:
            log.debug("record_event(%s) failed", kind, exc_info=True)

    # ─── Phase 71.3: Auto-commit-per-turn ─────────────────────────────

    def _maybe_pre_turn_commit_dirty(self) -> None:
        """Commit pre-existing dirty work before the agent runs.

        Gated by ``state.git_auto_commit``; the actual git work
        lives in :mod:`cantrip.agent.auto_commit` so the
        conversation loop stays focused on its own concerns.
        Failures inside the helper are non-fatal (logged at
        DEBUG); we never want a broken auto-commit setup to break
        the agent loop.
        """
        if not self.state.git_auto_commit:
            return
        try:
            auto_commit.pre_turn_commit_dirty(self.state.charm_path)
        except Exception:  # noqa: BLE001 — never break the loop.
            log.debug("auto_commit pre-turn failed", exc_info=True)

    async def _summarise_for_commit(
        self,
        user_message: str,
        files: list[str],
    ) -> str | None:
        """Generate a one-line commit subject via the light provider.

        Returns ``None`` when no light provider is configured or
        when generation fails — :func:`auto_commit.build_commit_message`
        falls back to a user-message-derived subject.  The prompt
        is short to keep latency bounded; the subject is the only
        thing we need (the body is composed by
        :func:`auto_commit.build_commit_message` from raw inputs).
        """
        provider = self._light_provider or self.provider
        prompt = (
            "Write a single-line conventional-commit subject (≤72 "
            "characters, imperative mood, no trailing period) for the "
            "agent's edits below.  Return only the subject line — no "
            "preamble, no markdown.\n\n"
            f"User request: {user_message[:400]}\n"
            f"Files touched: {', '.join(files[:10])}"
        )
        try:
            response = await provider.complete(
                messages=[Message(role=Role.USER, content=prompt)],
                tools=None,
                temperature=0.3,
                max_tokens=80,
            )
        except Exception:  # noqa: BLE001 — fall back to derived subject.
            log.debug("auto_commit summary generation failed", exc_info=True)
            return None
        if response and response.content:
            self._record_usage(response, provider=provider)
            return response.content
        return None

    async def _maybe_post_turn_commit_agent_edits(
        self,
        user_message: str,
        turn_start_idx: int,
    ) -> None:
        """Commit files the agent touched in the just-finished turn.

        Walks ``state.messages[turn_start_idx:]`` to pick out
        file-mutating tool calls; if any fired, generates a commit
        subject via the light provider and lands the commit on
        ``state.charm_path`` with a Cantrip co-author trailer.
        Stamps the resulting SHA on
        ``state.last_cantrip_commit_sha`` for future audit.
        """
        if not self.state.git_auto_commit:
            return
        try:
            turn_slice = self.state.messages[turn_start_idx:]
            touched = auto_commit.collect_touched_files(turn_slice)
            if not touched:
                return
            summary = await self._summarise_for_commit(user_message, touched)
            sha = auto_commit.post_turn_commit_agent_edits(
                self.state.charm_path,
                turn_slice,
                user_message,
                summary=summary,
            )
            if sha:
                self.state.last_cantrip_commit_sha = sha
                self._ensure_store()
                if self._store:
                    try:
                        self._store.record_event(
                            "auto_commit",
                            {
                                "sha": sha,
                                "files": touched[:50],
                                "file_count": len(touched),
                            },
                        )
                    except sqlite3.Error:
                        log.debug("auto_commit event record failed", exc_info=True)
        except Exception:  # noqa: BLE001 — never break the loop.
            log.debug("auto_commit post-turn failed", exc_info=True)

    async def _run_architect_editor_turn(
        self,
        messages: list[Message],
        llm_tools: list[llm.Tool] | None,
    ) -> Response:
        """Run a single conversation-loop step as architect → editor.

        Returns a single :class:`Response` whose ``content`` is the
        editor's text and whose ``tool_calls`` are what the editor
        emitted.  Both passes get their usage recorded individually
        (so ``/cost`` shows two model lines per turn) and a
        transcript event each.

        The architect pass passes ``tools=None`` so a strict
        provider can't sneak a tool call in; the editor pass passes
        the full ``llm_tools`` list and is the source of any actual
        edits.

        Used in place of a single ``_complete_with_retry`` call from
        ``_run_conversation_loop`` and
        ``_run_conversation_loop_streaming`` whenever
        ``state.architect_mode`` is True.
        """
        architect_provider = self._architect_provider()
        # Architect: prepend the architect instruction as a SYSTEM
        # message so it's clear the request is "propose, don't act".
        # Don't mutate the caller's list.
        architect_msgs: list[Message] = list(messages) + [
            Message(role=Role.SYSTEM, content=self._ARCHITECT_INSTRUCTION),
        ]
        architect_resp = await self._complete_with_retry(
            architect_msgs,
            tools=None,
            provider=architect_provider,
        )
        self._record_usage(architect_resp, provider=architect_provider)
        self._record_architect_editor_event("architect_pass", architect_resp, architect_provider)
        try:
            self._event_bus.publish(
                ui_events.chat_message(
                    role="system",
                    content=(
                        f"_Architect ({architect_provider.name}/"
                        f"{architect_provider.model_name}) proposed_."
                    ),
                )
            )
        except Exception:  # noqa: BLE001 — UI hook must not break the loop.
            log.debug("architect_pass UI publish failed", exc_info=True)

        editor_provider = self._editor_provider()
        proposal = architect_resp.content or "(no proposal text)"
        # Editor: append the proposal as a synthetic USER message so
        # the conversation alternates cleanly (the prior message ends
        # ASSISTANT or TOOL — never USER — when this method is called).
        editor_msgs: list[Message] = list(messages) + [
            Message(
                role=Role.USER,
                content=self._EDITOR_INSTRUCTION_TEMPLATE.format(proposal=proposal),
            )
        ]
        editor_resp = await self._complete_with_retry(
            editor_msgs,
            tools=llm_tools,
            provider=editor_provider,
        )
        self._record_usage(editor_resp, provider=editor_provider)
        self._record_architect_editor_event("editor_pass", editor_resp, editor_provider)
        return editor_resp

    def _pause_executor(self) -> None:
        """Pause the background executor while handling a user message."""
        self._executor_ctl.pause()

    def _resume_executor(self) -> None:
        """Resume the background executor after handling a user message."""
        self._executor_ctl.resume()

    async def run_parliament(self, enabled: list[str]) -> ParliamentResult:
        """Convene the inner parliament over the current charm state.

        Experimental feature: each enabled emotion (joy, fear, anger,
        disgust, sadness) reviews the charm through its own lens and
        emits structured suggestions. The emotions run in parallel on
        the light model and have no tools — they react only to the
        context assembled from ``AgentState``.
        """
        provider = self._light_provider or self.provider
        return await run_parliament(
            enabled=enabled,
            provider=provider,
            charm_name=self.state.charm_name,
            charm_type=self.state.charm_type,
            framework=self.state.framework,
            charm_path=self.state.charm_path,
            decisions=[decision.to_dict() for decision in self.state.decisions],
        )

    async def process_message(self, user_message: str) -> str:
        """Process a user message and return the response.

        This handles the full conversation loop including tool calls.
        The loop continues until the model responds without tool calls
        or the maximum number of rounds is reached.

        The background executor is paused while the conversation loop is
        active so that user steering takes priority over autonomous work.
        """
        # Phase 110.1: a new user turn always gets a fresh chance to
        # re-plan, even after a previous turn produced a packed charm.
        self.state.pack_succeeded = False
        self._pause_executor()
        try:
            response = await self._process_message_inner(user_message)
        finally:
            self._resume_executor()
        self._maybe_schedule_correction_writer(user_message)
        return response

    async def _run_conversation_loop(self, user_message: str) -> Response:
        """Shared conversation loop: send a message, execute tool calls, repeat.

        Returns the final ``Response`` once the model responds without tool
        calls (or the maximum round count is reached).
        """
        # Record session start event on first message.
        if not self.state.messages:
            self._ensure_store()
            if self._store:
                self._store.record_event(
                    "session_start",
                    {
                        "provider": self.provider.name,
                        "model": self.provider.model_name,
                        "charm_name": self.state.charm_name,
                    },
                )

        # Phase 70.2: oracle's per-turn budget resets here so each
        # user message gets a fresh allowance.  Session totals and
        # cost cap survive across turns intentionally.
        self.state.oracle_calls_this_turn = 0

        # Phase 71.3: pre-turn dirty-commit so the agent's edits land
        # on a clean base.  Runs before the snapshot is taken so the
        # snapshot itself captures the post-pre-cantrip-commit state
        # (working tree clean, history advanced).  No-op when
        # ``git_auto_commit`` is off, when we're not in a git repo,
        # or when the working tree is already clean.
        self._maybe_pre_turn_commit_dirty()

        # Phase 104: in short-session mode each turn is near-fresh —
        # fold the prior conversation into the ledger and clear the
        # working set before the new user message lands.
        self._collapse_messages_for_short_session()

        user_msg = Message(role=Role.USER, content=user_message)
        user_msg = self._context_manager.virtualise_message(user_msg)
        self._snapshot_before_user_turn(user_msg)
        self.state.messages.append(user_msg)
        self._record_message(user_msg)
        # Track where this turn starts so the post-turn auto-commit
        # only stages files the agent actually touched (rather than
        # walking the whole history).
        turn_start_idx = len(self.state.messages) - 1

        messages = self._build_llm_messages(include_budget=True)
        llm_tools = self._tools_for_llm() if self._tools else None

        # Phase 71.2: when architect_mode is on, every LLM call routes
        # through the dual-pass orchestrator.  Otherwise the existing
        # single-call path runs unchanged.
        if self.state.architect_mode:
            self.state.architect_consecutive_failures = 0
            response = await self._run_architect_editor_turn(messages, llm_tools)
        else:
            response = await self._complete_with_retry(messages, llm_tools)
            self._record_usage(response)

        rounds = 0
        while response.tool_calls and rounds < MAX_TOOL_ROUNDS:
            rounds += 1

            # Record the assistant message with its tool calls.
            assistant_msg = Message(
                role=Role.ASSISTANT,
                content=response.content,
                tool_calls=response.tool_calls,
                metadata=response.metadata,
            )
            self.state.messages.append(assistant_msg)
            self._record_message(assistant_msg)

            # Bundled-tool rewrite: ``juju(subcommand="deploy", ...)``
            # \u2192 ``juju_deploy(...)`` so permissions, audit, hooks and
            # plan mode all see the canonical leaf name they were
            # written against.  Mutation is in-place; the transcript
            # still replays cleanly because ``resolve_subcommand`` is
            # a no-op on a leaf-name call (the leaf lives in
            # ``tool_map`` thanks to ``expand_leaves``).
            for tc in response.tool_calls:
                tc.name, tc.arguments = resolve_subcommand(self._tool_map, tc.name, tc.arguments)

            # Execute each tool and build TOOL result messages.
            tool_results = []
            for tc in response.tool_calls:
                self._publish_activity(f"\u27f3 running: {tc.name}")
                pre_results = await self._hook_runner.fire(
                    HookEvent.PRE_TOOL_CALL,
                    {"tool": tc.name, "arguments": tc.arguments, "source": "main"},
                )
                veto = first_veto(pre_results)
                # Hook-rewritten arguments (Phase 46.4b) flow into both
                # the tool invocation and the post_tool_call payload so
                # audit logs reflect what actually ran.
                effective_arguments = final_arguments(pre_results) or tc.arguments
                # Phase 68.4: plan mode refuses non-read-only tools.
                # We gate after the hook so a hook-rewritten argument
                # stays visible, and before execution so the tool body
                # never runs in read-only mode.  Subagents already hit
                # the full Phase 68.2 permission gate via their own
                # ``PermissionRuleset``; the main agent only consults
                # the plan-mode flag for scope reasons.
                plan_block = _plan_mode_refusal(self.state, tc.name)
                tool_start = time.monotonic()
                # Phase 82: emit the "running now" block before
                # dispatch so slow tools (charmcraft_pack, juju_wait,
                # web_fetch) produce visible feedback immediately.  The
                # matching TOOL_INVOKED below carries the same
                # tool_call_id so the renderer updates the same block
                # in place rather than appending a fresh line.
                self._publish_tool_invoked_pending(
                    tc.name,
                    effective_arguments,
                    source="main",
                    tool_call_id=tc.id,
                )
                if veto is not None:
                    # A pre-hook blocked the call \u2014 synthesise an error
                    # ToolResult so the LLM sees the veto on its next turn
                    # and can react (apologise, retry with different args,
                    # ask the user).  ``post_tool_call`` still fires with
                    # ``success: false`` and a ``vetoed_by`` field so
                    # observability hooks see the full decision record.
                    log.warning(
                        "Tool call %r vetoed by %s",
                        tc.name,
                        veto.veto_reason,
                    )
                    result = ToolResult(
                        success=False,
                        output="",
                        error=f"Blocked by {veto.veto_reason}",
                    )
                elif plan_block is not None:
                    log.info("Tool call %r refused by plan mode", tc.name)
                    result = plan_block
                else:
                    result = await self._execute_tool(tc.name, effective_arguments)
                tool_elapsed_ms = int((time.monotonic() - tool_start) * 1000)
                post_payload: dict[str, Any] = {
                    "tool": tc.name,
                    "arguments": effective_arguments,
                    "success": result.success,
                    "error": result.error,
                    "source": "main",
                }
                if veto is not None:
                    post_payload["vetoed_by"] = veto.name
                await self._hook_runner.fire(HookEvent.POST_TOOL_CALL, post_payload)
                self._publish_activity(f"\u27f3 {flavour.pick_activity_label()}...")
                self._capture_test_results(tc.name, result)
                self._publish_tool_invoked(
                    tc.name,
                    effective_arguments,
                    result,
                    source="main",
                    duration_ms=tool_elapsed_ms,
                    tool_call_id=tc.id,
                )
                self._track_tool_failure_streak(tc.name, effective_arguments, result.success)
                content = result.output if result.success else (result.error or "Unknown error")
                # Wrap tool output in delimiters to reduce prompt injection risk.
                content = f"<tool_result name={tc.name!r}>\n{content}\n</tool_result>"
                tool_results.append(
                    llm.ToolResult(
                        tool_call_id=tc.id,
                        content=content,
                        is_error=not result.success,
                        images=list(result.images),
                    )
                )

            tool_msg = Message(
                role=Role.TOOL,
                content="",
                tool_results=tool_results,
            )
            # Virtualise large tool results before storing.
            tool_msg = self._context_manager.virtualise_message(tool_msg)
            self.state.messages.append(tool_msg)
            self._record_message(tool_msg)

            # Phase 104: in short-session mode, fold the oldest in-turn
            # tool round into the ledger once the turn has built up more
            # than a couple — keeps the live working set tiny.
            self._maybe_fold_oldest_round_into_ledger(turn_start_idx)

            # Phase 107.3: one round before the cap, nudge the model to
            # change approach instead of retrying into a BLOCKED state.
            self._maybe_warn_before_failure_cap()
            # Phase 107: bail when the cap is hit.  Marks the active
            # work-queue task BLOCKED so Phase 106's loop-exit logic
            # fires; ``process_message`` returns its current response
            # text (which we accumulated through earlier rounds even
            # if the most recent rounds all failed).
            cap_reason = self._consecutive_failure_cap_exceeded()
            if cap_reason is not None:
                log.warning("Phase 107 cap fired: %s", cap_reason)
                self._mark_active_task_blocked(cap_reason)
                break

            # Compact if the context window is getting full.
            if self._context_manager.should_compact(self.state.messages):
                log.info("Compacting conversation context")
                tokens_before = self._context_manager.estimate_tokens(self.state.messages)
                pre_compact_results = await self._hook_runner.fire(
                    HookEvent.PRE_COMPACT,
                    {"tokens_before": tokens_before, "source": "main"},
                )
                compact_veto = first_veto(pre_compact_results)
                if compact_veto is not None:
                    # A ``pre_compact`` veto preserves the context as-is —
                    # users pin critical messages with this hook so they
                    # survive the summary rewrite.  No ``post_compact``
                    # fires because compaction didn't run.
                    log.info(
                        "Compaction blocked by %s; context preserved (%d tokens)",
                        compact_veto.veto_reason,
                        tokens_before,
                    )
                else:
                    await self._run_compaction(tokens_before=tokens_before, source="main")
                    await self._hook_runner.fire(
                        HookEvent.POST_COMPACT,
                        {
                            "tokens_before": tokens_before,
                            "tokens_after": self._context_manager.estimate_tokens(
                                self.state.messages
                            ),
                            "source": "main",
                        },
                    )

            # Phase 71.2: track editor-pass failures across rounds so
            # the dual-pass orchestrator can escalate to the architect
            # provider when the cheap editor keeps producing
            # unapplyable patches.  Reset on a turn that succeeded.
            if self.state.architect_mode:
                if self._all_tool_calls_failed(tool_results):
                    self.state.architect_consecutive_failures += 1
                else:
                    self.state.architect_consecutive_failures = 0

            # Call the LLM again with the updated history.
            messages = self._build_llm_messages(include_budget=True)
            if self.state.architect_mode:
                response = await self._run_architect_editor_turn(messages, llm_tools)
            else:
                response = await self._complete_with_retry(messages, llm_tools)
                self._record_usage(response)

        # Store the final assistant response.
        final_msg = Message(
            role=Role.ASSISTANT,
            content=response.content,
            metadata=response.metadata,
        )
        self.state.messages.append(final_msg)
        self._record_message(final_msg)
        # Phase 68.4: harvest a "Proposed changes" section whenever the
        # agent produces one while plan mode is on, so /build can splice
        # it back into context on the switch-over turn.
        if self.state.plan_mode:
            captured = _extract_proposed_changes(response.content or "")
            if captured:
                self.state.plan_summary = captured

        # Phase 71.3: agent commit lands at the very end of the turn,
        # after the final assistant message is recorded so the body's
        # "Touched:" list and the SHA stamped on ``state`` reflect the
        # complete turn.  No-op when no file-mutating tools fired,
        # when ``git_auto_commit`` is off, or when not in a git repo.
        await self._maybe_post_turn_commit_agent_edits(user_message, turn_start_idx)
        return response

    async def _process_message_inner(self, user_message: str) -> str:
        """Inner implementation of process_message (executor already paused)."""
        response = await self._run_conversation_loop(user_message)
        return response.content

    async def process_message_streaming(self, user_message: str) -> AsyncIterator[str]:
        """Process a message with streaming response.

        Yields text chunks as they arrive from the provider's ``stream()``
        method.  When the model requests tool calls, those are executed
        and the model is called again — streaming resumes for each
        subsequent LLM call until a text-only response is produced.

        The background executor is paused while the conversation loop is
        active so that user steering takes priority over autonomous work.
        """
        # Phase 110.1: same per-turn reset as the non-streaming path.
        self.state.pack_succeeded = False
        self._pause_executor()
        try:
            async for chunk in self._run_conversation_loop_streaming(user_message):
                yield chunk
        finally:
            self._resume_executor()
        self._maybe_schedule_correction_writer(user_message)

    async def _run_conversation_loop_streaming(
        self,
        user_message: str,
    ) -> AsyncIterator[str]:
        """Streaming variant of the conversation loop.

        Yields text chunks as they arrive from the provider.  Tool-call
        rounds are handled internally; only text destined for the user
        is yielded.
        """
        # Record session start event on first message.
        if not self.state.messages:
            self._ensure_store()
            if self._store:
                self._store.record_event(
                    "session_start",
                    {
                        "provider": self.provider.name,
                        "model": self.provider.model_name,
                        "charm_name": self.state.charm_name,
                    },
                )

        # Phase 70.2: oracle's per-turn budget resets here so each
        # user message gets a fresh allowance.  Session totals and
        # cost cap survive across turns intentionally.
        self.state.oracle_calls_this_turn = 0

        # Phase 71.3: pre-turn dirty-commit (see non-streaming loop
        # for rationale).  Same hook drives both paths.
        self._maybe_pre_turn_commit_dirty()

        # Phase 104: short-session per-turn collapse (see non-streaming loop).
        self._collapse_messages_for_short_session()

        user_msg = Message(role=Role.USER, content=user_message)
        user_msg = self._context_manager.virtualise_message(user_msg)
        self._snapshot_before_user_turn(user_msg)
        self.state.messages.append(user_msg)
        self._record_message(user_msg)
        turn_start_idx = len(self.state.messages) - 1

        messages = self._build_llm_messages(include_budget=True)
        llm_tools = self._tools_for_llm() if self._tools else None

        # Phase 71.2: architect mode bypasses streaming and runs a
        # dual-pass turn instead.  We yield the editor's content as a
        # single chunk; the architect's proposal is captured in the
        # transcript via ``architect_pass``.  Streaming loses
        # token-by-token rendering inside an architect-mode session,
        # but the dual-pass overhead dominates that cosmetic cost.
        if self.state.architect_mode:
            self.state.architect_consecutive_failures = 0
            response = await self._run_architect_editor_turn(messages, llm_tools)
            if response.content:
                yield response.content
        else:
            # Stream the first LLM call.
            accumulated = ""
            final_chunk = Chunk(is_final=True)
            async for chunk in self.provider.stream(messages=messages, tools=llm_tools):
                if chunk.content:
                    accumulated += chunk.content
                    yield chunk.content
                if chunk.is_final:
                    final_chunk = chunk

            # Build a synthetic Response for bookkeeping.
            response = Response(
                content=accumulated,
                tool_calls=final_chunk.tool_calls,
                usage=final_chunk.usage,
                metadata=final_chunk.metadata,
            )
            self._record_usage(response)

        rounds = 0
        while response.tool_calls and rounds < MAX_TOOL_ROUNDS:
            rounds += 1

            # Record the assistant message with its tool calls.
            assistant_msg = Message(
                role=Role.ASSISTANT,
                content=response.content,
                tool_calls=response.tool_calls,
                metadata=response.metadata,
            )
            self.state.messages.append(assistant_msg)
            self._record_message(assistant_msg)

            # Bundled-tool rewrite \u2014 same as the non-stream path.
            for tc in response.tool_calls:
                tc.name, tc.arguments = resolve_subcommand(self._tool_map, tc.name, tc.arguments)

            # Execute each tool and build TOOL result messages.
            tool_results = []
            for tc in response.tool_calls:
                self._publish_activity(f"\u27f3 running: {tc.name}")
                pre_results = await self._hook_runner.fire(
                    HookEvent.PRE_TOOL_CALL,
                    {"tool": tc.name, "arguments": tc.arguments, "source": "main-stream"},
                )
                veto = first_veto(pre_results)
                effective_arguments = final_arguments(pre_results) or tc.arguments
                plan_block = _plan_mode_refusal(self.state, tc.name)
                tool_start = time.monotonic()
                self._publish_tool_invoked_pending(
                    tc.name,
                    effective_arguments,
                    source="main-stream",
                    tool_call_id=tc.id,
                )
                if veto is not None:
                    log.warning(
                        "Tool call %r vetoed by %s",
                        tc.name,
                        veto.veto_reason,
                    )
                    result = ToolResult(
                        success=False,
                        output="",
                        error=f"Blocked by {veto.veto_reason}",
                    )
                elif plan_block is not None:
                    log.info("Tool call %r refused by plan mode (stream)", tc.name)
                    result = plan_block
                else:
                    result = await self._execute_tool(tc.name, effective_arguments)
                tool_elapsed_ms = int((time.monotonic() - tool_start) * 1000)
                post_payload: dict[str, Any] = {
                    "tool": tc.name,
                    "arguments": effective_arguments,
                    "success": result.success,
                    "error": result.error,
                    "source": "main-stream",
                }
                if veto is not None:
                    post_payload["vetoed_by"] = veto.name
                await self._hook_runner.fire(HookEvent.POST_TOOL_CALL, post_payload)
                self._publish_activity(f"\u27f3 {flavour.pick_activity_label()}...")
                self._capture_test_results(tc.name, result)
                self._publish_tool_invoked(
                    tc.name,
                    effective_arguments,
                    result,
                    source="main-stream",
                    duration_ms=tool_elapsed_ms,
                    tool_call_id=tc.id,
                )
                self._track_tool_failure_streak(tc.name, effective_arguments, result.success)
                content = result.output if result.success else (result.error or "Unknown error")
                content = f"<tool_result name={tc.name!r}>\n{content}\n</tool_result>"
                tool_results.append(
                    llm.ToolResult(
                        tool_call_id=tc.id,
                        content=content,
                        is_error=not result.success,
                        images=list(result.images),
                    )
                )

            tool_msg = Message(
                role=Role.TOOL,
                content="",
                tool_results=tool_results,
            )
            tool_msg = self._context_manager.virtualise_message(tool_msg)
            self.state.messages.append(tool_msg)
            self._record_message(tool_msg)

            # Phase 104: short-session in-turn ledger fold (see non-streaming loop).
            self._maybe_fold_oldest_round_into_ledger(turn_start_idx)

            # Phase 107.3 / 107: pre-cap nudge then cap check, as in the
            # non-streaming loop.
            self._maybe_warn_before_failure_cap()
            cap_reason = self._consecutive_failure_cap_exceeded()
            if cap_reason is not None:
                log.warning("Phase 107 cap fired (stream): %s", cap_reason)
                self._mark_active_task_blocked(cap_reason)
                break

            # Compact if the context window is getting full.
            if self._context_manager.should_compact(self.state.messages):
                log.info("Compacting conversation context")
                tokens_before = self._context_manager.estimate_tokens(self.state.messages)
                pre_compact_results = await self._hook_runner.fire(
                    HookEvent.PRE_COMPACT,
                    {"tokens_before": tokens_before, "source": "main-stream"},
                )
                compact_veto = first_veto(pre_compact_results)
                if compact_veto is not None:
                    log.info(
                        "Compaction blocked by %s; context preserved (%d tokens)",
                        compact_veto.veto_reason,
                        tokens_before,
                    )
                else:
                    await self._run_compaction(tokens_before=tokens_before, source="main-stream")
                    await self._hook_runner.fire(
                        HookEvent.POST_COMPACT,
                        {
                            "tokens_before": tokens_before,
                            "tokens_after": self._context_manager.estimate_tokens(
                                self.state.messages
                            ),
                            "source": "main-stream",
                        },
                    )

            # Phase 71.2: same fall-through tracking as the
            # non-streaming loop — count editor passes whose tools
            # all failed so the next pass can escalate.
            if self.state.architect_mode:
                if self._all_tool_calls_failed(tool_results):
                    self.state.architect_consecutive_failures += 1
                else:
                    self.state.architect_consecutive_failures = 0

            # Separate this round's text from the previous round's, since
            # each round is an independent LLM response with no leading
            # whitespace — without this, sentences run together visually.
            if response.content and not response.content[-1].isspace():
                yield "\n\n"

            # Stream the next LLM call.
            messages = self._build_llm_messages(include_budget=True)
            if self.state.architect_mode:
                response = await self._run_architect_editor_turn(messages, llm_tools)
                if response.content:
                    yield response.content
            else:
                accumulated = ""
                final_chunk = Chunk(is_final=True)
                async for chunk in self.provider.stream(messages=messages, tools=llm_tools):
                    if chunk.content:
                        accumulated += chunk.content
                        yield chunk.content
                    if chunk.is_final:
                        final_chunk = chunk

                response = Response(
                    content=accumulated,
                    tool_calls=final_chunk.tool_calls,
                    usage=final_chunk.usage,
                    metadata=final_chunk.metadata,
                )
                self._record_usage(response)

        # Store the final assistant response.
        final_msg = Message(
            role=Role.ASSISTANT,
            content=response.content,
            metadata=response.metadata,
        )
        self.state.messages.append(final_msg)
        self._record_message(final_msg)

        # Phase 71.3: agent commit at end of streaming turn (mirrors
        # the non-streaming loop).
        await self._maybe_post_turn_commit_agent_edits(user_message, turn_start_idx)

    # -- Design confirmation ---------------------------------------------------

    async def handle_design_confirmation(
        self,
        confirm_task_id: str,
        overrides: str | None = None,
    ) -> list[AgentTask]:
        """Process an approved design-confirm task and generate build tasks.

        1. Finds the synthesis task result from the dependency chain.
        2. Parses it into a ``DesignProposal``.
        3. Records key decisions.
        4. Generates build tasks via the planner.
        5. Adds build tasks to the work queue.
        """
        confirm_task = self._work_queue.get_task(confirm_task_id)
        if confirm_task is None:
            log.error(
                "Design confirm task %s not found — cannot generate build tasks", confirm_task_id
            )
            return []

        # Walk dependencies to find the synthesis result.
        design_text = ""
        for dep_id in confirm_task.dependencies:
            dep = self._work_queue.get_task(dep_id)
            if dep is not None and dep.result:
                design_text = dep.result
                break

        if not design_text:
            log.error(
                "No synthesis result found for design confirmation (task %s)", confirm_task_id
            )
            return []

        # Parse the design and store on state.
        proposal = parse_design_from_result(design_text)
        self.state.design_proposal = proposal

        # Record key decisions.
        if proposal.substrate:
            self.state.add_decision(
                "substrate", proposal.substrate, proposal.substrate_reasoning or None
            )
        if proposal.charm_path:
            self.state.add_decision(
                "charm_path", proposal.charm_path, proposal.charm_path_reasoning or None
            )
        if proposal.charmhub_recommendation:
            self.state.add_decision("charmhub", proposal.charmhub_recommendation)

        # Generate build tasks from the approved design.
        context = PlanningContext(
            intent=f"Build a charm for {proposal.workload_name or 'the workload'}",
            charm_name=self.state.charm_name,
            charm_type=self.state.charm_type or proposal.substrate or None,
            framework=self.state.framework,
            dev_model=self.state.dev_model,
            cos_model=self.state.cos_model,
            environment_ready=self.state.environment_ready,
        )

        design_md = proposal.to_design_md()
        if is_one_shot_build(context) and not overrides:
            build_tasks = plan_one_shot_build(context, design_md)
        else:
            planner = TaskPlanner(self.provider, code_intel=self.code_intel)
            build_tasks = await planner.plan_from_design(
                design_content=design_md,
                context=context,
                overrides=overrides,
            )
        self._work_queue.add_tasks(build_tasks)

        # Append day-2 operations research phase after the build/deploy tasks.
        anchor = find_day2_anchor(build_tasks)
        if anchor:
            day2_tasks = plan_day2_ops_phase(context, depends_on=anchor)
            self._work_queue.add_tasks(day2_tasks)

        self._ensure_store()
        if self._store:
            self._store.record_event(
                "design_confirmed",
                {
                    "workload": proposal.workload_name,
                    "substrate": proposal.substrate,
                    "charm_path": proposal.charm_path,
                    "build_task_count": len(build_tasks),
                },
            )

        return build_tasks

    # -- Day-2 operations confirmation -----------------------------------------

    async def handle_day2_confirmation(
        self,
        confirm_task_id: str,
        overrides: str | None = None,
    ) -> list[AgentTask]:
        """Process an approved day-2 confirm task and generate implementation tasks.

        1. Finds the synthesis task result from the dependency chain.
        2. Generates implementation tasks via the planner.
        3. Adds implementation tasks to the work queue.
        """
        confirm_task = self._work_queue.get_task(confirm_task_id)
        if confirm_task is None:
            log.error(
                "Day-2 confirm task %s not found — cannot generate implementation tasks",
                confirm_task_id,
            )
            return []

        # Walk dependencies to find the synthesis result.
        day2_text = ""
        for dep_id in confirm_task.dependencies:
            dep = self._work_queue.get_task(dep_id)
            if dep is not None and dep.result:
                day2_text = dep.result
                break

        if not day2_text:
            log.error(
                "No day-2 synthesis result found for confirmation (task %s)", confirm_task_id
            )
            return []

        context = PlanningContext(
            intent=(f"Implement day-2 operations for {self.state.charm_name or 'the charm'}"),
            charm_name=self.state.charm_name,
            charm_type=self.state.charm_type,
            framework=self.state.framework,
            dev_model=self.state.dev_model,
            cos_model=self.state.cos_model,
            environment_ready=self.state.environment_ready,
        )

        planner = TaskPlanner(self.provider, code_intel=self.code_intel)
        impl_tasks = await planner.plan_from_day2_findings(
            findings=day2_text,
            context=context,
            overrides=overrides,
        )
        self._work_queue.add_tasks(impl_tasks)

        self._ensure_store()
        if self._store:
            self._store.record_event(
                "day2_confirmed",
                {
                    "charm_name": self.state.charm_name,
                    "impl_task_count": len(impl_tasks),
                },
            )

        return impl_tasks

    # -- Improvement confirmation ----------------------------------------------

    async def handle_improvement_confirmation(
        self,
        confirm_task_id: str,
    ) -> list[AgentTask]:
        """Process an approved improvement-confirm task and generate fix tasks.

        1. Finds the audit task result from the dependency chain.
        2. Infers gaps from the audit report text (the structured ``data``
           dict is only available on the tool result, not persisted in the
           task result string — so we re-derive gaps heuristically).
        3. Generates fix tasks via ``plan_improvement_fixes``.
        4. Adds them to the work queue.
        """
        confirm_task = self._work_queue.get_task(confirm_task_id)
        if confirm_task is None:
            log.error(
                "Improvement confirm task %s not found — cannot generate fix tasks",
                confirm_task_id,
            )
            return []

        # Walk dependencies to find the audit result.
        audit_text = ""
        for dep_id in confirm_task.dependencies:
            dep = self._work_queue.get_task(dep_id)
            if dep is not None and dep.result:
                audit_text = dep.result
                break

        if not audit_text:
            log.error(
                "No audit result found for improvement confirmation (task %s)", confirm_task_id
            )
            return []

        self.state.audit_report = audit_text

        # Derive gaps from the audit text.  The subagent's result is
        # free-form Markdown, so we look for keywords to infer gaps.
        gaps = _infer_gaps_from_audit(audit_text)

        context = PlanningContext(
            intent="Improve the existing charm",
            charm_name=self.state.charm_name,
            charm_type=self.state.charm_type,
            framework=self.state.framework,
            dev_model=self.state.dev_model,
            cos_model=self.state.cos_model,
            environment_ready=self.state.environment_ready,
            existing_charm_path=str(self.state.charm_path) if self.state.charm_path else ".",
        )

        fix_tasks = plan_improvement_fixes(context, gaps, confirm_task_id=confirm_task_id)

        # Create a feature branch for improvement work.
        charm_name = self.state.charm_name or "charm"
        branch = self._create_feature_branch(f"improve-{charm_name}")

        # Append push-confirm task if a branch was created.
        if branch and fix_tasks:
            last_task_id = fix_tasks[-1].id
            fix_tasks.append(self._build_push_confirm_task(branch, last_task_id))

        self._work_queue.add_tasks(fix_tasks)

        self._ensure_store()
        if self._store:
            self._store.record_event(
                "improvement_confirmed",
                {
                    "charm_name": self.state.charm_name,
                    "gap_count": sum(1 for v in gaps.values() if v),
                    "fix_task_count": len(fix_tasks),
                    "branch": branch or "",
                },
            )

        return fix_tasks

    # -- Watcher integration ---------------------------------------------------

    @property
    def watcher_running(self) -> bool:
        """Whether the event watcher is currently running."""
        return self._watcher_ctl.running

    def start_watcher(
        self,
        config: WatcherConfig | None = None,
        on_event: Callable | None = None,
    ) -> bool:
        """Create and start the event watcher."""
        return self._watcher_ctl.start(config=config, on_event=on_event)

    async def stop_watcher(self) -> None:
        """Stop the event watcher if it is running."""
        await self._watcher_ctl.stop()

    @property
    def watcher_reacting(self) -> bool:
        """Whether watcher events are routed to the work queue.

        When ``False`` the watcher keeps observing (status panes and
        ``[Watcher]`` chat notices still update) but detected events do
        not become tasks, so the agent stops reacting autonomously.
        """
        return self.state.watcher_reacting

    def toggle_watcher_reacting(self) -> bool:
        """Flip whether watcher events queue tasks; return the new value."""
        self.state.watcher_reacting = not self.state.watcher_reacting
        return self.state.watcher_reacting

    def route_watcher_event(self, event: WatcherEvent) -> AgentTask | None:
        """Convert a watcher event into a task and add it to the work queue."""
        return self._watcher_ctl.route_event(event)

    async def process_watcher_event(self) -> str | None:
        """Dequeue one watcher event and route it to the task queue."""
        return await self._watcher_ctl.process_event()

    # -- Issue triage integration -----------------------------------------------

    @property
    def issue_triage_running(self) -> bool:
        """Whether the GitHub issue triage worker is active."""
        return self._triage_ctl.running

    def start_issue_triage(self) -> bool:
        """Start the background issue triage worker."""
        return self._triage_ctl.start()

    async def stop_issue_triage(self) -> None:
        """Stop the issue triage worker if running."""
        await self._triage_ctl.stop()

    def retriage_issues(self) -> bool:
        """Re-run issue triage to check for new issues."""
        return self._triage_ctl.retriage()

    def comment_on_issue(self, issue_number: int, pr_url: str) -> str:
        """Post a comment on a resolved GitHub issue."""
        return self._triage_ctl.comment_on_issue(issue_number, pr_url)

    def check_upstream(self) -> str | None:
        """Check if the default branch has diverged from the remote."""
        return self._triage_ctl.check_upstream()

    # -- PR feedback loop (Phase 42.7) ----------------------------------------

    def check_pr_feedback(self, pr_number: int) -> PrFeedback | None:
        """Fetch review feedback for a pull request.

        Returns structured feedback or ``None`` if unavailable.
        """
        repo = self.state.github_repo
        if not repo:
            return None
        return gh_pr_view(repo, pr_number)

    def create_pr_fix_tasks(
        self,
        feedback: PrFeedback,
        branch_name: str,
    ) -> list[AgentTask]:
        """Generate BUILD tasks to address PR review feedback.

        Creates one BUILD task that addresses all review comments,
        plus a push-confirm task at the end.
        """
        charm_path = str(self.state.charm_path) if self.state.charm_path else "."

        # Build a description from the review comments.
        comment_text = "\n".join(
            f"- **{c.author}**" + (f" (`{c.path}:{c.line}`)" if c.path else "") + f": {c.body}"
            for c in feedback.comments
            if c.body
        )

        fix_id = f"pr-fix-{feedback.pr_number}"
        fix_task = AgentTask(
            id=fix_id,
            title=f"Address review feedback on PR #{feedback.pr_number}",
            category=TaskCategory.BUILD,
            description=(
                f"Reviewers have requested changes on PR #{feedback.pr_number}.\n\n"
                f"**Review comments:**\n{comment_text}\n\n"
                f"Address each comment in `{charm_path}`. Commit with a message "
                f"referencing the PR (e.g. 'Address review feedback on #{feedback.pr_number}')."
            ),
        )

        tasks: list[AgentTask] = [fix_task]

        # Add push-confirm after the fix.
        tasks.append(self._build_push_confirm_task(branch_name, fix_id))

        self._work_queue.add_tasks(tasks)

        self._ensure_store()
        if self._store:
            self._store.record_event(
                "pr_fix_tasks_created",
                {
                    "pr_number": feedback.pr_number,
                    "comment_count": len(feedback.comments),
                    "task_count": len(tasks),
                },
            )

        return tasks

    def _create_feature_branch(self, description: str) -> str | None:
        """Create a feature branch if a GitHub remote is detected.

        Returns the branch name on success, or ``None`` if branching is
        not applicable (no GitHub remote or no charm path).
        """
        if not self.state.github_repo or not self.state.charm_path:
            return None
        branch = create_branch(str(self.state.charm_path), description)
        if branch:
            self._ensure_store()
            if self._store:
                self._store.record_event(
                    "branch_created",
                    {"branch": branch, "repo": self.state.github_repo or ""},
                )
        return branch

    def _build_push_confirm_task(
        self,
        branch_name: str,
        last_task_id: str,
    ) -> AgentTask:
        """Build a CONFIRM task asking whether to push a feature branch."""
        return AgentTask(
            id=f"{PUSH_CONFIRM_PREFIX}{branch_name}",
            title=f"Push branch {branch_name}?",
            category=TaskCategory.CONFIRM,
            description=(
                f"All work on branch **{branch_name}** is complete and tests have passed.\n\n"
                f"Approve to push the branch to **origin** (for PR creation).\n"
                f"Skip to leave the branch local for manual review."
            ),
            dependencies=[last_task_id],
        )

    # ── Blind A/B arena (Phase 47.5) ────────────────────────────────────

    @property
    def active_arena(self) -> object | None:
        """The pending blind A/B arena, or ``None`` when idle."""
        return self._arena_ctl.active

    async def begin_arena(self, prompt: str) -> str:
        """Run a blind A/B arena for *prompt* and return the formatted output."""
        return await self._arena_ctl.begin(prompt)

    def handle_arena_pick(self, message: str) -> str | None:
        """Resolve a pending arena pick from a raw user reply."""
        return self._arena_ctl.handle_pick(message)

    def handle_race_confirmation(self, confirm_task_id: str, *, approved: bool) -> str:
        """Resolve a race-cost CONFIRM task and unblock the parent."""
        return self._confirmations.handle_race(confirm_task_id, approved=approved)

    def handle_push_confirmation(self, confirm_task_id: str, *, approved: bool) -> str:
        """Handle an approved or skipped push-confirm task."""
        return self._confirmations.handle_push(confirm_task_id, approved=approved)

    def handle_pr_creation(self, branch_name: str, *, draft: bool = False) -> str:
        """Create a pull request for *branch_name*."""
        return self._confirmations.handle_pr_creation(branch_name, draft=draft)

    def should_offer_bootstrap(self) -> bool:
        """Return ``True`` if repo bootstrap should be offered to the user."""
        return self._confirmations.should_offer_bootstrap()

    def build_repo_bootstrap_confirm_task(self) -> AgentTask:
        """Build the CONFIRM task that offers to create a GitHub repo."""
        return self._confirmations.build_repo_bootstrap_confirm_task()

    def handle_repo_bootstrap(
        self, name: str, *, private: bool = True, description: str = "", org: str = ""
    ) -> str:
        """Create a GitHub repository and push the initial commit."""
        return self._confirmations.handle_repo_bootstrap(
            name, private=private, description=description, org=org
        )

    def handle_triage_confirmation(self, confirm_task_id: str) -> list[AgentTask]:
        """Process an approved triage-confirm task and generate work tasks."""
        return self._confirmations.handle_triage(confirm_task_id)

    # -- Executor integration -------------------------------------------------

    @property
    def _executor(self):
        """Backward-compatible access to the live background executor."""
        return self._executor_ctl._executor

    @property
    def executor_running(self) -> bool:
        """Whether the background executor is currently running."""
        return self._executor_ctl.running

    def start_executor(
        self,
        max_concurrency: int | None = None,
    ) -> None:
        """Create and start the background executor."""
        self._executor_ctl.start(
            queue=self._work_queue,
            tools=self._tools,
            provider=self.provider,
            store=self._store,
            light_provider=self._light_provider,
            hook_runner=self._hook_runner,
            ensure_store=self._ensure_store,
            max_concurrency=max_concurrency,
        )
        # Phase 73.2: wire MCP App iframe tool calls through the same
        # permission gate and audit writer the executor uses.  Done
        # after start so ``self._executor`` exists; the controller
        # silently rejects iframe calls until this fires (defensive —
        # the Web UI doesn't render any iframes before tool dispatch
        # has happened anyway).
        self._wire_mcp_app_dispatcher()

    def _wire_mcp_app_dispatcher(self) -> None:
        """Register the MCP-App permission + dispatch hooks on the controller.

        Permission evaluation reads the *current* executor ruleset on
        every call so a runtime ``/plan`` / ``/build`` mode flip is
        picked up without re-registering.  Dispatch routes through the
        same :func:`execute_tool` helper the agent's tool loop uses,
        so MCP-App calls share validation, error shaping, and post-edit
        lint hooks with agent-initiated calls.  Audit writes land in
        the same ``.cantrip-audit.jsonl`` the rest of the dispatch path
        appends to.
        """
        from cantrip.agent.audit import AUDIT_FILENAME, AuditWriter
        from cantrip.agent.permissions import evaluate as evaluate_permissions
        from cantrip.agent.tools.base import execute_tool as base_execute_tool

        executor = self._executor
        if executor is None:
            return

        def _evaluate(name: str, arguments: dict[str, Any]) -> PermissionDecision:
            return evaluate_permissions(
                executor.permissions,
                name,
                arguments,
                agent_name="mcp-app",
            )

        async def _dispatch(name: str, arguments: dict[str, Any]) -> ToolResult:
            return await base_execute_tool(self._tool_map, name, arguments)

        audit_writer: AuditWriter | None = None
        if self.state.charm_path is not None:
            audit_writer = AuditWriter(pathlib.Path(self.state.charm_path) / AUDIT_FILENAME)

        self._mcp.register_app_dispatcher(
            evaluate_permission=_evaluate,
            dispatch_tool=_dispatch,
            permission_manager=executor.permission_manager,
            audit_writer=audit_writer,
        )

    async def stop_executor(self) -> None:
        """Stop the background executor if it is running."""
        await self._executor_ctl.stop()

    # -- MCP integration ------------------------------------------------------

    @property
    def mcp_registry(self) -> "MCPRegistry":
        """Lazy registry of configured MCP servers — see :class:`MCPController`."""
        return self._mcp.registry

    @property
    def mcp_marketplace_sources(self) -> "list[MarketplaceSource]":
        """Marketplace sources declared in user + repo MCP configs."""
        return self._mcp.marketplace_sources

    @property
    def mcp_marketplace_loader(self) -> "MarketplaceLoader":
        """Lazy :class:`MarketplaceLoader` shared across slash-command calls."""
        return self._mcp.marketplace_loader

    async def start_mcp(self) -> None:
        """Open every configured MCP connection.  Idempotent."""
        await self._mcp.start()

    def _on_mcp_elicitation(self, request: object) -> None:
        """Forward an MCP elicitation request to the UI event bus."""
        self._mcp.handle_elicitation(request)

    def complete_mcp_elicitation(
        self,
        request_id: str,
        action: str,
        content: dict[str, Any] | None = None,
    ) -> bool:
        """UI entry point — answer a parked MCP elicitation by id."""
        return self._mcp.complete_elicitation(request_id, action, content)

    async def stop_mcp(self) -> None:
        """Tear down every MCP connection.  Best-effort, never raises."""
        await self._mcp.stop()

    def save_state(self) -> None:
        """Save agent state to the session store."""
        self._persistence.save_state()

    def preview_session(self) -> SessionPreview:
        """Peek at the persisted session without mutating agent state."""
        return self._persistence.preview_session()

    def transcript_tail(self, limit: int = 20) -> list[Message]:
        """Return the last ``limit`` persisted messages, for "review" mode."""
        return self._persistence.transcript_tail(limit)

    def archive_session(self) -> pathlib.Path | None:
        """Rename the current ``.cantrip`` file aside so a fresh session can start."""
        return self._persistence.archive_session()

    def load_state(self) -> bool:
        """Load agent state from the session store."""
        return self._persistence.load_state()

    def build_resume_summary(self) -> str | None:
        """Build a structured summary of prior session work."""
        return self._persistence.build_resume_summary()

    async def prepare(
        self,
        preset: str = DEFAULT_PRESET,
        callback: PreflightCallback | None = None,
    ) -> PreflightResult:
        """Run the full environment preparation eagerly.

        Calls ``concierge prepare --preset {preset}`` (installing snaps *and*
        bootstrapping) so the environment is ready by the time the user
        finishes describing their charm.
        """
        self._preflight = PreflightRunner(self.state, callback=callback)
        result = await self._preflight.prepare(preset)
        self.state.environment_ready = result.fully_ready
        return result

    async def warm_up(self, callback: PreflightCallback | None = None) -> PreflightResult:
        """Run phase 1 preflight: install snaps without bootstrapping."""
        self._preflight = PreflightRunner(self.state, callback=callback)
        return await self._preflight.warm_up()

    async def bootstrap_environment(
        self,
        preset: str,
        callback: PreflightCallback | None = None,
    ) -> PreflightResult:
        """Run phase 2 preflight: bootstrap controller and deploy COS.

        If ``prepare()`` already completed with the same preset, this is a
        no-op.
        """
        if self._preflight.result.fully_ready and self._preflight.result.preset == preset:
            return self._preflight.result

        self._preflight._callback = callback
        result = await self._preflight.bootstrap(preset)
        self.state.environment_ready = result.fully_ready
        return result

    @property
    def preflight_result(self) -> PreflightResult:
        """Current preflight result."""
        return self._preflight.result


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _infer_gaps_from_audit(text: str) -> dict[str, bool]:
    """Derive a gaps dictionary from free-form audit Markdown.

    The ``CharmAuditTool`` emits structured ``data["gaps"]`` on its tool
    result, but subagent task results are plain text summaries.  This
    function heuristically scans the text for keywords to reconstruct
    the boolean gaps map that ``plan_improvement_fixes`` expects.

    Matching is done at the sentence level (splitting on ``.``, ``\\n``,
    and ``*``/``-`` list markers) to avoid false positives from keywords
    co-occurring in unrelated sections of the document.
    """
    # Split into sentences / list items for scoped matching.
    sentences = re.split(r"[.\n]|\s[-*]\s", text.lower())

    def _gap(topic: str, negatives: tuple[str, ...]) -> bool:
        """Return True if any sentence mentions *topic* with a negative."""
        return any(topic in s and any(neg in s for neg in negatives) for s in sentences)

    _missing = ("missing", "absent", "not found", "not present", "not configured")

    return {
        "cos_tracing": _gap("tracing", (*_missing, "no tracing")),
        "cos_metrics": _gap("metrics", (*_missing, "no metrics")),
        "cos_logging": _gap("logging", (*_missing, "no logging")),
        "cos_dashboards": _gap("dashboard", (*_missing, "no dashboard")),
        "ops_tracing": _gap("ops-tracing", (*_missing, "not installed")),
        "unit_tests": _gap("unit test", (*_missing, "no unit")),
        "integration_tests": _gap("integration test", (*_missing, "no integration")),
        "deprecated_apis": any(
            kw in text.lower() for kw in ("deprecated", "storedstate", "harness", "fetch-libs")
        ),
        "reactive_framework": any(
            kw in text.lower()
            for kw in ("reactive framework", "charms.reactive", "@when", "@hook")
        ),
        "readme": _gap("readme", (*_missing, "no readme")),
        "licence": _gap("licen", (*_missing, "no licen")),
        "listing_metadata": _gap("listing", (*_missing, "incomplete")),
        "type_annotations": _gap("type annotation", (*_missing, "no type")),
        "modern_patterns": _gap("modern pattern", (*_missing, "no modern")),
    }
