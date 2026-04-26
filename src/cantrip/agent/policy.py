"""Stacked tool-access policies for the subagent dispatcher.

Phase 80.1: replace the single-level category allowlist in
``subagent._filter_tools`` with a composable policy stack — global
floor + per-category + per-charm rules, plus a per-goal rate limit,
a review list, and the plumbing for later sub-phases (dispatcher
wiring in 80.2, rate limit in 80.3, audit in 80.4, destructive-
command gate in 80.5).

The design lifts the keep/defer/reject verdicts from the
`Phase 55.4` investigation in ``design/TOOLS.md``.  Three primitives
from awesome-copilot's ``agent-governance`` skill ship here:

* ``GovernancePolicy`` — a frozen dataclass carrying allow / block /
  review / rate-limit sets.
* ``compose_policies(*policies)`` — most-restrictive-wins: allow-lists
  intersect, block and review unions; rate limit picks the strictest
  non-``None`` value.
* A small YAML loader so operators can drop policy files into
  ``~/.config/cantrip/policies/`` or ``<charm>/cantrip.policies.yaml``
  and have them composed into the active policy at subagent-dispatch
  time.

The module deliberately does **not** wire policies into the subagent
(Phase 80.2) or export a user-facing audit / CLI subcommand (Phase
80.4).  It's the primitive layer; later sub-phases consume it.
"""

from __future__ import annotations

import dataclasses
import enum
import logging
import pathlib

import yaml

log = logging.getLogger(__name__)


class PolicyAction(enum.StrEnum):
    """Outcome of :meth:`GovernancePolicy.check_tool`."""

    ALLOW = "allow"
    DENY = "deny"
    REVIEW = "review"


@dataclasses.dataclass(frozen=True, slots=True)
class GovernancePolicy:
    """A single layer of the policy stack.

    An *empty* ``allowed_tools`` set means "no allow constraint" — not
    "allow nothing".  This keeps the composition rule "intersect
    allow-lists" well-defined: composing an empty policy with a
    non-empty one yields the non-empty one.

    ``blocked_tools`` and ``require_human_approval`` are straight
    sets; composition unions them.  Any tool in
    ``require_human_approval`` but not in ``blocked_tools`` maps to
    :attr:`PolicyAction.REVIEW` at check time.

    ``max_calls_per_request`` is the per-goal rate limit consumed by
    Phase 80.3; ``None`` means "no limit at this layer".  Composition
    picks the strictest (lowest) non-``None`` value across the stack.

    *name* is carried through composition as ``"<a>+<b>"`` so audit
    events (Phase 80.4) can show which stack produced a decision.
    """

    allowed_tools: frozenset[str] = frozenset()
    blocked_tools: frozenset[str] = frozenset()
    require_human_approval: frozenset[str] = frozenset()
    max_calls_per_request: int | None = None
    name: str = "unnamed"
    # Phase 80.5: explicit opt-in for destructive commands.  OR-composed
    # across the stack — any layer with ``True`` lets the in-code gate
    # inside ``tools/juju.py`` and ``tools/run_command.py`` through.
    # Intended for unattended / ``--yolo`` sessions where the operator
    # has accepted the blast radius ahead of time.
    approve_destructive: bool = False

    def check_tool(self, tool_name: str) -> PolicyAction:
        """Return the policy verdict for *tool_name*.

        Evaluation order (first hit wins):

        1. If the tool is explicitly blocked, ``DENY``.
        2. If the tool is in the approval list, ``REVIEW``.
        3. If an allow-list is set and the tool isn't in it, ``DENY``.
        4. Otherwise, ``ALLOW``.
        """
        if tool_name in self.blocked_tools:
            return PolicyAction.DENY
        if tool_name in self.require_human_approval:
            return PolicyAction.REVIEW
        if self.allowed_tools and tool_name not in self.allowed_tools:
            return PolicyAction.DENY
        return PolicyAction.ALLOW


