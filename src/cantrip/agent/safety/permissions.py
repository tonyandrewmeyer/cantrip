"""Declarative permission config (``.cantrip/permissions.yaml``).

Phase 68.2.  Three-way per-call gate (``allow`` / ``ask`` / ``deny``)
on tool invocations, expressed as ordered glob-pattern → outcome maps
so the rules transfer one-for-one from OpenCode's ``opencode.json``.

The layering story lines up with the rest of the defence-in-depth
stack in ``design/TOOLS.md``:

* Phase 46 hooks run first — they can mutate arguments or veto.
* Phase 80 :class:`~cantrip.agent.policy.policy.GovernancePolicy` runs next —
  coarse, category-scoped allow / deny / review.
* Phase 68.2 (this module) runs on the *post-hook* arguments — it
  reads the command string the call is actually about to use, so a
  hook that rewrote ``rm -rf /`` into ``rm -rf /tmp/foo`` still gets
  matched by the right bash pattern.
* Phase 49 subprocess sandboxing is the kernel-level backstop.

The module owns four things:

* :class:`PermissionRuleset` — ordered rule maps across three
  sections (``tools``, ``bash``, ``paths``) plus per-agent overrides.
* :func:`evaluate` — the decision function; walks the rules
  last-match-wins within a section and takes the most restrictive
  outcome across sections.
* YAML loader + discovery (``~/.config/cantrip/permissions.yaml`` +
  ``<repo>/.cantrip/permissions.yaml``).  Repo wins on conflict, as
  it does everywhere else in Cantrip.
* :class:`PermissionManager` — tracks pending ``ask`` requests with
  :class:`asyncio.Future` values, mirroring the MCP elicitation flow.
  The conversation layer calls :meth:`PermissionManager.resolve` when
  the user answers yes / no on the CONFIRM task surface.
"""

from __future__ import annotations

import asyncio
import dataclasses
import enum
import fnmatch
import logging
import pathlib
import shlex
import uuid
from collections.abc import Callable, Iterator, Mapping
from typing import Any

import yaml

log = logging.getLogger(__name__)


#: Default time the subagent will wait for a user response to an
#: ``ask`` before auto-denying.  Kept below the shortest subagent
#: task timeout (``RESEARCH = 300s``) so a parked ask never steals
#: the whole task budget.
DEFAULT_ASK_TIMEOUT_SECONDS = 240.0


#: CONFIRM task id prefix used by the ``ask`` flow.  Kept distinct
#: from the race confirm prefix (``race-confirm-``) so the
#: conversation layer's handlers stay unambiguous.
PERMISSION_CONFIRM_PREFIX = "permission-confirm-"


class PermissionOutcome(enum.StrEnum):
    """Three-way verdict for a tool call.

    Values are the same strings users write in ``permissions.yaml``
    so a config round-trips without translation.
    """

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


#: Ordering for "most restrictive wins".  ``deny`` beats ``ask`` beats
#: ``allow`` when sections disagree (``tools`` says allow but ``bash``
#: says deny ⇒ deny).
_RESTRICTIVENESS = {
    PermissionOutcome.ALLOW: 0,
    PermissionOutcome.ASK: 1,
    PermissionOutcome.DENY: 2,
}


#: Names of arguments the ``paths`` section walks when matching a tool
#: call.  Covers every path-carrying tool in ``agent/tools/files.py``
#: plus the common ``file_path`` alias used elsewhere; unknown tools
#: contribute nothing to path-based matching.
_PATH_ARGUMENT_KEYS: tuple[str, ...] = ("path", "file_path", "filename")


#: Tool name whose first positional argument is a bash command and so
#: contributes to the ``bash`` section.  Extend via
#: :attr:`PermissionRuleset.bash_tools` if the repo adds its own shell
#: wrapper.
DEFAULT_BASH_TOOLS: frozenset[str] = frozenset({"run_command"})


#: Keys within a ``run_command`` argument bundle that may carry the
#: command text.  ``command`` is the canonical, ``argv`` the list
#: shape (rare, but some wrappers pass it).
_BASH_ARGUMENT_KEYS: tuple[str, ...] = ("command", "argv", "cmd")


