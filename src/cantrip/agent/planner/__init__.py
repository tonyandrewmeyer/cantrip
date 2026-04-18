"""Task planner — LLM-powered decomposition of user intent into agent tasks.

For the common "build a charm for X" flow, the research phase uses
deterministic task templates (``deterministic``).  LLM planning
(``llm``) is reserved for replanning (scope changes) and for generating
build/day2 tasks from an approved design or operations plan.

The public API is re-exported from this package root so existing
``from cantrip.agent.planner import ...`` imports keep working after
the Phase 53.3 split.
"""

from cantrip.agent.planner.context import PlanningContext
from cantrip.agent.planner.deterministic import (
    DAY2_CONFIRM_BASE,
    DAY2_RESEARCH_PREFIX,
    DESIGN_CONFIRM_BASE,
    IMPROVEMENT_CONFIRM_BASE,
    OPERABILITY_CONFIRM_BASE,
    OPERABILITY_PREFIX,
    SPRINT_BUILD_PREFIX,
    SPRINT_DEPLOY_PREFIX,
    find_day2_anchor,
    is_fast_path,
    is_improvement,
    is_one_shot_build,
    is_sprint,
    plan_day2_ops_phase,
    plan_fast_path,
    plan_improvement_fixes,
    plan_improvement_phase,
    plan_one_shot_build,
    plan_operability_assessment,
    plan_operability_fixes,
    plan_research_phase,
    plan_sprint_deploy,
)
from cantrip.agent.planner.llm import TaskPlanner

# Private helpers re-exported for the existing test suite.  Tests import
# these from ``cantrip.agent.planner``; the ``X as X`` shape tells ruff the
# aliasing is intentional (the symbols are not part of the public API).
from cantrip.agent.planner.llm import _build_day2_to_build_prompt as _build_day2_to_build_prompt
from cantrip.agent.planner.llm import (
    _build_design_to_build_prompt as _build_design_to_build_prompt,
)
from cantrip.agent.planner.llm import _build_planning_prompt as _build_planning_prompt
from cantrip.agent.planner.llm import _build_replanning_prompt as _build_replanning_prompt
from cantrip.agent.planner.llm import _extract_json as _extract_json
from cantrip.agent.planner.llm import _merge_tasks as _merge_tasks
from cantrip.agent.planner.llm import _parse_single_task as _parse_single_task
from cantrip.agent.planner.llm import _parse_task_list as _parse_task_list
from cantrip.agent.planner.llm import _validate_dependencies as _validate_dependencies

__all__ = [
    "DAY2_CONFIRM_BASE",
    "DAY2_RESEARCH_PREFIX",
    "DESIGN_CONFIRM_BASE",
    "IMPROVEMENT_CONFIRM_BASE",
    "OPERABILITY_CONFIRM_BASE",
    "OPERABILITY_PREFIX",
    "SPRINT_BUILD_PREFIX",
    "SPRINT_DEPLOY_PREFIX",
    "PlanningContext",
    "TaskPlanner",
    "find_day2_anchor",
    "is_fast_path",
    "is_improvement",
    "is_one_shot_build",
    "is_sprint",
    "plan_day2_ops_phase",
    "plan_fast_path",
    "plan_improvement_fixes",
    "plan_improvement_phase",
    "plan_one_shot_build",
    "plan_operability_assessment",
    "plan_operability_fixes",
    "plan_research_phase",
    "plan_sprint_deploy",
]
