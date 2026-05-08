"""Tests for the ``/flow`` slash-command dispatcher (Phase 69.4)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from types import SimpleNamespace

from cantrip.agent import flows
from cantrip.agent.commands import slash as slash_commands
from cantrip.agent.commands.flows import handle_flow
from cantrip.agent.commands.slash import SlashResult, dispatch


async def _drain(awaitable: Awaitable[str]) -> str:
    return await awaitable


def _agent(
    *,
    flows_registry: flows.FlowRegistry | None = None,
    process_response: str = "",
) -> SimpleNamespace:
    received: list[str] = []

    async def process_message(prompt: str) -> str:
        received.append(prompt)
        return process_response

    namespace = SimpleNamespace(
        flows=flows_registry or flows.FlowRegistry(),
        process_message=process_message,
    )
    namespace._received = received
    return namespace


def _make_flow(name: str, *, description: str | None = None) -> flows.Flow:
    """Hand-build a minimal :class:`Flow` without parsing Mermaid.

    Tests for dispatcher behaviour don't need a parser round-trip;
    constructing the dataclass directly keeps assertions tight.
    """
    nodes = (
        flows.FlowNode(
            id="start",
            label="Begin",
            kind=flows.NodeKind.ACTION,
            annotation="Do the thing.",
        ),
        flows.FlowNode(
            id="finish",
            label="Done",
            kind=flows.NodeKind.TERMINAL,
            annotation="Stop.",
        ),
    )
    edges = (flows.FlowEdge(src="start", dest="finish"),)
    return flows.Flow(
        name=name,
        description=description or f"Description for {name}.",
        intro_prose="",
        diagram_source="flowchart TD\nstart[Begin]\nfinish(Done)\nstart --> finish",
        entry_node="start",
        nodes=nodes,
        edges=edges,
    )


# ---------------------------------------------------------------------------
# Catalogue / help
# ---------------------------------------------------------------------------


class TestCatalogue:
    def test_no_flows(self) -> None:
        agent = _agent()
        result = handle_flow(agent, "/flow", "")
        assert result.followup is None
        assert "No flows loaded" in result.text
        assert ".cantrip-flows" in result.text

    def test_lists_loaded_flows(self) -> None:
        registry = flows.FlowRegistry(flows=(_make_flow("alpha"), _make_flow("beta")))
        agent = _agent(flows_registry=registry)
        result = handle_flow(agent, "/flow", "")
        assert result.markdown is True
        assert "/flow alpha" in result.text
        assert "/flow beta" in result.text

    def test_help_subcommand_lists_catalogue(self) -> None:
        registry = flows.FlowRegistry(flows=(_make_flow("alpha"),))
        agent = _agent(flows_registry=registry)
        result = handle_flow(agent, "/flow", "help")
        assert "/flow alpha" in result.text

    def test_help_with_name(self) -> None:
        flow = _make_flow("alpha")
        registry = flows.FlowRegistry(flows=(flow,))
        agent = _agent(flows_registry=registry)
        result = handle_flow(agent, "/flow", "alpha --help")
        assert "Entry node:" in result.text
        assert "`start`" in result.text
        assert "`finish`" in result.text  # terminal listed

    def test_help_unknown_flow(self) -> None:
        registry = flows.FlowRegistry(flows=(_make_flow("alpha"),))
        agent = _agent(flows_registry=registry)
        result = handle_flow(agent, "/flow", "help missing")
        assert "No flow named" in result.text


# ---------------------------------------------------------------------------
# Invocation paths
# ---------------------------------------------------------------------------


class TestInvocation:
    def test_unknown_flow(self) -> None:
        agent = _agent()
        result = handle_flow(agent, "/flow", "missing")
        assert "No flow named" in result.text
        assert result.followup is None

    def test_happy_path_renders_and_dispatches(self) -> None:
        registry = flows.FlowRegistry(flows=(_make_flow("alpha"),))
        agent = _agent(flows_registry=registry, process_response="walked")
        result = handle_flow(agent, "/flow", "alpha")
        assert result.followup is not None
        output = asyncio.run(_drain(result.followup))
        assert output == "walked"
        # The agent received the rendered flow prompt — fence + walking
        # instructions are part of the contract.
        assert len(agent._received) == 1
        prompt = agent._received[0]
        assert "```mermaid" in prompt
        assert "BRANCH:" in prompt
        assert "Do the thing." in prompt

    def test_colon_form_routes_to_named_flow(self) -> None:
        # ``/flow:alpha`` is the bundled-syntax shape; dispatcher
        # passes the verb through verbatim and the handler splits it.
        registry = flows.FlowRegistry(flows=(_make_flow("alpha"),))
        agent = _agent(flows_registry=registry, process_response="walked")
        result = handle_flow(agent, "/flow:alpha", "")
        output = asyncio.run(_drain(result.followup))
        assert output == "walked"

    def test_colon_form_with_unknown_name_refuses(self) -> None:
        registry = flows.FlowRegistry(flows=(_make_flow("alpha"),))
        agent = _agent(flows_registry=registry)
        result = handle_flow(agent, "/flow:ghost", "")
        assert "No flow named" in result.text
        assert result.followup is None

    def test_extra_args_rejected_with_recipe_pointer(self) -> None:
        # Flows take no parameters — the refusal points the user at
        # /recipe instead so the next command is obvious.
        registry = flows.FlowRegistry(flows=(_make_flow("alpha"),))
        agent = _agent(flows_registry=registry)
        result = handle_flow(agent, "/flow", "alpha key=value")
        assert "does not accept arguments" in result.text
        assert "/recipe" in result.text


# ---------------------------------------------------------------------------
# End-to-end dispatch through ``slash.dispatch``
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_dispatch_routes_flow(self) -> None:
        registry = flows.FlowRegistry(flows=(_make_flow("alpha"),))
        agent = _agent(flows_registry=registry)
        result = dispatch(agent, "/flow")
        assert isinstance(result, SlashResult)
        assert "/flow alpha" in result.text

    def test_dispatch_routes_colon_form(self) -> None:
        # Verifies the `verb.startswith(_FLOW_VERB + ":")` branch in
        # `_dispatch_inner` — without it, the colon form falls through
        # to the unknown-verb path.
        registry = flows.FlowRegistry(flows=(_make_flow("alpha"),))
        agent = _agent(flows_registry=registry, process_response="walked")
        result = dispatch(agent, "/flow:alpha")
        assert isinstance(result, SlashResult)
        assert result.followup is not None
        output = asyncio.run(_drain(result.followup))
        assert output == "walked"

    def test_flow_in_catalogue(self) -> None:
        verbs = {cmd.verb for cmd in slash_commands.COMMAND_CATALOGUE}
        assert "/flow" in verbs

    def test_flow_in_help_text(self) -> None:
        text = slash_commands.help_text(None)
        assert "/flow" in text
