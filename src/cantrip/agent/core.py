"""Core agent logic."""

from dataclasses import dataclass, field
from pathlib import Path

from cantrip.llm.base import LLMProvider, Message, Role, Tool


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
    decisions: list[dict] = field(default_factory=list)


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
        self._system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        """Build the system prompt."""
        # TODO: Load from file and incorporate charming-with-claude guidance
        return """You are Cantrip, an AI agent specialised in building Juju charms.

Your goal is to help users create production-quality charms through natural
conversation. You handle the implementation; the user provides operational
knowledge about how their application should behave.

Key principles:
1. Get to active/running status fast (2 minutes for simple charms)
2. Iterate through conversation - don't try to be perfect first time
3. Use observability (traces, logs) to debug issues
4. Default to fast dev cycle (juju ssh), validate with full pack/refresh
5. Integrate with the ecosystem - observability, databases, ingress

Always use UK English."""

    def _build_tools(self) -> list[Tool]:
        """Build available tools."""
        # TODO: Implement actual tools
        return []

    async def process_message(self, user_message: str) -> str:
        """Process a user message and return the response."""
        # Add user message to history
        self.state.messages.append(Message(role=Role.USER, content=user_message))

        # Build messages for LLM
        messages = [
            Message(role=Role.SYSTEM, content=self._system_prompt),
            *self.state.messages,
        ]

        # Get response
        response = await self.provider.complete(
            messages=messages,
            tools=self._tools if self._tools else None,
            temperature=0.7,
        )

        # Handle tool calls if present
        if response.tool_calls:
            # TODO: Execute tools and continue conversation
            pass

        # Add assistant message to history
        self.state.messages.append(Message(role=Role.ASSISTANT, content=response.content))

        return response.content

    def save_state(self, path: Path) -> None:
        """Save agent state to disk."""
        # TODO: Implement persistence
        pass

    def load_state(self, path: Path) -> None:
        """Load agent state from disk."""
        # TODO: Implement persistence
        pass
