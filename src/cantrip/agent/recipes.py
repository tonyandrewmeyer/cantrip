"""Recipes — parameterised, repeatable, retryable workflows (Phase 73.1).

A recipe is a YAML bundle a charm team checks into the repo (or
``~/.config/cantrip/recipes/`` for personal use) so a parameterised
workflow can be invoked deterministically: ``/recipe charm-cos-add
charm_name=ntfy metrics_endpoint=/metrics`` runs a Jinja-templated
prompt with declared parameters, optional schema-validated output
(Phase 73.3), and optional shell-validator-driven retry (Phase 73.4).

Distinct from neighbouring shapes:

* :mod:`cantrip.agent.skills` — knowledge bundles the agent reads.
* :mod:`cantrip.agent.flows` (Phase 69.4) — visual decision diagrams.
* :class:`cantrip.agent.commands.custom.CustomCommand` — single-shot
  prompt template with positional / file / shell expansions.
* :class:`Recipe` — typed parameters, structured-output enforcement,
  repeatable execution.  Recipes compose with both flows (the diagram
  is the decision tree, the recipe is the parameterised execution)
  and skills (a recipe may rely on a skill being loadable).

The module owns three things:

1. The :class:`Recipe`, :class:`Parameter`, :class:`RecipeSettings`,
   :class:`RecipeResponseSpec`, :class:`SubRecipeRef` dataclasses.
2. A discovery + loader path that walks the user and repo recipe
   dirs and turns ``*.yaml`` files into validated :class:`Recipe`
   objects.
3. :func:`bind_parameters` (argv → dict) and :func:`render_instructions`
   (dict + recipe → expanded prompt) so the dispatcher in
   :mod:`cantrip.agent.commands.slash` can stay thin.

Sub-recipe orchestration, the three built-in recipes
(``charm-new`` / ``charm-cos-add`` / ``charm-reactive-to-ops``),
the ``settings.model`` mid-session swap, and ``extensions`` MCP-
server enforcement are deferred to a follow-up landing — call sites
that touch them today raise :class:`RecipeError` with the relevant
sub-task pointer.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import pathlib
import re
import shlex
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import jinja2
import jinja2.sandbox
import yaml

from cantrip.agent.declarative_retry import (
    RetryConfig,
    RetryConfigError,
    parse_retry_config,
)
from cantrip.llm import schemas as llm_schemas

log = logging.getLogger(__name__)


#: Frontmatter delimiter — recipes are pure YAML (no markdown body),
#: so a single ``yaml.safe_load`` covers the whole file.
_INSTRUCTIONS_KEY = "instructions"


#: Permitted top-level keys.  Unknown keys raise so a typo doesn't
#: silently fall back to a default — mirrors ``custom.py`` and
#: ``declarative_retry.py``.
_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "version",
        "title",
        "description",
        "parameters",
        "instructions",
        "settings",
        "extensions",
        "response",
        "retry",
        "sub_recipes",
    }
)


_SETTINGS_KEYS: frozenset[str] = frozenset({"model", "temperature", "max_turns"})


_PARAMETER_KEYS: frozenset[str] = frozenset(
    {"name", "type", "requirement", "default", "description", "options"}
)


_RESPONSE_KEYS: frozenset[str] = frozenset({"json_schema", "schema_name"})


_SUB_RECIPE_KEYS: frozenset[str] = frozenset({"name", "values", "sequential_when_repeated"})


#: Canonical discovery roots.  Sibling-of-SQLite layout matches
#: ``.cantrip-shared/``, ``.cantrip-codeintel.json`` etc., because
#: ``<charm>/.cantrip`` is the SQLite session file and a single path
#: cannot be both a file and a directory.  Phase 51b notes this
#: collision in detail.
USER_CONFIG_RECIPES_DIR = pathlib.Path(".config") / "cantrip" / "recipes"
REPO_RECIPES_DIR = pathlib.Path(".cantrip-recipes")

#: Bundled recipes ship inside the Cantrip wheel at ``cantrip/recipes/``
#: (a sibling of ``cantrip/skills/``).  This is a *content* directory,
#: not a Python package — there is no ``__init__.py``.  Built-ins are
#: walked first, so user and repo recipes can override a built-in by
#: naming a YAML file the same.
BUNDLED_RECIPES_DIR = pathlib.Path(__file__).resolve().parents[1] / "recipes"


_VALID_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


#: Parameter type discriminators.
PARAMETER_TYPES: frozenset[str] = frozenset(
    {"string", "number", "boolean", "date", "file", "select"}
)


#: Parameter requirement levels.  ``prompted`` defers binding to a
#: caller-supplied callback (matches the ``ask`` pattern Phase 51b
#: uses for shared-memory writes).
PARAMETER_REQUIREMENTS: frozenset[str] = frozenset({"required", "optional", "prompted"})


#: Characters that could trigger Jinja2 template logic.  Mirrors
#: ``cantrip.agent.prompts.system._JINJA_SYNTAX`` so string
#: parameters cannot smuggle ``{{ … }}`` into the rendered prompt.
_JINJA_SYNTAX = re.compile(r"[{}%]")


class RecipeError(ValueError):
    """Raised on recipe parse, bind, render, or dispatch failure.

    Subclass of :class:`ValueError` so existing ``except ValueError``
    handlers still catch it — same posture as
    :class:`cantrip.agent.declarative_retry.RetryConfigError`.
    """


# ---------------------------------------------------------------------------
# Schema dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class Parameter:
    """One declared parameter.

    ``default`` is stored as the *coerced* Python value (a number is
    a ``float``, a date is a :class:`datetime.date`, etc.) so binding
    a recipe with a default never has to re-coerce the literal.

    ``options`` is non-empty for ``select``-type parameters and
    ``None`` everywhere else.  The loader enforces this so binding
    can trust the field.
    """

    name: str
    type: str
    requirement: str = "required"
    default: Any = None
    description: str = ""
    options: tuple[Any, ...] | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class RecipeSettings:
    """Optional model / runtime overrides.

    All fields are recorded but not yet honoured at dispatch.  v1
    surfaces the settings as parsed values so a downstream landing
    can wire them into the conversation loop without re-parsing.
    The dispatcher emits a warning if any setting is non-default so
    users know it's recorded-but-not-applied.
    """

    model: str | None = None
    temperature: float | None = None
    max_turns: int | None = None

    def is_default(self) -> bool:
        """Return ``True`` when no field is set — used by the dispatcher."""
        return self.model is None and self.temperature is None and self.max_turns is None


@dataclasses.dataclass(frozen=True, slots=True)
class RecipeResponseSpec:
    """Schema-validated final-output enforcement.

    Either ``schema`` (an inline JSON Schema dict) or ``schema_name``
    (a key into :data:`cantrip.llm.schemas.BUILTIN_SCHEMAS`) is set;
    the loader enforces exactly-one.  The dispatcher resolves
    ``schema_name`` to the dict at invocation time so a future schema
    addition lands without a recipe rewrite.
    """

    schema: dict[str, Any] | None = None
    schema_name: str | None = None

    def resolved_schema(self) -> dict[str, Any]:
        """Return the JSON Schema dict, resolving a built-in name if needed."""
        if self.schema is not None:
            return self.schema
        assert self.schema_name is not None  # invariant from loader
        return llm_schemas.BUILTIN_SCHEMAS[self.schema_name]


@dataclasses.dataclass(frozen=True, slots=True)
class SubRecipeRef:
    """Reference to another recipe invoked from this one.

    Sub-recipe orchestration (sequential vs parallel via Phase 44
    worktrees) is deferred — the dataclass exists so a recipe author
    can describe the intent today and the runtime catches up later.
    """

    name: str
    values: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    sequential_when_repeated: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class Recipe:
    """One loaded recipe.

    ``name`` is the verb-safe stem (no leading slash); the dispatcher
    composes ``/recipe <name> …`` to invoke it.  ``instructions`` is
    the raw Jinja2 template — :func:`render_instructions` evaluates
    it against bound parameters at dispatch time.
    """

    name: str
    title: str
    description: str
    parameters: tuple[Parameter, ...]
    instructions: str
    settings: RecipeSettings = RecipeSettings()
    extensions: tuple[str, ...] = ()
    response: RecipeResponseSpec | None = None
    retry: RetryConfig | None = None
    sub_recipes: tuple[SubRecipeRef, ...] = ()
    source: pathlib.Path | None = None
    version: str = "1"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _name_from_filename(path: pathlib.Path) -> str:
    """Validate ``path.stem`` matches the recipe-name shape and return it."""
    stem = path.stem.lower()
    if not _VALID_NAME_RE.fullmatch(stem):
        raise RecipeError(
            f"{path}: invalid recipe name {stem!r}; must match "
            "[a-z0-9][a-z0-9_-]* — letters, digits, hyphens, underscores"
        )
    return stem


def _require_string(path: pathlib.Path, key: str, value: object) -> str:
    """Reject non-string values for a required string field."""
    if not isinstance(value, str) or not value.strip():
        raise RecipeError(f"{path}: {key!r} must be a non-empty string")
    return value.strip()


def _coerce_default(
    path: pathlib.Path,
    param_name: str,
    type_: str,
    value: object,
    options: tuple[Any, ...] | None,
) -> Any:
    """Coerce a YAML default value to the parameter's Python type.

    Booleans and ints share a JSON tag so we treat the boolean-as-int
    edge case explicitly, matching the same guard
    :mod:`declarative_retry` uses.  Errors raise :class:`RecipeError`
    so the loader can prefix the path.
    """
    if value is None:
        return None
    try:
        return _coerce_value(type_, value, options=options)
    except RecipeError as exc:
        raise RecipeError(
            f"{path}: parameter {param_name!r} default {value!r} invalid: {exc}"
        ) from exc


def _parse_parameter(path: pathlib.Path, index: int, raw: object) -> Parameter:
    if not isinstance(raw, dict):
        raise RecipeError(
            f"{path}: parameters[{index}] must be a YAML mapping, got {type(raw).__name__}"
        )
    unknown = set(raw.keys()) - _PARAMETER_KEYS
    if unknown:
        raise RecipeError(
            f"{path}: parameters[{index}] has unknown keys {sorted(unknown)}; "
            f"expected subset of {sorted(_PARAMETER_KEYS)}"
        )
    name_obj = raw.get("name")
    if not isinstance(name_obj, str) or not _VALID_NAME_RE.fullmatch(name_obj):
        raise RecipeError(
            f"{path}: parameters[{index}].name must match [a-z0-9][a-z0-9_-]*; got {name_obj!r}"
        )
    type_obj = raw.get("type", "string")
    if type_obj not in PARAMETER_TYPES:
        raise RecipeError(
            f"{path}: parameters[{index}].type must be one of "
            f"{sorted(PARAMETER_TYPES)}; got {type_obj!r}"
        )
    requirement_obj = raw.get("requirement", "required")
    if requirement_obj not in PARAMETER_REQUIREMENTS:
        raise RecipeError(
            f"{path}: parameters[{index}].requirement must be one of "
            f"{sorted(PARAMETER_REQUIREMENTS)}; got {requirement_obj!r}"
        )
    description_obj = raw.get("description", "")
    if not isinstance(description_obj, str):
        raise RecipeError(f"{path}: parameters[{index}].description must be a string")

    options: tuple[Any, ...] | None = None
    if type_obj == "select":
        options_obj = raw.get("options")
        if not isinstance(options_obj, list) or not options_obj:
            raise RecipeError(
                f"{path}: parameters[{index}] type=select needs a non-empty 'options' list"
            )
        options = tuple(options_obj)
    elif "options" in raw:
        raise RecipeError(f"{path}: parameters[{index}] type={type_obj!r} cannot carry 'options'")

    default = _coerce_default(path, name_obj, type_obj, raw.get("default"), options)
    return Parameter(
        name=name_obj,
        type=type_obj,
        requirement=requirement_obj,
        default=default,
        description=description_obj.strip(),
        options=options,
    )


def _parse_settings(path: pathlib.Path, raw: object) -> RecipeSettings:
    if raw is None:
        return RecipeSettings()
    if not isinstance(raw, dict):
        raise RecipeError(f"{path}: 'settings' must be a YAML mapping")
    unknown = set(raw.keys()) - _SETTINGS_KEYS
    if unknown:
        raise RecipeError(
            f"{path}: 'settings' has unknown keys {sorted(unknown)}; "
            f"expected subset of {sorted(_SETTINGS_KEYS)}"
        )
    model_obj = raw.get("model")
    if model_obj is not None and (not isinstance(model_obj, str) or not model_obj.strip()):
        raise RecipeError(f"{path}: 'settings.model' must be a non-empty string or null")
    temp_obj = raw.get("temperature")
    if temp_obj is not None and (
        isinstance(temp_obj, bool) or not isinstance(temp_obj, (int, float))
    ):
        raise RecipeError(f"{path}: 'settings.temperature' must be a number or null")
    if temp_obj is not None and not 0 <= float(temp_obj) <= 2:
        raise RecipeError(f"{path}: 'settings.temperature' must be in [0, 2]; got {temp_obj}")
    turns_obj = raw.get("max_turns")
    if turns_obj is not None and (isinstance(turns_obj, bool) or not isinstance(turns_obj, int)):
        raise RecipeError(f"{path}: 'settings.max_turns' must be a positive integer or null")
    if turns_obj is not None and turns_obj <= 0:
        raise RecipeError(f"{path}: 'settings.max_turns' must be > 0; got {turns_obj}")
    return RecipeSettings(
        model=model_obj.strip() if isinstance(model_obj, str) else None,
        temperature=float(temp_obj) if temp_obj is not None else None,
        max_turns=turns_obj,
    )


def _parse_extensions(path: pathlib.Path, raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise RecipeError(f"{path}: 'extensions' must be a YAML list")
    parsed: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str) or not item.strip():
            raise RecipeError(f"{path}: extensions[{index}] must be a non-empty string")
        parsed.append(item.strip())
    return tuple(parsed)


def _parse_response(path: pathlib.Path, raw: object) -> RecipeResponseSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise RecipeError(f"{path}: 'response' must be a YAML mapping")
    unknown = set(raw.keys()) - _RESPONSE_KEYS
    if unknown:
        raise RecipeError(
            f"{path}: 'response' has unknown keys {sorted(unknown)}; "
            f"expected subset of {sorted(_RESPONSE_KEYS)}"
        )
    schema_obj = raw.get("json_schema")
    name_obj = raw.get("schema_name")
    if schema_obj is None and name_obj is None:
        raise RecipeError(
            f"{path}: 'response' must set exactly one of 'json_schema' or 'schema_name'"
        )
    if schema_obj is not None and name_obj is not None:
        raise RecipeError(
            f"{path}: 'response' must set only one of 'json_schema' or 'schema_name'"
        )
    if schema_obj is not None and not isinstance(schema_obj, dict):
        raise RecipeError(f"{path}: 'response.json_schema' must be a YAML mapping")
    if name_obj is not None:
        if not isinstance(name_obj, str):
            raise RecipeError(f"{path}: 'response.schema_name' must be a string")
        if name_obj not in llm_schemas.BUILTIN_SCHEMAS:
            raise RecipeError(
                f"{path}: 'response.schema_name' {name_obj!r} is not a built-in; "
                f"available: {sorted(llm_schemas.BUILTIN_SCHEMAS)}"
            )
    return RecipeResponseSpec(schema=schema_obj, schema_name=name_obj)


def _parse_sub_recipes(path: pathlib.Path, raw: object) -> tuple[SubRecipeRef, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise RecipeError(f"{path}: 'sub_recipes' must be a YAML list")
    parsed: list[SubRecipeRef] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise RecipeError(f"{path}: sub_recipes[{index}] must be a YAML mapping")
        unknown = set(item.keys()) - _SUB_RECIPE_KEYS
        if unknown:
            raise RecipeError(
                f"{path}: sub_recipes[{index}] has unknown keys {sorted(unknown)}; "
                f"expected subset of {sorted(_SUB_RECIPE_KEYS)}"
            )
        name_obj = item.get("name")
        if not isinstance(name_obj, str) or not _VALID_NAME_RE.fullmatch(name_obj):
            raise RecipeError(
                f"{path}: sub_recipes[{index}].name must match "
                f"[a-z0-9][a-z0-9_-]*; got {name_obj!r}"
            )
        values_obj = item.get("values", {})
        if not isinstance(values_obj, dict):
            raise RecipeError(f"{path}: sub_recipes[{index}].values must be a YAML mapping")
        seq_obj = item.get("sequential_when_repeated", False)
        if not isinstance(seq_obj, bool):
            raise RecipeError(
                f"{path}: sub_recipes[{index}].sequential_when_repeated must be a boolean"
            )
        parsed.append(
            SubRecipeRef(
                name=name_obj,
                values=dict(values_obj),
                sequential_when_repeated=seq_obj,
            )
        )
    return tuple(parsed)


def load_recipe_file(path: pathlib.Path) -> Recipe:
    """Load one recipe file into a :class:`Recipe`.

    Raises :class:`RecipeError` with a path-prefixed message on any
    problem.  Callers that prefer "log + skip" semantics should catch
    and log rather than letting a malformed file halt the session.
    """
    name = _name_from_filename(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RecipeError(f"{path}: read failed: {exc}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise RecipeError(f"{path}: invalid YAML: {exc}") from exc
    if data is None:
        raise RecipeError(f"{path}: recipe file is empty")
    if not isinstance(data, dict):
        raise RecipeError(f"{path}: recipe must be a YAML mapping at the top level")

    unknown = set(data.keys()) - _TOP_LEVEL_KEYS
    if unknown:
        raise RecipeError(
            f"{path}: unknown top-level keys {sorted(unknown)}; "
            f"expected subset of {sorted(_TOP_LEVEL_KEYS)}"
        )

    title = _require_string(path, "title", data.get("title"))
    description = _require_string(path, "description", data.get("description"))
    instructions_obj = data.get(_INSTRUCTIONS_KEY)
    if not isinstance(instructions_obj, str) or not instructions_obj.strip():
        raise RecipeError(f"{path}: {_INSTRUCTIONS_KEY!r} must be a non-empty string")
    instructions = instructions_obj.strip("\n")

    parameters_obj = data.get("parameters", [])
    if not isinstance(parameters_obj, list):
        raise RecipeError(f"{path}: 'parameters' must be a YAML list")
    seen: set[str] = set()
    parsed_parameters: list[Parameter] = []
    for index, item in enumerate(parameters_obj):
        param = _parse_parameter(path, index, item)
        if param.name in seen:
            raise RecipeError(f"{path}: parameter {param.name!r} declared twice")
        seen.add(param.name)
        parsed_parameters.append(param)

    settings = _parse_settings(path, data.get("settings"))
    extensions = _parse_extensions(path, data.get("extensions"))
    response = _parse_response(path, data.get("response"))
    sub_recipes = _parse_sub_recipes(path, data.get("sub_recipes"))

    try:
        retry_config = parse_retry_config(data.get("retry"))
    except RetryConfigError as exc:
        raise RecipeError(f"{path}: {exc}") from exc

    version_obj = data.get("version", "1")
    if not isinstance(version_obj, (str, int)):
        raise RecipeError(f"{path}: 'version' must be a string or integer")
    version = str(version_obj)

    return Recipe(
        name=name,
        title=title,
        description=description,
        parameters=tuple(parsed_parameters),
        instructions=instructions,
        settings=settings,
        extensions=extensions,
        response=response,
        retry=retry_config,
        sub_recipes=sub_recipes,
        source=path,
        version=version,
    )


def _collect_recipes(directory: pathlib.Path) -> dict[str, Recipe]:
    """Walk *directory* for ``*.yaml`` / ``*.yml`` and load each one.

    Malformed files log a warning and are skipped — one bad recipe
    shouldn't break the others.  Mirrors
    :func:`cantrip.agent.commands.custom._collect_commands`.
    """
    found: dict[str, Recipe] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in {".yaml", ".yml"} or not path.is_file():
            continue
        try:
            recipe = load_recipe_file(path)
        except RecipeError as exc:
            log.warning("Skipping malformed recipe file %s: %s", path, exc)
            continue
        found[recipe.name] = recipe
    return found


def discover_recipes(
    *,
    charm_path: pathlib.Path | None = None,
    user_config_dir: pathlib.Path | None = None,
    bundled_dir: pathlib.Path | None = None,
) -> list[Recipe]:
    """Discover recipes from bundled, user, and repo directories.

    Returns a list in ``name`` order.  Precedence (later wins on
    name collision): bundled built-ins < user (``~/.config/cantrip/
    recipes/``) < repo (``<charm>/.cantrip-recipes/``).  This mirrors
    :mod:`cantrip.agent.commands.custom` for slash commands and lets
    a user override a built-in just by dropping a same-named YAML
    file into either personal or repo scope.  ``user_config_dir``
    defaults to ``~/.config/cantrip/`` and ``bundled_dir`` defaults
    to :data:`BUNDLED_RECIPES_DIR` — override for tests.
    """
    if user_config_dir is None:
        user_config_dir = pathlib.Path.home() / ".config" / "cantrip"
    if bundled_dir is None:
        bundled_dir = BUNDLED_RECIPES_DIR
    user_dir = user_config_dir / "recipes"
    merged: dict[str, Recipe] = dict(_collect_recipes(bundled_dir))
    merged.update(_collect_recipes(user_dir))
    if charm_path is not None:
        repo_dir = charm_path / REPO_RECIPES_DIR
        merged.update(_collect_recipes(repo_dir))
    return sorted(merged.values(), key=lambda r: r.name)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class RecipeRegistry:
    """Immutable view over the loaded recipes.

    Mirrors :class:`cantrip.agent.commands.custom.CustomCommandRegistry`
    so surfaces (TUI autocomplete, Web UI, CLI) can share a single
    read-only object without worrying about underlying list mutation.
    """

    recipes: tuple[Recipe, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        """Names of every loaded recipe, in catalogue order."""
        return tuple(r.name for r in self.recipes)

    def get(self, name: str) -> Recipe | None:
        """Look up a recipe by name; returns ``None`` on miss."""
        for recipe in self.recipes:
            if recipe.name == name:
                return recipe
        return None


# ---------------------------------------------------------------------------
# Parameter binding
# ---------------------------------------------------------------------------


#: Type used by the dispatcher when a ``prompted`` parameter needs
#: input from the user.  Returns ``None`` if the user declined to
#: provide a value, in which case the binder treats the parameter as
#: missing (raises :class:`RecipeError` for ``required`` semantics).
PromptCallback = Callable[[Parameter], Awaitable[str | None]]


def _coerce_value(type_: str, value: object, *, options: tuple[Any, ...] | None) -> Any:
    """Coerce a string or scalar into the parameter's Python type."""
    if type_ == "string":
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float, bool)):
            return str(value)
        raise RecipeError(f"expected string, got {type(value).__name__}")
    if type_ == "number":
        if isinstance(value, bool):
            raise RecipeError("expected number, got boolean")
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError as exc:
                raise RecipeError(f"expected number, got {value!r}") from exc
        raise RecipeError(f"expected number, got {type(value).__name__}")
    if type_ == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.lower()
            if lowered in {"true", "yes", "1", "on"}:
                return True
            if lowered in {"false", "no", "0", "off"}:
                return False
            raise RecipeError(f"expected boolean (true/false/yes/no/1/0), got {value!r}")
        raise RecipeError(f"expected boolean, got {type(value).__name__}")
    if type_ == "date":
        if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
            return value
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, str):
            try:
                return datetime.date.fromisoformat(value)
            except ValueError as exc:
                raise RecipeError(f"expected ISO 8601 date (YYYY-MM-DD), got {value!r}") from exc
        raise RecipeError(f"expected date, got {type(value).__name__}")
    if type_ == "file":
        if not isinstance(value, str) or not value:
            raise RecipeError(f"expected file path string, got {value!r}")
        return value
    if type_ == "select":
        assert options is not None  # invariant from loader
        # Allow either the option as-is or its string form so YAML
        # ``options: [1, 2, 3]`` and CLI ``size=2`` both bind.
        for option in options:
            if value == option or str(value) == str(option):
                return option
        raise RecipeError(f"expected one of {list(options)!r}, got {value!r}")
    raise RecipeError(f"unhandled parameter type {type_!r}")  # unreachable


