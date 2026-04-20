"""Peek at a persisted ``.cantrip`` session without loading it.

Phase 31.3 replaces the old "silently load whatever's on disk" behaviour
with a choice: *Resume*, *Fresh*, or *Transcript*.  Each surface (CLI,
TUI, Web) renders the prompt differently, so they share a lightweight
preview value.  The preview is pure data — no network, no ``state``
mutation — so building it is always cheap enough to run on launch.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class SessionPreview:
    """Snapshot of a persisted session used to render a resume prompt.

    ``exists`` is False when no ``.cantrip`` file is on disk or no
    session row has been written yet; the other fields should be
    ignored in that case.
    """

    exists: bool = False
    charm_name: str | None = None
    charm_type: str | None = None
    framework: str | None = None
    dev_model: str | None = None
    cos_model: str | None = None
    updated_at: str | None = None
    message_count: int = 0
    task_counts: dict[str, int] = dataclasses.field(default_factory=dict)

    @property
    def has_unfinished_tasks(self) -> bool:
        """True if any task in the queue is pending, active, or blocked."""
        return any(self.task_counts.get(s, 0) > 0 for s in ("pending", "active", "blocked"))

    def summary(self) -> str:
        """One-line human-readable summary used in prompts."""
        if not self.exists:
            return "No prior session."
        bits: list[str] = []
        if self.charm_name:
            kind = f" ({self.charm_type})" if self.charm_type else ""
            bits.append(f"{self.charm_name}{kind}")
        if self.message_count:
            bits.append(f"{self.message_count} messages")
        pending = sum(self.task_counts.get(s, 0) for s in ("pending", "active", "blocked"))
        done = self.task_counts.get("done", 0)
        failed = self.task_counts.get("failed", 0)
        if pending or done or failed:
            parts = []
            if done:
                parts.append(f"{done} done")
            if pending:
                parts.append(f"{pending} pending")
            if failed:
                parts.append(f"{failed} failed")
            bits.append(", ".join(parts))
        if self.updated_at:
            bits.append(f"saved {self.updated_at}")
        return "Prior session: " + " · ".join(bits) if bits else "Prior session on disk."
