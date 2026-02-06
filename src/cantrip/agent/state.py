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
class AgentState:
    """Current agent state."""

    charm_name: str | None = None
    charm_path: Path | None = None
    charm_type: str | None = None  # "machine" or "k8s"
    framework: str | None = None

    dev_model: str | None = None
    cos_model: str | None = None

    messages: list[Message] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)

    def add_decision(self, type: str, choice: str, reason: str | None = None) -> None:
        """Record a decision."""
        self.decisions.append(Decision(type=type, choice=choice, reason=reason))