@dataclasses.dataclass(frozen=True, slots=True)
class PermissionRule:
    """One ``glob → outcome`` entry with its source file / section.

    Preserves the source so audit logs and error messages can name
    the rule that matched (``<file>:tools:<pattern>``).  Rules keep
    insertion order because "last-match-wins" is position-sensitive
    — the dataclass is hashable so a ruleset can dedupe identical
    rules imported twice.
    """

    pattern: str
    outcome: PermissionOutcome
    source: str = "builtin"

    def matches(self, subject: str) -> bool:
        """``fnmatch``-style glob match on *subject*.

        Case-sensitive so ``Rm *`` does not accidentally catch
        ``rm -rf``.  Unix shell globs (``*``, ``?``, ``[abc]``) only
        — regex is deliberately out of scope so a typo can't
        accidentally relax a rule by matching too widely.
        """
        return fnmatch.fnmatchcase(subject, self.pattern)


@dataclasses.dataclass(frozen=True, slots=True)
class PermissionDecision:
    """Outcome of an :func:`evaluate` call.

    ``reason`` is a human-readable phrase naming the matched rule
    so the synthetic ``ToolResult`` and the audit log line are both
    self-explanatory.  ``matched_rule`` is ``None`` when no rule
    matched and the evaluator fell through to the default allow.
    """

    outcome: PermissionOutcome
    reason: str
    matched_rule: PermissionRule | None = None

    @property
    def denied(self) -> bool:
        """``True`` when the decision blocks the call outright."""
        return self.outcome is PermissionOutcome.DENY

    @property
    def needs_ask(self) -> bool:
        """``True`` when the decision requires user confirmation."""
        return self.outcome is PermissionOutcome.ASK


@dataclasses.dataclass(frozen=True, slots=True)
class PermissionRuleset:
    """Composed rule map for one resolution (global + per-agent).

    Rule sections are tuples rather than dicts so composition can
    cleanly concatenate without worrying about dict-insertion-order
    quirks across Python builds.  Last-match-wins means the *final*
    rule in each tuple (per section) that matches a subject takes
    effect, so composing repo over user is as simple as user-rules
    first + repo-rules second.

    *bash_tools* names the tools whose arguments feed the ``bash``
    section.  Defaults to :data:`DEFAULT_BASH_TOOLS`; lets a repo
    plug in a custom shell wrapper without code changes.
    """

    tools: tuple[PermissionRule, ...] = ()
    bash: tuple[PermissionRule, ...] = ()
    paths: tuple[PermissionRule, ...] = ()
    # Mapping ``agent_name → sub-ruleset``.  ``agent_name`` matches
    # ``SubagentContext.task.category.value`` — the category is the
    # closest thing Cantrip has to OpenCode's "agent" concept today.
    agents: Mapping[str, PermissionRuleset] = dataclasses.field(default_factory=dict)
    bash_tools: frozenset[str] = DEFAULT_BASH_TOOLS
    name: str = "empty"


def _walk_rules(
    rules: tuple[PermissionRule, ...],
    subject: str,
) -> PermissionRule | None:
    """Return the last rule whose glob matches *subject*, or ``None``.

    Walks in reverse so the short-circuit on the first hit is still
    last-match-wins by construction.  Cheaper than building a list
    of matches and picking the last when ``subject`` is hot.
    """
    for rule in reversed(rules):
        if rule.matches(subject):
            return rule
    return None


def _path_candidates(arguments: Mapping[str, Any]) -> Iterator[str]:
    """Yield path-like argument values for ``paths`` matching."""
    for key in _PATH_ARGUMENT_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value:
            yield value


def _bash_command_string(arguments: Mapping[str, Any]) -> str | None:
    """Collapse a ``run_command`` argument bundle to a single command string.

    Returns ``None`` when no bash-carrying key is present so the
    caller can skip the ``bash`` section entirely.  For ``argv`` lists
    the elements are ``shlex.quote``-joined so a pattern like
    ``rm -rf *`` still matches an argv shape of
    ``["rm", "-rf", "/tmp/x"]``.
    """
    for key in _BASH_ARGUMENT_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, list) and value:
            parts = [str(item) for item in value]
            return " ".join(shlex.quote(p) for p in parts) if parts else None
    return None


