"""Tests for MCP elicitation routing (Phase 45.4c)."""

from __future__ import annotations

import asyncio

import mcp.types as mcp_types
import pytest

from cantrip.mcp.elicitation import (
    DEFAULT_ELICITATION_TIMEOUT,
    ElicitationManager,
    ElicitationRequest,
    ElicitationResponse,
)


def _form_params(message: str = "Pick a value") -> mcp_types.ElicitRequestFormParams:
    return mcp_types.ElicitRequestFormParams(
        message=message,
        requested_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
        },
    )


# ── ElicitationManager.handle ───────────────────────────────────────────


class TestElicitationManager:
    @pytest.mark.asyncio
    async def test_round_trip_accept(self) -> None:
        seen: list[ElicitationRequest] = []
        manager = ElicitationManager("stub", on_request=seen.append)
        params = _form_params()

        async def _user_responds() -> None:
            # Wait until the request lands.
            for _ in range(200):
                if manager.pending:
                    break
                await asyncio.sleep(0.005)
            assert seen, "callback never fired"
            request_id = seen[0].request_id
            assert manager.complete(request_id, "accept", {"name": "alice"})

        responder = asyncio.create_task(_user_responds())
        result = await manager.handle(None, params)
        await responder

        assert isinstance(result, mcp_types.ElicitResult)
        assert result.action == "accept"
        assert result.content == {"name": "alice"}
        assert manager.pending == []

    @pytest.mark.asyncio
    async def test_round_trip_decline(self) -> None:
        seen: list[ElicitationRequest] = []
        manager = ElicitationManager("stub", on_request=seen.append)

        async def _user_responds() -> None:
            for _ in range(200):
                if manager.pending:
                    break
                await asyncio.sleep(0.005)
            manager.complete(seen[0].request_id, "decline")

        responder = asyncio.create_task(_user_responds())
        result = await manager.handle(None, _form_params())
        await responder
        assert isinstance(result, mcp_types.ElicitResult)
        assert result.action == "decline"
        assert result.content is None

    @pytest.mark.asyncio
    async def test_request_payload_shape(self) -> None:
        seen: list[ElicitationRequest] = []
        manager = ElicitationManager("charmhub", on_request=seen.append)

        async def _responder() -> None:
            for _ in range(200):
                if manager.pending:
                    break
                await asyncio.sleep(0.005)
            manager.complete(seen[0].request_id, "decline")

        asyncio.create_task(_responder())
        await manager.handle(None, _form_params(message="What namespace?"))
        assert len(seen) == 1
        request = seen[0]
        assert request.server_name == "charmhub"
        assert request.message == "What namespace?"
        assert request.mode == "form"
        assert request.requested_schema is not None
        assert "name" in request.requested_schema["properties"]

    @pytest.mark.asyncio
    async def test_timeout_auto_declines(self) -> None:
        manager = ElicitationManager("stub", timeout=0.05)
        result = await manager.handle(None, _form_params())
        assert isinstance(result, mcp_types.ElicitResult)
        assert result.action == "decline"
        assert manager.pending == []

    @pytest.mark.asyncio
    async def test_complete_unknown_id_returns_false(self) -> None:
        manager = ElicitationManager("stub")
        assert not manager.complete("does-not-exist", "accept")

    @pytest.mark.asyncio
    async def test_complete_rejects_invalid_action(self) -> None:
        manager = ElicitationManager("stub")
        with pytest.raises(ValueError, match="unknown elicitation action"):
            manager.complete("any", "approve")

    @pytest.mark.asyncio
    async def test_cancel_all_resolves_pending(self) -> None:
        seen: list[ElicitationRequest] = []
        manager = ElicitationManager("stub", on_request=seen.append, timeout=10)

        async def _later_cancel() -> None:
            for _ in range(200):
                if manager.pending:
                    break
                await asyncio.sleep(0.005)
            manager.cancel_all()

        asyncio.create_task(_later_cancel())
        result = await manager.handle(None, _form_params())
        assert isinstance(result, mcp_types.ElicitResult)
        assert result.action == "decline"
        assert manager.pending == []

    @pytest.mark.asyncio
    async def test_callback_failure_isolated(self) -> None:
        """A broken UI callback never breaks the SDK round-trip."""

        def boom(_request: ElicitationRequest) -> None:
            raise RuntimeError("ui exploded")

        manager = ElicitationManager("stub", on_request=boom, timeout=0.05)
        # Even with a busted callback the manager still parks + auto-declines.
        result = await manager.handle(None, _form_params())
        assert isinstance(result, mcp_types.ElicitResult)
        assert result.action == "decline"

    def test_set_callback_after_construction(self) -> None:
        manager = ElicitationManager("stub")
        seen: list[ElicitationRequest] = []
        manager.set_callback(seen.append)
        # Cannot easily exercise without await, but assignment works.
        assert manager._on_request is not None

    def test_default_timeout_constant(self) -> None:
        assert DEFAULT_ELICITATION_TIMEOUT >= 60


