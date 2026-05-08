"""Tests for parameterised, retryable recipes (Phase 73.1)."""

from __future__ import annotations

import datetime
import pathlib
import textwrap

import pytest

from cantrip.agent import recipes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(tmp_path: pathlib.Path, name: str, body: str) -> pathlib.Path:
    """Drop *body* into ``<tmp_path>/<name>.yaml`` and return the path."""
    path = tmp_path / f"{name}.yaml"
    path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return path


_MINIMAL_RECIPE = """
    title: Minimal
    description: Minimal recipe with no parameters.
    instructions: |
      Do the thing.
"""


# ---------------------------------------------------------------------------
# Loader — happy paths
# ---------------------------------------------------------------------------


class TestLoaderHappy:
    def test_minimal(self, tmp_path):
        path = _write(tmp_path, "minimal", _MINIMAL_RECIPE)
        recipe = recipes.load_recipe_file(path)
        assert recipe.name == "minimal"
        assert recipe.title == "Minimal"
        assert recipe.description.startswith("Minimal")
        assert recipe.parameters == ()
        assert recipe.settings.is_default()
        assert recipe.extensions == ()
        assert recipe.response is None
        assert recipe.retry is None
        assert recipe.sub_recipes == ()
        assert recipe.source == path
        assert recipe.version == "1"

    def test_full_round_trip(self, tmp_path):
        path = _write(
            tmp_path,
            "charm-cos-add",
            """
            version: 1
            title: Add COS to a charm
            description: Wires Prometheus, Grafana, and Loki integrations into an existing charm.
            parameters:
              - name: charm_name
                type: string
                requirement: required
                description: Charm directory under cwd.
              - name: scrape_path
                type: string
                requirement: optional
                default: /metrics
              - name: scale
                type: number
                default: 1
              - name: enable_logs
                type: boolean
                default: true
              - name: cutover
                type: date
                default: 2026-12-01
              - name: tier
                type: select
                options: [free, pro, enterprise]
                default: pro
            settings:
              model: claude-opus-4-7
              temperature: 0.4
              max_turns: 25
            extensions:
              - mcp:charmhub
              - tool:juju_status
            instructions: |
              Add COS to {{ charm_name }}.
              Tier: {{ tier }}; scrape: {{ scrape_path }}.
            response:
              schema_name: check_result
            retry:
              max_retries: 2
              timeout_seconds: 600
              checks:
                - type: shell
                  command: make check
            """,
        )
        recipe = recipes.load_recipe_file(path)
        assert recipe.name == "charm-cos-add"
        assert recipe.version == "1"
        assert len(recipe.parameters) == 6
        # Parameter coercion at the loader maps default literals to the
        # parameter's Python type — number floats, boolean stays bool,
        # date parses to datetime.date, select rejects non-options.
        kinds = {p.name: p for p in recipe.parameters}
        assert kinds["scrape_path"].default == "/metrics"
        assert kinds["scale"].default == 1.0
        assert isinstance(kinds["scale"].default, float)
        assert kinds["enable_logs"].default is True
        assert kinds["cutover"].default == datetime.date(2026, 12, 1)
        assert kinds["tier"].default == "pro"
        assert kinds["tier"].options == ("free", "pro", "enterprise")
        assert recipe.settings.model == "claude-opus-4-7"
        assert recipe.settings.temperature == pytest.approx(0.4)
        assert recipe.settings.max_turns == 25
        assert recipe.extensions == ("mcp:charmhub", "tool:juju_status")
        assert recipe.response is not None
        assert recipe.response.schema_name == "check_result"
        assert recipe.retry is not None
        assert recipe.retry.max_retries == 2
        assert "Add COS" in recipe.instructions

    def test_inline_response_schema(self, tmp_path):
        path = _write(
            tmp_path,
            "inline",
            """
            title: Inline schema
            description: Tests inline JSON Schema in the response block.
            instructions: |
              do it
            response:
              json_schema:
                type: object
                properties:
                  status: {type: string}
                required: [status]
            """,
        )
        recipe = recipes.load_recipe_file(path)
        assert recipe.response is not None
        assert recipe.response.schema_name is None
        assert recipe.response.schema is not None
        assert recipe.response.resolved_schema()["properties"]["status"] == {"type": "string"}


# ---------------------------------------------------------------------------
# Loader — failure paths
# ---------------------------------------------------------------------------