def evaluate(
    ruleset: PermissionRuleset,
    tool_name: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    agent_name: str | None = None,
) -> PermissionDecision:
    """Decide ``allow`` / ``ask`` / ``deny`` for one tool call.

    Matching strategy:

    1. Within each section (``tools``, ``bash``, ``paths``) a walk
       in reverse insertion order stops on the first glob hit —
       i.e., the last-written rule wins.
    2. If a per-agent ruleset is registered for *agent_name*, its
       sections are evaluated *after* the global sections.  A later
       hit overrides an earlier one, so per-agent rules can either
       tighten or loosen the global map.
    3. Across sections, the most restrictive of the individual
       per-section decisions wins (``deny > ask > allow``).  An
       ``ask`` in ``bash`` trumps an ``allow`` in ``tools`` so the
       gate errs safe when two sections disagree.
    4. When no rule matches in any section, the decision is a
       default ``allow`` with an explanatory reason — matching the
       "everything else → ``allow``" baseline from Phase 68.2's
       roadmap entry.

    Arguments are optional — callers that only want tool-name
    matching (e.g. an LLM-tool-filter pre-filter) can omit them.
    """
    args: Mapping[str, Any] = arguments or {}
    candidates: list[tuple[PermissionRule, str]] = []

    def collect(sub: PermissionRuleset) -> None:
        tool_hit = _walk_rules(sub.tools, tool_name)
        if tool_hit is not None:
            candidates.append((tool_hit, f"tool name matches {tool_hit.pattern!r}"))
        if tool_name in sub.bash_tools:
            command = _bash_command_string(args)
            if command is not None:
                bash_hit = _walk_rules(sub.bash, command)
                if bash_hit is not None:
                    candidates.append((bash_hit, f"bash command matches {bash_hit.pattern!r}"))
        for candidate_path in _path_candidates(args):
            path_hit = _walk_rules(sub.paths, candidate_path)
            if path_hit is not None:
                candidates.append(
                    (path_hit, f"path {candidate_path!r} matches {path_hit.pattern!r}")
                )

    collect(ruleset)
    if agent_name is not None:
        agent_overlay = ruleset.agents.get(agent_name)
        if agent_overlay is not None:
            collect(agent_overlay)

    if not candidates:
        return PermissionDecision(
            outcome=PermissionOutcome.ALLOW,
            reason="no permission rule matched; default allow",
        )

    chosen_rule, chosen_reason = max(
        candidates,
        key=lambda item: _RESTRICTIVENESS[item[0].outcome],
    )
    return PermissionDecision(
        outcome=chosen_rule.outcome,
        reason=f"{chosen_reason} → {chosen_rule.outcome.value} ({chosen_rule.source})",
        matched_rule=chosen_rule,
    )


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


class PermissionParseError(ValueError):
    """Raised when a ``permissions.yaml`` file is malformed."""


_SECTION_KEYS = frozenset({"tools", "bash", "paths"})
_TOP_LEVEL_KEYS = _SECTION_KEYS | {"agents", "bash_tools"}
_OUTCOME_STRINGS = {o.value for o in PermissionOutcome}


def _parse_section(
    raw: object,
    *,
    section_name: str,
    source: str,
) -> tuple[PermissionRule, ...]:
    """Parse one section of glob → outcome pairs into an ordered rule tuple."""
    if raw is None:
        return ()
    if not isinstance(raw, dict):
        raise PermissionParseError(
            f"{source}: {section_name!r} must be a mapping of glob → outcome, "
            f"got {type(raw).__name__}"
        )
    rules: list[PermissionRule] = []
    for pattern, outcome in raw.items():
        if not isinstance(pattern, str):
            raise PermissionParseError(
                f"{source}: {section_name!r} keys must be strings, got {pattern!r}"
            )
        if not isinstance(outcome, str) or outcome not in _OUTCOME_STRINGS:
            raise PermissionParseError(
                f"{source}: {section_name!r}[{pattern!r}] must be one of "
                f"{sorted(_OUTCOME_STRINGS)}, got {outcome!r}"
            )
        rules.append(
            PermissionRule(
                pattern=pattern,
                outcome=PermissionOutcome(outcome),
                source=f"{source}:{section_name}",
            )
        )
    return tuple(rules)


def _parse_bash_tools(raw: object, *, source: str) -> frozenset[str]:
    """Parse the ``bash_tools`` override (list of tool names)."""
    if raw is None:
        return DEFAULT_BASH_TOOLS
    if not isinstance(raw, list):
        raise PermissionParseError(
            f"{source}: 'bash_tools' must be a list of tool names, got {type(raw).__name__}"
        )
    names: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str):
            raise PermissionParseError(
                f"{source}: 'bash_tools' entries must be strings, got {entry!r}"
            )
        names.add(entry)
    return frozenset(names) if names else DEFAULT_BASH_TOOLS


