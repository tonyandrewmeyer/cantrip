"""Task planning tool — conversation-facing wrapper for the TaskPlanner."""

import logging
import shutil
import subprocess
from typing import Any

from cantrip.agent.planner import PlanningContext, TaskPlanner, is_sprint
from cantrip.agent.queue import WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.llm import base as llm

log = logging.getLogger(__name__)


class PlanTasksTool(Tool):
    """Decompose a charm-building intent into an ordered task list.

    The conversation LLM calls this tool when it recognises that the user
    wants to build (or significantly change) a charm. The planner calls
    the LLM separately to generate concrete tasks, adds them to the work
    queue, and returns a human-readable summary.
    """

    def __init__(
        self,
        provider: llm.LLMProvider,
        state: AgentState,
        queue: WorkQueue,
    ) -> None:
        self._planner = TaskPlanner(provider)
        self._state = state
        self._queue = queue

    @property
    def name(self) -> str:
        return "plan_tasks"

    @property
    def description(self) -> str:
        return (
            "Decompose a charm-building intent into an ordered task list. "
            "Call this when the user describes a new charm to build or requests "
            "a major scope change. Returns a structured plan with dependencies."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "description": (
                        "What the user wants to build or change, e.g. 'build a charm for Redis'"
                    ),
                },
                "charm_name": {
                    "type": "string",
                    "description": "Name for the charm (optional, inferred if omitted)",
                },
                "charm_type": {
                    "type": "string",
                    "enum": ["k8s", "machine"],
                    "description": "Substrate type (optional)",
                },
            },
            "required": ["intent"],
        }

    async def execute(
        self,
        intent: str,
        charm_name: str | None = None,
        charm_type: str | None = None,
    ) -> ToolResult:
        """Plan tasks for the given intent and add them to the work queue."""
        if not intent.strip():
            return ToolResult(
                success=False,
                output="",
                error="Intent must not be empty.",
            )

        # Determine existing charm path for improvement mode.
        existing_charm_path: str | None = None
        if self._state.mode == "improve" and self._state.charm_path:
            existing_charm_path = str(self._state.charm_path)

        context = PlanningContext(
            intent=intent,
            charm_name=charm_name or self._state.charm_name,
            charm_type=charm_type or self._state.charm_type,
            framework=self._state.framework,
            dev_model=self._state.dev_model,
            cos_model=self._state.cos_model,
            environment_ready=self._state.environment_ready,
            existing_tasks=self._queue.all_tasks(),
            existing_charm_path=existing_charm_path,
        )

        # Replan if there are already tasks in the queue.
        try:
            if context.existing_tasks:
                context.new_context = intent
                tasks = await self._planner.replan(context)
            else:
                tasks = await self._planner.plan(context)
        except ValueError:
            log.exception("Failed to parse planning response")
            return ToolResult(
                success=False,
                output="",
                error="Failed to generate a valid task plan. Please try rephrasing.",
            )

        self._queue.add_tasks(tasks)

        # Sprint path: eagerly set state so deploy tasks can proceed
        # without the conversation LLM needing to set things up.
        if is_sprint(context):
            if not self._state.dev_model:
                detected = _detect_current_juju_model()
                if detected:
                    self._state.dev_model = detected
                    log.info("Sprint: auto-detected dev model '%s'", detected)
            # Set charm_path to where charmcraft_init will scaffold.
            if context.charm_name and self._state.charm_path:
                from pathlib import Path

                expected_path = Path(self._state.charm_path) / context.charm_name
                self._state.charm_path = expected_path
                log.info("Sprint: set charm_path to '%s'", expected_path)

        # Persist charm_name and charm_type from the planning context.
        if context.charm_name and not self._state.charm_name:
            self._state.charm_name = context.charm_name
        if context.charm_type and not self._state.charm_type:
            self._state.charm_type = context.charm_type

        summary = _format_plan_summary(tasks)
        return ToolResult(
            success=True,
            output=summary,
            data={"task_count": len(tasks)},
        )


def _detect_current_juju_model() -> str | None:
    """Return the name of the currently active (starred) Juju model.

    Prefers the model marked as current (``*`` in ``juju models``).
    Skips the controller model and ``cos`` (which is for observability).
    """
    juju = shutil.which("juju")
    if not juju:
        return None
    try:
        result = subprocess.run(
            [juju, "models", "--format=json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        import json

        data = json.loads(result.stdout)
        current_model = data.get("current-model")
        models = data.get("models", [])

        # Prefer the current model if it's not controller/cos.
        skip = {"controller", "cos"}
        if current_model and current_model not in skip:
            return current_model

        # Otherwise pick the first non-controller, non-cos model.
        for model in models:
            if model.get("is-controller"):
                continue
            name = model.get("short-name", "")
            if name in skip:
                continue
            if name:
                return name
    except (subprocess.TimeoutExpired, OSError, ValueError, KeyError):
        return None
    return None


def _format_plan_summary(tasks: list) -> str:
    """Format a human-readable plan summary."""
    if not tasks:
        return "No tasks generated."

    lines = [f"**Task plan** ({len(tasks)} tasks):\n"]
    for i, task in enumerate(tasks, 1):
        deps = ""
        if task.dependencies:
            deps = f" (after: {', '.join(task.dependencies)})"
        lines.append(f"{i}. [{task.category.value}] **{task.title}**{deps}")
        if task.description:
            lines.append(f"   {task.description}")

    lines.append("\nShall I proceed with this plan?")
    return "\n".join(lines)