class TestLoaderErrors:
    def test_invalid_filename(self, tmp_path):
        # Leading hyphen fails the [a-z0-9] anchor.  Uppercase filenames
        # are silently lowered (matches custom.py's convention), so a
        # name with a true-bad shape is the right thing to test.
        path = tmp_path / "-leading-hyphen.yaml"
        path.write_text(_MINIMAL_RECIPE, encoding="utf-8")
        with pytest.raises(recipes.RecipeError, match="invalid recipe name"):
            recipes.load_recipe_file(path)

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        with pytest.raises(recipes.RecipeError, match="recipe file is empty"):
            recipes.load_recipe_file(path)

    def test_top_level_must_be_mapping(self, tmp_path):
        path = _write(tmp_path, "list", "- a\n- b\n")
        with pytest.raises(recipes.RecipeError, match="must be a YAML mapping"):
            recipes.load_recipe_file(path)

    def test_invalid_yaml(self, tmp_path):
        path = tmp_path / "broken.yaml"
        path.write_text("title: 'unterminated", encoding="utf-8")
        with pytest.raises(recipes.RecipeError, match="invalid YAML"):
            recipes.load_recipe_file(path)

    def test_unknown_top_level_key(self, tmp_path):
        path = _write(
            tmp_path,
            "unknown",
            """
            title: x
            description: y
            instructions: z
            unsupported_key: hello
            """,
        )
        with pytest.raises(recipes.RecipeError, match="unknown top-level keys"):
            recipes.load_recipe_file(path)

    def test_missing_title(self, tmp_path):
        path = _write(
            tmp_path,
            "no-title",
            """
            description: x
            instructions: y
            """,
        )
        with pytest.raises(recipes.RecipeError, match="'title' must be a non-empty string"):
            recipes.load_recipe_file(path)

    def test_missing_instructions(self, tmp_path):
        path = _write(
            tmp_path,
            "no-instructions",
            """
            title: x
            description: y
            """,
        )
        with pytest.raises(recipes.RecipeError, match="'instructions' must be"):
            recipes.load_recipe_file(path)

    def test_blank_instructions(self, tmp_path):
        path = _write(
            tmp_path,
            "blank",
            """
            title: x
            description: y
            instructions: ""
            """,
        )
        with pytest.raises(recipes.RecipeError, match="'instructions' must be"):
            recipes.load_recipe_file(path)

    def test_parameters_must_be_list(self, tmp_path):
        path = _write(
            tmp_path,
            "p-not-list",
            """
            title: x
            description: y
            instructions: z
            parameters:
              not_a_list: yes
            """,
        )
        with pytest.raises(recipes.RecipeError, match="'parameters' must be a YAML list"):
            recipes.load_recipe_file(path)

    def test_parameter_type_validated(self, tmp_path):
        path = _write(
            tmp_path,
            "bad-type",
            """
            title: x
            description: y
            instructions: z
            parameters:
              - name: p
                type: not-a-real-type
            """,
        )
        with pytest.raises(recipes.RecipeError, match="must be one of"):
            recipes.load_recipe_file(path)

    def test_parameter_unknown_key(self, tmp_path):
        path = _write(
            tmp_path,
            "bad-key",
            """
            title: x
            description: y
            instructions: z
            parameters:
              - name: p
                type: string
                bogus: 1
            """,
        )
        with pytest.raises(recipes.RecipeError, match="unknown keys"):
            recipes.load_recipe_file(path)

    def test_parameter_select_needs_options(self, tmp_path):
        path = _write(
            tmp_path,
            "no-opts",
            """
            title: x
            description: y
            instructions: z
            parameters:
              - name: tier
                type: select
            """,
        )
        with pytest.raises(recipes.RecipeError, match="needs a non-empty 'options' list"):
            recipes.load_recipe_file(path)

    def test_parameter_options_only_for_select(self, tmp_path):
        path = _write(
            tmp_path,
            "stray-opts",
            """
            title: x
            description: y
            instructions: z
            parameters:
              - name: name
                type: string
                options: [a, b]
            """,
        )
        with pytest.raises(recipes.RecipeError, match="cannot carry 'options'"):
            recipes.load_recipe_file(path)

    def test_parameter_default_coerced(self, tmp_path):
        path = _write(
            tmp_path,
            "bad-default",
            """
            title: x
            description: y
            instructions: z
            parameters:
              - name: count
                type: number
                default: not-a-number
            """,
        )
        with pytest.raises(recipes.RecipeError, match="default 'not-a-number' invalid"):
            recipes.load_recipe_file(path)

    def test_duplicate_parameter_name(self, tmp_path):
        path = _write(
            tmp_path,
            "dupe",
            """
            title: x
            description: y
            instructions: z
            parameters:
              - name: x
                type: string
              - name: x
                type: number
            """,
        )
        with pytest.raises(recipes.RecipeError, match="declared twice"):
            recipes.load_recipe_file(path)

    def test_settings_temperature_range(self, tmp_path):
        path = _write(
            tmp_path,
            "bad-temp",
            """
            title: x
            description: y
            instructions: z
            settings:
              temperature: 7
            """,
        )
        with pytest.raises(recipes.RecipeError, match="temperature' must be in"):
            recipes.load_recipe_file(path)

    def test_settings_max_turns_positive(self, tmp_path):
        path = _write(
            tmp_path,
            "bad-turns",
            """
            title: x
            description: y
            instructions: z
            settings:
              max_turns: 0
            """,
        )
        with pytest.raises(recipes.RecipeError, match="max_turns' must be > 0"):
            recipes.load_recipe_file(path)

    def test_response_requires_one_of(self, tmp_path):
        path = _write(
            tmp_path,
            "no-schema",
            """
            title: x
            description: y
            instructions: z
            response: {}
            """,
        )
        with pytest.raises(recipes.RecipeError, match="exactly one of"):
            recipes.load_recipe_file(path)

    def test_response_rejects_both(self, tmp_path):
        path = _write(
            tmp_path,
            "two-schemas",
            """
            title: x
            description: y
            instructions: z
            response:
              json_schema: {type: object}
              schema_name: check_result
            """,
        )
        with pytest.raises(recipes.RecipeError, match="only one of"):
            recipes.load_recipe_file(path)

    def test_response_unknown_built_in(self, tmp_path):
        path = _write(
            tmp_path,
            "unknown-built-in",
            """
            title: x
            description: y
            instructions: z
            response:
              schema_name: not_a_real_one
            """,
        )
        with pytest.raises(recipes.RecipeError, match="not a built-in"):
            recipes.load_recipe_file(path)

    def test_extensions_must_be_strings(self, tmp_path):
        path = _write(
            tmp_path,
            "bad-ext",
            """
            title: x
            description: y
            instructions: z
            extensions:
              - 1
            """,
        )
        with pytest.raises(recipes.RecipeError, match="must be a non-empty string"):
            recipes.load_recipe_file(path)

    def test_sub_recipes_require_name(self, tmp_path):
        path = _write(
            tmp_path,
            "bad-sub",
            """
            title: x
            description: y
            instructions: z
            sub_recipes:
              - {}
            """,
        )
        with pytest.raises(recipes.RecipeError, match=r"sub_recipes\[0\]\.name"):
            recipes.load_recipe_file(path)

    def test_retry_block_propagates_error(self, tmp_path):
        # ``timeout_seconds: -1`` is rejected by parse_retry_config;
        # we need the recipe loader to surface that with the path
        # prefix preserved so users don't have to guess the file.
        path = _write(
            tmp_path,
            "bad-retry",
            """
            title: x
            description: y
            instructions: z
            retry:
              timeout_seconds: -1
            """,
        )
        with pytest.raises(recipes.RecipeError, match="must be > 0"):
            recipes.load_recipe_file(path)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_repo_overrides_user(self, tmp_path):
        user_root = tmp_path / "user"
        user_dir = user_root / "recipes"
        user_dir.mkdir(parents=True)
        repo = tmp_path / "repo"
        repo_dir = repo / ".cantrip-recipes"
        repo_dir.mkdir(parents=True)
        (user_dir / "shared.yaml").write_text(
            textwrap.dedent(
                """
                title: User
                description: User-scope.
                instructions: u
                """
            ).lstrip("\n"),
            encoding="utf-8",
        )
        (repo_dir / "shared.yaml").write_text(
            textwrap.dedent(
                """
                title: Repo
                description: Repo-scope.
                instructions: r
                """
            ).lstrip("\n"),
            encoding="utf-8",
        )
        (user_dir / "personal.yaml").write_text(
            textwrap.dedent(
                """
                title: Personal
                description: Only at user scope.
                instructions: p
                """
            ).lstrip("\n"),
            encoding="utf-8",
        )
        loaded = recipes.discover_recipes(charm_path=repo, user_config_dir=user_root)
        names = {r.name: r for r in loaded}
        # Repo wins for the shared name; personal still appears.
        assert names["shared"].title == "Repo"
        assert names["personal"].title == "Personal"

    def test_malformed_file_skipped(self, tmp_path, caplog):
        repo = tmp_path / "repo"
        repo_dir = repo / ".cantrip-recipes"
        repo_dir.mkdir(parents=True)
        (repo_dir / "ok.yaml").write_text(_MINIMAL_RECIPE.lstrip("\n"), encoding="utf-8")
        # Missing description — loader rejects, discover_recipes logs and skips.
        (repo_dir / "broken.yaml").write_text(
            textwrap.dedent(
                """
                title: x
                instructions: z
                """
            ).lstrip("\n"),
            encoding="utf-8",
        )
        user_root = tmp_path / "user"
        with caplog.at_level("WARNING"):
            loaded = recipes.discover_recipes(charm_path=repo, user_config_dir=user_root)
        assert [r.name for r in loaded] == ["ok"]
        assert any("broken.yaml" in m for m in caplog.messages)

    def test_yml_extension_also_loaded(self, tmp_path):
        repo = tmp_path / "repo"
        repo_dir = repo / ".cantrip-recipes"
        repo_dir.mkdir(parents=True)
        (repo_dir / "alt.yml").write_text(_MINIMAL_RECIPE.lstrip("\n"), encoding="utf-8")
        loaded = recipes.discover_recipes(charm_path=repo, user_config_dir=tmp_path / "u")
        assert [r.name for r in loaded] == ["alt"]

    def test_missing_dirs_return_empty(self, tmp_path):
        # Neither charm_path nor user_config_dir exist on disk — caller
        # gets an empty list instead of an exception.
        loaded = recipes.discover_recipes(
            charm_path=tmp_path / "absent",
            user_config_dir=tmp_path / "also-absent",
        )
        assert loaded == []


