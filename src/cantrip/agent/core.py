"""Core agent logic."""

import asyncio
import logging
import os
import pathlib
import re
import sqlite3
import subprocess
from typing import Any

from cantrip.agent.cache_monitor import CacheCascadeDetector
from cantrip.agent.commands import custom as custom_commands
from cantrip.agent.context import context_providers, context_providers_builtin
from cantrip.agent.context.context import (
    ContextManager,
    VirtualFileStore,
    resolve_short_session_mode,
)
from cantrip.agent.controllers.arena_controller import ArenaController
from cantrip.agent.controllers.executor_controller import ExecutorController
from cantrip.agent.controllers.mcp_controller import MCPController
from cantrip.agent.controllers.triage_controller import TriageController
from cantrip.agent.controllers.watcher_controller import WatcherController
from cantrip.agent.core_services.architect_editor import ArchitectEditorMixin
from cantrip.agent.core_services.integration import IntegrationMixin
from cantrip.agent.core_services.message_history import MessageHistory
from cantrip.agent.core_services.persistence import PersistenceController
from cantrip.agent.core_services.planning_confirmations import PlanningConfirmationsMixin
from cantrip.agent.core_services.provider_manager import ProviderManager
from cantrip.agent.core_services.repo_map_service import RepoMapService
from cantrip.agent.core_services.tool_builder import ToolBuilder
from cantrip.agent.core_services.tooling import ToolingMixin
from cantrip.agent.core_services.turn_engine import TurnEngineMixin
from cantrip.agent.core_services.usage_tracker import UsageTracker
from cantrip.agent.design import parse_design_from_result
from cantrip.agent.git.git_branch import create_branch, gh_pr_view
from cantrip.agent.memory import (
    AutoWriter,
    MemoryEntry,
    MemoryManager,
    TriggerKind,
    WriteMemoryContext,
    collect_file_citations,
)
from cantrip.agent.planner import (
    TaskPlanner,
    find_day2_anchor,
    is_one_shot_build,
    plan_day2_ops_phase,
    plan_one_shot_build,
)
from cantrip.agent.prompts import agents_md
from cantrip.agent.queue import (
    TaskStatus,
    WorkQueue,
)
from cantrip.agent.runtime.preflight import (
    PreflightRunner,
)
from cantrip.agent.safety import sandbox
from cantrip.agent.safety.confirmations import ConfirmationsController
from cantrip.agent.safety.permissions import (
    PLAN_MODE_ALLOWED_TOOLS,
    plan_mode_message,
)
from cantrip.agent.skills_runtime.skills import SkillsIndex
from cantrip.agent.snapshots import SnapshotManager
from cantrip.agent.state import AgentState, Decision
from cantrip.agent.store import SessionStore
from cantrip.agent.tools import (
    Tool,
    ToolResult,
    expand_leaves,
)
from cantrip.agent.workflows import flows as flows_module
from cantrip.agent.workflows import recipes as recipes_module
from cantrip.codeintel import CodeIntel
from cantrip.hooks import (
    HookResult,
    HookRunner,
    HookStats,
)
from cantrip.llm import create_provider, resolve_light_provider, roles
from cantrip.llm.base import LLMProvider, Message, Response, Role
from cantrip.repomap import RepoMap
from cantrip.ui import events as ui_events

log = logging.getLogger(__name__)

# Re-export for backwards compatibility. ``create_provider`` and
# ``resolve_light_provider`` are kept on this module as the seam the
# model-switching tests patch (``cantrip.agent.core.create_provider``);
# ProviderManager resolves them through this module so the patches take effect.
# The planner entry points and git helpers below are the same kind of seam:
# the confirmation handlers now live in ``PlanningConfirmationsMixin`` and the
# PR / branch flow in ``IntegrationMixin``, and both reach these names through
# ``cantrip.agent.core.<name>`` at call time, so the existing
# ``patch("cantrip.agent.core.<name>")`` tests keep biting.
__all__ = [
    "AgentState",
    "CantripAgent",
    "Decision",
    "TaskPlanner",
    "create_branch",
    "create_provider",
    "find_day2_anchor",
    "gh_pr_view",
    "is_one_shot_build",
    "parse_design_from_result",
    "plan_day2_ops_phase",
    "plan_one_shot_build",
    "resolve_light_provider",
]

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


class CantripAgent(
    ArchitectEditorMixin,
    IntegrationMixin,
    PlanningConfirmationsMixin,
    ToolingMixin,
    TurnEngineMixin,
):
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
        self._messages = MessageHistory(self)
        self._providers = ProviderManager(self)

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
        ``budget-limited`` per :func:`cantrip.agent.runtime.lifecycle.lifecycle_label`.
        Read-only — every input lives on existing fields, so callers can
        invoke this on every task / pause / budget event without worrying
        about mutating state.  The TUI status bar and the Web UI status
        indicator both call this so the two surfaces never disagree.
        """
        from cantrip.agent.runtime.lifecycle import lifecycle_label

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
        return self._messages.record_message(msg)

    def _rebuild_messages_from_active_branch(self) -> int:
        return self._messages.rebuild_messages_from_active_branch()

    def _get_provider(self, purpose: str) -> LLMProvider:
        return self._providers.get_provider(purpose)

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

    def _build_llm_messages(self, include_budget: bool = False) -> list[Message]:
        return self._messages.build_llm_messages(include_budget)

    def _collapse_messages_for_short_session(self) -> None:
        return self._messages.collapse_messages_for_short_session()

    def _maybe_fold_oldest_round_into_ledger(self, turn_start_idx: int) -> None:
        return self._messages.maybe_fold_oldest_round_into_ledger(turn_start_idx)


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
