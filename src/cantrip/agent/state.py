"""Agent state data structures."""

from __future__ import annotations

import datetime
import pathlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from cantrip.llm.base import Message

if TYPE_CHECKING:
    from cantrip.agent.goal_budget import GoalBudget


@dataclass
class Decision:
    """A decision made during the session."""

    type: str
    choice: str
    reason: str | None = None
    timestamp: datetime.datetime = field(default_factory=datetime.datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.type,
            "choice": self.choice,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class TestResults:
    """Parsed results from the most recent test run."""

    __test__ = False  # Not a pytest test class.

    test_type: str  # "unit" or "integration"
    passed: int = 0
    failed: int = 0
    error: int = 0
    skipped: int = 0

    def format_summary(self) -> str:
        """Format a one-line summary for the status bar."""
        parts: list[str] = []
        if self.failed:
            parts.append(f"{self.failed} failed")
        if self.error:
            parts.append(f"{self.error} error")
        if self.passed:
            parts.append(f"{self.passed} passed")
        if self.skipped:
            parts.append(f"{self.skipped} skipped")
        if not parts:
            return ""
        icon = "✗" if (self.failed or self.error) else "✓"
        return f"{icon} {', '.join(parts)}"


@dataclass
class AgentState:
    """Current agent state."""

    charm_name: str | None = None
    charm_path: pathlib.Path | None = None
    charm_type: str | None = None  # "machine" or "k8s"
    framework: str | None = None

    dev_model: str | None = None
    cos_model: str | None = None

    # "build" for new charms, "improve" when auditing/improving an existing charm.
    mode: str = "build"

    # Transient — not persisted to SQLite, re-determined each startup.
    environment_ready: bool = False
    watcher_enabled: bool = False
    test_results: TestResults | None = None

    # GitHub remote — detected from git origin, e.g. "canonical/grafana-k8s".
    github_repo: str | None = None

    # Design proposal — persisted as raw Markdown, re-parsed on load.
    design_proposal: object | None = None

    # Transient audit report — populated after charm_audit completes.
    audit_report: str | None = None

    # Phase 55.3: optional per-goal iteration / token budget.  When
    # set, the executor consults it before spawning each task and
    # marks the task BLOCKED once the cap is reached.  Mutable so
    # ``/budget`` can raise caps in place.  Not persisted — each
    # session re-opts-in via CLI flags or env vars so a budget stop
    # doesn't silently cascade across resumes.
    goal_budget: GoalBudget | None = None

    # Phase 68.1: per-turn working-tree snapshots feed ``/undo`` and
    # ``/redo``.  Disable for monorepos where snapshotting the tree
    # is too expensive — escape hatch is the ``--no-snapshots`` CLI
    # flag or ``CANTRIP_SNAPSHOTS=false``.
    snapshot_enabled: bool = True

    # Phase 68.4: session-level read-only mode.  When ``True`` the
    # executor composes ``PLAN_MODE_OVERLAY`` onto every subagent's
    # permission ruleset and the main-agent tool dispatcher refuses
    # non-allowlisted tools with a "plan mode" error.  Toggled via
    # the ``/plan`` and ``/build`` slash commands; sticky for the
    # session, not persisted across restarts.  ``plan_summary``
    # stores the most recent "Proposed changes" section so
    # ``/build`` can feed it back as resume context.
    plan_mode: bool = False
    plan_summary: str | None = None

    # Phase 69.2: unattended ("yolo") mode.  When ``True`` every
    # Phase 68.2 ``ask`` decision auto-approves instead of parking
    # on a user CONFIRM — useful for CI runs.  ``deny`` rules still
    # block outright.  Toggled via ``/yolo`` or the ``--yolo`` CLI
    # flag; sticky for the session and not persisted.
    yolo_mode: bool = False

    # Phase 69.1: Ralph Loop refinement cap.  ``0`` disables the
    # outer iterate-until-green loop (single-shot); ``-1`` means
    # unlimited (the loop is bounded only by convergence /
    # stall detection); positive integers cap the run.  Toggled
    # via ``/ralph N`` or ``--ralph N`` on the run subparser; the
    # convergence signal defaults to ``STOP`` and is currently not
    # user-configurable per session.  Sticky for the session, not
    # persisted across restarts (a CI run picks up its cap from
    # the CLI flag every time).
    ralph_max_iterations: int = 0

    # Phase 70.2: Oracle — on-demand consult of a stronger model.
    # ``oracle_provider_name`` / ``oracle_model`` override the
    # defaults (``claude`` / ``claude-opus-4-7``).  The two budget
    # caps stop the agent spamming the expensive model: at most
    # ``oracle_max_calls_per_turn`` invocations between user
    # messages, and at most ``oracle_max_session_cost_usd`` USD
    # across the whole session (cumulative).  The ``oracle_*``
    # counters track usage; ``oracle_calls_this_turn`` resets at
    # the top of each conversation turn, the rest are session
    # totals.  Not persisted — every CI run starts fresh.
    oracle_provider_name: str | None = None
    oracle_model: str | None = None
    oracle_max_calls_per_turn: int = 1
    oracle_max_session_cost_usd: float = 2.0
    oracle_calls_this_turn: int = 0
    oracle_calls_total: int = 0
    oracle_session_cost_usd: float = 0.0

    # Phase 71.4: per-edit lint feedback.  When ``True`` the
    # primary-agent dispatcher runs ``ruff`` (Python), ``ty``
    # (Python types) and ``charmlint`` (charm YAML) against the
    # touched file after every successful ``write_file`` /
    # ``edit_file`` / ``multi_edit`` call and appends any
    # diagnostics to the tool result so the agent reacts in the
    # same turn.  Failing diagnostics never demote the original
    # tool result — the file edit succeeded, the lint is advisory.
    # Sticky for the session; toggled via ``--no-auto-lint`` at
    # startup or directly on ``state.auto_lint``.
    auto_lint: bool = True

    # Phase 71.3: auto-commit-per-turn.  When ``True``, every turn
    # that mutates files lands as a discrete, attributed git commit
    # with a ``Co-Authored-By: Cantrip`` trailer.  Pre-existing
    # dirty work commits separately as ``chore(pre-cantrip): save
    # in-progress work`` so the user's hand-edits stay distinct
    # from the agent's edits in ``git log``.  Toggled via
    # ``--no-auto-commit`` at startup or ``/auto-commit on|off``
    # mid-session.  ``last_cantrip_commit_sha`` records the most
    # recent agent-authored commit so future audit / undo logic
    # can find it without re-walking ``git log``.
    git_auto_commit: bool = True
    last_cantrip_commit_sha: str | None = None

    # Phase 71.2: architect/editor two-model split.  When ``True``,
    # every LLM call in the conversation loop runs through two
    # passes: an *architect* pass on the main provider that emits
    # a plain-prose proposal (no tools), then an *editor* pass on
    # a cheaper provider that consumes the proposal and emits the
    # actual ``fs_edit`` / ``fs_write`` tool calls.  Saves cost on
    # BUILD turns where the expensive thinking happens once and the
    # mechanical edits run on a cheap model.  When the
    # ``editor_provider`` / ``editor_model`` overrides are unset
    # the editor falls back to ``resolve_light_provider``'s
    # same-family choice; if no lighter variant exists the editor
    # ends up on the main provider (no cost saving but the dual-
    # pass shape stays).  Toggled via ``/architect`` or the
    # ``--architect`` CLI flag.  ``architect_consecutive_failures``
    # tracks the per-turn count of editor passes whose tool calls
    # all failed; after ``architect_failure_threshold`` consecutive
    # failures the next editor pass is escalated to the architect
    # provider so a weak model can't get stuck.
    architect_mode: bool = False
    editor_provider: str | None = None
    editor_model: str | None = None
    architect_consecutive_failures: int = 0
    architect_failure_threshold: int = 2

    messages: list[Message] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)

    def add_decision(self, type: str, choice: str, reason: str | None = None) -> None:
        """Record a decision."""
        self.decisions.append(Decision(type=type, choice=choice, reason=reason))
