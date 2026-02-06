"""Tool for loading agent skills on demand."""

from typing import Any

from cantrip.agent.skills import SkillsIndex
from cantrip.agent.tools.base import Tool, ToolResult


class LoadSkillTool(Tool):
    """Load a charm development skill by name."""

    def __init__(self, skills_index: SkillsIndex) -> None:
        self._index = skills_index

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

        return ToolResult(success=True, output=content)
