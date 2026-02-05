"""Core agent logic."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from cantrip.agent.prompts import build_system_prompt
from cantrip.agent.tools import (
    AnalyseFrameworkTool,
    CharmcraftFetchLibsTool,
    CharmcraftInitTool,
    CharmcraftPackTool,
    EditFileTool,
    JujuDeployTool,
    JujuRefreshTool,
    JujuRelateTool,
    JujuRunActionTool,
    JujuSSHTool,
    JujuStatusTool,
    ListDirectoryTool,
    ReadFileTool,
    Tool,
    ToolResult,
    WriteFileTool,
)
from cantrip.llm.base import LLMProvider, Message, Role
from cantrip.llm.base import Tool as LLMTool


@dataclass
class Decision:
    """A decision made during the session."""

    type: str
    choice: str
    reason: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.type,
            "choice": self.choice,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class AgentState:
    """Current agent state."""

    charm_name: str | None = None
    charm_path: Path | None = None
    charm_type: str | None = None  # "machine" or "k8s"
    framework: str | None = None

    dev_model: str | None = None
    cos_model: str | None = None

    messages: list[Message] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)

    def add_decision(self, type: str, choice: str, reason: str | None = None) -> None:
        """Record a decision."""
        self.decisions.append(Decision(type=type, choice=choice, reason=reason))


class CantripAgent:
    """Main Cantrip agent."""

    def __init__(
        self,
        provider: LLMProvider,
        charm_path: Path | None = None,
    ):
        """Initialise the agent."""
        self.provider = provider
        self.state = AgentState(charm_path=charm_path)
        self._tools = self._build_tools()
        self._tool_map = {tool.name: tool for tool in self._tools}

    def _build_tools(self) -> list[Tool]:
        """Build available tools."""
        base_path = self.state.charm_path

        return [
            # File operations
            ReadFileTool(base_path=base_path),
            WriteFileTool(base_path=base_path),
            ListDirectoryTool(base_path=base_path),
            EditFileTool(base_path=base_path),
            # Charm operations
            CharmcraftInitTool(),
            CharmcraftPackTool(),
            CharmcraftFetchLibsTool(),
            AnalyseFrameworkTool(),
            # Juju operations
            JujuStatusTool(),
            JujuDeployTool(),
            JujuRefreshTool(),
            JujuRelateTool(),
            JujuSSHTool(),
            JujuRunActionTool(),
        ]

    def _build_system_prompt(self) -> str:
        """Build the current system prompt."""
        return build_system_prompt(
            charm_name=self.state.charm_name,
            charm_path=str(self.state.charm_path) if self.state.charm_path else None,
            charm_type=self.state.charm_type,
            framework=self.state.framework,
            dev_model=self.state.dev_model,
            cos_model=self.state.cos_model,
            recent_decisions=[d.to_dict() for d in self.state.decisions],
        )

    def _tools_for_llm(self) -> list[LLMTool]:
        """Convert tools to LLM format."""
        return [
            LLMTool(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters,
            )
            for tool in self._tools
        ]

    async def _execute_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool by name."""
        tool = self._tool_map.get(name)
        if not tool:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown tool: {name}",
            )

        try:
            return await tool.execute(**arguments)
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Tool execution failed: {e}",
            )

    async def process_message(self, user_message: str) -> str:
        """Process a user message and return the response.

        This handles the full conversation loop including tool calls.
        """
        # Add user message to history
        self.state.messages.append(Message(role=Role.USER, content=user_message))

        # Build messages for LLM
        messages = [
            Message(role=Role.SYSTEM, content=self._build_system_prompt()),
            *self.state.messages,
        ]

        # Get response (may include tool calls)
        response = await self.provider.complete(
            messages=messages,
            tools=self._tools_for_llm() if self._tools else None,
            temperature=0.7,
        )

        # Handle tool calls in a loop
        while response.tool_calls:
            # Execute each tool call
            tool_results = []
            for tool_call in response.tool_calls:
                result = await self._execute_tool(tool_call.name, tool_call.arguments)
                tool_results.append(
                    f"Tool: {tool_call.name}\n"
                    f"Result: {'Success' if result.success else 'Failed'}\n"
                    f"Output: {result.output or result.error}"
                )

            # Add tool results to context and get next response
            tool_message = Message(
                role=Role.ASSISTANT,
                content="\n\n".join(tool_results),
            )
            messages.append(tool_message)

            response = await self.provider.complete(
                messages=messages,
                tools=self._tools_for_llm() if self._tools else None,
                temperature=0.7,
            )

        # Add final assistant message to history
        self.state.messages.append(Message(role=Role.ASSISTANT, content=response.content))

        return response.content

    async def process_message_streaming(self, user_message: str):
        """Process a message with streaming response.

        Yields chunks as they arrive.
        """
        # Add user message to history
        self.state.messages.append(Message(role=Role.USER, content=user_message))

        # Build messages for LLM
        messages = [
            Message(role=Role.SYSTEM, content=self._build_system_prompt()),
            *self.state.messages,
        ]

        # Stream response
        full_response = ""
        async for chunk in self.provider.stream(
            messages=messages,
            tools=self._tools_for_llm() if self._tools else None,
            temperature=0.7,
        ):
            if chunk.content:
                full_response += chunk.content
                yield chunk.content

        # Add to history
        self.state.messages.append(Message(role=Role.ASSISTANT, content=full_response))

    def save_state(self, path: Path) -> None:
        """Save agent state to disk."""
        import json

        cantrip_dir = path / ".cantrip"
        cantrip_dir.mkdir(exist_ok=True)

        state_data = {
            "charm_name": self.state.charm_name,
            "charm_path": str(self.state.charm_path) if self.state.charm_path else None,
            "charm_type": self.state.charm_type,
            "framework": self.state.framework,
            "dev_model": self.state.dev_model,
            "cos_model": self.state.cos_model,
            "decisions": [d.to_dict() for d in self.state.decisions],
            # Don't save full message history - too large
            # Instead, save a summary
            "message_count": len(self.state.messages),
        }

        (cantrip_dir / "session.json").write_text(json.dumps(state_data, indent=2))

    def load_state(self, path: Path) -> bool:
        """Load agent state from disk.

        Returns True if state was loaded, False if no state exists.
        """
        import json

        cantrip_dir = path / ".cantrip"
        session_file = cantrip_dir / "session.json"

        if not session_file.exists():
            return False

        try:
            state_data = json.loads(session_file.read_text())

            self.state.charm_name = state_data.get("charm_name")
            if state_data.get("charm_path"):
                self.state.charm_path = Path(state_data["charm_path"])
            self.state.charm_type = state_data.get("charm_type")
            self.state.framework = state_data.get("framework")
            self.state.dev_model = state_data.get("dev_model")
            self.state.cos_model = state_data.get("cos_model")

            # Restore decisions
            self.state.decisions = [
                Decision(
                    type=d["type"],
                    choice=d["choice"],
                    reason=d.get("reason"),
                )
                for d in state_data.get("decisions", [])
            ]

            return True
        except Exception:
            return False
