"""``/recipe`` slash-command handler (Phase 73.1).

Recipes live under :mod:`cantrip.agent.recipes`; this module owns the
dispatch glue:

* No-arg / ``help`` — print the catalogue and per-recipe parameter list
  so users can discover what's available without leaving the chat.
* Named invocation — bind ``key=value`` argv to declared parameters,
  render the Jinja-templated instructions, and feed the result into
  the agent's primary conversation loop (``agent.process_message``).
* Composes with Phase 73.4 retry — a recipe carrying ``retry:``
  routes through :func:`run_with_retry` exactly like a custom command.
* Composes with Phase 73.3 structured output — when a recipe declares
  ``response:``, the final assistant text is validated against the
  schema and a clear error is surfaced on mismatch.

Sub-recipes, ``settings.model`` mid-session swap, and ``extensions``
MCP-server enforcement are explicitly deferred — :class:`Recipe`
parses them so the YAML is well-formed today, but the dispatcher
warns when they would otherwise apply silently.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cantrip.agent import declarative_retry, recipes
from cantrip.llm import structured

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cantrip.agent.commands.slash import SlashResult
    from cantrip.agent.core import CantripAgent


# ---------------------------------------------------------------------------
# Catalogue / help rendering
# ---------------------------------------------------------------------------


def _format_parameter_line(parameter: recipes.Parameter) -> str:
    """One bullet describing a parameter for help output."""
    bits = [f"`{parameter.name}` ({parameter.type}, {parameter.requirement})"]
    if parameter.options is not None:
        bits.append(f"options: {list(parameter.options)!r}")
    if parameter.default is not None:
        bits.append(f"default: `{parameter.default!r}`")
    head = " — ".join(bits)
    if parameter.description:
        return f"  - {head} — {parameter.description}"
    return f"  - {head}"


def _format_recipe_help(recipe: recipes.Recipe) -> str:
    """Detail page for a single recipe (used by ``/recipe <name> --help``)."""
    lines = [f"**`/recipe {recipe.name}`** — {recipe.title}", "", recipe.description, ""]
    if recipe.parameters:
        lines.append("**Parameters:**")
        lines.extend(_format_parameter_line(p) for p in recipe.parameters)
    else:
        lines.append("_No parameters._")
    if recipe.response is not None:
        if recipe.response.schema_name is not None:
            lines.append("")
            lines.append(
                f"_Output validated against built-in schema_ `{recipe.response.schema_name}`."
            )
        else:
            lines.append("")
            lines.append("_Output validated against an inline JSON Schema._")
    if recipe.retry is not None:
        lines.append("")
        lines.append(
            f"_Retries up to {recipe.retry.total_attempts_cap} time(s) "
            f"with {len(recipe.retry.checks)} check(s)._"
        )
    if not recipe.settings.is_default():
        lines.append("")
        lines.append(
            "_Settings (model / temperature / max_turns) are recorded but "
            "not yet applied at dispatch — a follow-up will wire them in._"
        )
    if recipe.extensions:
        lines.append("")
        lines.append(
            "_Extensions are recorded but enforcement is deferred — see "
            "design/RECIPES.md for the rationale._"
        )
    if recipe.sub_recipes:
        lines.append("")
        lines.append(
            "_Sub-recipes are recorded but orchestration is deferred — "
            "this recipe will run its top-level instructions only._"
        )
    return "\n".join(lines)


def _format_catalogue(registry: recipes.RecipeRegistry) -> str:
    """No-arg ``/recipe`` listing."""
    if not registry.recipes:
        return (
            "_No recipes loaded._  Drop a YAML file into "
            "`.cantrip-recipes/` (repo) or `~/.config/cantrip/recipes/` "
            "(user) — see `design/RECIPES.md` for the schema."
        )
    lines = ["**Recipes**", ""]
    for recipe in registry.recipes:
        lines.append(f"- `/recipe {recipe.name}` — {recipe.title}")
    lines.append("")
    lines.append(
        "Run `/recipe <name> --help` for the parameter list.  Invoke "
        "with `/recipe <name> key=value …`."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def handle_recipe(agent: CantripAgent, args: str) -> SlashResult:
    """Dispatch ``/recipe`` from :func:`cantrip.agent.commands.slash.dispatch`.

    Returns a :class:`SlashResult` with the prelude in ``text`` and
    the recipe-execution coroutine in ``followup`` for invocations
    that reach the conversation loop.  No-arg / help paths return a
    plain :class:`SlashResult` with markdown formatting on.
    """
    # Imported lazily to avoid the slash-dispatcher → recipes-handler →
    # slash-dispatcher import cycle.
    from cantrip.agent.commands.slash import SlashResult

    registry = getattr(agent, "recipes", None)
    if not isinstance(registry, recipes.RecipeRegistry):
        return SlashResult(text="_`/recipe` is unavailable — agent has no recipe registry._")

    tokens = args.split(maxsplit=1)
    if not tokens or tokens[0] in {"help", "--help", "-h"}:
        # ``/recipe`` and ``/recipe help`` both list the catalogue.
        if len(tokens) == 2 and tokens[0] in {"help", "--help", "-h"}:
            # ``/recipe help <name>`` shows that recipe's parameter
            # list — same shape as ``/recipe <name> --help``.
            recipe = registry.get(tokens[1].strip())
            if recipe is None:
                return SlashResult(
                    text=f"_No recipe named `{tokens[1].strip()}`._",
                    markdown=True,
                )
            return SlashResult(text=_format_recipe_help(recipe), markdown=True)
        return SlashResult(text=_format_catalogue(registry), markdown=True)

    name, _, rest = args.partition(" ")
    name = name.strip()
    rest = rest.strip()

    recipe = registry.get(name)
    if recipe is None:
        return SlashResult(
            text=(f"_No recipe named `{name}`._  Run `/recipe` to list available recipes."),
            markdown=True,
        )

    if rest in {"--help", "-h", "help"}:
        return SlashResult(text=_format_recipe_help(recipe), markdown=True)

    prelude = f"Running `/recipe {name}`…"

    async def _run() -> str:
        return await _invoke_recipe(agent, recipe, rest)

    return SlashResult(text=prelude, followup=_run())


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------


async def _invoke_recipe(agent: CantripAgent, recipe: recipes.Recipe, args: str) -> str:
    """Bind, render, and run *recipe* through the agent's primary loop."""
    try:
        bound = await recipes.bind_parameters(
            recipe, args, prompt_callback=_make_prompt_callback(agent, recipe)
        )
    except recipes.RecipeError as exc:
        return f"`/recipe {recipe.name}` failed: {exc}"

    try:
        prompt = recipes.render_instructions(recipe, bound)
    except recipes.RecipeError as exc:
        return f"`/recipe {recipe.name}` failed: {exc}"

    if recipe.retry is not None:
        outcome = await declarative_retry.run_with_retry(
            agent.process_message,
            prompt,
            config=recipe.retry,
            repo_root=agent.state.charm_path,
            permissions=agent.executor.permissions if agent.executor else None,
            permission_manager=(agent.executor.permission_manager if agent.executor else None),
            agent_name="primary",
        )
        response_text = _format_retry_outcome(outcome)
    else:
        response_text = await agent.process_message(prompt)

    if recipe.response is not None:
        validation_note = _validate_response(recipe, response_text)
        if validation_note is not None:
            response_text = f"{response_text}\n\n{validation_note}"

    return response_text