def _parse_argv(args: str) -> dict[str, str]:
    """Parse ``key=value …`` argv into a ``{name: raw_value}`` dict.

    Tokens without ``=`` raise :class:`RecipeError` so a typo doesn't
    silently bind nothing.  Quoted values survive intact via
    :func:`shlex.split` (so ``msg="hello world"`` reaches the binder
    as a single value), and unquoted whitespace splits as expected.
    """
    if not args.strip():
        return {}
    try:
        tokens = shlex.split(args)
    except ValueError as exc:
        raise RecipeError(f"could not parse arguments: {exc}") from exc
    bound: dict[str, str] = {}
    for token in tokens:
        key, _, value = token.partition("=")
        if not _ or not key:
            raise RecipeError(f"argument {token!r} is not in 'key=value' form")
        if key in bound:
            raise RecipeError(f"argument {key!r} given twice")
        bound[key] = value
    return bound


async def bind_parameters(
    recipe: Recipe,
    args: str,
    *,
    prompt_callback: PromptCallback | None = None,
) -> dict[str, Any]:
    """Bind ``key=value`` argv against *recipe*'s declared parameters.

    Returns a mapping of parameter name to coerced Python value.
    Behaviour by requirement:

    * ``required`` — must appear in argv (or carry a default);
      :class:`RecipeError` otherwise.
    * ``optional`` — defaults silently when absent.
    * ``prompted`` — when absent, calls *prompt_callback* (if given)
      and binds the answer; treats a ``None`` callback or refusal
      the same as ``required``-missing (so an unwired interactive
      surface fails loudly rather than silently dropping the param).
    """
    raw_argv = _parse_argv(args)
    return await _bind_values(recipe, raw_argv, prompt_callback=prompt_callback)