def _parse_agents(
    raw: object,
    *,
    source: str,
) -> dict[str, PermissionRuleset]:
    """Parse ``agents:`` sub-map into per-agent rulesets.

    Each sub-map is validated the same way the top level is so a
    per-agent override can contain ``tools``, ``bash`` and ``paths``
    — but not nested ``agents`` (we avoid recursion on purpose).
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PermissionParseError(
            f"{source}: 'agents' must be a mapping of agent_name → ruleset, "
            f"got {type(raw).__name__}"
        )
    overlays: dict[str, PermissionRuleset] = {}
    for agent_name, body in raw.items():
        if not isinstance(agent_name, str):
            raise PermissionParseError(
                f"{source}: 'agents' keys must be strings, got {agent_name!r}"
            )
        if not isinstance(body, dict):
            raise PermissionParseError(
                f"{source}: 'agents[{agent_name!r}]' must be a mapping, got {type(body).__name__}"
            )
        unknown = set(body.keys()) - _SECTION_KEYS
        if unknown:
            raise PermissionParseError(
                f"{source}: 'agents[{agent_name!r}]' has unknown keys "
                f"{sorted(unknown)}; expected subset of {sorted(_SECTION_KEYS)}"
            )
        sub_source = f"{source}:agents:{agent_name}"
        overlays[agent_name] = PermissionRuleset(
            tools=_parse_section(body.get("tools"), section_name="tools", source=sub_source),
            bash=_parse_section(body.get("bash"), section_name="bash", source=sub_source),
            paths=_parse_section(body.get("paths"), section_name="paths", source=sub_source),
            name=sub_source,
        )
    return overlays


def ruleset_from_dict(
    raw: dict[str, object],
    *,
    source: str = "inline",
) -> PermissionRuleset:
    """Build a :class:`PermissionRuleset` from a parsed YAML dict."""
    if not isinstance(raw, dict):
        raise PermissionParseError(f"{source}: root must be a mapping")
    unknown = set(raw.keys()) - _TOP_LEVEL_KEYS
    if unknown:
        raise PermissionParseError(
            f"{source}: unknown top-level keys {sorted(unknown)}; "
            f"expected subset of {sorted(_TOP_LEVEL_KEYS)}"
        )
    return PermissionRuleset(
        tools=_parse_section(raw.get("tools"), section_name="tools", source=source),
        bash=_parse_section(raw.get("bash"), section_name="bash", source=source),
        paths=_parse_section(raw.get("paths"), section_name="paths", source=source),
        agents=_parse_agents(raw.get("agents"), source=source),
        bash_tools=_parse_bash_tools(raw.get("bash_tools"), source=source),
        name=source,
    )


def load_permissions_file(path: pathlib.Path) -> PermissionRuleset:
    """Load one ``permissions.yaml`` file.

    Raises :class:`PermissionParseError` on parse failure; callers may
    downgrade this to a warning + fallback if they prefer to keep the
    agent running when a single file is broken.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PermissionParseError(f"{path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise PermissionParseError(f"{path}: not valid UTF-8: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PermissionParseError(f"{path}: {exc}") from exc
    except RecursionError as exc:
        # PyYAML can blow the Python stack while tokenising a file
        # with thousands of nested mappings.  Wrap as a parse error so
        # the dispatcher logs ``Skipping malformed`` and continues
        # instead of crashing the agent.
        raise PermissionParseError(f"{path}: nesting too deep ({exc})") from exc
    if raw is None:
        return PermissionRuleset(name=str(path))
    return ruleset_from_dict(raw, source=str(path))


def compose_rulesets(*rulesets: PermissionRuleset) -> PermissionRuleset:
    """Compose rulesets with later layers appended (last wins).

    Rule tuples concatenate, so the final composed section preserves
    insertion order across all layers.  Agent overlays *themselves*
    compose the same way — a per-agent rule in the later layer wins
    over an earlier one.  ``bash_tools`` unions across layers.
    """
    if not rulesets:
        return PermissionRuleset(name="empty")
    if len(rulesets) == 1:
        return rulesets[0]

    tools: list[PermissionRule] = []
    bash: list[PermissionRule] = []
    paths: list[PermissionRule] = []
    bash_tools: set[str] = set()
    agent_accumulator: dict[str, list[PermissionRuleset]] = {}

    for rs in rulesets:
        tools.extend(rs.tools)
        bash.extend(rs.bash)
        paths.extend(rs.paths)
        bash_tools.update(rs.bash_tools)
        for name, overlay in rs.agents.items():
            agent_accumulator.setdefault(name, []).append(overlay)

    composed_agents: dict[str, PermissionRuleset] = {}
    for name, layers in agent_accumulator.items():
        if len(layers) == 1:
            composed_agents[name] = layers[0]
            continue
        composed_agents[name] = PermissionRuleset(
            tools=tuple(rule for layer in layers for rule in layer.tools),
            bash=tuple(rule for layer in layers for rule in layer.bash),
            paths=tuple(rule for layer in layers for rule in layer.paths),
            name=f"agent:{name}",
        )

    return PermissionRuleset(
        tools=tuple(tools),
        bash=tuple(bash),
        paths=tuple(paths),
        agents=composed_agents,
        bash_tools=frozenset(bash_tools) if bash_tools else DEFAULT_BASH_TOOLS,
        name="+".join(rs.name for rs in rulesets),
    )


def _builtin_defaults() -> PermissionRuleset:
    """Safe-by-default floor — the roadmap's baked-in rules.

    ``rm -rf *`` and ``rm -fr *`` always deny; ``sudo *`` and
    ``git push *`` always ask; common ``.env`` shapes deny to match
    the "``.env`` reads → ``deny``" expectation.  Explicit user rules
    override because they appear later in the composed tuple.
    """
    bash_rules: tuple[PermissionRule, ...] = (
        PermissionRule("rm -rf *", PermissionOutcome.DENY, source="builtin:bash"),
        PermissionRule("rm -fr *", PermissionOutcome.DENY, source="builtin:bash"),
        PermissionRule("sudo *", PermissionOutcome.ASK, source="builtin:bash"),
        PermissionRule("git push *", PermissionOutcome.ASK, source="builtin:bash"),
    )
    path_rules: tuple[PermissionRule, ...] = (
        PermissionRule(".env", PermissionOutcome.DENY, source="builtin:paths"),
        PermissionRule("*/.env", PermissionOutcome.DENY, source="builtin:paths"),
        PermissionRule("*.env", PermissionOutcome.DENY, source="builtin:paths"),
    )
    return PermissionRuleset(
        bash=bash_rules,
        paths=path_rules,
        name="builtin",
    )


#: Safe-by-default ruleset, prepended at discovery time so user rules
#: always have the chance to override via "last-match-wins".
BUILTIN_PERMISSIONS: PermissionRuleset = _builtin_defaults()


#: Read-only toolset permitted in plan mode (Phase 68.4).  Covers
#: code / filesystem reads, git history, live Juju inspection, memory
#: lookup, and network fetches.  Every other tool denies with a
#: "plan mode — switch to /build to execute" message so the LLM sees
#: a clear error and the user can't accidentally mutate state while
#: still in read-only mode.
PLAN_MODE_ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        # File + code reads
        "read_file",
        "list_directory",
        "glob",
        "grep",
        # Git history reads
        "git_status",
        "git_diff",
        "git_log",
        # Juju introspection
        "juju_status",
        "juju_list_secrets",
        "juju_show_secret",
        "juju_read_relation_data",
        "juju_get_app_config",
        "juju_list_offers",
        "juju_show_unit",
        # Memory lookup (safe — doesn't mutate)
        "memory_list",
        "memory_read",
        "memory_search",
        # Network reads
        "web_search",
        "web_fetch",
    }
)


