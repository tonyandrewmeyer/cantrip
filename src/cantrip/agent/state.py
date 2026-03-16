"""Agent state data structures."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from cantrip.llm.base import Message


@dataclass
class Decision:
    """A decision made during the session."""

    type: str
    choice: str
    reason: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)

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
    charm_path: Path | None = None
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

    # Transient design proposal — not persisted, populated after synthesis.
    design_proposal: object | None = None

    # Transient audit report — populated after charm_audit completes.
    audit_report: str | None = None

    messages: list[Message] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)

    def add_decision(self, type: str, choice: str, reason: str | None = None) -> None:
        """Record a decision."""
        self.decisions.append(Decision(type=type, choice=choice, reason=reason))