# ---------------------------------------------------------------------------
# Parameter binding
# ---------------------------------------------------------------------------


def _recipe_with_params(*params: recipes.Parameter) -> recipes.Recipe:
    return recipes.Recipe(
        name="t",
        title="T",
        description="t",
        parameters=tuple(params),
        instructions="ignored",
    )


class TestBindParameters:
    @pytest.mark.asyncio
    async def test_string(self):
        recipe = _recipe_with_params(recipes.Parameter("name", "string"))
        bound = await recipes.bind_parameters(recipe, "name=ntfy")
        assert bound == {"name": "ntfy"}

    @pytest.mark.asyncio
    async def test_number(self):
        recipe = _recipe_with_params(recipes.Parameter("count", "number"))
        bound = await recipes.bind_parameters(recipe, "count=3")
        assert bound == {"count": 3.0}

    @pytest.mark.asyncio
    async def test_boolean_truthy_strings(self):
        recipe = _recipe_with_params(recipes.Parameter("flag", "boolean"))
        for variant in ("true", "yes", "1", "on", "True"):
            bound = await recipes.bind_parameters(recipe, f"flag={variant}")
            assert bound == {"flag": True}

    @pytest.mark.asyncio
    async def test_boolean_falsy_strings(self):
        recipe = _recipe_with_params(recipes.Parameter("flag", "boolean"))
        for variant in ("false", "no", "0", "off", "False"):
            bound = await recipes.bind_parameters(recipe, f"flag={variant}")
            assert bound == {"flag": False}

    @pytest.mark.asyncio
    async def test_boolean_nonsense_rejected(self):
        recipe = _recipe_with_params(recipes.Parameter("flag", "boolean"))
        with pytest.raises(recipes.RecipeError, match="expected boolean"):
            await recipes.bind_parameters(recipe, "flag=maybe")

    @pytest.mark.asyncio
    async def test_date(self):
        recipe = _recipe_with_params(recipes.Parameter("when", "date"))
        bound = await recipes.bind_parameters(recipe, "when=2026-05-09")
        assert bound == {"when": datetime.date(2026, 5, 9)}

    @pytest.mark.asyncio
    async def test_date_invalid(self):
        recipe = _recipe_with_params(recipes.Parameter("when", "date"))
        with pytest.raises(recipes.RecipeError, match="ISO 8601"):
            await recipes.bind_parameters(recipe, "when=tomorrow")

    @pytest.mark.asyncio
    async def test_file_passthrough(self):
        recipe = _recipe_with_params(recipes.Parameter("source", "file"))
        bound = await recipes.bind_parameters(recipe, "source=src/charm.py")
        assert bound == {"source": "src/charm.py"}

    @pytest.mark.asyncio
    async def test_select_accepts_option(self):
        recipe = _recipe_with_params(recipes.Parameter("tier", "select", options=("free", "pro")))
        bound = await recipes.bind_parameters(recipe, "tier=pro")
        assert bound == {"tier": "pro"}

    @pytest.mark.asyncio
    async def test_select_rejects_non_option(self):
        recipe = _recipe_with_params(recipes.Parameter("tier", "select", options=("free", "pro")))
        with pytest.raises(recipes.RecipeError, match=r"expected one of"):
            await recipes.bind_parameters(recipe, "tier=enterprise")

    @pytest.mark.asyncio
    async def test_required_missing(self):
        recipe = _recipe_with_params(recipes.Parameter("name", "string"))
        with pytest.raises(recipes.RecipeError, match="missing required parameter"):
            await recipes.bind_parameters(recipe, "")

    @pytest.mark.asyncio
    async def test_optional_missing_binds_none(self):
        recipe = _recipe_with_params(recipes.Parameter("note", "string", requirement="optional"))
        bound = await recipes.bind_parameters(recipe, "")
        assert bound == {"note": None}

    @pytest.mark.asyncio
    async def test_default_used_when_missing(self):
        recipe = _recipe_with_params(recipes.Parameter("port", "number", default=80.0))
        bound = await recipes.bind_parameters(recipe, "")
        assert bound == {"port": 80.0}

    @pytest.mark.asyncio
    async def test_argv_overrides_default(self):
        recipe = _recipe_with_params(recipes.Parameter("port", "number", default=80.0))
        bound = await recipes.bind_parameters(recipe, "port=8080")
        assert bound == {"port": 8080.0}

    @pytest.mark.asyncio
    async def test_prompted_uses_callback(self):
        recipe = _recipe_with_params(
            recipes.Parameter("charm_name", "string", requirement="prompted")
        )
        seen: list[str] = []

        async def callback(parameter):
            seen.append(parameter.name)
            return "ntfy-operator"

        bound = await recipes.bind_parameters(recipe, "", prompt_callback=callback)
        assert bound == {"charm_name": "ntfy-operator"}
        assert seen == ["charm_name"]

    @pytest.mark.asyncio
    async def test_prompted_decline_raises(self):
        recipe = _recipe_with_params(
            recipes.Parameter("charm_name", "string", requirement="prompted")
        )

        async def callback(_parameter):
            return None

        with pytest.raises(recipes.RecipeError, match="declined at prompt"):
            await recipes.bind_parameters(recipe, "", prompt_callback=callback)

    @pytest.mark.asyncio
    async def test_prompted_no_callback_raises(self):
        recipe = _recipe_with_params(
            recipes.Parameter("charm_name", "string", requirement="prompted")
        )
        with pytest.raises(recipes.RecipeError, match="missing required parameter"):
            await recipes.bind_parameters(recipe, "")

    @pytest.mark.asyncio
    async def test_unknown_argument_rejected(self):
        recipe = _recipe_with_params(recipes.Parameter("name", "string"))
        with pytest.raises(recipes.RecipeError, match="unknown parameters"):
            await recipes.bind_parameters(recipe, "name=x stranger=y")

    @pytest.mark.asyncio
    async def test_repeated_argument_rejected(self):
        recipe = _recipe_with_params(recipes.Parameter("name", "string"))
        with pytest.raises(recipes.RecipeError, match="given twice"):
            await recipes.bind_parameters(recipe, "name=x name=y")

    @pytest.mark.asyncio
    async def test_argument_without_equals(self):
        recipe = _recipe_with_params(recipes.Parameter("name", "string"))
        with pytest.raises(recipes.RecipeError, match="not in 'key=value' form"):
            await recipes.bind_parameters(recipe, "stray")

    @pytest.mark.asyncio
    async def test_quoted_value_survives(self):
        recipe = _recipe_with_params(recipes.Parameter("note", "string"))
        bound = await recipes.bind_parameters(recipe, 'note="hello world"')
        assert bound == {"note": "hello world"}


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _render_recipe(instructions: str, **params: recipes.Parameter) -> recipes.Recipe:
    return recipes.Recipe(
        name="r",
        title="R",
        description="r",
        parameters=tuple(params.values()),
        instructions=instructions,
    )