def _plan_mode_overlay() -> PermissionRuleset:
    """Build the plan-mode overlay ruleset.

    Implementation detail: a wildcard deny plus an explicit allow for
    every read-only tool.  Last-match-wins within the ``tools``
    section picks the literal on a hit and falls back to the
    wildcard deny otherwise.  Cross-section composition is unaffected
    — ``bash`` and ``paths`` sections from the base ruleset still
    apply, but any tool not in the allow-list is denied outright
    because most-restrictive-wins chooses the overlay's ``deny``.
    """
    rules: list[PermissionRule] = [
        PermissionRule("*", PermissionOutcome.DENY, source="plan-mode"),
    ]
    rules.extend(
        PermissionRule(tool, PermissionOutcome.ALLOW, source="plan-mode")
        for tool in sorted(PLAN_MODE_ALLOWED_TOOLS)
    )
    return PermissionRuleset(tools=tuple(rules), name="plan-mode")


#: The plan-mode overlay, composed onto the active ruleset whenever
#: :attr:`cantrip.agent.state.AgentState.plan_mode` is ``True``.  Built
#: once at import so compose calls don't re-allocate on every tool
#: invocation.
PLAN_MODE_OVERLAY: PermissionRuleset = _plan_mode_overlay()


def plan_mode_message(tool_name: str) -> str:
    """Standard denial message for a tool refused by plan mode.

    Surfaces in the synthetic ``ToolResult`` error a subagent returns
    when plan mode blocks a call.  Centralised here so the wording is
    consistent across the main-agent and subagent code paths.
    """
    return (
        f"Plan mode — {tool_name!r} is not available in read-only mode.  "
        "Switch to ``/build`` to execute, or pick a read-only tool instead."
    )