def compose_policies(*policies: GovernancePolicy) -> GovernancePolicy:
    """Compose a stack of policies with most-restrictive-wins semantics.

    * ``allowed_tools`` is the intersection of every non-empty allow
      set (empty layers are treated as "no constraint" and dropped
      before intersection).  If every layer is empty, the composed
      allow-set is empty — meaning, again, "no allow constraint"
      rather than "deny everything".
    * ``blocked_tools`` and ``require_human_approval`` union across
      every layer.
    * ``max_calls_per_request`` picks the lowest non-``None`` value.

    With no layers, returns a permissive zero-policy.
    """
    if not policies:
        return GovernancePolicy(name="empty")

    # Intersection of non-empty allow sets, treating empty ones as
    # "no constraint" rather than "deny everything".
    non_empty_allows = [p.allowed_tools for p in policies if p.allowed_tools]
    allowed = frozenset.intersection(*non_empty_allows) if non_empty_allows else frozenset()

    blocked: frozenset[str] = frozenset()
    for p in policies:
        blocked = blocked | p.blocked_tools

    approval: frozenset[str] = frozenset()
    for p in policies:
        approval = approval | p.require_human_approval

    rate_limits = [
        p.max_calls_per_request for p in policies if p.max_calls_per_request is not None
    ]
    rate_limit = min(rate_limits) if rate_limits else None

    # approve_destructive: OR across layers — any opt-in wins.  This
    # is the one field where a more-permissive layer overrides a more-
    # restrictive one, because the flag exists specifically to let an
    # operator accept the blast radius ahead of time for unattended
    # ``--yolo``-style sessions.
    approve_destructive = any(p.approve_destructive for p in policies)

    composed_name = "+".join(p.name for p in policies)

    return GovernancePolicy(
        allowed_tools=allowed,
        blocked_tools=blocked,
        require_human_approval=approval,
        max_calls_per_request=rate_limit,
        name=composed_name,
        approve_destructive=approve_destructive,
    )


# ---------------------------------------------------------------------------
# YAML serialisation
# ---------------------------------------------------------------------------


class PolicyParseError(ValueError):
    """Raised when a YAML policy file is malformed."""


_POLICY_FIELDS = {
    "allowed_tools",
    "blocked_tools",
    "require_human_approval",
    "max_calls_per_request",
    "name",
    "approve_destructive",
}


def policy_from_dict(raw: dict[str, object], *, default_name: str = "unnamed") -> GovernancePolicy:
    """Build a :class:`GovernancePolicy` from a plain dict.

    Raises :class:`PolicyParseError` on unknown keys, wrong types, or
    negative rate limits.  The loader is deliberately strict — typos
    in a policy file shouldn't silently relax the policy.
    """
    if not isinstance(raw, dict):
        raise PolicyParseError(f"policy must be a mapping, got {type(raw).__name__}")

    unknown = set(raw.keys()) - _POLICY_FIELDS
    if unknown:
        raise PolicyParseError(f"unknown policy fields: {sorted(unknown)}")

    def _frozen_set(key: str) -> frozenset[str]:
        value = raw.get(key, [])
        if value is None:
            return frozenset()
        if not isinstance(value, list):
            raise PolicyParseError(
                f"{key} must be a list of tool names, got {type(value).__name__}"
            )
        result: set[str] = set()
        for entry in value:
            if not isinstance(entry, str):
                raise PolicyParseError(f"{key} entries must be strings, got {entry!r}")
            result.add(entry)
        return frozenset(result)

    rate = raw.get("max_calls_per_request")
    if rate is not None:
        if not isinstance(rate, int) or isinstance(rate, bool):
            raise PolicyParseError(
                f"max_calls_per_request must be an integer or null, got {type(rate).__name__}"
            )
        if rate < 0:
            raise PolicyParseError(f"max_calls_per_request must be >= 0, got {rate}")

    name = raw.get("name", default_name)
    if not isinstance(name, str):
        raise PolicyParseError(f"name must be a string, got {type(name).__name__}")

    approve_destructive = raw.get("approve_destructive", False)
    if not isinstance(approve_destructive, bool):
        raise PolicyParseError(
            f"approve_destructive must be a boolean, got {type(approve_destructive).__name__}"
        )

    return GovernancePolicy(
        allowed_tools=_frozen_set("allowed_tools"),
        blocked_tools=_frozen_set("blocked_tools"),
        require_human_approval=_frozen_set("require_human_approval"),
        max_calls_per_request=rate,
        name=name,
        approve_destructive=approve_destructive,
    )


def policy_to_dict(policy: GovernancePolicy) -> dict[str, object]:
    """Serialise a policy for YAML round-trip.

    Empty sets round-trip as empty lists so the file shape stays
    stable under ``yaml.safe_dump`` — the loader treats an omitted
    key and an empty list identically, but emitting keys explicitly
    makes it obvious to a human reader that the policy was
    authored, not truncated.
    """
    return {
        "name": policy.name,
        "allowed_tools": sorted(policy.allowed_tools),
        "blocked_tools": sorted(policy.blocked_tools),
        "require_human_approval": sorted(policy.require_human_approval),
        "max_calls_per_request": policy.max_calls_per_request,
        "approve_destructive": policy.approve_destructive,
    }


