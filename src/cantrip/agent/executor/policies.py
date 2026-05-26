"""Default ``EnvironmentChecker`` and ``FollowupPlanner`` implementations."""

import pathlib

from cantrip.agent.autodeploy import followup_tasks, openstack_acceptance_task
from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.agent.state import AgentState


class _DefaultEnvironmentChecker:
    """Pre-task environment validation using AgentState."""

    def __init__(self, state: AgentState) -> None:
        self._state = state

    def check(self, task: AgentTask) -> str | None:
        if task.category == TaskCategory.DEPLOY:
            if not self._state.dev_model:
                return "No development model set — cannot deploy"
            if not self._state.charm_path:
                return "No charm path set — cannot deploy"
            if not pathlib.Path(self._state.charm_path).exists():
                return f"Charm path {self._state.charm_path} does not exist"

        if task.category == TaskCategory.TEST:
            if not self._state.charm_path:
                return "No charm path set — cannot test"
            charm_dir = pathlib.Path(self._state.charm_path)
            if not charm_dir.exists():
                return f"Charm path {self._state.charm_path} does not exist"
            if not list(charm_dir.glob("*.charm")):
                return "No packed charm found — run charmcraft_pack first"

        return None


class _DefaultFollowupPlanner:
    """Creates follow-up tasks using autodeploy.followup_tasks()."""

    def __init__(self, state: AgentState) -> None:
        self._state = state

    def followup_tasks(self, task: AgentTask) -> list[AgentTask]:
        if not self._state.dev_model:
            return []
        followups = list(followup_tasks(task))
        # Phase 97.3: layer the OpenStack acceptance task on top of the
        # base follow-ups when the active controller is on a Canonical
        # OpenStack / Sunbeam cloud.  ``state.active_cloud`` is empty
        # until the agent has built a system prompt at least once —
        # which always happens before the executor dispatches a TEST
        # task, so the hint is reliably present by the time a TEST
        # finishes.
        followups.extend(openstack_acceptance_task(task, active_cloud=self._state.active_cloud))
        return followups
