"""Tool for loading agent skills on demand."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cantrip.agent.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from cantrip.agent.skills import SkillsIndex
    from cantrip.mcp import MCPRegistry


_MISSING_MCP_BANNER = (
    "> ⚠️  This skill declares MCP server dependencies that are NOT "
    "configured in the current session: {missing}.\n"
    "> The content below may reference tools from those servers that "
    "won't be available.  Configure the servers via `~/.config/cantrip/"
    "mcp.yaml` or `cantrip.mcp.yaml`, or adapt the workflow to skip "
    "those steps.\n\n"
)


class LoadSkillTool(Tool):
    """Load a charm development skill by name.

    When the skill declares MCP server dependencies (via ``mcp_servers:``
    in its frontmatter — Phase 50.4), the returned content is prefixed
    with a warning banner naming the missing servers so the agent can
    either configure them or adapt the workflow.  The skill body is
    always returned — gating at load time would silently hide skills
    the agent might still extract value from; a visible warning is a
    better failure mode.
    """

    def __init__(
        self,
        skills_index: SkillsIndex,
        mcp_registry: MCPRegistry | None = None,
    ) -> None:
        self._index = skills_index
        self._mcp_registry = mcp_registry

    @property
    def name(self) -> str:
        return "load_skill"

    @property
    def description(self) -> str:
        return (
            "Load a charm development skill by name. Returns the full skill "
            "content with step-by-step instructions. Use this when you need "
            "detailed guidance on a specific topic listed in the available skills."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the skill to load.",
                },
            },
            "required": ["skill_name"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool."""
        skill_name: str = kwargs.get("skill_name", "")
        try:
            content = self._index.load_skill(skill_name)
        except KeyError:
            available = ", ".join(s.name for s in self._index.list_skills())
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown skill: {skill_name!r}. Available skills: {available}",
            )

        banner = self._mcp_warning_banner(skill_name)
        output = f"{banner}{content}" if banner else content
        return ToolResult(success=True, output=output)

    def _mcp_warning_banner(self, skill_name: str) -> str:
        """Return a warning banner listing any unconfigured MCP servers.

        Returns the empty string when the skill has no MCP deps or when
        every declared server is configured — so happy-path loads don't
        pay any formatting cost.
        """
        metadata = self._index.metadata_for(skill_name)
        if metadata is None or not metadata.mcp_servers:
            return ""
        if self._mcp_registry is None:
            # No MCP registry wired in at all — treat every declared
            # server as missing so the user sees what's needed.
            missing = list(metadata.mcp_servers)
        else:
            configured = {cfg.name for cfg in self._mcp_registry.configured}
            missing = [name for name in metadata.mcp_servers if name not in configured]
        if not missing:
            return ""
        return _MISSING_MCP_BANNER.format(missing=", ".join(missing))
