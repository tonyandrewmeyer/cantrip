"""Tests for the ``/recipe`` slash-command dispatcher (Phase 73.1)."""

from __future__ import annotations

import asyncio
import pathlib
from collections.abc import Awaitable
from types import SimpleNamespace

from cantrip.agent.commands import slash as slash_commands
from cantrip.agent.commands.recipes import handle_recipe
from cantrip.agent.commands.slash import SlashResult, dispatch
from cantrip.agent.policy import declarative_retry
from cantrip.agent.workflows import recipes


async def _drain(awaitable: Awaitable[str]) -> str:
    return await awaitable


class _FakeMCPSnapshot(SimpleNamespace):
    """Stand-in for :class:`cantrip.mcp.registry.ServerSnapshot`.

    The recipe extension check stringifies ``snapshot.status`` and looks
    for ``"connected"``; ``SimpleNamespace`` is enough — no need to drag
    the full mcp package into a unit test.
    """


def _agent(
    *,
    recipes_registry: recipes.RecipeRegistry | None = None,
    process_response: str = "",
    response_for: dict[str, str] | None = None,
    charm_path: pathlib.Path | None = None,
    mcp_servers: dict[str, str] | None = None,
    tool_names: tuple[str, ...] = (),
) -> SimpleNamespace:
    """Smallest agent shape the recipe handler reads.

    Mirrors :func:`tests.unit.agent.commands.test_slash._fake_agent` but
    inlined here because the slash conftest hierarchy doesn't expose
    that helper to neighbouring test files.

    ``mcp_servers`` is a ``{name: status}`` mapping — supply
    ``{"charmhub": "connected"}`` to satisfy ``extensions: [mcp:charmhub]``.
    ``tool_names`` lists the tools the session has registered; supply
    ``("juju_status",)`` to satisfy ``extensions: [tool:juju_status]``.
    ``response_for`` is a ``{first-line-substring: response}`` map used
    by the sub-recipe tests to give the parent and its children
    distinct replies; falls back to ``process_response`` on miss.
    """
    received: list[str] = []

    async def process_message(prompt: str) -> str:
        received.append(prompt)
        if response_for is not None:
            for needle, reply in response_for.items():
                if needle in prompt:
                    return reply
        return process_response

    mcp_registry: SimpleNamespace | None = None
    if mcp_servers is not None:
        snapshots = [
            _FakeMCPSnapshot(name=name, status=status) for name, status in mcp_servers.items()
        ]
        mcp_registry = SimpleNamespace(snapshot=lambda: snapshots)

    namespace = SimpleNamespace(
        recipes=recipes_registry or recipes.RecipeRegistry(),
        state=SimpleNamespace(charm_path=charm_path),
        executor=None,
        process_message=process_message,
        custom_commands=None,
        mcp_registry=mcp_registry,
    )
    # ``_tool_map`` is the canonical executor-side lookup; the recipe
    # handler reads it for ``extensions: [tool:<name>]`` enforcement.
    namespace._tool_map = {name: object() for name in tool_names}
    namespace._received = received  # for assertions
    return namespace


