"""Tests for the ``/recipe`` slash-command dispatcher (Phase 73.1)."""

from __future__ import annotations

import asyncio
import pathlib
from collections.abc import Awaitable
from types import SimpleNamespace

from cantrip.agent import recipes
from cantrip.agent.commands import slash as slash_commands
from cantrip.agent.commands.recipes import handle_recipe
from cantrip.agent.commands.slash import SlashResult, dispatch


async def _drain(awaitable: Awaitable[str]) -> str:
    return await awaitable


def _agent(
    *,
    recipes_registry: recipes.RecipeRegistry | None = None,
    process_response: str = "",
    charm_path: pathlib.Path | None = None,
) -> SimpleNamespace:
    """Smallest agent shape the recipe handler reads.

    Mirrors :func:`tests.unit.agent.commands.test_slash._fake_agent` but
    inlined here because the slash conftest hierarchy doesn't expose
    that helper to neighbouring test files.
    """
    received: list[str] = []

    async def process_message(prompt: str) -> str:
        received.append(prompt)
        return process_response

    namespace = SimpleNamespace(
        recipes=recipes_registry or recipes.RecipeRegistry(),
        state=SimpleNamespace(charm_path=charm_path),
        executor=None,
        process_message=process_message,
        custom_commands=None,
    )
    namespace._received = received  # for assertions
    return namespace


def _make_recipe(
    name: str,
    *,
    instructions: str = "Do {{ thing }}.",
    parameters: tuple[recipes.Parameter, ...] = (recipes.Parameter("thing", "string"),),
    response: recipes.RecipeResponseSpec | None = None,
    retry_config=None,
) -> recipes.Recipe:
    return recipes.Recipe(
        name=name,
        title=f"Recipe {name}",
        description=f"Description for {name}.",
        parameters=parameters,
        instructions=instructions,
        response=response,
        retry=retry_config,
    )


# ---------------------------------------------------------------------------
# Catalogue / help paths
# ---------------------------------------------------------------------------


class TestCatalogue:
    def test_no_recipes(self) -> None:
        agent = _agent()
        result = handle_recipe(agent, "")
        assert isinstance(result, SlashResult)
        assert result.followup is None
        assert "No recipes loaded" in result.text
        assert ".cantrip-recipes" in result.text

    def test_lists_loaded_recipes(self) -> None:
        registry = recipes.RecipeRegistry(recipes=(_make_recipe("first"), _make_recipe("second")))
        agent = _agent(recipes_registry=registry)
        result = handle_recipe(agent, "")
        assert isinstance(result, SlashResult)
        assert result.markdown is True
        assert "/recipe first" in result.text
        assert "/recipe second" in result.text

    def test_help_lists_catalogue(self) -> None:
        registry = recipes.RecipeRegistry(recipes=(_make_recipe("first"),))
        agent = _agent(recipes_registry=registry)
        result = handle_recipe(agent, "help")
        assert "/recipe first" in result.text

    def test_recipe_help_shows_parameters(self) -> None:
        recipe = _make_recipe(
            "with-params",
            parameters=(
                recipes.Parameter(
                    "name",
                    "string",
                    description="Charm name.",
                ),
                recipes.Parameter(
                    "tier",
                    "select",
                    options=("free", "pro"),
                    default="pro",
                ),
            ),
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        agent = _agent(recipes_registry=registry)
        result = handle_recipe(agent, "with-params --help")
        assert "Charm name." in result.text
        assert "options" in result.text
        assert "free" in result.text and "pro" in result.text

    def test_help_unknown_recipe(self) -> None:
        registry = recipes.RecipeRegistry(recipes=(_make_recipe("first"),))
        agent = _agent(recipes_registry=registry)
        result = handle_recipe(agent, "help no-such-thing")
        assert "No recipe named" in result.text


# ---------------------------------------------------------------------------
# Invocation paths (followup coroutine)
# ---------------------------------------------------------------------------


class TestInvocation:
    def test_unknown_recipe(self) -> None:
        agent = _agent()
        result = handle_recipe(agent, "missing thing=x")
        assert "No recipe named" in result.text
        assert result.followup is None

    def test_happy_path_renders_and_dispatches(self) -> None:
        recipe = _make_recipe(
            "build",
            instructions="Build {{ thing }}.",
            parameters=(recipes.Parameter("thing", "string"),),
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        agent = _agent(
            recipes_registry=registry,
            process_response="ok done",
        )
        result = handle_recipe(agent, "build thing=charm")
        assert result.followup is not None
        output = asyncio.run(_drain(result.followup))
        assert output == "ok done"
        assert agent._received == ["Build charm."]

    def test_missing_required_parameter_surfaces_clear_error(self) -> None:
        recipe = _make_recipe("build")
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        agent = _agent(recipes_registry=registry)
        result = handle_recipe(agent, "build")
        output = asyncio.run(_drain(result.followup))
        assert "missing required parameter" in output
        # No prompt should have reached process_message.
        assert agent._received == []

    def test_unknown_argument_surfaces_clear_error(self) -> None:
        recipe = _make_recipe("build")
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        agent = _agent(recipes_registry=registry)
        result = handle_recipe(agent, "build thing=ok stranger=oops")
        output = asyncio.run(_drain(result.followup))
        assert "unknown parameters" in output
        assert agent._received == []

    def test_response_schema_validation_appended_on_failure(self) -> None:
        recipe = _make_recipe(
            "with-schema",
            instructions="Reply with JSON.",
            parameters=(),
            response=recipes.RecipeResponseSpec(
                schema={
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                    "required": ["status"],
                }
            ),
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        agent = _agent(
            recipes_registry=registry,
            process_response="this is not JSON at all",
        )
        result = handle_recipe(agent, "with-schema")
        output = asyncio.run(_drain(result.followup))
        assert "this is not JSON at all" in output  # original reply preserved
        assert "schema validation failed" in output

    def test_response_schema_silent_on_success(self) -> None:
        recipe = _make_recipe(
            "with-schema",
            instructions="Reply with JSON.",
            parameters=(),
            response=recipes.RecipeResponseSpec(
                schema={
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                    "required": ["status"],
                }
            ),
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        agent = _agent(
            recipes_registry=registry,
            process_response='{"status": "ok"}',
        )
        result = handle_recipe(agent, "with-schema")
        output = asyncio.run(_drain(result.followup))
        # No validator note appended — the response already matches.
        assert "schema validation failed" not in output


# ---------------------------------------------------------------------------
# End-to-end dispatch through ``slash.dispatch``
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_dispatch_routes_recipe(self) -> None:
        registry = recipes.RecipeRegistry(recipes=(_make_recipe("first"),))
        agent = _agent(recipes_registry=registry)
        result = dispatch(agent, "/recipe")
        assert isinstance(result, SlashResult)
        assert "/recipe first" in result.text

    def test_recipe_in_catalogue(self) -> None:
        # Drift guard — the new verb must appear in the shared catalogue
        # (already enforced globally; this asserts the explicit entry).
        verbs = {cmd.verb for cmd in slash_commands.COMMAND_CATALOGUE}
        assert "/recipe" in verbs

    def test_recipe_help_text(self) -> None:
        # Help surface for the new verb must be discoverable from
        # `/help`, otherwise the test_help_renders smoke test in
        # ``test_slash.py`` doesn't catch a missing entry.
        text = slash_commands.help_text(None)
        assert "/recipe" in text