# ── Registry-level fanout ─────────────────────────────────────────────


class TestRegistryElicitation:
    """``MCPRegistry`` forwards completion to the right per-server manager."""

    @pytest.mark.asyncio
    async def test_completion_routes_to_correct_server(self) -> None:
        from cantrip.mcp import MCPRegistry, ServerConfig
        from cantrip.mcp.types import TransportKind

        # Two never-started clients — we drive their managers directly.
        reg = MCPRegistry(
            [
                ServerConfig(
                    name="a",
                    transport=TransportKind.STDIO,
                    command="x",
                ),
                ServerConfig(
                    name="b",
                    transport=TransportKind.STDIO,
                    command="x",
                ),
            ]
        )
        seen: list[ElicitationRequest] = []
        reg.set_elicitation_callback(seen.append)

        client_a = reg.get_client("a")
        client_b = reg.get_client("b")
        assert client_a is not None and client_b is not None

        async def _drive_a() -> ElicitationResponse:
            response_via_handle = await client_a.elicitation.handle(None, _form_params())
            return ElicitationResponse(
                action=response_via_handle.action,  # type: ignore[union-attr]
                content=response_via_handle.content,  # type: ignore[union-attr]
            )

        async def _drive_b() -> ElicitationResponse:
            response_via_handle = await client_b.elicitation.handle(None, _form_params())
            return ElicitationResponse(
                action=response_via_handle.action,  # type: ignore[union-attr]
                content=response_via_handle.content,  # type: ignore[union-attr]
            )

        task_a = asyncio.create_task(_drive_a())
        task_b = asyncio.create_task(_drive_b())

        # Wait for both to land.
        for _ in range(200):
            if len(seen) == 2:
                break
            await asyncio.sleep(0.005)
        assert len(seen) == 2

        # The registry routes by request_id, no matter which server.
        # Resolve both via the registry-level method.
        for request in seen:
            assert reg.complete_elicitation(request.request_id, "decline")

        results = await asyncio.gather(task_a, task_b)
        assert all(r.action == "decline" for r in results)

    def test_completion_unknown_id_returns_false(self) -> None:
        from cantrip.mcp import MCPRegistry

        reg = MCPRegistry([])
        assert not reg.complete_elicitation("nope", "accept")


# ── Agent integration ─────────────────────────────────────────────────


class TestAgentElicitationWiring:
    """``CantripAgent`` publishes elicitation requests and routes responses."""

    @pytest.mark.asyncio
    async def test_publishes_to_event_bus(self, tmp_path) -> None:
        from cantrip.agent.core import CantripAgent
        from cantrip.ui.events import EventType
        from tests.conftest import FakeProvider

        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        # Force the lazy registry to materialise (empty).
        _ = agent.mcp_registry

        captured: list[dict] = []

        def _capture(event) -> None:
            captured.append(dict(event.payload))

        agent.event_bus.subscribe(EventType.MCP_ELICITATION_REQUEST, _capture)

        # Manually trigger via the private hook to verify the bridge.
        request = ElicitationRequest(
            request_id="abc123",
            server_name="charmhub",
            mode="form",
            message="Pick something",
            requested_schema={"type": "object"},
        )
        agent._on_mcp_elicitation(request)

        assert len(captured) == 1
        payload = captured[0]
        assert payload["request_id"] == "abc123"
        assert payload["server_name"] == "charmhub"
        assert payload["mode"] == "form"

    def test_complete_returns_false_when_no_registry(self, tmp_path) -> None:
        from cantrip.agent.core import CantripAgent
        from tests.conftest import FakeProvider

        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        # No registry constructed yet.
        assert not agent.complete_mcp_elicitation("nope", "decline")
