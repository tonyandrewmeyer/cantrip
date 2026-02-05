"""Core agent logic."""

import json
from collections.abc import AsyncIterator
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
from cantrip.llm.base import ToolResult as LLMToolResult

# Maximum tool-call rounds before we force the model to respond with text.
MAX_TOOL_ROUNDS = 20


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
        except TypeError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Invalid arguments for {name}: {e}",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Tool execution failed: {e}",
            )

    def _build_llm_messages(self) -> list[Message]:
        """Build the full message list for the LLM including system prompt."""
        return [
            Message(role=Role.SYSTEM, content=self._build_system_prompt()),
            *self.state.messages,
        ]

    async def process_message(self, user_message: str) -> str:
        """Process a user message and return the response.

        This handles the full conversation loop including tool calls.
        The loop continues until the model responds without tool calls
        or the maximum number of rounds is reached.
        """
        self.state.messages.append(Message(role=Role.USER, content=user_message))

        messages = self._build_llm_messages()
        llm_tools = self._tools_for_llm() if self._tools else None

        response = await self.provider.complete(
            messages=messages,
            tools=llm_tools,
            temperature=0.7,
        )

        rounds = 0
        while response.tool_calls and rounds < MAX_TOOL_ROUNDS:
            rounds += 1

            # Record the assistant message with its tool calls.
            assistant_msg = Message(
                role=Role.ASSISTANT,
                content=response.content,
                tool_calls=response.tool_calls,
            )
            self.state.messages.append(assistant_msg)

            # Execute each tool and build TOOL result messages.
            tool_results = []
            for tc in response.tool_calls:
                result = await self._execute_tool(tc.name, tc.arguments)
                content = result.output if result.success else (result.error or "Unknown error")
                tool_results.append(
                    LLMToolResult(
                        tool_call_id=tc.id,
                        content=content,
                        is_error=not result.success,
                    )
                )

            tool_msg = Message(
                role=Role.TOOL,
                content="",
                tool_results=tool_results,
            )
            self.state.messages.append(tool_msg)

            # Call the LLM again with the updated history.
            messages = self._build_llm_messages()
            response = await self.provider.complete(
                messages=messages,
                tools=llm_tools,
                temperature=0.7,
            )

        # Store the final assistant response.
        self.state.messages.append(Message(role=Role.ASSISTANT, content=response.content))
        return response.content

    async def process_message_streaming(self, user_message: str) -> AsyncIterator[str]:
        """Process a message with streaming response.

        Yields text chunks as they arrive. If the model requests tool calls,
        those are executed and the model is called again (non-streaming for
        intermediate rounds, streaming for the final text response).
        """
        self.state.messages.append(Message(role=Role.USER, content=user_message))

        llm_tools = self._tools_for_llm() if self._tools else None

        # Use non-streaming complete for potential tool call rounds.
        messages = self._build_llm_messages()
        response = await self.provider.complete(
            messages=messages,
            tools=llm_tools,
            temperature=0.7,
        )

        rounds = 0
        while response.tool_calls and rounds < MAX_TOOL_ROUNDS:
            rounds += 1

            assistant_msg = Message(
                role=Role.ASSISTANT,
                content=response.content,
                tool_calls=response.tool_calls,
            )
            self.state.messages.append(assistant_msg)

            tool_results = []
            for tc in response.tool_calls:
                result = await self._execute_tool(tc.name, tc.arguments)
                content = result.output if result.success else (result.error or "Unknown error")
                tool_results.append(
                    LLMToolResult(
                        tool_call_id=tc.id,
                        content=content,
                        is_error=not result.success,
                    )
                )

            tool_msg = Message(
                role=Role.TOOL,
                content="",
                tool_results=tool_results,
            )
            self.state.messages.append(tool_msg)

            messages = self._build_llm_messages()
            response = await self.provider.complete(
                messages=messages,
                tools=llm_tools,
                temperature=0.7,
            )

        # Now stream the final text response.
        messages = self._build_llm_messages()
        # Remove the last assistant response from messages since we'll re-stream it.
        # Actually, `response` already has the content but we want to stream it.
        # Since we already have the content from `complete()`, just yield it.
        full_response = response.content
        self.state.messages.append(Message(role=Role.ASSISTANT, content=full_response))
        yield full_response

    def save_state(self, path: Path) -> None:
        """Save agent state to disk."""
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
            "message_count": len(self.state.messages),
        }

        (cantrip_dir / "session.json").write_text(json.dumps(state_data, indent=2))

    def load_state(self, path: Path) -> bool:
        """Load agent state from disk.

        Returns True if state was loaded, False if no state exists.
        """
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

            self.state.decisions = [
                Decision(
                    type=d["type"],
                    choice=d["choice"],
                    reason=d.get("reason"),
                )
                for d in state_data.get("decisions", [])
            ]

            return True
        except (json.JSONDecodeError, KeyError):
            return False
