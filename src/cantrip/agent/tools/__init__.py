"""Agent tools."""

from cantrip.agent.tools.base import Tool, ToolResult, tool_to_schema
from cantrip.agent.tools.charm import (
    AnalyseFrameworkTool,
    CharmcraftFetchLibsTool,
    CharmcraftInitTool,
    CharmcraftPackTool,
    CharmValidateTool,
)
from cantrip.agent.tools.charmhub import (
    CharmhubInfoTool,
    CharmhubSearchTool,
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
    CharmSyncTool,
    JujuAddModelTool,
    JujuConfigTool,
    JujuConsumeTool,
    JujuDeployTool,
    JujuDestroyModelTool,
    JujuDispatchTool,
    JujuOfferTool,
    JujuRefreshTool,
    JujuRelateTool,
    JujuRunActionTool,
    JujuSSHTool,
    JujuStatusTool,
    JujuWaitTool,
)
from cantrip.agent.tools.observability import (
    JujuDebugLogTool,
    LokiQueryTool,
    TempoQueryTool,
)
from cantrip.agent.tools.planning import PlanTasksTool
from cantrip.agent.tools.publishing import (
    CharmcraftReleaseTool,
    CharmcraftUploadTool,
    GenerateReadmeTool,
)
from cantrip.agent.tools.registry import (
    RegistryImageInfoTool,
    RegistrySearchTool,
)
from cantrip.agent.tools.rockcraft import (
    RockcraftInitTool,
    RockcraftPackTool,
    SkopeoRegistryPushTool,
)
from cantrip.agent.tools.skills import LoadSkillTool
from cantrip.agent.tools.task_management import ManageTasksTool
from cantrip.agent.tools.testing import RunCharmTestsTool
from cantrip.agent.tools.virtual_files import VirtualFileReadTool, VirtualFileSearchTool
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
    "CharmValidateTool",
    "CharmcraftFetchLibsTool",
    "AnalyseFrameworkTool",
    # Charmhub
    "CharmhubSearchTool",
    "CharmhubInfoTool",
    # Environment
    "ConciergePrepareTool",
    "ConciergeStatusTool",
    # Registry
    "RegistrySearchTool",
    "RegistryImageInfoTool",
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
    "JujuConfigTool",
    "JujuConsumeTool",
    "JujuWaitTool",
    "CharmSyncTool",
    "JujuDispatchTool",
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
    # Observability
    "JujuDebugLogTool",
    "TempoQueryTool",
    "LokiQueryTool",
    # Testing
    "RunCharmTestsTool",
    # Planning
    "PlanTasksTool",
    # Task management
    "ManageTasksTool",
    # Skills
    "LoadSkillTool",
    # Virtual files
    "VirtualFileReadTool",
    "VirtualFileSearchTool",
    # Publishing
    "CharmcraftUploadTool",
    "CharmcraftReleaseTool",
    "GenerateReadmeTool",
    # Web
    "WebFetchTool",
]
