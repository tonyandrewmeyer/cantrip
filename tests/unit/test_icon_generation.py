"""Tests for the Phase 70.5 Painter (charm-icon generation).

Covers:
- ``cantrip.llm.image`` provider abstraction (factory, error path).
- ``CharmIconGenerateTool`` happy path with a stubbed image provider.
- Refusal to overwrite a non-default existing ``icon.svg``.
- Cost-cap enforcement (``state.icon_max_session_cost_usd``).
- Session cost accumulator and per-call accounting.
- ``/icon`` slash command dispatch (usage, missing charm, followup).

No real image-generation calls — every provider interaction is
stubbed, including ``google-genai`` itself so the Imagen import isn't
exercised.
"""

from __future__ import annotations

import base64
import pathlib
from unittest.mock import MagicMock

import pytest

from cantrip.agent import slash_commands
from cantrip.agent.state import AgentState
from cantrip.agent.tools.icon import (
    _GENERATED_MARKER,
    _PLACEHOLDER_FINGERPRINT,
    CharmIconGenerateTool,
    _build_prompt,
    _embed_png_in_svg,
    _existing_icon_is_expendable,
)
from cantrip.llm.image import (
    DEFAULT_IMAGE_MODEL,
    ImageGenerationError,
    ImageProvider,
    ImageResult,
    create_image_provider,
)

# ---------------------------------------------------------------------------
# Test scaffolding
# ---------------------------------------------------------------------------


class _StubImageProvider(ImageProvider):
    """Returns a fixed ImageResult so tests don't need real Imagen calls."""

    def __init__(
        self,
        *,
        data: bytes = b"\x89PNG\r\n\x1a\nfake-png-data",
        cost: float = 0.04,
        model: str = DEFAULT_IMAGE_MODEL,
        raise_on_call: Exception | None = None,
    ) -> None:
        super().__init__(model=model)
        self._data = data
        self._cost = cost
        self._raise = raise_on_call
        self.called_with: list[tuple[str, tuple[int, int]]] = []

    @property
    def name(self) -> str:
        return "stub"

    async def generate(
        self,
        prompt: str,
        *,
        size: tuple[int, int] = (1024, 1024),
    ) -> ImageResult:
        self.called_with.append((prompt, size))
        if self._raise is not None:
            raise self._raise
        return ImageResult(
            data=self._data,
            mime="image/png",
            model=self.model,
            cost_usd=self._cost,
        )


def _make_tool(
    *,
    state: AgentState | None = None,
    provider: ImageProvider | None = None,
    raise_factory: Exception | None = None,
) -> tuple[CharmIconGenerateTool, _StubImageProvider | None, AgentState]:
    state = state or AgentState()
    stub = provider if provider is not None else _StubImageProvider()

    def _factory(_name: str | None, _model: str | None) -> ImageProvider:
        if raise_factory is not None:
            raise raise_factory
        return stub

    tool = CharmIconGenerateTool(state=state, provider_factory=_factory)
    return tool, (stub if isinstance(stub, _StubImageProvider) else None), state


@pytest.fixture
def charm_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """A minimal charm directory with a charmcraft.yaml so the tool can read the name."""
    (tmp_path / "charmcraft.yaml").write_text("name: myapp\ntype: charm\n")
    return tmp_path


# ---------------------------------------------------------------------------
# Image provider abstraction
# ---------------------------------------------------------------------------