async def bind_parameter_values(
    recipe: Recipe,
    values: Mapping[str, Any],
    *,
    prompt_callback: PromptCallback | None = None,
) -> dict[str, Any]:
    """Bind a YAML / dict-shaped values map against declared parameters.

    Same semantics as :func:`bind_parameters` but the inputs come from
    a pre-parsed mapping (e.g.  :pyattr:`SubRecipeRef.values`) instead
    of an argv string.  Coercion still runs so YAML literals that
    don't already match the parameter type (a ``string`` in place of a
    ``number``, or a stringified date) bind correctly.
    """
    return await _bind_values(recipe, values, prompt_callback=prompt_callback)


async def _bind_values(
    recipe: Recipe,
    raw_values: Mapping[str, Any],
    *,
    prompt_callback: PromptCallback | None = None,
) -> dict[str, Any]:
    """Shared binder used by both argv and pre-parsed-mapping callers."""
    declared = {p.name: p for p in recipe.parameters}
    unknown = set(raw_values.keys()) - set(declared.keys())
    if unknown:
        raise RecipeError(
            f"unknown parameters {sorted(unknown)}; "
            f"recipe accepts {sorted(declared.keys()) or ['(none)']}"
        )
    bound: dict[str, Any] = {}
    for parameter in recipe.parameters:
        if parameter.name in raw_values:
            try:
                bound[parameter.name] = _coerce_value(
                    parameter.type,
                    raw_values[parameter.name],
                    options=parameter.options,
                )
            except RecipeError as exc:
                raise RecipeError(f"parameter {parameter.name!r}: {exc}") from exc
            continue

        # Not in inputs — fall through to default / prompt / error.
        if parameter.default is not None:
            bound[parameter.name] = parameter.default
            continue

        if parameter.requirement == "optional":
            bound[parameter.name] = None
            continue

        if parameter.requirement == "prompted" and prompt_callback is not None:
            answer = await prompt_callback(parameter)
            if answer is None:
                raise RecipeError(f"parameter {parameter.name!r} declined at prompt")
            try:
                bound[parameter.name] = _coerce_value(
                    parameter.type, answer, options=parameter.options
                )
            except RecipeError as exc:
                raise RecipeError(f"parameter {parameter.name!r} (prompted): {exc}") from exc
            continue

        # required (or prompted with no callback) and no default
        raise RecipeError(f"missing required parameter {parameter.name!r} (type={parameter.type})")
    return bound


