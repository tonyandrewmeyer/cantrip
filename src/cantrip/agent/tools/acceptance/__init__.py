"""Acceptance testing tools — exercise a deployed charm like a real operator.

Provides five tools for acceptance testing:
- ActionExerciserTool: run every action and verify results
- RelationSmokeTool: deploy partner charms and verify integrations
- WorkloadEndpointTool: probe HTTP/TCP endpoints on the running workload
- ConfigVariationTool: set each config option and verify the charm settles
- AcceptanceReportTool: consolidate results into ACCEPTANCE.md

The tools split across submodules by surface; the shared helpers and the
patchable ``juju_subprocess`` reference live in ``_common``.
"""

from cantrip.agent.tools import juju_subprocess
from cantrip.agent.tools.acceptance._common import (
    _DESTRUCTIVE_PATTERNS,
    _INTERFACE_PARTNERS,
    _generate_action_params,
    _generate_test_value,
    _get_unit_address,
    _load_charm_metadata,
    _verify_relation_data,
)
from cantrip.agent.tools.acceptance.actions import ActionExerciserTool
from cantrip.agent.tools.acceptance.config import ConfigUnderLoadTool, ConfigVariationTool
from cantrip.agent.tools.acceptance.endpoints import WorkloadEndpointTool
from cantrip.agent.tools.acceptance.relations import RelationSmokeTool
from cantrip.agent.tools.acceptance.report import AcceptanceReportTool

__all__ = [
    "ActionExerciserTool",
    "RelationSmokeTool",
    "WorkloadEndpointTool",
    "ConfigVariationTool",
    "ConfigUnderLoadTool",
    "AcceptanceReportTool",
    "juju_subprocess",
    "_DESTRUCTIVE_PATTERNS",
    "_INTERFACE_PARTNERS",
    "_generate_action_params",
    "_generate_test_value",
    "_get_unit_address",
    "_load_charm_metadata",
    "_verify_relation_data",
]
