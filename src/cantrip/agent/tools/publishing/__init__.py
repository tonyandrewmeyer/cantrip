"""Charmhub publishing, README generation, icon, and documentation tools.

This package groups the publishing surfaces into one module each
(charmcraft upload/release, icon, diagram, readme, docs scaffold, design
decisions, troubleshooting).  Every public name — and the private helpers
the test-suite imports — is re-exported here so
``cantrip.agent.tools.publishing`` stays the single import point.
"""

from cantrip.agent.tools.publishing._common import (
    _read_charm_metadata,
    generate_architecture_diagram,
)
from cantrip.agent.tools.publishing.charmcraft import (
    CharmcraftReleaseTool,
    CharmcraftUploadTool,
)
from cantrip.agent.tools.publishing.design_decisions import (
    _DECISIONS_MARKER,
    ExtractDesignDecisionsTool,
    _compose_architecture_page,
    _read_decisions,
    _resolve_architecture_intro,
    format_decision_log,
)
from cantrip.agent.tools.publishing.diagram import GenerateDiagramTool
from cantrip.agent.tools.publishing.docs_scaffold import (
    AcceptanceArtefacts,
    GenerateDocsTool,
    _build_actions_block,
    _build_actions_ref_block,
    _build_config_block,
    _build_config_ref_block,
    _build_integ_ref_block,
    _build_integrate_block,
    _build_integrations_block,
    _docs_template_env,
    _populate_actions_from_artefacts,
    _populate_deploy_and_verify_from_artefacts,
    _populate_tutorial_from_artefacts,
    _replace_first_h1,
    _rewrite_links,
    _rewrite_root_link,
    bridge_root_file,
    generate_docs_scaffold,
    load_acceptance_artefacts,
    sanitise_capture,
)
from cantrip.agent.tools.publishing.icon import (
    GenerateIconTool,
    generate_placeholder_svg,
)
from cantrip.agent.tools.publishing.readme import GenerateReadmeTool
from cantrip.agent.tools.publishing.troubleshooting import (
    _CATEGORY_ORDER,
    _MIN_DIAGNOSTIC_LINES,
    _TROUBLESHOOTING_MARKER,
    ExtractTroubleshootingTool,
    TroubleshootingEntry,
    _categorise_error,
    _compose_troubleshooting_page,
    _ensure_troubleshooting_in_toctree,
    _format_troubleshooting_entry,
    _read_transcript_pairs,
    _resolve_troubleshooting_intro,
    _strip_tool_result_wrapper,
    format_troubleshooting_page,
)

# Every re-exported name is listed so it counts as part of the package's
# public surface (and so the lint catches genuinely unused imports).  This
# includes the private helpers the unit suite imports directly through the
# package — they stay importable from ``cantrip.agent.tools.publishing``.
__all__ = [
    "_CATEGORY_ORDER",
    "_DECISIONS_MARKER",
    "_MIN_DIAGNOSTIC_LINES",
    "_TROUBLESHOOTING_MARKER",
    "AcceptanceArtefacts",
    "CharmcraftReleaseTool",
    "CharmcraftUploadTool",
    "ExtractDesignDecisionsTool",
    "ExtractTroubleshootingTool",
    "GenerateDiagramTool",
    "GenerateDocsTool",
    "GenerateIconTool",
    "GenerateReadmeTool",
    "TroubleshootingEntry",
    "_build_actions_block",
    "_build_actions_ref_block",
    "_build_config_block",
    "_build_config_ref_block",
    "_build_integ_ref_block",
    "_build_integrate_block",
    "_build_integrations_block",
    "_categorise_error",
    "_compose_architecture_page",
    "_compose_troubleshooting_page",
    "_docs_template_env",
    "_ensure_troubleshooting_in_toctree",
    "_format_troubleshooting_entry",
    "_populate_actions_from_artefacts",
    "_populate_deploy_and_verify_from_artefacts",
    "_populate_tutorial_from_artefacts",
    "_read_charm_metadata",
    "_read_decisions",
    "_read_transcript_pairs",
    "_replace_first_h1",
    "_resolve_architecture_intro",
    "_resolve_troubleshooting_intro",
    "_rewrite_links",
    "_rewrite_root_link",
    "_strip_tool_result_wrapper",
    "bridge_root_file",
    "format_decision_log",
    "format_troubleshooting_page",
    "generate_architecture_diagram",
    "generate_docs_scaffold",
    "generate_placeholder_svg",
    "load_acceptance_artefacts",
    "sanitise_capture",
]