def _validate_response(recipe: recipes.Recipe, response: str) -> str | None:
    """Run the recipe's response schema against *response*.

    Returns ``None`` on success (no message appended) or a one-paragraph
    note on failure.  The recipe's text reply is always returned to the
    user — the validator is advisory unless the recipe also declares a
    ``json_schema`` check inside ``retry:``, which converges the loop.
    """
    assert recipe.response is not None  # narrow for type checker
    schema = recipe.response.resolved_schema()
    try:
        structured.validate_against_schema(response, schema)
    except structured.StructuredOutputError as exc:
        return (
            f"_⚠ Response schema validation failed: {exc}.  Add a "
            "`json_schema` check inside `retry:` to make Cantrip re-run "
            "until the output validates._"
        )
    return None


def _format_retry_outcome(
    outcome: declarative_retry.RetryOutcome,
) -> str:
    """Render :class:`RetryOutcome` for the chat — same shape as
    :func:`cantrip.agent.commands.slash._run_primary_with_retry`."""
    if outcome.converged:
        if outcome.attempts == 1:
            return outcome.output
        return outcome.output + f"\n\n_Retry: converged after {outcome.attempts} attempts._"
    failure_lines = [f"  - {result.label}: {result.detail}" for result in outcome.failures]
    summary = (
        f"\n\n_Retry: did not converge after {outcome.attempts} attempt(s)"
        + (" (timed out)" if outcome.timed_out else "")
        + "; failed checks:_\n"
        + "\n".join(failure_lines)
    )
    if outcome.on_failure_ran:
        summary += "\n_on_failure cleanup ran._"
    return outcome.output + summary


def _make_prompt_callback(
    agent: CantripAgent, recipe: recipes.Recipe
) -> recipes.PromptCallback | None:
    """Return a callback that asks the user for a missing ``prompted`` parameter.

    The slash dispatcher runs in async context so the callback can
    park on whichever interactive surface the agent has wired up.
    For v1 we return ``None`` — when no surface is wired the binder
    treats ``prompted`` parameters identically to ``required`` and
    surfaces a clear "missing" error.  A follow-up landing wires the
    TUI / Web prompt manager into this callback so an interactive
    user gets a real ask-and-bind path.
    """
    # Phase 73.1 v1: no interactive prompt surface.  Binder will
    # raise a clear missing-parameter error if a ``prompted`` param
    # has no default and no argv value.  A future hook can return a
    # callback bound to the active UI surface here.
    del agent, recipe
    return None


__all__ = ["handle_recipe"]