# ---------------------------------------------------------------------------
# Jinja rendering
# ---------------------------------------------------------------------------


_JINJA_ENV: jinja2.sandbox.SandboxedEnvironment | None = None


def _get_env() -> jinja2.sandbox.SandboxedEnvironment:
    """Return the recipe-instructions Jinja2 environment.

    Sandboxed because recipes come from the repo (or the user's home)
    and may be authored by someone other than the operator running
    the agent — the sandbox blocks access to attribute paths that
    leak file IO / module internals.  ``StrictUndefined`` so a
    missing parameter raises at render rather than silently producing
    empty output.
    """
    global _JINJA_ENV
    if _JINJA_ENV is None:
        _JINJA_ENV = jinja2.sandbox.SandboxedEnvironment(
            keep_trailing_newline=True,
            undefined=jinja2.StrictUndefined,
            autoescape=False,
        )
    return _JINJA_ENV


def _scrub(value: Any) -> Any:
    """Strip Jinja syntax characters from string values.

    Numbers, booleans, dates, lists, and dicts pass through unchanged
    — they round-trip through Jinja safely because the renderer
    coerces them to ``str`` only at the leaves.  String parameters are
    the smuggling channel, so they get the same scrub treatment
    :mod:`cantrip.agent.prompts.system` applies to untrusted inputs
    in the system prompt.
    """
    if isinstance(value, str):
        return _JINJA_SYNTAX.sub("", value)
    return value


