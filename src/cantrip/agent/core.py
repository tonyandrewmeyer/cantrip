"""Core agent logic."""

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from cantrip.agent.prompts import build_system_prompt, claude_md
from cantrip.agent.skills import SkillsIndex
from cantrip.agent.state import AgentState, Decision
from cantrip.agent.store import SessionStore
from cantrip.agent.tools import (
    AnalyseFrameworkTool,
    CharmcraftFetchLibsTool,
    CharmcraftInitTool,
    CharmcraftPackTool,
    ConciergePrepareTool,
    ConciergeStatusTool,
    EditFileTool,
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
    ListDirectoryTool,
    LoadSkillTool,
    ReadFileTool,
    RockcraftInitTool,
    RockcraftPackTool,
    SkopeoRegistryPushTool,
    Tool,
    ToolResult,
    WebFetchTool,
    WriteFileTool,
)
from cantrip.llm.base import LLMProvider, Message, Response, Role
from cantrip.llm.base import Tool as LLMTool
from cantrip.llm.base import ToolResult as LLMToolResult

log = logging.getLogger(__name__)

# Re-export for backwards compatibility.
__all__ = ["AgentState", "CantripAgent", "Decision"]

# Maximum tool-call rounds before we force the model to respond with text.
MAX_TOOL_ROUNDS = 20


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
        self._skills_index = SkillsIndex()
        self._skills_index.discover()
        self._tools = self._build_tools()
        self._tool_map = {tool.name: tool for tool in self._tools}
        self._store: SessionStore | None = None
        if charm_path:
            self._init_store(charm_path)

    def _init_store(self, charm_path: Path) -> None:
        """Initialise the session store, migrating from JSON if necessary."""
        db_path = charm_path / ".cantrip"

        # Migrate from the old directory-based layout.
        old_dir = charm_path / ".cantrip"
        if old_dir.is_dir():
            json_file = old_dir / "session.json"
            backup = charm_path / ".cantrip.bak"
            if json_file.exists():
                temp_db = charm_path / ".cantrip.tmp"
                SessionStore.migrate_from_json(json_file, temp_db)
                old_dir.rename(backup)
                temp_db.rename(db_path)
                log.info("Migrated .cantrip/ to SQLite (old directory saved as .cantrip.bak)")
            else:
                old_dir.rename(backup)

        self._store = SessionStore(db_path)
        self._store.open()
        self._ensure_claude_md(charm_path)

    def _ensure_claude_md(self, charm_path: Path) -> None:
        """Write a CLAUDE.md into the charm directory if one does not exist."""
        target = charm_path / "CLAUDE.md"
        if target.exists():
            return
        charm_name = self.state.charm_name or charm_path.name
        content = claude_md.render_claude_md(charm_name, charm_type=self.state.charm_type)
        target.write_text(content)
        log.info("Wrote CLAUDE.md to %s", charm_path)

    def _record_usage(self, response: Response) -> None:
        """Record token usage from a provider response if a store is active."""
        if self._store and response.usage:
            self._store.record_usage(
                provider=self.provider.name,
                model=self.provider.model_name,
                prompt_tokens=response.usage.get("prompt_tokens", 0),
                completion_tokens=response.usage.get("completion_tokens", 0),
            )

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
            # Web
            WebFetchTool(),
            # Skills
            LoadSkillTool(self._skills_index),
            # Rockcraft operations
            RockcraftInitTool(),
            RockcraftPackTool(),
            SkopeoRegistryPushTool(),
            # Environment
            ConciergePrepareTool(),
            ConciergeStatusTool(),
            # Juju operations
            JujuStatusTool(),
            JujuDeployTool(),
            JujuRefreshTool(),
            JujuRelateTool(),
            JujuSSHTool(),
            JujuRunActionTool(),
            JujuAddModelTool(),
            JujuDestroyModelTool(),
            JujuOfferTool(),
            JujuConsumeTool(),
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
            skills_index=self._skills_index.format_for_prompt(),
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
        self._record_usage(response)

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
            self._record_usage(response)

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
        self._record_usage(response)

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
            self._record_usage(response)

        # Now stream the final text response.
        messages = self._build_llm_messages()
        # Remove the last assistant response from messages since we'll re-stream it.
        # Actually, `response` already has the content but we want to stream it.
        # Since we already have the content from `complete()`, just yield it.
        full_response = response.content
        self.state.messages.append(Message(role=Role.ASSISTANT, content=full_response))
        yield full_response

    def save_state(self) -> None:
        """Save agent state to the session store."""
        if self._store:
            self._store.save_session(self.state)

    def load_state(self) -> bool:
        """Load agent state from the session store.

        Returns True if state was loaded, False if no state exists.
        """
        if not self._store:
            return False

        loaded = self._store.load_session()
        if loaded is None:
            return False

        self.state.charm_name = loaded.charm_name
        self.state.charm_path = loaded.charm_path
        self.state.charm_type = loaded.charm_type
        self.state.framework = loaded.framework
        self.state.dev_model = loaded.dev_model
        self.state.cos_model = loaded.cos_model
        self.state.decisions = loaded.decisions
        return True
