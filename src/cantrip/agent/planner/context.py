"""Shared planning-context dataclass used by both planner paths."""

from __future__ import annotations

import dataclasses

from cantrip.agent.queue import AgentTask


@dataclasses.dataclass
class PlanningContext:
    """Bundles context for a planning or replanning call."""

    intent: str
    charm_name: str | None = None
    charm_type: str | None = None
    framework: str | None = None
    dev_model: str | None = None
    cos_model: str | None = None
    environment_ready: bool = False
    existing_tasks: list[AgentTask] = dataclasses.field(default_factory=list)
    new_context: str | None = None
    source_url: str | None = None
    existing_charm_path: str | None = None
