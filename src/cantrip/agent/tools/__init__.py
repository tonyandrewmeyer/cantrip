"""Agent tools."""

from __future__ import annotations

import pathlib
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from cantrip.agent.tools.base import Tool, ToolResult, execute_tool, tool_to_schema
from cantrip.agent.tools.subcommand import (
    SubcommandTool,
    expand_leaves,
    resolve_subcommand,
)


def build_tools(
    *,
    base_path: pathlib.Path | None = None,
    skills_index: SkillsIndex | None = None,
    virtual_store: VirtualFileStore | None = None,
    provider: Any = None,
    state: Any = None,
    queue: Any = None,
    memory_manager: MemoryManager | None = None,
    mcp_registry: MCPRegistry | None = None,
    store_getter: Callable[[], Any] | None = None,
    role_router: Any = None,
    invalidate_tools_cache: Callable[[], None] | None = None,
    code_intel_getter: Callable[[], Any] | None = None,
) -> list[Tool]:
    """Build all agent tool instances.

    Centralises tool construction so callers do not need to import
    every tool class individually.  Parameters with dependencies
    (skills, virtual store, etc.) are passed in explicitly.

    Tool modules are imported lazily inside this function — importing
    all ~100 tool classes at package-import time previously added ~1.6s
    to every TUI / CLI startup, even for commands that never build an
    agent.
    """
    # Late imports: keep ``cantrip.agent.tools`` itself cheap to import.
    from cantrip.agent.tools.acceptance import (
        AcceptanceReportTool,
        ActionExerciserTool,
        ConfigUnderLoadTool,
        ConfigVariationTool,
        RelationSmokeTool,
        WorkloadEndpointTool,
    )
    from cantrip.agent.tools.audit import CharmAuditTool
    from cantrip.agent.tools.benchmark import HookBenchmarkTool
    from cantrip.agent.tools.chaos import ChaosTestTool
    from cantrip.agent.tools.charm import (
        AnalyseFrameworkTool,
        CharmcraftFetchLibsTool,
        CharmcraftInitTool,
        CharmcraftPackTool,
        CharmValidateTool,
        GenerateTerraformTool,
        QuickPackTool,
        ValidateTerraformTool,
    )
    from cantrip.agent.tools.charmhub import (
        CharmhubFetchTool,
        CharmhubInfoTool,
        CharmhubSearchTool,
    )
    from cantrip.agent.tools.charmlint_tool import CharmlintTool
    from cantrip.agent.tools.codeintel import build_codeintel_tools
    from cantrip.agent.tools.docs_search import DocsSearchTool
    from cantrip.agent.tools.env_keys import InspectEnvKeysTool
    from cantrip.agent.tools.environment import (
        ConciergePrepareTool,
        ConciergeRestoreTool,
        ConciergeStatusTool,
    )
    from cantrip.agent.tools.files import (
        EditFileTool,
        ListDirectoryTool,
        ReadFileTool,
        WriteFileTool,
    )
    from cantrip.agent.tools.fuzz import FuzzTestTool
    from cantrip.agent.tools.git import (
        GitAddTool,
        GitBranchTool,
        GitCheckoutTool,
        GitCloneTool,
        GitCommitTool,
        GitDiffTool,
        GitInitTool,
        GitLogTool,
        GitPushTool,
        GitStashTool,
        GitStatusTool,
    )
    from cantrip.agent.tools.github import (
        GhIssueListTool,
        GhPrCreateTool,
        GhPrListTool,
        GhPrViewTool,
        GhRepoBootstrapTool,
        GhRepoCreateTool,
    )
    from cantrip.agent.tools.glob import GlobTool
    from cantrip.agent.tools.grep import GrepTool
    from cantrip.agent.tools.harness_inventory import HarnessInventoryTool
    from cantrip.agent.tools.icon import CharmIconGenerateTool
    from cantrip.agent.tools.inference import ListInferenceSnapsTool
    from cantrip.agent.tools.juju import (
        BundleDeployTool,
        CharmSyncTool,
        JujuAddModelTool,
        JujuCliTool,
        JujuConfigTool,
        JujuConsumeTool,
        JujuDeployTool,
        JujuDestroyModelTool,
        JujuDispatchTool,
        JujuGetAppConfigTool,
        JujuListOffersTool,
        JujuListSecretsTool,
        JujuOfferTool,
        JujuReadRelationDataTool,
        JujuRefreshTool,
        JujuRelateTool,
        JujuRemoveApplicationTool,
        JujuRunActionTool,
        JujuShowSecretTool,
        JujuShowUnitTool,
        JujuSSHTool,
        JujuStatusTool,
        JujuTrustTool,
        JujuWaitTool,
    )
    from cantrip.agent.tools.launchpad import LaunchpadFetchTool, LaunchpadSearchTool
    from cantrip.agent.tools.loadtest import GenerateLoadTestTool
    from cantrip.agent.tools.mcp_tool import MCPTool
    from cantrip.agent.tools.memory import build_memory_tools
    from cantrip.agent.tools.multi_edit import MultiEditTool
    from cantrip.agent.tools.observability import (
        GrafanaScreenshotTool,
        JujuDebugLogTool,
        JujuStatusRenderTool,
        JujuStreamLogsTool,
        LokiQueryTool,
        TempoQueryTool,
        TempoWaterfallTool,
    )
    from cantrip.agent.tools.oci_registry import (
        RegistryImageInfoTool,
        RegistrySearchTool,
    )
    from cantrip.agent.tools.operational_readiness import OperationalReadinessTool
    from cantrip.agent.tools.oracle import OracleTool
    from cantrip.agent.tools.planning import PlanTasksTool
    from cantrip.agent.tools.pr_review import PrReviewReplyTool, PrReviewTool
    from cantrip.agent.tools.preflight import PreflightTargetsTool
    from cantrip.agent.tools.publishing import (
        CharmcraftReleaseTool,
        CharmcraftUploadTool,
        ExtractDesignDecisionsTool,
        ExtractTroubleshootingTool,
        GenerateDiagramTool,
        GenerateDocsTool,
        GenerateIconTool,
        GenerateReadmeTool,
    )
    from cantrip.agent.tools.report import TestReportTool
    from cantrip.agent.tools.rockcraft import (
        LocalRegistryStatusTool,
        RegistryImageExistsTool,
        RegistryMirrorTool,
        RockContractCheckTool,
        RockcraftInitTool,
        RockcraftPackTool,
        SetupLocalRegistryTool,
        SkopeoRegistryPushTool,
    )
    from cantrip.agent.tools.rodney import RodneyTool
    from cantrip.agent.tools.run_command import RunCommandTool
    from cantrip.agent.tools.scaling import ScalingTestTool
    from cantrip.agent.tools.scenario_coverage import ScenarioCoverageTool
    from cantrip.agent.tools.showboat import ShowboatTool
    from cantrip.agent.tools.skills import LoadSkillTool
    from cantrip.agent.tools.task_management import ManageTasksTool
    from cantrip.agent.tools.testing import GenerateTestsTool, RunCharmTestsTool
    from cantrip.agent.tools.upgrade import UpgradeTestTool
    from cantrip.agent.tools.virtual_files import VirtualFileReadTool, VirtualFileSearchTool
    from cantrip.agent.tools.wait_for import WaitForTool
    from cantrip.agent.tools.web import WebFetchTool
    from cantrip.agent.tools.web_search import WebSearchTool
    from cantrip.agent.tools.workspace import WorkspaceInfoTool

    tools: list[Tool] = [
        # File operations
        ReadFileTool(base_path=base_path),
        WriteFileTool(base_path=base_path),
        ListDirectoryTool(base_path=base_path),
        EditFileTool(base_path=base_path),
        GrepTool(base_path=base_path),
        GlobTool(base_path=base_path),
        MultiEditTool(base_path=base_path),
        # Audit & lint
        CharmAuditTool(),
        CharmlintTool(),
        HarnessInventoryTool(),
        ScenarioCoverageTool(),
        OperationalReadinessTool(),
        # Charm operations
        CharmcraftInitTool(),
        # ``state`` lets the pack tool resolve ``path="."`` against the
        # active charm directory after sprint mode reroots it; without
        # the link the tool resolves against the process cwd and 404s.
        CharmcraftPackTool(state=state),
        QuickPackTool(),
        CharmValidateTool(),
        CharmcraftFetchLibsTool(),
        AnalyseFrameworkTool(),
        InspectEnvKeysTool(),
        # Terraform
        GenerateTerraformTool(),
        ValidateTerraformTool(),
        # Publishing
        CharmcraftUploadTool(),
        CharmcraftReleaseTool(),
        GenerateReadmeTool(),
        GenerateIconTool(),
        GenerateDocsTool(),
        GenerateDiagramTool(),
        ExtractDesignDecisionsTool(),
        ExtractTroubleshootingTool(),
        GenerateLoadTestTool(),
        # Demo
        ShowboatTool(),
        RodneyTool(),
        # Web
        WebFetchTool(),
        WebSearchTool(),
        # Phase 72.1: indexed charm-ecosystem docs.  Reads through
        # the role router so a session without an embed provider
        # surfaces a clean "no embed" error instead of crashing.
        *([DocsSearchTool(role_router)] if role_router is not None else []),
        # Charmhub / Launchpad (Phase 70.1 Librarian)
        CharmhubSearchTool(),
        CharmhubInfoTool(),
        CharmhubFetchTool(),
        LaunchpadSearchTool(),
        LaunchpadFetchTool(),
        # Registry
        RegistrySearchTool(),
        RegistryImageInfoTool(),
        # Rockcraft operations
        RockcraftInitTool(),
        RockContractCheckTool(),
        RockcraftPackTool(),
        SkopeoRegistryPushTool(),
        RegistryImageExistsTool(),
        RegistryMirrorTool(),
        LocalRegistryStatusTool(),
        SetupLocalRegistryTool(),
        # Environment
        ConciergePrepareTool(),
        ConciergeStatusTool(),
        ConciergeRestoreTool(),
        PreflightTargetsTool(),
        # Git operations — bundled behind a single ``git`` tool so the
        # OpenAI-compatible 128-tool cap is never threatened.  Each
        # subcommand keeps its full per-action argument schema (visible
        # in the bundle's description); permissions and audit see the
        # canonical ``git_*`` leaf names because the executor rewrites
        # ``git(subcommand="status")`` into ``git_status(...)`` before
        # any gate runs.
        SubcommandTool(
            "git",
            "Git operations: clone, init, status, diff, log, add, commit, "
            "push, branch, checkout, stash. Same surface as the underlying "
            "git CLI, with structured arguments per subcommand.",
            {
                "clone": GitCloneTool(),
                "init": GitInitTool(),
                "status": GitStatusTool(),
                "diff": GitDiffTool(),
                "log": GitLogTool(),
                "add": GitAddTool(),
                "commit": GitCommitTool(),
                "push": GitPushTool(),
                "branch": GitBranchTool(),
                "checkout": GitCheckoutTool(),
                "stash": GitStashTool(),
            },
        ),
        # GitHub operations — bundled behind a single ``gh`` tool.
        SubcommandTool(
            "gh",
            "GitHub operations via the ``gh`` CLI: create/bootstrap repos, "
            "create/list/view PRs, list issues, fetch and reply to PR review "
            "comments.",
            {
                "repo_create": GhRepoCreateTool(),
                "repo_bootstrap": GhRepoBootstrapTool(),
                "pr_create": GhPrCreateTool(),
                "pr_list": GhPrListTool(),
                "pr_view": GhPrViewTool(),
                "issue_list": GhIssueListTool(),
                "pr_review": PrReviewTool(),
                "pr_review_reply": PrReviewReplyTool(),
            },
        ),
        # Juju operations — bundled behind a single ``juju`` tool.
        # Lifecycle, relations, configuration, secrets, offers, model
        # control — all subcommands of one entry.
        SubcommandTool(
            "juju",
            "Juju operations via Jubilant: status, deploy, refresh, relate, "
            "trust, ssh, run-action, model lifecycle, offers/consume, config, "
            "wait, dispatch, secrets, relation/app introspection, raw CLI.",
            {
                "status": JujuStatusTool(),
                "deploy": JujuDeployTool(),
                "bundle_deploy": BundleDeployTool(),
                "refresh": JujuRefreshTool(),
                "relate": JujuRelateTool(),
                "trust": JujuTrustTool(),
                "ssh": JujuSSHTool(),
                "run_action": JujuRunActionTool(),
                "add_model": JujuAddModelTool(),
                "destroy_model": JujuDestroyModelTool(),
                "offer": JujuOfferTool(),
                "consume": JujuConsumeTool(),
                "config": JujuConfigTool(),
                "wait": JujuWaitTool(),
                "charm_sync": CharmSyncTool(),
                "dispatch": JujuDispatchTool(),
                "list_secrets": JujuListSecretsTool(),
                "show_secret": JujuShowSecretTool(),
                "read_relation_data": JujuReadRelationDataTool(),
                "get_app_config": JujuGetAppConfigTool(),
                "list_offers": JujuListOffersTool(),
                "remove_application": JujuRemoveApplicationTool(),
                "show_unit": JujuShowUnitTool(),
                "cli": JujuCliTool(),
            },
        ),
        # Observability
        JujuDebugLogTool(),
        JujuStreamLogsTool(),
        TempoQueryTool(),
        LokiQueryTool(),
        GrafanaScreenshotTool(),
        TempoWaterfallTool(),
        JujuStatusRenderTool(),
        # Inference snaps
        ListInferenceSnapsTool(),
        # Testing — ``state`` for the same charm-dir resolution
        # reason as ``CharmcraftPackTool`` above.
        RunCharmTestsTool(state=state),
        GenerateTestsTool(),
        HookBenchmarkTool(),
        FuzzTestTool(),
        TestReportTool(),
        ChaosTestTool(),
        ScalingTestTool(),
        UpgradeTestTool(),
        # Acceptance testing
        ActionExerciserTool(),
        RelationSmokeTool(),
        WorkloadEndpointTool(),
        ConfigVariationTool(),
        AcceptanceReportTool(),
        ConfigUnderLoadTool(),
        # Command runner
        RunCommandTool(),
        # Block until a typed predicate flips (Phase 100).
        WaitForTool(),
        # Multi-charm workspace
        WorkspaceInfoTool(),
    ]

    # Tools with dependencies.
    if skills_index is not None:
        # mcp_registry is forwarded so LoadSkillTool can warn when a
        # skill declares MCP server deps that aren't configured
        # (Phase 50.4).  ``None`` is fine — the tool treats every
        # declared server as missing and surfaces that in the banner.
        tools.append(LoadSkillTool(skills_index, mcp_registry=mcp_registry))
    if virtual_store is not None:
        tools.append(VirtualFileReadTool(virtual_store))
        tools.append(VirtualFileSearchTool(virtual_store))
    if provider is not None and state is not None and queue is not None:
        tools.append(
            PlanTasksTool(
                provider=provider,
                state=state,
                queue=queue,
                invalidate_tools_cache=invalidate_tools_cache,
                code_intel_getter=code_intel_getter,
            )
        )
        tools.append(ManageTasksTool(queue=queue))
    if state is not None:
        tools.append(OracleTool(state=state, store_getter=store_getter))
        tools.append(CharmIconGenerateTool(state=state, store_getter=store_getter))
    if memory_manager is not None:
        # Memory operations — bundled behind a single ``memory`` tool.
        memory_leaves = build_memory_tools(memory_manager)
        memory_subcommands: dict[str, Tool] = {}
        for leaf in memory_leaves:
            # Leaves are named ``memory_<verb>``; strip the prefix so
            # the bundle subcommand label is the natural action verb.
            sub = leaf.name.removeprefix("memory_")
            memory_subcommands[sub] = leaf
        tools.append(
            SubcommandTool(
                "memory",
                "Auto-memory store: list, read, search, write, update, "
                "revalidate, sweep, purge_check, forget. See each subcommand's "
                "schema for what it returns.",
                memory_subcommands,
            )
        )
    if mcp_registry is not None:
        for info in mcp_registry.aggregated_tools():
            tools.append(MCPTool(info, mcp_registry))

    # Phase 72b: read-only code intelligence.  Skipped when no getter
    # is supplied — the agent gets the getter wired up at construction
    # time; bare ``build_tools`` callers in tests opt out by omission.
    if code_intel_getter is not None:
        tools.extend(build_codeintel_tools(code_intel_getter))

    return tools


if TYPE_CHECKING:
    from cantrip.agent.context import VirtualFileStore
    from cantrip.agent.memory import MemoryManager
    from cantrip.agent.skills import SkillsIndex
    from cantrip.mcp import MCPRegistry


__all__ = [
    "SubcommandTool",
    "Tool",
    "ToolResult",
    "build_tools",
    "execute_tool",
    "expand_leaves",
    "resolve_subcommand",
    "tool_to_schema",
]
