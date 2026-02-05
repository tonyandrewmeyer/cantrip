"""Agent tools."""

from cantrip.agent.tools.base import Tool, ToolResult, tool_to_schema
from cantrip.agent.tools.charm import (
    AnalyseFrameworkTool,
    CharmcraftFetchLibsTool,
    CharmcraftInitTool,
    CharmcraftPackTool,
)
from cantrip.agent.tools.files import (
    EditFileTool,
    ListDirectoryTool,
    ReadFileTool,
    WriteFileTool,
)
from cantrip.agent.tools.juju import (
    JujuDeployTool,
    JujuRefreshTool,
    JujuRelateTool,
    JujuRunActionTool,
    JujuSSHTool,
    JujuStatusTool,
)
from cantrip.agent.tools.web import WebFetchTool

__all__ = [
    # Base
    "Tool",
    "ToolResult",
    "tool_to_schema",
    # Files
    "ReadFileTool",
    "WriteFileTool",
    "ListDirectoryTool",
    "EditFileTool",
    # Charm
    "CharmcraftInitTool",
    "CharmcraftPackTool",
    "CharmcraftFetchLibsTool",
    "AnalyseFrameworkTool",
    # Juju
    "JujuStatusTool",
    "JujuDeployTool",
    "JujuRefreshTool",
    "JujuRelateTool",
    "JujuSSHTool",
    "JujuRunActionTool",
    # Web
    "WebFetchTool",
]
