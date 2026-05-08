"""Task planning tool — conversation-facing wrapper for the TaskPlanner."""

import json
import logging
import pathlib
import shutil
import subprocess
from collections.abc import Callable
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
        invalidate_tools_cache: Callable[[], None] | None = None,
    ) -> None:
        self._planner = TaskPlanner(provider)
        self._state = state
        self._queue = queue
        self._invalidate_tools_cache = invalidate_tools_cache

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

        # Persist charm_name and charm_type from the planning context first
        # so that downstream auto-detection can prefer the right substrate.
        if context.charm_name and not self._state.charm_name:
            self._state.charm_name = context.charm_name
        if context.charm_type and not self._state.charm_type:
            self._state.charm_type = context.charm_type

        # Sprint path: eagerly set state so deploy tasks can proceed
        # without the conversation LLM needing to set things up.
        if is_sprint(context):
            substrate = self._state.charm_type
            # If a previously-detected dev_model has the wrong substrate
            # (e.g. an LXD model when the charm is k8s), drop it and
            # re-detect — the original guess was made before charm_type
            # was known.
            if self._state.dev_model and substrate:
                actual = juju_model_substrate(self._state.dev_model)
                if actual is not None and actual != substrate:
                    log.info(
                        "Sprint: dev_model '%s' is %s but charm is %s — re-detecting",
                        self._state.dev_model,
                        actual,
                        substrate,
                    )
                    self._state.dev_model = None
            if not self._state.dev_model:
                detected = detect_current_juju_model(prefer_substrate=substrate)
                if detected:
                    self._state.dev_model = detected
                    log.info("Sprint: auto-detected dev model '%s'", detected)
            # Set charm_path to where charmcraft_init will scaffold.
            if context.charm_name and self._state.charm_path:
                expected_path = pathlib.Path(self._state.charm_path) / context.charm_name
                self._state.charm_path = expected_path
                log.info("Sprint: set charm_path to '%s'", expected_path)
                # File tools captured the old base_path at construction;
                # rebuild them so subsequent ``edit_file("charmcraft.yaml")``
                # resolves against the scaffold subdir without the model
                # having to prefix every path with ``<charm_name>/``.
                if self._invalidate_tools_cache is not None:
                    self._invalidate_tools_cache()

        summary = _format_plan_summary(tasks)
        return ToolResult(
            success=True,
            output=summary,
            data={"task_count": len(tasks)},
        )


_SKIP_MODELS = frozenset({"controller", "cos"})


def _substrate_for_model_type(model_type: str | None) -> str | None:
    """Translate a Juju ``model-type`` into the cantrip substrate label.

    ``caas`` is Kubernetes; ``iaas`` is machine (lxd, MAAS, openstack, …).
    Anything else is unknown.
    """
    if model_type == "caas":
        return "k8s"
    if model_type == "iaas":
        return "machine"
    return None