def render_instructions(
    recipe: Recipe,
    bound: Mapping[str, Any],
    *,
    recipe_dir: pathlib.Path | None = None,
) -> str:
    """Render *recipe*'s instructions template against *bound*.

    The template scope receives every bound parameter by name plus
    ``recipe_dir`` (the directory the recipe file lives in, useful
    for ``{% include %}``-style references in a follow-up).  String
    parameter values are scrubbed of Jinja syntax characters so a
    user-supplied string cannot smuggle template logic into the
    rendered prompt.

    Raises :class:`RecipeError` on any Jinja error (StrictUndefined,
    syntax error, sandbox block) with the recipe name prefixed so
    the dispatcher can surface a clear failure.
    """
    env = _get_env()
    try:
        template = env.from_string(recipe.instructions)
    except jinja2.TemplateError as exc:
        raise RecipeError(f"recipe {recipe.name!r} instructions failed to compile: {exc}") from exc

    scope: dict[str, Any] = {name: _scrub(value) for name, value in bound.items()}
    if recipe_dir is not None:
        scope["recipe_dir"] = str(recipe_dir)
    elif recipe.source is not None:
        scope["recipe_dir"] = str(recipe.source.parent)
    else:
        scope["recipe_dir"] = ""

    try:
        return template.render(scope)
    except jinja2.TemplateError as exc:
        raise RecipeError(f"recipe {recipe.name!r} instructions failed to render: {exc}") from exc


__all__ = [
    "BUNDLED_RECIPES_DIR",
    "PARAMETER_REQUIREMENTS",
    "PARAMETER_TYPES",
    "REPO_RECIPES_DIR",
    "USER_CONFIG_RECIPES_DIR",
    "Parameter",
    "PromptCallback",
    "Recipe",
    "RecipeError",
    "RecipeRegistry",
    "RecipeResponseSpec",
    "RecipeSettings",
    "SubRecipeRef",
    "bind_parameter_values",
    "bind_parameters",
    "discover_recipes",
    "load_recipe_file",
    "render_instructions",
]