class TestImageProviderFactory:
    """The factory must construct Gemini by default and reject unknown names."""

    def test_default_returns_gemini(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        provider = create_image_provider()
        assert provider.name == "gemini"
        assert provider.model == DEFAULT_IMAGE_MODEL

    def test_unknown_provider_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        with pytest.raises(ValueError, match="Unknown image provider"):
            create_image_provider("nopesy")

    def test_missing_api_key_clean_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            create_image_provider("gemini")


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    """Prompt composition must always include the Charmhub style guidance."""

    def test_prompt_contains_style_block(self) -> None:
        prompt = _build_prompt("myapp", "PostgreSQL database", None)
        assert "square" in prompt
        assert "myapp" in prompt
        assert "PostgreSQL database" in prompt

    def test_palette_hint_optional(self) -> None:
        without = _build_prompt("myapp", "Postgres", None)
        with_hint = _build_prompt("myapp", "Postgres", "cool blues")
        assert "cool blues" in with_hint
        assert "cool blues" not in without

    def test_empty_description_omitted(self) -> None:
        prompt = _build_prompt("myapp", "", None)
        # The "Workload:" prefix should not appear when description is empty.
        assert "Workload:" not in prompt


class TestEmbedPngInSvg:
    """The SVG envelope must be valid, single-file, and carry the marker."""

    def test_envelope_includes_marker(self) -> None:
        svg = _embed_png_in_svg(b"\x89PNG\r\n\x1a\nx", "myapp")
        assert _GENERATED_MARKER in svg
        assert svg.startswith('<?xml version="1.0"')
        assert svg.rstrip().endswith("</svg>")

    def test_payload_is_base64(self) -> None:
        png = b"\x89PNG\r\n\x1a\nhello-world"
        svg = _embed_png_in_svg(png, "myapp")
        encoded = base64.b64encode(png).decode("ascii")
        assert encoded in svg

    def test_charm_name_sanitised(self) -> None:
        svg = _embed_png_in_svg(b"x", "my--weird---name")
        # Double dashes collapse so the marker comment stays a valid XML comment.
        assert "<!-- " in svg
        assert "--->" not in svg


class TestExistingIconIsExpendable:
    """Overwrite gating: keep user art, replace placeholders / our outputs."""

    def test_missing_file_is_expendable(self, tmp_path: pathlib.Path) -> None:
        assert _existing_icon_is_expendable(tmp_path / "icon.svg")

    def test_marker_file_is_expendable(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "icon.svg"
        path.write_text(f"<!-- {_GENERATED_MARKER} -->\n<svg/>\n")
        assert _existing_icon_is_expendable(path)

    def test_placeholder_fingerprint_is_expendable(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "icon.svg"
        path.write_text(f"<svg>{_PLACEHOLDER_FINGERPRINT}</svg>\n")
        assert _existing_icon_is_expendable(path)

    def test_unrelated_user_art_protected(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "icon.svg"
        path.write_text("<svg><path d='custom'/></svg>\n")
        assert not _existing_icon_is_expendable(path)


# ---------------------------------------------------------------------------
# CharmIconGenerateTool — happy path + edge cases
# ---------------------------------------------------------------------------


class TestCharmIconGenerate:
    """Exercises the tool's success path, refusal logic, and cost accounting."""

    @pytest.mark.asyncio
    async def test_empty_description_rejected(self, charm_dir: pathlib.Path) -> None:
        tool, _, _ = _make_tool()
        result = await tool.execute(description="", path=str(charm_dir))
        assert not result.success
        assert "non-empty description" in result.error

    @pytest.mark.asyncio
    async def test_missing_directory_rejected(self) -> None:
        tool, _, _ = _make_tool()
        result = await tool.execute(description="x", path="/nonexistent-dir-zzz")
        assert not result.success
        assert "Charm directory not found" in result.error

    @pytest.mark.asyncio
    async def test_happy_path_writes_svg(self, charm_dir: pathlib.Path) -> None:
        tool, stub, state = _make_tool()
        result = await tool.execute(
            description="PostgreSQL database",
            path=str(charm_dir),
        )
        assert result.success, result.error
        icon_path = pathlib.Path(result.data["path"])
        assert icon_path == charm_dir / "icon.svg"
        content = icon_path.read_text()
        assert _GENERATED_MARKER in content
        assert "data:image/png;base64" in content
        # Cost accumulated.
        assert state.icon_calls_total == 1
        assert state.icon_session_cost_usd == pytest.approx(0.04)
        assert result.data["embedded_png"] is True
        assert result.data["charm_name"] == "myapp"
        # Stub received the assembled prompt with the workload phrase.
        prompt, _size = stub.called_with[0]
        assert "PostgreSQL database" in prompt
        assert "myapp" in prompt

    @pytest.mark.asyncio
    async def test_charm_name_falls_back_to_dir_name(self, tmp_path: pathlib.Path) -> None:
        # No charmcraft.yaml — should use directory name.
        tool, _, _ = _make_tool()
        result = await tool.execute(description="x", path=str(tmp_path))
        assert result.success
        assert result.data["charm_name"] == tmp_path.name

    @pytest.mark.asyncio
    async def test_explicit_charm_name_overrides_yaml(self, charm_dir: pathlib.Path) -> None:
        tool, _, _ = _make_tool()
        result = await tool.execute(
            description="x",
            path=str(charm_dir),
            charm_name="overridden",
        )
        assert result.success
        assert result.data["charm_name"] == "overridden"

    @pytest.mark.asyncio
    async def test_refuses_to_overwrite_user_art(self, charm_dir: pathlib.Path) -> None:
        # Pre-existing icon that doesn't match the placeholder shape.
        (charm_dir / "icon.svg").write_text("<svg><path d='custom'/></svg>")
        tool, stub, state = _make_tool()
        result = await tool.execute(description="x", path=str(charm_dir))
        assert not result.success
        assert "Refusing to overwrite" in result.error
        # Provider was not called and no cost was charged.
        assert stub.called_with == []
        assert state.icon_session_cost_usd == 0.0

    @pytest.mark.asyncio
    async def test_force_overwrites_user_art(self, charm_dir: pathlib.Path) -> None:
        (charm_dir / "icon.svg").write_text("<svg><path d='custom'/></svg>")
        tool, _, _ = _make_tool()
        result = await tool.execute(description="x", path=str(charm_dir), force=True)
        assert result.success
        assert _GENERATED_MARKER in (charm_dir / "icon.svg").read_text()

    @pytest.mark.asyncio
    async def test_overwrites_placeholder_without_force(self, charm_dir: pathlib.Path) -> None:
        (charm_dir / "icon.svg").write_text(f'<svg>{_PLACEHOLDER_FINGERPRINT} r="120"/></svg>')
        tool, _, _ = _make_tool()
        result = await tool.execute(description="x", path=str(charm_dir))
        assert result.success

    @pytest.mark.asyncio
    async def test_overwrites_own_marker_without_force(self, charm_dir: pathlib.Path) -> None:
        (charm_dir / "icon.svg").write_text(f"<!-- {_GENERATED_MARKER} -->\n<svg/>\n")
        tool, _, _ = _make_tool()
        result = await tool.execute(description="x", path=str(charm_dir))
        assert result.success

    @pytest.mark.asyncio
    async def test_cost_cap_blocks_call(self, charm_dir: pathlib.Path) -> None:
        state = AgentState()
        state.icon_session_cost_usd = 5.0
        state.icon_max_session_cost_usd = 1.0
        tool, stub, _ = _make_tool(state=state)
        result = await tool.execute(description="x", path=str(charm_dir))
        assert not result.success
        assert "session cost cap reached" in result.error
        # Provider not called when budget already exceeded.
        assert stub.called_with == []

    @pytest.mark.asyncio
    async def test_image_generation_error_surfaces_cleanly(self, charm_dir: pathlib.Path) -> None:
        stub = _StubImageProvider(raise_on_call=ImageGenerationError("safety filter blocked"))
        tool, _, state = _make_tool(provider=stub)
        result = await tool.execute(description="x", path=str(charm_dir))
        assert not result.success
        assert "safety filter blocked" in result.error
        # No cost charged, no icon written.
        assert state.icon_session_cost_usd == 0.0
        assert not (charm_dir / "icon.svg").exists()

    @pytest.mark.asyncio
    async def test_provider_construction_failure_surfaces(self, charm_dir: pathlib.Path) -> None:
        tool, _, _ = _make_tool(raise_factory=ValueError("no API key"))
        result = await tool.execute(description="x", path=str(charm_dir))
        assert not result.success
        assert "Failed to construct image provider" in result.error

    @pytest.mark.asyncio
    async def test_records_transcript_event(self, charm_dir: pathlib.Path) -> None:
        store = MagicMock()
        state = AgentState()

        def _factory(_name: str | None, _model: str | None) -> ImageProvider:
            return _StubImageProvider()

        tool = CharmIconGenerateTool(
            state=state,
            store_getter=lambda: store,
            provider_factory=_factory,
        )
        result = await tool.execute(description="redis", path=str(charm_dir))
        assert result.success
        store.record_event.assert_called_once()
        event_name, payload = store.record_event.call_args[0]
        assert event_name == "icon_generated"
        assert payload["charm_name"] == "myapp"
        assert payload["description"] == "redis"
        assert payload["cost_usd"] == pytest.approx(0.04)


# ---------------------------------------------------------------------------
# /icon slash command
# ---------------------------------------------------------------------------


class _FakeAgent:
    """Minimal agent stand-in for the /icon dispatcher."""

    def __init__(self, charm_path: pathlib.Path | None) -> None:
        self.state = AgentState()
        self.state.charm_path = charm_path


class TestIconSlash:
    """The /icon dispatcher must short-circuit cleanly on every edge case."""

    def test_empty_args_returns_usage(self) -> None:
        result = slash_commands._handle_icon(_FakeAgent(pathlib.Path("/tmp")), "")
        assert result.followup is None
        assert "Usage" in result.text

    def test_missing_charm_path_short_circuits(self) -> None:
        result = slash_commands._handle_icon(_FakeAgent(None), "redis")
        assert result.followup is None
        assert "no charm path" in result.text.lower()

    def test_charm_path_does_not_exist_short_circuits(self, tmp_path: pathlib.Path) -> None:
        bogus = tmp_path / "nope"
        result = slash_commands._handle_icon(_FakeAgent(bogus), "redis")
        assert result.followup is None
        assert "does not exist" in result.text.lower()

    def test_with_description_returns_followup(self, charm_dir: pathlib.Path) -> None:
        result = slash_commands._handle_icon(_FakeAgent(charm_dir), "redis db")
        assert result.followup is not None
        assert "Painting" in result.text
        assert result.markdown is True
        result.followup.close()

    @pytest.mark.asyncio
    async def test_followup_invokes_painter_and_renders(
        self, charm_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Patch the slash module's runner so we can inject a stub
        # provider without needing a real Imagen API key.
        async def _patched_run(agent: object, description: str, charm_path: str) -> str:
            from cantrip.agent.tools.icon import CharmIconGenerateTool

            stub = _StubImageProvider()

            def _factory(_n: str | None, _m: str | None) -> ImageProvider:
                return stub

            tool = CharmIconGenerateTool(state=agent.state, provider_factory=_factory)
            result = await tool.execute(description=description, path=charm_path)
            return result.output if result.success else f"_failed: {result.error}_"

        # Replace the slash module's runner with our stubbed version.
        monkeypatch.setattr(slash_commands, "_run_icon", _patched_run)
        result = slash_commands._handle_icon(_FakeAgent(charm_dir), "redis cache")
        assert result.followup is not None
        text = await result.followup
        assert "Generated icon.svg" in text
        assert "myapp" in text
        # Icon really written.
        assert (charm_dir / "icon.svg").exists()

    def test_catalogue_entry_present(self) -> None:
        verbs = {cmd.verb for cmd in slash_commands.COMMAND_CATALOGUE}
        assert "/icon" in verbs
        assert "/icon" in slash_commands.SHARED_VERBS