def load_policy_file(path: pathlib.Path) -> GovernancePolicy:
    """Load a single YAML policy file.

    The filename stem is the default ``name`` if the file doesn't
    carry one.  Raises :class:`PolicyParseError` on parse failure or
    schema violation; callers may convert that into a log + skip if
    they want a partially-broken policy directory to still produce a
    usable composition.
    """
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise PolicyParseError(f"{path}: {exc}") from exc
    if raw is None:
        # Empty file — treat as zero-policy named after the file.
        return GovernancePolicy(name=path.stem)
    return policy_from_dict(raw, default_name=path.stem)


def discover_policies(
    *,
    charm_path: pathlib.Path | None = None,
    user_config_dir: pathlib.Path | None = None,
) -> list[GovernancePolicy]:
    """Discover and load the active policy stack.

    Returns policies in composition order — built-in floors first,
    then user-wide overrides, then the per-charm overlay.  Callers
    pass the result to :func:`compose_policies`.

    * ``user_config_dir`` defaults to ``~/.config/cantrip/policies/``
      when ``None``; set to a different path for tests.  Every
      ``*.yaml`` / ``*.yml`` file in the directory is loaded.  A
      malformed file logs a warning and is skipped rather than
      raising — one broken file shouldn't lock the operator out.
    * ``charm_path / "cantrip.policies.yaml"`` is loaded last when it
      exists, so a per-charm file can tighten (never loosen) the
      stack.

    Built-in policies are **not** prepended here — callers wire them
    in explicitly via :data:`BUILTIN_POLICIES` so the three
    defence-in-depth layers (Phase 55.4) stay visible at the
    dispatcher site.
    """
    policies: list[GovernancePolicy] = []

    if user_config_dir is None:
        user_config_dir = pathlib.Path.home() / ".config" / "cantrip" / "policies"

    if user_config_dir.is_dir():
        # Sort so the composition order is stable across runs.
        for path in sorted(user_config_dir.iterdir()):
            if path.suffix not in (".yaml", ".yml") or not path.is_file():
                continue
            try:
                policies.append(load_policy_file(path))
            except PolicyParseError as exc:
                log.warning("Skipping malformed policy file %s: %s", path, exc)

    if charm_path is not None:
        per_charm = charm_path / "cantrip.policies.yaml"
        if per_charm.is_file():
            try:
                policies.append(load_policy_file(per_charm))
            except PolicyParseError as exc:
                log.warning("Skipping malformed charm policy %s: %s", per_charm, exc)

    return policies


# ---------------------------------------------------------------------------
# Built-in policies
# ---------------------------------------------------------------------------

# Global floor: tools that are never OK without explicit operator
# consent, regardless of category.  Pairs with the in-code
# destructive-command gate that Phase 80.5 adds inside the juju /
# run_command tools — the policy layer and the in-code gate are the
# two halves of the defence-in-depth story from design/TOOLS.md.
ORG_WIDE_POLICY = GovernancePolicy(
    name="org-wide",
    require_human_approval=frozenset(
        {
            "juju_destroy_model",
            "juju_destroy_controller",
            "juju_remove_application",
            "juju_remove_relation",
            "run_command",
            "git_push",
        }
    ),
)


#: Tools whose ``execute`` method consults the in-code destructive
#: gate (Phase 80.5) before calling subprocess / juju.  Kept as a
#: module-level constant so the list is discoverable without
#: walking each tool file.  Subset of ORG_WIDE_POLICY's approval
#: list — the approval list gates *the LLM's ability to request
#: the tool*, while this set gates *the tool's own execution path*
#: so a direct call (main-agent, future scripting entry point) also
#: hits the gate.
DESTRUCTIVE_TOOLS: frozenset[str] = frozenset(
    {
        "juju_destroy_model",
        "juju_destroy_controller",
        "juju_remove_application",
        "juju_remove_relation",
    }
)


def _is_short_flag(token: str, letter: str) -> bool:
    """True when *token* is a POSIX short-flag bundle containing *letter*.

    Handles ``-r``, ``-rf``, ``-fr`` uniformly while rejecting
    long-form options that happen to contain the letter (``--recurse``
    wouldn't qualify as a ``-r`` hit).
    """
    return (
        len(token) >= 2
        and token.startswith("-")
        and not token.startswith("--")
        and letter in token[1:]
    )