#: Canonical filenames the discovery helper walks.  Kept as module
#: constants so docs and tests can reference the same paths without
#: duplicating the strings.
USER_CONFIG_FILENAME = "permissions.yaml"
REPO_CONFIG_RELATIVE = pathlib.Path(".cantrip") / "permissions.yaml"


def discover_permissions(
    *,
    charm_path: pathlib.Path | None = None,
    user_config_dir: pathlib.Path | None = None,
    include_builtin: bool = True,
) -> PermissionRuleset:
    """Load and compose the active permission stack.

    Order (each layer is optional; missing layers are skipped):

    1. Built-in safe defaults (:data:`BUILTIN_PERMISSIONS`).
    2. User-wide: ``~/.config/cantrip/permissions.yaml`` (or the
       override in ``user_config_dir``).
    3. Per-charm: ``<charm>/.cantrip/permissions.yaml``.

    Malformed files log a warning and are skipped rather than
    raising so a typo in one layer doesn't lock the user out — the
    pattern matches :func:`cantrip.agent.policy.policy.discover_policies`.
    """
    layers: list[PermissionRuleset] = []
    if include_builtin:
        layers.append(BUILTIN_PERMISSIONS)

    if user_config_dir is None:
        user_config_dir = pathlib.Path.home() / ".config" / "cantrip"
    user_file = user_config_dir / USER_CONFIG_FILENAME
    if user_file.is_file():
        try:
            layers.append(load_permissions_file(user_file))
        except PermissionParseError as exc:
            log.warning("Skipping malformed user permissions file %s: %s", user_file, exc)

    if charm_path is not None:
        repo_file = charm_path / REPO_CONFIG_RELATIVE
        if repo_file.is_file():
            try:
                layers.append(load_permissions_file(repo_file))
            except PermissionParseError as exc:
                log.warning("Skipping malformed repo permissions file %s: %s", repo_file, exc)

    return compose_rulesets(*layers) if layers else PermissionRuleset(name="empty")


# ---------------------------------------------------------------------------
# Async ask manager
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PermissionAskRequest:
    """Payload handed to the UI when an ``ask`` decision parks a call.

    Mirrors :class:`~cantrip.mcp.elicitation.ElicitationRequest` in
    shape so UI surfaces can reuse the same modal / task widget
    machinery without much adaptation.  ``task_id`` is the CONFIRM
    task's id so the handler can resolve it by id rather than
    inspecting description text.
    """

    request_id: str
    task_id: str
    tool_name: str
    reason: str
    command: str | None
    arguments: dict[str, Any]