def _list_juju_models() -> tuple[str | None, list[dict[str, Any]]]:
    """Return ``(current_model, models)`` from ``juju models --format=json``.

    Returns ``(None, [])`` if Juju is unavailable or the call fails — callers
    treat that as "no Juju on this host" and skip auto-detection.
    """
    juju = shutil.which("juju")
    if not juju:
        return None, []
    try:
        result = subprocess.run(
            [juju, "models", "--format=json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None, []
        data = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, OSError, ValueError, KeyError):
        return None, []
    return data.get("current-model"), data.get("models", []) or []


def detect_current_juju_model(prefer_substrate: str | None = None) -> str | None:
    """Return the name of an active Juju model suitable for ``dev_model``.

    Prefers the model marked as current (``*`` in ``juju models``) and
    skips the controller model and ``cos`` (which is for observability).

    When ``prefer_substrate`` is ``"k8s"`` or ``"machine"``, models whose
    ``model-type`` matches that substrate are preferred (k8s ↔ ``caas``,
    machine ↔ ``iaas``).  This stops auto-detection picking, say, an
    LXD model when the charm under development is a Kubernetes charm.
    If no model matches the preferred substrate the function falls back
    to the first non-controller, non-cos model so behaviour without Juju
    type metadata stays stable.
    """
    current_model, models = _list_juju_models()
    if not models and not current_model:
        return None

    candidates: list[tuple[str, str | None]] = []
    for model in models:
        if model.get("is-controller"):
            continue
        name = model.get("short-name") or ""
        if not name or name in _SKIP_MODELS:
            continue
        candidates.append((name, _substrate_for_model_type(model.get("model-type"))))

    def _matches(substrate: str | None) -> bool:
        return prefer_substrate is None or substrate == prefer_substrate

    # Prefer the current model when it is eligible and matches the substrate.
    if current_model and current_model not in _SKIP_MODELS:
        for name, substrate in candidates:
            if name == current_model and _matches(substrate):
                return name

    # Otherwise the first substrate-matching candidate.
    for name, substrate in candidates:
        if _matches(substrate):
            return name

    # No substrate-matching candidate: fall back to the legacy behaviour so
    # callers without a substrate preference (or against older Juju that
    # omits ``model-type``) keep getting an answer.
    if prefer_substrate is not None:
        if current_model and current_model not in _SKIP_MODELS:
            return current_model
        for name, _ in candidates:
            return name
    return None


def juju_model_substrate(model_name: str) -> str | None:
    """Return the substrate label (``"k8s"``/``"machine"``) of ``model_name``.

    Used to validate an already-set ``dev_model`` against a known
    ``charm_type``.  Returns ``None`` when Juju is unavailable, the
    model is unknown, or its ``model-type`` is not recognised.
    """
    if not model_name:
        return None
    _, models = _list_juju_models()
    for model in models:
        if model.get("short-name") == model_name:
            return _substrate_for_model_type(model.get("model-type"))
    return None


def detect_cos_juju_model() -> str | None:
    """Return the name of the ``cos`` model if the controller has one.

    Cantrip conventionally deploys COS into a model called ``cos``;
    this helper answers yes/no without hard-coding the name at the
    call site so the Dev/COS panes can auto-populate.
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
        data = json.loads(result.stdout)
        for model in data.get("models", []):
            if model.get("short-name") == "cos":
                return "cos"
    except (subprocess.TimeoutExpired, OSError, ValueError, KeyError):
        return None
    return None


def _format_plan_summary(tasks: list) -> str:
    """Format a human-readable plan summary.

    Each task's full description (the imperative subagent prompt with
    its own "Do NOT…" directives) is omitted on purpose: small models
    occasionally read the directive list as instructions for the main
    conversation and start racing the executor on the same files.  A
    title-only summary keeps the conversation LLM focused on handing
    off rather than re-implementing the build itself.  The first
    sentence of the description is included as a hint so the user (and
    the model) still see what each task is for.
    """
    if not tasks:
        return "No tasks generated."

    lines = [f"**Task plan** ({len(tasks)} tasks):\n"]
    for i, task in enumerate(tasks, 1):
        deps = ""
        if task.dependencies:
            deps = f" (after: {', '.join(task.dependencies)})"
        lines.append(f"{i}. [{task.category.value}] **{task.title}**{deps}")
        if task.description:
            hint = _first_sentence(task.description)
            if hint:
                lines.append(f"   {hint}")

    lines.append(
        "\nThe work queue will run these tasks autonomously — do not "
        "attempt to do the build yourself.  Acknowledge briefly and stop."
    )
    return "\n".join(lines)


def _first_sentence(text: str, *, max_chars: int = 200) -> str:
    """Return the first sentence of *text*, capped at *max_chars*.

    Sprint task descriptions begin with a one-liner summary ("Build a
    minimal charm and pack it as fast as possible."); we want that to
    travel through the plan summary while the imperative steps below
    stay scoped to the subagent prompt.
    """
    stripped = text.strip()
    if not stripped:
        return ""
    head = stripped.split("\n", 1)[0]
    period = head.find(". ")
    if 0 <= period < max_chars:
        return head[: period + 1]
    return head[:max_chars]