def destructive_gate(
    tool_name: str,
    *,
    charm_path: pathlib.Path | None = None,
    user_config_dir: pathlib.Path | None = None,
    extra_policies: tuple[GovernancePolicy, ...] = (),
) -> tuple[bool, str]:
    """Check whether a destructive tool is approved to run.

    Returns ``(approved, reason)``.  A tool not in
    :data:`DESTRUCTIVE_TOOLS` is always approved — the gate is a
    backstop, not the primary allow-list.  For a destructive tool,
    the gate composes ``ORG_WIDE_POLICY`` with any discovered user /
    per-charm policies (plus *extra_policies* for tests) and lets
    the call through only when the composed
    ``approve_destructive`` flag is ``True``.

    The denial reason names the composed policy stack so audit
    consumers (Phase 80.4) can trace it.
    """
    if tool_name not in DESTRUCTIVE_TOOLS:
        return True, ""
    layers: list[GovernancePolicy] = [ORG_WIDE_POLICY]
    layers.extend(discover_policies(charm_path=charm_path, user_config_dir=user_config_dir))
    layers.extend(extra_policies)
    composed = compose_policies(*layers)
    if composed.approve_destructive:
        return True, ""
    reason = (
        f"Destructive tool {tool_name!r} requires explicit approval "
        f"under policy stack {composed.name!r}.  Add "
        "``approve_destructive: true`` to a charm-local or user "
        "policy file to enable this call."
    )
    return False, reason


def destructive_command_check(argv: list[str]) -> tuple[bool, str]:
    """Detect destructive shapes in a shell-parsed argv.

    Returns ``(is_destructive, description)``.  When destructive,
    ``tools/run_command.py`` composes the active policy stack and
    refuses unless ``approve_destructive`` is ``True`` — same
    semantic as :func:`destructive_gate` but triggered by the command
    shape rather than the tool name.

    Shapes caught, each corresponding to one of the command forms
    Phase 80.5 committed to gating:

    * ``rm`` with both ``-r`` and ``-f`` flags (combined or split —
      ``-rf``, ``-fr``, ``-r -f``, ``-r --force`` all trip).
    * ``git push`` with ``--force`` or ``-f``.
    * ``git reset`` with ``--hard``.

    A long-form flag that happens to contain the letter (e.g.
    ``--recurse-submodules``) does not trip the ``rm`` rule because
    short-flag detection rejects ``--`` prefixes.
    """
    if not argv:
        return False, ""
    base = argv[0]
    rest = argv[1:]
    if base == "rm":
        has_r = any(_is_short_flag(t, "r") for t in rest) or "--recursive" in rest
        has_f = any(_is_short_flag(t, "f") for t in rest) or "--force" in rest
        if has_r and has_f:
            return True, "rm -rf"
    if base == "git" and len(rest) >= 1:
        subcommand = rest[0]
        subargs = rest[1:]
        if subcommand == "push" and any(
            arg in {"--force", "-f", "--force-with-lease"} for arg in subargs
        ):
            return True, "git push --force"
        if subcommand == "reset" and "--hard" in subargs:
            return True, "git reset --hard"
    return False, ""


# Sprint / demo sessions: a charm author is moving fast and wants
# destructive ops unblocked (they'll re-deploy from scratch anyway),
# but still wants the rate-limit safety valve so a looping subagent
# can't run up a bill.  Operators opt in by dropping a file called
# ``sprint.yaml`` into ``~/.config/cantrip/policies/`` or symlinking
# this built-in.
SPRINT_POLICY = GovernancePolicy(
    name="sprint",
    max_calls_per_request=200,
)


def category_policy(category_name: str, allowed_tools: frozenset[str]) -> GovernancePolicy:
    """Build a per-category policy layer from the existing ``_CATEGORY_TOOLS`` data.

    Phase 80.2 wires this in place of the current
    ``subagent._filter_tools`` allow-list: each subagent dispatch
    composes the org-wide floor with the category layer and any
    per-charm file.  Extracted as a helper so the subagent code
    doesn't need to know the dataclass shape.
    """
    return GovernancePolicy(
        name=f"category:{category_name}",
        allowed_tools=allowed_tools,
    )