class PermissionManager:
    """Park ``ask`` decisions on futures, resolve when the user answers.

    Thin analogue of :class:`cantrip.mcp.elicitation.ElicitationManager`.
    The subagent's tool-dispatch loop calls :meth:`request` which
    creates an ``asyncio.Future``, publishes a CONFIRM task + event
    via the caller-supplied callback, and ``await``\\ s the future
    with a timeout.  The conversation layer calls :meth:`resolve`
    when the user types ``yes`` / ``no`` on the CONFIRM task.

    The manager is thread-safe under the usual asyncio rules: the
    ``_pending`` dict is only mutated from the event-loop thread.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_ASK_TIMEOUT_SECONDS,
        on_request: Callable[[PermissionAskRequest], None] | None = None,
        on_auto_approve: Callable[[PermissionAskRequest], None] | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._on_request = on_request
        # Phase 69.2: separate fanout for auto-approvals so the audit
        # trail captures them distinctly from operator-resolved asks.
        self._on_auto_approve = on_auto_approve
        self._pending: dict[str, asyncio.Future[bool]] = {}
        # Phase 69.2: ``--yolo`` / ``/yolo`` sets this to ``True`` and
        # ``request()`` short-circuits to an auto-approval instead of
        # parking on a future.  ``deny`` decisions still block because
        # they never reach the manager — this only toggles the ``ask``
        # tier.
        self._yolo_mode: bool = False

    @property
    def pending(self) -> list[str]:
        """Request ids still waiting for a user decision."""
        return list(self._pending)

    @property
    def yolo_mode(self) -> bool:
        """Whether every ``ask`` is auto-approved (Phase 69.2)."""
        return self._yolo_mode

    def set_yolo(self, enabled: bool) -> None:
        """Enable or disable yolo mode mid-session.

        When flipping on, every pending ``ask`` is also resolved as
        approved so a subagent waiting on a future doesn't stall the
        run.  Turning yolo off leaves any already-granted approvals
        in place — only future calls are affected.
        """
        self._yolo_mode = bool(enabled)
        if self._yolo_mode:
            for future in list(self._pending.values()):
                if not future.done():
                    future.set_result(True)

    def set_on_request(
        self,
        callback: Callable[[PermissionAskRequest], None] | None,
    ) -> None:
        """Register (or clear) the UI-fanout callback after construction."""
        self._on_request = callback

    def set_on_auto_approve(
        self,
        callback: Callable[[PermissionAskRequest], None] | None,
    ) -> None:
        """Register (or clear) the yolo auto-approval fanout callback."""
        self._on_auto_approve = callback

    async def request(
        self,
        *,
        tool_name: str,
        reason: str,
        arguments: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> bool:
        """Park an ``ask`` until the user resolves it.

        Returns ``True`` when the user approved, ``False`` on refusal
        or timeout.  Timing out auto-denies — callers don't need to
        catch :class:`TimeoutError` themselves.  The ``request_id``
        defaults to a random uuid; explicit ids let tests drive the
        manager deterministically.

        Phase 69.2: when :attr:`yolo_mode` is ``True`` the request
        resolves to ``True`` immediately and a
        ``permission_auto_approved`` event fires through
        :meth:`set_on_auto_approve` so the audit trail captures the
        decision.  Deny decisions never reach this method (they
        short-circuit upstream), so yolo only loosens the ``ask``
        tier.
        """
        args: dict[str, Any] = dict(arguments or {})
        rid = request_id or uuid.uuid4().hex
        task_id = f"{PERMISSION_CONFIRM_PREFIX}{rid}"

        if self._yolo_mode:
            if self._on_auto_approve is not None:
                payload = PermissionAskRequest(
                    request_id=rid,
                    task_id=task_id,
                    tool_name=tool_name,
                    reason=reason,
                    command=_bash_command_string(args),
                    arguments=args,
                )
                try:
                    self._on_auto_approve(payload)
                except Exception:  # noqa: BLE001 — callback is user code; a broken UI hook must not block tool dispatch.
                    log.debug(
                        "permission auto-approve callback failed for %s",
                        tool_name,
                        exc_info=True,
                    )
            log.info(
                "Permission ask for %r auto-approved by yolo mode: %s",
                tool_name,
                reason,
            )
            return True

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[rid] = future

        if self._on_request is not None:
            payload = PermissionAskRequest(
                request_id=rid,
                task_id=task_id,
                tool_name=tool_name,
                reason=reason,
                command=_bash_command_string(args),
                arguments=args,
            )
            try:
                self._on_request(payload)
            except Exception:  # noqa: BLE001 — callback is user code; a broken UI hook must not block the prompt.
                log.debug("permission ask callback failed for %s", tool_name, exc_info=True)

        try:
            return await asyncio.wait_for(future, timeout=self._timeout)
        except TimeoutError:
            log.warning(
                "Permission ask %s for tool %r timed out after %.0fs; auto-denying",
                rid,
                tool_name,
                self._timeout,
            )
            return False
        finally:
            self._pending.pop(rid, None)

    def resolve(self, request_id: str, *, approved: bool) -> bool:
        """Resolve a parked ask; returns ``True`` if one was found."""
        future = self._pending.get(request_id)
        if future is None or future.done():
            return False
        future.set_result(approved)
        return True

    def cancel_all(self) -> None:
        """Auto-deny every pending ask — used on shutdown."""
        for rid, future in list(self._pending.items()):
            if not future.done():
                future.set_result(False)
            self._pending.pop(rid, None)