def _make_recipe(
    name: str,
    *,
    instructions: str = "Do {{ thing }}.",
    parameters: tuple[recipes.Parameter, ...] = (recipes.Parameter("thing", "string"),),
    response: recipes.RecipeResponseSpec | None = None,
    retry_config=None,
    extensions: tuple[str, ...] = (),
    sub_recipes: tuple[recipes.SubRecipeRef, ...] = (),
) -> recipes.Recipe:
    return recipes.Recipe(
        name=name,
        title=f"Recipe {name}",
        description=f"Description for {name}.",
        parameters=parameters,
        instructions=instructions,
        response=response,
        retry=retry_config,
        extensions=extensions,
        sub_recipes=sub_recipes,
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
# Extensions enforcement
# ---------------------------------------------------------------------------


class TestExtensions:
    def test_no_extensions_invokes_normally(self) -> None:
        # Sanity — recipes without an ``extensions`` block always run.
        recipe = _make_recipe("plain", parameters=(), instructions="ok")
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        agent = _agent(recipes_registry=registry, process_response="reply")
        result = handle_recipe(agent, "plain")
        output = asyncio.run(_drain(result.followup))
        assert output == "reply"

    def test_missing_mcp_extension_refuses(self) -> None:
        recipe = _make_recipe(
            "needs-charmhub",
            parameters=(),
            instructions="run it",
            extensions=("mcp:charmhub",),
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        # No mcp_registry on the agent — every mcp:* extension is missing.
        agent = _agent(recipes_registry=registry)
        result = handle_recipe(agent, "needs-charmhub")
        output = asyncio.run(_drain(result.followup))
        assert "cannot run" in output
        assert "mcp:charmhub" in output
        assert agent._received == []

    def test_disconnected_mcp_counts_as_missing(self) -> None:
        recipe = _make_recipe(
            "needs-charmhub",
            parameters=(),
            instructions="run it",
            extensions=("mcp:charmhub",),
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        # Server exists but is FAILED — must still refuse rather than
        # sending the agent off to call missing tools.
        agent = _agent(
            recipes_registry=registry,
            mcp_servers={"charmhub": "failed"},
        )
        result = handle_recipe(agent, "needs-charmhub")
        output = asyncio.run(_drain(result.followup))
        assert "cannot run" in output
        assert "mcp:charmhub" in output

    def test_connected_mcp_satisfies(self) -> None:
        recipe = _make_recipe(
            "needs-charmhub",
            parameters=(),
            instructions="run it",
            extensions=("mcp:charmhub",),
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        agent = _agent(
            recipes_registry=registry,
            mcp_servers={"charmhub": "connected"},
            process_response="ok",
        )
        result = handle_recipe(agent, "needs-charmhub")
        output = asyncio.run(_drain(result.followup))
        assert output == "ok"

    def test_missing_tool_extension_refuses(self) -> None:
        recipe = _make_recipe(
            "needs-juju",
            parameters=(),
            instructions="run it",
            extensions=("tool:juju_status",),
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        agent = _agent(recipes_registry=registry)  # no tools registered
        result = handle_recipe(agent, "needs-juju")
        output = asyncio.run(_drain(result.followup))
        assert "tool:juju_status" in output

    def test_present_tool_extension_satisfies(self) -> None:
        recipe = _make_recipe(
            "needs-juju",
            parameters=(),
            instructions="run it",
            extensions=("tool:juju_status",),
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        agent = _agent(
            recipes_registry=registry,
            tool_names=("juju_status",),
            process_response="ok",
        )
        result = handle_recipe(agent, "needs-juju")
        output = asyncio.run(_drain(result.followup))
        assert output == "ok"

    def test_unknown_prefix_treated_as_missing(self) -> None:
        # An ``extensions:`` entry without ``mcp:`` / ``tool:`` is a
        # likely typo; refuse rather than silently passing.
        recipe = _make_recipe(
            "typo-ext",
            parameters=(),
            instructions="run it",
            extensions=("mcpcharmhub",),
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        agent = _agent(recipes_registry=registry)
        result = handle_recipe(agent, "typo-ext")
        output = asyncio.run(_drain(result.followup))
        assert "cannot run" in output
        assert "mcpcharmhub" in output

    def test_partial_satisfaction_lists_only_missing(self) -> None:
        # When some extensions are met but not all, the refusal lists
        # only the unmet ones — easier to read than re-listing the lot.
        recipe = _make_recipe(
            "mixed",
            parameters=(),
            instructions="run it",
            extensions=("mcp:charmhub", "mcp:absent", "tool:juju_status"),
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        agent = _agent(
            recipes_registry=registry,
            mcp_servers={"charmhub": "connected"},
            tool_names=("juju_status",),
        )
        result = handle_recipe(agent, "mixed")
        output = asyncio.run(_drain(result.followup))
        assert "mcp:absent" in output
        # Met extensions stay quiet.
        assert "mcp:charmhub" not in output
        assert "tool:juju_status" not in output


# ---------------------------------------------------------------------------
# Sub-recipe orchestration (sequential v1)
# ---------------------------------------------------------------------------


class TestSubRecipes:
    def test_runs_after_parent_in_declaration_order(self) -> None:
        # Parent → child A → child B; both children get their own
        # ``process_message`` and their replies tail the parent's.
        parent = _make_recipe(
            "parent",
            parameters=(),
            instructions="Parent prompt.",
            sub_recipes=(
                recipes.SubRecipeRef(name="child-a", values={"note": "first"}),
                recipes.SubRecipeRef(name="child-b", values={"note": "second"}),
            ),
        )
        child_a = _make_recipe(
            "child-a",
            parameters=(recipes.Parameter("note", "string"),),
            instructions="Child A {{ note }}.",
        )
        child_b = _make_recipe(
            "child-b",
            parameters=(recipes.Parameter("note", "string"),),
            instructions="Child B {{ note }}.",
        )
        registry = recipes.RecipeRegistry(recipes=(parent, child_a, child_b))
        agent = _agent(
            recipes_registry=registry,
            response_for={
                "Parent prompt": "parent-reply",
                "Child A first": "child-a-reply",
                "Child B second": "child-b-reply",
            },
        )
        result = handle_recipe(agent, "parent")
        output = asyncio.run(_drain(result.followup))
        # Parent reply first, then each child framed with a header that
        # names the sub-recipe.
        assert output.startswith("parent-reply")
        assert "Sub-recipe 1/2: `child-a`" in output
        assert "Sub-recipe 2/2: `child-b`" in output
        assert "child-a-reply" in output
        assert "child-b-reply" in output
        # Order: parent before A before B.
        assert output.index("child-a-reply") < output.index("child-b-reply")
        # process_message ran exactly three times in declaration order.
        assert agent._received == [
            "Parent prompt.",
            "Child A first.",
            "Child B second.",
        ]

    def test_cycle_detected(self) -> None:
        # ``parent`` → ``parent`` is the simplest cycle; the handler
        # must refuse rather than recurse.
        recipe = _make_recipe(
            "parent",
            parameters=(),
            instructions="Parent prompt.",
            sub_recipes=(recipes.SubRecipeRef(name="parent"),),
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        agent = _agent(
            recipes_registry=registry,
            process_response="parent-reply",
        )
        result = handle_recipe(agent, "parent")
        output = asyncio.run(_drain(result.followup))
        assert "Refused — cycle detected" in output
        assert "parent → parent" in output
        # Only the parent ran — the cycle stopped recursion before the
        # second invocation of ``parent``.
        assert agent._received == ["Parent prompt."]

    def test_indirect_cycle_detected(self) -> None:
        # parent → middle → parent.  The middle recipe's sub_recipes
        # block names ``parent`` again and must be refused.
        parent = _make_recipe(
            "parent",
            parameters=(),
            instructions="Parent prompt.",
            sub_recipes=(recipes.SubRecipeRef(name="middle"),),
        )
        middle = _make_recipe(
            "middle",
            parameters=(),
            instructions="Middle prompt.",
            sub_recipes=(recipes.SubRecipeRef(name="parent"),),
        )
        registry = recipes.RecipeRegistry(recipes=(parent, middle))
        agent = _agent(
            recipes_registry=registry,
            response_for={
                "Parent prompt": "parent-reply",
                "Middle prompt": "middle-reply",
            },
        )
        result = handle_recipe(agent, "parent")
        output = asyncio.run(_drain(result.followup))
        assert "parent-reply" in output
        assert "middle-reply" in output
        assert "Refused — cycle detected" in output
        assert "parent → middle → parent" in output

    def test_missing_sub_recipe_skipped_with_note(self) -> None:
        # A sub_recipes entry naming an unknown recipe surfaces the
        # miss but doesn't break the rest of the chain.
        parent = _make_recipe(
            "parent",
            parameters=(),
            instructions="Parent prompt.",
            sub_recipes=(
                recipes.SubRecipeRef(name="ghost"),
                recipes.SubRecipeRef(name="child"),
            ),
        )
        child = _make_recipe("child", parameters=(), instructions="Child prompt.")
        registry = recipes.RecipeRegistry(recipes=(parent, child))
        agent = _agent(
            recipes_registry=registry,
            response_for={
                "Parent prompt": "parent-reply",
                "Child prompt": "child-reply",
            },
        )
        result = handle_recipe(agent, "parent")
        output = asyncio.run(_drain(result.followup))
        assert "No recipe named `ghost`" in output
        assert "child-reply" in output

    def test_sub_recipe_values_coerced(self) -> None:
        # A child declares ``port: number``.  The parent passes
        # ``values: {port: "8080"}`` (a string), and the binder coerces
        # it through the same path argv would.
        parent = _make_recipe(
            "parent",
            parameters=(),
            instructions="Parent prompt.",
            sub_recipes=(recipes.SubRecipeRef(name="child", values={"port": "8080"}),),
        )
        child = _make_recipe(
            "child",
            parameters=(recipes.Parameter("port", "number"),),
            instructions="Listening on {{ port }}.",
        )
        registry = recipes.RecipeRegistry(recipes=(parent, child))
        agent = _agent(
            recipes_registry=registry,
            response_for={"Listening on 8080.0": "child-reply"},
            process_response="parent-reply",
        )
        result = handle_recipe(agent, "parent")
        output = asyncio.run(_drain(result.followup))
        assert "child-reply" in output
        assert "Listening on 8080.0." in agent._received

    def test_sub_recipe_extensions_enforced(self) -> None:
        # A child sub-recipe with an unmet extension refuses at
        # dispatch — the parent's reply still surfaces but the
        # child's slot carries the refusal text.
        parent = _make_recipe(
            "parent",
            parameters=(),
            instructions="Parent prompt.",
            sub_recipes=(recipes.SubRecipeRef(name="child"),),
        )
        child = _make_recipe(
            "child",
            parameters=(),
            instructions="Child prompt.",
            extensions=("mcp:absent",),
        )
        registry = recipes.RecipeRegistry(recipes=(parent, child))
        agent = _agent(
            recipes_registry=registry,
            process_response="parent-reply",
        )
        result = handle_recipe(agent, "parent")
        output = asyncio.run(_drain(result.followup))
        assert "parent-reply" in output
        assert "cannot run" in output
        assert "mcp:absent" in output


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


# ---------------------------------------------------------------------------
# Help-page rendering — the optional detail blocks
# ---------------------------------------------------------------------------


class TestHelpPageBlocks:
    """``/recipe <name> --help`` renders each optional section."""

    def test_no_recipe_registry_is_unavailable(self) -> None:
        # An agent missing the ``recipes`` attribute (or holding a
        # non-registry) short-circuits before any parsing.
        agent = SimpleNamespace(recipes=None)
        result = handle_recipe(agent, "anything")
        assert "is unavailable" in result.text

    def test_help_name_form_shows_parameters(self) -> None:
        # ``/recipe help <name>`` is the colon-free twin of
        # ``/recipe <name> --help`` and routes through the same renderer.
        registry = recipes.RecipeRegistry(recipes=(_make_recipe("first"),))
        agent = _agent(recipes_registry=registry)
        result = handle_recipe(agent, "help first")
        assert "Parameters:" in result.text

    def test_no_parameters_block(self) -> None:
        recipe = _make_recipe("plain", parameters=(), instructions="ok")
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        result = handle_recipe(_agent(recipes_registry=registry), "plain --help")
        assert "_No parameters._" in result.text

    def test_inline_response_schema_note(self) -> None:
        recipe = _make_recipe(
            "schema-inline",
            parameters=(),
            response=recipes.RecipeResponseSpec(
                schema={"type": "object", "properties": {"ok": {"type": "string"}}},
            ),
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        result = handle_recipe(_agent(recipes_registry=registry), "schema-inline --help")
        assert "inline JSON Schema" in result.text

    def test_named_response_schema_note(self) -> None:
        recipe = _make_recipe(
            "schema-named",
            parameters=(),
            response=recipes.RecipeResponseSpec(schema_name="charm_plan"),
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        result = handle_recipe(_agent(recipes_registry=registry), "schema-named --help")
        assert "built-in schema" in result.text
        assert "charm_plan" in result.text

    def test_retry_note(self) -> None:
        retry = declarative_retry.RetryConfig(
            max_retries=2,
            checks=(declarative_retry.JsonSchemaCheck(schema={"type": "object"}),),
        )
        recipe = _make_recipe("with-retry", parameters=(), retry_config=retry)
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        result = handle_recipe(_agent(recipes_registry=registry), "with-retry --help")
        assert "Retries up to" in result.text
        assert "1 check(s)" in result.text

    def test_extensions_note(self) -> None:
        recipe = _make_recipe("with-ext", parameters=(), extensions=("mcp:charmhub",))
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        result = handle_recipe(_agent(recipes_registry=registry), "with-ext --help")
        assert "Required extensions" in result.text
        assert "mcp:charmhub" in result.text

    def test_sub_recipes_note(self) -> None:
        recipe = _make_recipe(
            "parent",
            parameters=(),
            sub_recipes=(recipes.SubRecipeRef(name="child"),),
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        result = handle_recipe(_agent(recipes_registry=registry), "parent --help")
        assert "sub-recipe(s) sequentially" in result.text


# ---------------------------------------------------------------------------
# Render-time failure and unknown-prefix extensions
# ---------------------------------------------------------------------------


class TestRenderAndExtensionEdges:
    def test_render_error_surfaces_recipe_failure(self) -> None:
        # ``render_instructions`` uses StrictUndefined; an instruction
        # referencing a variable with no matching parameter raises a
        # RecipeError that the handler turns into a friendly failure.
        recipe = _make_recipe(
            "bad-template",
            parameters=(),
            instructions="Use {{ undefined_thing }}.",
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        agent = _agent(recipes_registry=registry)
        result = handle_recipe(agent, "bad-template")
        output = asyncio.run(_drain(result.followup))
        assert "failed:" in output
        assert agent._received == []

    def test_unknown_prefix_with_colon_treated_as_missing(self) -> None:
        # ``foo:bar`` has a colon but an unrecognised prefix — the
        # else-branch of the extension classifier flags it as missing.
        recipe = _make_recipe(
            "weird-ext",
            parameters=(),
            instructions="run it",
            extensions=("foo:bar",),
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        agent = _agent(recipes_registry=registry)
        result = handle_recipe(agent, "weird-ext")
        output = asyncio.run(_drain(result.followup))
        assert "cannot run" in output
        assert "foo:bar" in output

    def test_mcp_snapshot_error_counts_as_unconnected(self) -> None:
        # A registry whose ``snapshot`` raises (an unusual shim) is the
        # same as "nothing connected" — the mcp extension stays unmet.
        recipe = _make_recipe(
            "needs-charmhub",
            parameters=(),
            instructions="run it",
            extensions=("mcp:charmhub",),
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        agent = _agent(recipes_registry=registry)

        def _boom() -> list:
            raise TypeError("bad shim")

        agent.mcp_registry = SimpleNamespace(snapshot=_boom)
        result = handle_recipe(agent, "needs-charmhub")
        output = asyncio.run(_drain(result.followup))
        assert "cannot run" in output
        assert "mcp:charmhub" in output


# ---------------------------------------------------------------------------
# Retry-outcome rendering
# ---------------------------------------------------------------------------


class TestRetryOutcomeRendering:
    def test_converged_single_attempt_is_bare_output(self) -> None:
        outcome = declarative_retry.RetryOutcome(
            output="done", attempts=1, converged=True, timed_out=False
        )
        from cantrip.agent.commands.recipes import _format_retry_outcome

        assert _format_retry_outcome(outcome) == "done"

    def test_converged_multi_attempt_appends_note(self) -> None:
        from cantrip.agent.commands.recipes import _format_retry_outcome

        outcome = declarative_retry.RetryOutcome(
            output="done", attempts=3, converged=True, timed_out=False
        )
        text = _format_retry_outcome(outcome)
        assert "converged after 3 attempts" in text

    def test_unconverged_lists_failed_checks(self) -> None:
        from cantrip.agent.commands.recipes import _format_retry_outcome

        failure = declarative_retry.CheckResult(
            check=declarative_retry.JsonSchemaCheck(schema={"type": "object"}),
            passed=False,
            detail="not an object",
        )
        outcome = declarative_retry.RetryOutcome(
            output="partial",
            attempts=2,
            converged=False,
            timed_out=True,
            failures=(failure,),
            on_failure_ran=True,
        )
        text = _format_retry_outcome(outcome)
        assert "did not converge after 2 attempt(s)" in text
        assert "(timed out)" in text
        assert "json_schema: not an object" in text
        assert "on_failure cleanup ran." in text

    def test_retry_path_runs_through_invoke(self) -> None:
        # End-to-end: a recipe with a retry block routes through
        # ``run_with_retry`` and the converged single-attempt outcome
        # surfaces as the plain reply.
        retry = declarative_retry.RetryConfig(max_retries=1, checks=())
        recipe = _make_recipe(
            "retrying",
            parameters=(),
            instructions="do it",
            retry_config=retry,
        )
        registry = recipes.RecipeRegistry(recipes=(recipe,))
        agent = _agent(recipes_registry=registry, process_response="all good")
        result = handle_recipe(agent, "retrying")
        output = asyncio.run(_drain(result.followup))
        assert output == "all good"