#: The built-in policies callers can reach for without reading YAML.
#:
#: A later sub-phase (80.2) will extend this with per-category
#: policies derived from ``subagent._CATEGORY_TOOLS`` at dispatcher
#: construction time.  Keeping the data as an explicit frozenset
#: here rather than re-deriving from ``TaskCategory`` avoids an
#: import cycle (``subagent`` imports the policy module, not the
#: other way round).
BUILTIN_POLICIES: dict[str, GovernancePolicy] = {
    ORG_WIDE_POLICY.name: ORG_WIDE_POLICY,
    SPRINT_POLICY.name: SPRINT_POLICY,
}


# ---------------------------------------------------------------------------
# Dispatcher-facing enforcer (Phase 80.2)
# ---------------------------------------------------------------------------


#: Prefix identifying MCP-provided tools, which bypass the policy
#: stack — Phase 45.2's per-server ``allowed_tools`` YAML is the gate
#: for those.  Operators who want category-scoped MCP access remove
#: unwanted servers from ``mcp.yaml`` rather than listing each MCP
#: tool in a policy file (the names are dynamic and provider-defined).
MCP_TOOL_PREFIX = "mcp__"


@dataclasses.dataclass(frozen=True)
class PolicyEnforcer:
    """Composed-once-per-subagent-run gate for tool access.

    Phase 80.2 wires this in place of ``subagent._filter_tools``.  The
    dispatcher builds one per subagent run from the org-wide floor,
    the per-category allow-list (derived from
    ``subagent._CATEGORY_TOOLS``), and any per-charm /
    ``~/.config/cantrip/policies/`` files, then both:

    * filters the list of tools the LLM sees (so the LLM never tries
      a tool that would be refused at call time), and
    * checks each tool invocation as it happens so a tool that became
      blocked partway through the run (e.g. rate-limited by 80.3)
      produces a synthetic error ``ToolResult`` rather than actually
      firing.

    MCP-provided tools (prefix ``mcp__``) bypass the policy stack
    entirely — they're gated by the per-server ``allowed_tools`` YAML
    from Phase 45.2.
    """

    policy: GovernancePolicy

    @classmethod
    def compose(cls, *policies: GovernancePolicy) -> PolicyEnforcer:
        """Build an enforcer by composing a stack of policies."""
        return cls(policy=compose_policies(*policies))

    def check_tool(self, tool_name: str) -> PolicyAction:
        """Policy verdict for *tool_name*; MCP tools always ``ALLOW``."""
        if tool_name.startswith(MCP_TOOL_PREFIX):
            return PolicyAction.ALLOW
        return self.policy.check_tool(tool_name)

    def filter_tools(self, tools):
        """Return *tools* filtered to those the policy permits.

        Tools that resolve to ``REVIEW`` are excluded from the list
        until Phase 68.2 lands declarative permission prompting —
        until then, a ``REVIEW`` verdict degrades to ``DENY`` with a
        log line suggesting the user add an approval rule.  Once
        68.2 arrives, the ``REVIEW`` branch will route through the
        confirmation prompt instead of being filtered out here.
        """
        kept = []
        for tool in tools:
            verdict = self.check_tool(tool.name)
            if verdict is PolicyAction.ALLOW:
                kept.append(tool)
            elif verdict is PolicyAction.REVIEW:
                log.info(
                    "Tool %r requires human approval under policy %r; "
                    "hidden from subagent until an approval rule is added.",
                    tool.name,
                    self.policy.name,
                )
        return kept

    def destructive_approved(self) -> bool:
        """Whether the composed policy opts in to destructive commands.

        Phase 80.5's in-code gate inside destructive tool wrappers
        consults this flag to decide whether to short-circuit a
        destructive call with a synthetic error or let the subprocess
        fire.  Exposed as a method (not a property) to stay symmetric
        with ``check_tool`` and ``deny_reason``.
        """
        return self.policy.approve_destructive

    def deny_reason(self, tool_name: str) -> str:
        """Human-readable reason a tool call would be denied.

        Used by the subagent to build the synthetic
        ``ToolResult(is_error=True)`` when a policy DENY fires at
        call time.  Names the composed policy stack so audit
        consumers can trace the decision back to the layer that
        caused it.
        """
        verdict = self.check_tool(tool_name)
        if verdict is PolicyAction.DENY:
            return f"Tool {tool_name!r} blocked by policy {self.policy.name!r}"
        if verdict is PolicyAction.REVIEW:
            return (
                f"Tool {tool_name!r} requires human approval under "
                f"policy {self.policy.name!r}; add an approval rule "
                "to permit this call"
            )
        return ""
