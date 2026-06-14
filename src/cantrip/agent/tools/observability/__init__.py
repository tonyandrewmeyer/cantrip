"""Observability tools for querying debug logs, Tempo traces, and Loki logs.

The tools split across submodules by surface: ``logs`` holds the text
query/log tools (debug-log, stream, Tempo query, Loki query); ``rendering``
holds the image-rendering tools (Grafana screenshot, Tempo waterfall, Juju
status render); ``_common`` holds the shared COS-unit lookup, output
truncation, and SSH fetch helpers plus the patchable ``_juju_available``.
"""

# Re-exported so ``observability.jubilant`` / ``observability.asyncio`` remain
# the patch targets the tests reach for (both are shared module objects).
import asyncio  # noqa: F401

import jubilant  # noqa: F401

from cantrip.agent.tools.observability._common import _find_cos_unit
from cantrip.agent.tools.observability.logs import (
    JujuDebugLogTool,
    JujuStreamLogsTool,
    LokiQueryTool,
    TempoQueryTool,
)
from cantrip.agent.tools.observability.rendering import (
    _PNG_MAGIC,
    _STATUS_MAX_LINES,
    GrafanaScreenshotTool,
    JujuStatusRenderTool,
    TempoWaterfallTool,
    _collect_relation_entries,
    _collect_spans_from_trace,
    _format_duration,
    _grafana_admin_password,
    _juju_status_tree_lines,
    _render_status_png,
    _render_waterfall_png,
)

__all__ = [
    "JujuDebugLogTool",
    "JujuStreamLogsTool",
    "TempoQueryTool",
    "LokiQueryTool",
    "GrafanaScreenshotTool",
    "TempoWaterfallTool",
    "JujuStatusRenderTool",
    "_find_cos_unit",
    "_PNG_MAGIC",
    "_STATUS_MAX_LINES",
    "_collect_relation_entries",
    "_collect_spans_from_trace",
    "_format_duration",
    "_grafana_admin_password",
    "_juju_status_tree_lines",
    "_render_status_png",
    "_render_waterfall_png",
]
