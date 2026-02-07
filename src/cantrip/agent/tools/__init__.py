"""Agent tools."""

from cantrip.agent.tools.base import Tool, ToolResult, tool_to_schema
from cantrip.agent.tools.charm import (
    AnalyseFrameworkTool,
    CharmcraftFetchLibsTool,
    CharmcraftInitTool,
    CharmcraftPackTool,
)
from cantrip.agent.tools.environment import (
    ConciergePrepareTool,
    ConciergeStatusTool,
)
from cantrip.agent.tools.files import (
    EditFileTool,
    ListDirectoryTool,
    ReadFileTool,
    WriteFileTool,
)
from cantrip.agent.tools.git import (
    GitAddTool,
    GitCloneTool,
    GitCommitTool,
    GitDiffTool,
    GitInitTool,
    GitLogTool,
    GitPushTool,
    GitStatusTool,
)
from cantrip.agent.tools.github import (
    GhIssueListTool,
    GhPrCreateTool,
    GhRepoCreateTool,
)
from cantrip.agent.tools.juju import (
    JujuAddModelTool,
    JujuConsumeTool,
    JujuDeployTool,
    JujuDestroyModelTool,
    JujuOfferTool,
    JujuRefreshTool,
    JujuRelateTool,
    JujuRunActionTool,
    JujuSSHTool,
    JujuStatusTool,
)
from cantrip.agent.tools.rockcraft import (
    RockcraftInitTool,
    RockcraftPackTool,
    SkopeoRegistryPushTool,
)
from cantrip.agent.tools.skills import LoadSkillTool
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
    # Environment
    "ConciergePrepareTool",
    "ConciergeStatusTool",
    # Rockcraft
    "RockcraftInitTool",
    "RockcraftPackTool",
    "SkopeoRegistryPushTool",
    # Juju
    "JujuStatusTool",
    "JujuDeployTool",
    "JujuRefreshTool",
    "JujuRelateTool",
    "JujuSSHTool",
    "JujuRunActionTool",
    "JujuAddModelTool",
    "JujuDestroyModelTool",
    "JujuOfferTool",
    "JujuConsumeTool",
    # Git
    "GitCloneTool",
    "GitInitTool",
    "GitStatusTool",
    "GitDiffTool",
    "GitLogTool",
    "GitAddTool",
    "GitCommitTool",
    "GitPushTool",
    # GitHub
    "GhRepoCreateTool",
    "GhPrCreateTool",
    "GhIssueListTool",
    # Skills
    "LoadSkillTool",
    # Web
    "WebFetchTool",
]