class TestRender:
    def test_basic_substitution(self):
        recipe = _render_recipe(
            "Build {{ charm_name }} for tier {{ tier }}.",
            charm_name=recipes.Parameter("charm_name", "string"),
            tier=recipes.Parameter("tier", "string"),
        )
        out = recipes.render_instructions(recipe, {"charm_name": "ntfy", "tier": "pro"})
        assert "Build ntfy for tier pro." in out

    def test_strict_undefined_raises(self):
        recipe = _render_recipe("Hello {{ missing_param }}.")
        with pytest.raises(recipes.RecipeError, match="failed to render"):
            recipes.render_instructions(recipe, {})

    def test_recipe_dir_in_scope(self, tmp_path):
        recipe = _render_recipe("Recipe lives at {{ recipe_dir }}.")
        out = recipes.render_instructions(recipe, {}, recipe_dir=tmp_path)
        assert str(tmp_path) in out

    def test_recipe_dir_falls_back_to_source_parent(self, tmp_path):
        recipe = recipes.Recipe(
            name="r",
            title="R",
            description="r",
            parameters=(),
            instructions="At {{ recipe_dir }}.",
            source=tmp_path / "r.yaml",
        )
        out = recipes.render_instructions(recipe, {})
        assert str(tmp_path) in out

    def test_string_param_jinja_scrubbed(self):
        recipe = _render_recipe(
            "Greet {{ greeting }}.",
            greeting=recipes.Parameter("greeting", "string"),
        )
        # A user-supplied string carrying ``{{ malicious }}`` must be
        # scrubbed of Jinja syntax before reaching the renderer.  The
        # rendered output keeps the alphanumeric content but loses the
        # template control characters.
        out = recipes.render_instructions(recipe, {"greeting": "Hello {{ leakage }} world"})
        assert "leakage" in out
        assert "{" not in out
        assert "}" not in out

    def test_non_string_value_passthrough(self):
        # Numbers, dates, and booleans should not be scrubbed — the
        # scrub strips ``{`` / ``}`` / ``%``, none of which appear in
        # those repr forms anyway, and round-tripping them through
        # ``str`` must keep them readable.
        recipe = _render_recipe(
            "Port {{ port }} on {{ when }} (active={{ active }}).",
            port=recipes.Parameter("port", "number"),
            when=recipes.Parameter("when", "date"),
            active=recipes.Parameter("active", "boolean"),
        )
        out = recipes.render_instructions(
            recipe,
            {
                "port": 8080.0,
                "when": datetime.date(2026, 5, 9),
                "active": True,
            },
        )
        assert "Port 8080.0" in out
        assert "2026-05-09" in out
        assert "active=True" in out

    def test_sandbox_blocks_attribute_access(self):
        # Jinja2's SandboxedEnvironment refuses to expose ``__class__``,
        # ``__bases__``, ``__subclasses__`` etc., which is what catches
        # the classic "instance.__class__.__mro__[1].__subclasses__()"
        # escape route.  A render that touches one of those attrs
        # must raise — not return the leaked object.
        recipe = _render_recipe(
            "{{ obj.__class__ }}",
            obj=recipes.Parameter("obj", "string"),
        )
        with pytest.raises(recipes.RecipeError, match="failed to render"):
            recipes.render_instructions(recipe, {"obj": "x"})


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_get_returns_recipe(self):
        r1 = recipes.Recipe(name="a", title="A", description="a", parameters=(), instructions="x")
        r2 = recipes.Recipe(name="b", title="B", description="b", parameters=(), instructions="y")
        registry = recipes.RecipeRegistry(recipes=(r1, r2))
        assert registry.get("a") is r1
        assert registry.get("b") is r2
        assert registry.get("missing") is None

    def test_names_in_order(self):
        r1 = recipes.Recipe(name="a", title="A", description="a", parameters=(), instructions="x")
        r2 = recipes.Recipe(name="b", title="B", description="b", parameters=(), instructions="y")
        registry = recipes.RecipeRegistry(recipes=(r1, r2))
        assert registry.names == ("a", "b")
