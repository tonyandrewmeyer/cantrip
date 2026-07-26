"""Structure and verifier checks for the ``cookbook/`` recipes (Phase 55.6).

Two levels of protection:

1. **Structure drift.**  Every ``cookbook/<name>/`` directory must
   carry ``README.md``, ``prompts.md``, and ``verify.py``; the
   verifier must be syntactically valid Python and import cleanly.
   A future recipe can't land with a broken format.
2. **Output drift (per-recipe).**  For recipes that ship an
   ``expected/`` charm fixture, the verifier runs against it and
   must pass.  For recipes without ``expected/``, we build a
   hand-written in-memory fixture that matches what the recipe
   promises and verify against that.  The goal is the same: CI
   fails loudly if a recipe's shape assertions drift from reality.

Live Cantrip runs (LLM + charmcraft + juju) are **not** part of
this suite — they're too slow, too credentialled, and too
environment-dependent.  The cookbook is documentation plus a shape
contract, not an end-to-end integration harness.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import textwrap

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
COOKBOOK_ROOT = REPO_ROOT / "cookbook"


def _recipe_dirs() -> list[pathlib.Path]:
    """Return every cookbook recipe directory (child of ``cookbook/``)."""
    if not COOKBOOK_ROOT.is_dir():
        return []
    return sorted(p for p in COOKBOOK_ROOT.iterdir() if p.is_dir())


def _load_verifier(verify_path: pathlib.Path):
    """Import ``verify.py`` as a module for in-process testing."""
    spec = importlib.util.spec_from_file_location(
        f"cookbook_verify_{verify_path.parent.name}", verify_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestCookbookStructure:
    """Every recipe directory must follow the shared format."""

    def test_cookbook_root_exists(self) -> None:
        assert COOKBOOK_ROOT.is_dir(), (
            f"cookbook/ must exist at repo root; looked under {COOKBOOK_ROOT}"
        )

    def test_cookbook_has_readme(self) -> None:
        readme = COOKBOOK_ROOT / "README.md"
        assert readme.is_file(), "cookbook/README.md is required"
        body = readme.read_text(encoding="utf-8")
        # The index must at least list the recipe format and link to recipes.
        assert "Recipe format" in body
        assert "Recipes" in body

    @pytest.mark.parametrize(
        "recipe_dir",
        _recipe_dirs() or [pytest.param(None, marks=pytest.mark.skip(reason="no recipes"))],
        ids=lambda p: p.name if p else "none",
    )
    def test_recipe_has_required_files(self, recipe_dir: pathlib.Path) -> None:
        for required in ("README.md", "prompts.md", "verify.py"):
            path = recipe_dir / required
            assert path.is_file(), f"{recipe_dir.name}/{required} is required"

    @pytest.mark.parametrize(
        "recipe_dir",
        _recipe_dirs() or [pytest.param(None, marks=pytest.mark.skip(reason="no recipes"))],
        ids=lambda p: p.name if p else "none",
    )
    def test_verify_is_valid_python(self, recipe_dir: pathlib.Path) -> None:
        source = (recipe_dir / "verify.py").read_text(encoding="utf-8")
        ast.parse(source)  # Raises SyntaxError if malformed.


# Each recipe below gets its own class so failures point to the recipe.


class TestSprintCharmVerifier:
    """Verifier for ``cookbook/build-a-sprint-charm/``.

    Builds an in-process charm directory that matches the sprint-mode
    shape and exercises the verifier's happy path plus each failure
    mode.  No real charmcraft runs.
    """

    RECIPE = COOKBOOK_ROOT / "build-a-sprint-charm"

    @pytest.fixture
    def verifier(self):
        return _load_verifier(self.RECIPE / "verify.py")

    @staticmethod
    def _write_sprint_charm(
        root: pathlib.Path,
        *,
        charmcraft_yaml: str | None = None,
        requirements_txt: str = "ops>=3,<4\n",
        src_charm_py: str | None = "pass\n",
    ) -> pathlib.Path:
        """Write a minimal sprint-mode charm tree into *root*."""
        if charmcraft_yaml is None:
            charmcraft_yaml = textwrap.dedent("""\
                name: hello-sprint
                type: charm
                base: ubuntu@24.04
                platforms:
                  amd64:
                parts:
                  charm:
                    plugin: charm
                """)
        (root / "charmcraft.yaml").write_text(charmcraft_yaml, encoding="utf-8")
        (root / "requirements.txt").write_text(requirements_txt, encoding="utf-8")
        if src_charm_py is not None:
            (root / "src").mkdir()
            (root / "src" / "charm.py").write_text(src_charm_py, encoding="utf-8")
        return root

    def test_happy_path(self, tmp_path: pathlib.Path, verifier) -> None:
        charm_dir = self._write_sprint_charm(tmp_path)
        # verify() raises VerifyError on failure, returns None on success.
        verifier.verify(charm_dir)

    def test_missing_charmcraft_yaml_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        (tmp_path / "requirements.txt").write_text("ops>=3,<4\n", encoding="utf-8")
        with pytest.raises(verifier.VerifyError, match=r"charmcraft.yaml"):
            verifier.verify(tmp_path)

    def test_wrong_base_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        bad = textwrap.dedent("""\
            name: x
            type: charm
            base: ubuntu@22.04
            parts:
              charm:
                plugin: charm
            """)
        self._write_sprint_charm(tmp_path, charmcraft_yaml=bad)
        with pytest.raises(verifier.VerifyError, match=r"ubuntu@24.04"):
            verifier.verify(tmp_path)

    def test_uv_plugin_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        bad = textwrap.dedent("""\
            name: x
            type: charm
            base: ubuntu@24.04
            parts:
              charm:
                plugin: uv
            """)
        self._write_sprint_charm(tmp_path, charmcraft_yaml=bad)
        with pytest.raises(verifier.VerifyError, match=r"charm plugin|plugin: charm"):
            verifier.verify(tmp_path)

    def test_build_snaps_present_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        bad = textwrap.dedent("""\
            name: x
            type: charm
            base: ubuntu@24.04
            parts:
              charm:
                plugin: charm
                build-snaps: [rustup]
            """)
        self._write_sprint_charm(tmp_path, charmcraft_yaml=bad)
        with pytest.raises(verifier.VerifyError, match="build-snaps"):
            verifier.verify(tmp_path)

    def test_ops_tracing_in_requirements_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_sprint_charm(
            tmp_path,
            requirements_txt="ops>=3,<4\nops-tracing>=0.1\n",
        )
        with pytest.raises(verifier.VerifyError, match="ops-tracing"):
            verifier.verify(tmp_path)

    def test_extra_requirement_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_sprint_charm(
            tmp_path,
            requirements_txt="ops>=3,<4\nrequests>=2\n",
        )
        with pytest.raises(verifier.VerifyError, match="non-blank line"):
            verifier.verify(tmp_path)

    def test_missing_ops_pin_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_sprint_charm(
            tmp_path,
            requirements_txt="ops>=2\n",
        )
        with pytest.raises(verifier.VerifyError, match="ops>=3"):
            verifier.verify(tmp_path)

    def test_missing_src_charm_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_sprint_charm(tmp_path, src_charm_py=None)
        with pytest.raises(verifier.VerifyError, match=r"src/charm.py"):
            verifier.verify(tmp_path)

    def test_verifier_cli_returns_0_on_success(
        self, tmp_path: pathlib.Path, verifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        charm_dir = self._write_sprint_charm(tmp_path)
        code = verifier.main([str(charm_dir)])
        assert code == 0
        assert "OK" in capsys.readouterr().out

    def test_verifier_cli_returns_1_on_failure(
        self, tmp_path: pathlib.Path, verifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = verifier.main([str(tmp_path)])  # Empty dir → missing charmcraft.yaml.
        assert code == 1
        assert "FAIL" in capsys.readouterr().err

    def test_verifier_cli_returns_2_on_wrong_argv(
        self, verifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = verifier.main([])
        assert code == 2
        assert "Usage" in capsys.readouterr().err


class TestHarnessMigrationVerifier:
    """Verifier for ``cookbook/migrate-harness-to-scenario/``.

    Builds an in-process charm tree that matches the post-migration
    shape (Scenario tests, ``ops[testing]`` wired up, no Harness) and
    exercises the verifier's happy path plus each failure mode.  No
    real tests run.
    """

    RECIPE = COOKBOOK_ROOT / "migrate-harness-to-scenario"

    _SCENARIO_TEST = textwrap.dedent("""\
        from ops import testing
        from charm import MyCharm

        def test_start():
            ctx = testing.Context(MyCharm)
            state_out = ctx.run(ctx.on.start(), testing.State())
            assert state_out.unit_status == testing.ActiveStatus()
        """)
    _HARNESS_TEST = textwrap.dedent("""\
        from ops.testing import Harness
        from charm import MyCharm

        def test_start():
            harness = Harness(MyCharm)
            harness.begin()
            harness.charm.on.start.emit()
        """)
    _PYPROJECT = textwrap.dedent("""\
        [project]
        name = "my-charm"
        version = "0.1.0"
        dependencies = ["ops>=3,<4"]

        [dependency-groups]
        unit = ["ops[testing]", "pytest"]
        """)

    @pytest.fixture
    def verifier(self):
        return _load_verifier(self.RECIPE / "verify.py")

    @staticmethod
    def _write_migrated_charm(
        root: pathlib.Path,
        *,
        test_files: dict[str, str] | None = None,
        pyproject_toml: str | None = None,
        write_tests_dir: bool = True,
    ) -> pathlib.Path:
        """Write a minimal post-migration charm tree into *root*."""
        if write_tests_dir:
            if test_files is None:
                test_files = {"unit/test_charm.py": TestHarnessMigrationVerifier._SCENARIO_TEST}
            for rel, body in test_files.items():
                path = root / "tests" / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body, encoding="utf-8")
        if pyproject_toml is None:
            pyproject_toml = TestHarnessMigrationVerifier._PYPROJECT
        (root / "pyproject.toml").write_text(pyproject_toml, encoding="utf-8")
        return root

    def test_happy_path(self, tmp_path: pathlib.Path, verifier) -> None:
        charm_dir = self._write_migrated_charm(tmp_path)
        verifier.verify(charm_dir)

    def test_no_tests_dir_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_migrated_charm(tmp_path, write_tests_dir=False)
        with pytest.raises(verifier.VerifyError, match="tests/"):
            verifier.verify(tmp_path)

    def test_empty_tests_dir_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        (tmp_path / "tests").mkdir()
        (tmp_path / "pyproject.toml").write_text(self._PYPROJECT, encoding="utf-8")
        with pytest.raises(verifier.VerifyError, match=r"no .py files"):
            verifier.verify(tmp_path)

    def test_lingering_harness_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_migrated_charm(
            tmp_path,
            test_files={
                "unit/test_charm.py": self._SCENARIO_TEST,
                "unit/test_legacy.py": self._HARNESS_TEST,
            },
        )
        with pytest.raises(verifier.VerifyError, match="Harness"):
            verifier.verify(tmp_path)

    def test_no_scenario_construct_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        # A test file with neither Harness nor Scenario — the suite was
        # gutted, not migrated.
        self._write_migrated_charm(
            tmp_path,
            test_files={"unit/test_charm.py": "def test_nothing():\n    assert True\n"},
        )
        with pytest.raises(verifier.VerifyError, match="state-transition"):
            verifier.verify(tmp_path)

    def test_missing_pyproject_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        (tmp_path / "tests" / "unit").mkdir(parents=True)
        (tmp_path / "tests" / "unit" / "test_charm.py").write_text(
            self._SCENARIO_TEST, encoding="utf-8"
        )
        with pytest.raises(verifier.VerifyError, match=r"pyproject.toml"):
            verifier.verify(tmp_path)

    def test_invalid_pyproject_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_migrated_charm(tmp_path, pyproject_toml="this is not = valid = toml\n[")
        with pytest.raises(verifier.VerifyError, match="valid TOML"):
            verifier.verify(tmp_path)

    def test_no_ops_testing_extra_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        bad = textwrap.dedent("""\
            [project]
            name = "my-charm"
            dependencies = ["ops>=3,<4"]

            [dependency-groups]
            unit = ["pytest"]
            """)
        self._write_migrated_charm(tmp_path, pyproject_toml=bad)
        with pytest.raises(verifier.VerifyError, match=r"ops\[testing\]"):
            verifier.verify(tmp_path)

    def test_standalone_ops_scenario_pin_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        bad = textwrap.dedent("""\
            [project]
            name = "my-charm"
            dependencies = ["ops>=3,<4"]

            [dependency-groups]
            unit = ["ops[testing]", "ops-scenario>=7", "pytest"]
            """)
        self._write_migrated_charm(tmp_path, pyproject_toml=bad)
        with pytest.raises(verifier.VerifyError, match="ops-scenario"):
            verifier.verify(tmp_path)

    def test_ops_testing_in_optional_dependencies_passes(
        self, tmp_path: pathlib.Path, verifier
    ) -> None:
        ok = textwrap.dedent("""\
            [project]
            name = "my-charm"
            dependencies = ["ops>=3,<4"]

            [project.optional-dependencies]
            dev = ["ops[testing]", "pytest"]
            """)
        charm_dir = self._write_migrated_charm(tmp_path, pyproject_toml=ok)
        verifier.verify(charm_dir)

    def test_verifier_cli_returns_0_on_success(
        self, tmp_path: pathlib.Path, verifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        charm_dir = self._write_migrated_charm(tmp_path)
        code = verifier.main([str(charm_dir)])
        assert code == 0
        assert "OK" in capsys.readouterr().out

    def test_verifier_cli_returns_1_on_failure(
        self, tmp_path: pathlib.Path, verifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = verifier.main([str(tmp_path)])  # Empty dir → no tests/.
        assert code == 1
        assert "FAIL" in capsys.readouterr().err

    def test_verifier_cli_returns_2_on_wrong_argv(
        self, verifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = verifier.main(["a", "b"])
        assert code == 2
        assert "Usage" in capsys.readouterr().err


class TestStatefulCharmVerifier:
    """Verifier for ``cookbook/build-a-stateful-charm/``.

    Builds an in-process charm tree matching the full-build shape
    (Scenario unit tests, ops-tracing, COS relations, Jubilant
    integration tests) and exercises the verifier's happy path plus
    every failure mode.  No real charmcraft / juju / pytest runs.
    """

    RECIPE = COOKBOOK_ROOT / "build-a-stateful-charm"

    _CHARMCRAFT = textwrap.dedent("""\
        name: my-stateful
        type: charm
        base: ubuntu@24.04
        platforms:
          amd64:
        requires:
          tracing:
            interface: tracing
            limit: 1
          logging:
            interface: loki_push_api
        provides:
          metrics-endpoint:
            interface: prometheus_scrape
          grafana-dashboard:
            interface: grafana_dashboard
        """)
    _CHARM_PY = textwrap.dedent("""\
        import ops
        import ops_tracing


        class MyStatefulCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self._tracing = ops_tracing.Tracing(self, "tracing")
        """)
    _PYPROJECT = textwrap.dedent("""\
        [project]
        name = "my-stateful"
        version = "0.1.0"
        dependencies = ["ops>=3,<4", "ops-tracing"]

        [dependency-groups]
        unit = ["ops[testing]", "pytest"]
        integration = ["jubilant", "pytest"]
        """)
    _UNIT_TEST = textwrap.dedent("""\
        from ops import testing
        from charm import MyStatefulCharm

        def test_start():
            ctx = testing.Context(MyStatefulCharm)
            state_out = ctx.run(ctx.on.start(), testing.State())
            assert state_out.unit_status == testing.ActiveStatus()
        """)
    _INTEGRATION_TEST = textwrap.dedent("""\
        import jubilant

        def test_deploy(juju: jubilant.Juju):
            juju.deploy("./my-stateful_amd64.charm")
            juju.wait(jubilant.all_active)
        """)

    @pytest.fixture
    def verifier(self):
        return _load_verifier(self.RECIPE / "verify.py")

    @staticmethod
    def _write_full_charm(
        root: pathlib.Path,
        *,
        charmcraft_yaml: str | None = None,
        charm_py: str | None = None,
        pyproject_toml: str | None = None,
        unit_tests: dict[str, str] | None = None,
        integration_tests: dict[str, str] | None = None,
        dashboard_dir: bool = False,
        write_charmcraft: bool = True,
        write_charm_py: bool = True,
        write_tests: bool = True,
    ) -> pathlib.Path:
        """Write a minimal full-build charm tree into *root*."""
        cls = TestStatefulCharmVerifier
        if write_charmcraft:
            (root / "charmcraft.yaml").write_text(
                charmcraft_yaml if charmcraft_yaml is not None else cls._CHARMCRAFT,
                encoding="utf-8",
            )
        (root / "pyproject.toml").write_text(
            pyproject_toml if pyproject_toml is not None else cls._PYPROJECT,
            encoding="utf-8",
        )
        if write_charm_py:
            (root / "src").mkdir(exist_ok=True)
            (root / "src" / "charm.py").write_text(
                charm_py if charm_py is not None else cls._CHARM_PY, encoding="utf-8"
            )
        if dashboard_dir:
            (root / "src" / "grafana_dashboards").mkdir(parents=True, exist_ok=True)
            (root / "src" / "grafana_dashboards" / "overview.json").write_text(
                "{}\n", encoding="utf-8"
            )
        if write_tests:
            unit = unit_tests if unit_tests is not None else {"unit/test_charm.py": cls._UNIT_TEST}
            integ = (
                integration_tests
                if integration_tests is not None
                else {"integration/test_charm.py": cls._INTEGRATION_TEST}
            )
            for rel, body in {**unit, **integ}.items():
                path = root / "tests" / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body, encoding="utf-8")
        return root

    def test_happy_path(self, tmp_path: pathlib.Path, verifier) -> None:
        verifier.verify(self._write_full_charm(tmp_path))

    def test_missing_charmcraft_yaml_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_full_charm(tmp_path, write_charmcraft=False)
        with pytest.raises(verifier.VerifyError, match=r"charmcraft.yaml"):
            verifier.verify(tmp_path)

    def test_charmcraft_without_name_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_full_charm(tmp_path, charmcraft_yaml="type: charm\nbase: ubuntu@24.04\n")
        with pytest.raises(verifier.VerifyError, match="name"):
            verifier.verify(tmp_path)

    def test_missing_src_charm_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_full_charm(tmp_path, write_charm_py=False)
        with pytest.raises(verifier.VerifyError, match=r"src/charm.py"):
            verifier.verify(tmp_path)

    def test_no_ops_tracing_dep_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_full_charm(
            tmp_path,
            pyproject_toml='[project]\nname = "x"\ndependencies = ["ops>=3,<4"]\n',
        )
        with pytest.raises(verifier.VerifyError, match="ops-tracing dependency"):
            verifier.verify(tmp_path)

    def test_charm_py_without_ops_tracing_import_fails(
        self, tmp_path: pathlib.Path, verifier
    ) -> None:
        self._write_full_charm(
            tmp_path,
            charm_py="import ops\n\nclass C(ops.CharmBase):\n    pass\n",
        )
        with pytest.raises(verifier.VerifyError, match="ops_tracing module"):
            verifier.verify(tmp_path)

    def test_no_tracing_relation_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        no_tracing = textwrap.dedent("""\
            name: x
            type: charm
            base: ubuntu@24.04
            provides:
              metrics-endpoint:
                interface: prometheus_scrape
            """)
        self._write_full_charm(tmp_path, charmcraft_yaml=no_tracing)
        with pytest.raises(verifier.VerifyError, match="tracing relation"):
            verifier.verify(tmp_path)

    def test_no_cos_beyond_tracing_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        tracing_only = textwrap.dedent("""\
            name: x
            type: charm
            base: ubuntu@24.04
            requires:
              tracing:
                interface: tracing
            """)
        self._write_full_charm(tmp_path, charmcraft_yaml=tracing_only)
        with pytest.raises(verifier.VerifyError, match="COS integration beyond tracing"):
            verifier.verify(tmp_path)

    def test_cos_via_dashboard_dir_passes(self, tmp_path: pathlib.Path, verifier) -> None:
        tracing_only = textwrap.dedent("""\
            name: x
            type: charm
            base: ubuntu@24.04
            requires:
              tracing:
                interface: tracing
            """)
        charm_dir = self._write_full_charm(
            tmp_path, charmcraft_yaml=tracing_only, dashboard_dir=True
        )
        verifier.verify(charm_dir)

    def test_no_tests_dir_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_full_charm(tmp_path, write_tests=False)
        with pytest.raises(verifier.VerifyError, match="tests/ directory"):
            verifier.verify(tmp_path)

    def test_harness_in_unit_test_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        legacy = textwrap.dedent("""\
            from ops.testing import Harness
            from charm import MyStatefulCharm

            def test_start():
                harness = Harness(MyStatefulCharm)
                harness.begin()
            """)
        self._write_full_charm(
            tmp_path,
            unit_tests={"unit/test_charm.py": self._UNIT_TEST, "unit/test_legacy.py": legacy},
        )
        with pytest.raises(verifier.VerifyError, match="Harness"):
            verifier.verify(tmp_path)

    def test_no_scenario_construct_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_full_charm(
            tmp_path,
            unit_tests={"unit/test_charm.py": "def test_nothing():\n    assert True\n"},
        )
        with pytest.raises(verifier.VerifyError, match="state-transition"):
            verifier.verify(tmp_path)

    def test_no_integration_tests_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_full_charm(tmp_path, integration_tests={})
        with pytest.raises(verifier.VerifyError, match="Jubilant integration"):
            verifier.verify(tmp_path)

    def test_integration_via_jubilant_import_passes(
        self, tmp_path: pathlib.Path, verifier
    ) -> None:
        charm_dir = self._write_full_charm(
            tmp_path,
            integration_tests={"test_integration.py": self._INTEGRATION_TEST},
        )
        verifier.verify(charm_dir)

    def test_verifier_cli_returns_0_on_success(
        self, tmp_path: pathlib.Path, verifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = verifier.main([str(self._write_full_charm(tmp_path))])
        assert code == 0
        assert "OK" in capsys.readouterr().out

    def test_verifier_cli_returns_1_on_failure(
        self, tmp_path: pathlib.Path, verifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = verifier.main([str(tmp_path)])  # Empty dir → missing charmcraft.yaml.
        assert code == 1
        assert "FAIL" in capsys.readouterr().err

    def test_verifier_cli_returns_2_on_wrong_argv(
        self, verifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = verifier.main([])
        assert code == 2
        assert "Usage" in capsys.readouterr().err


class TestTerraformModuleVerifier:
    """Verifier for ``cookbook/generate-a-terraform-module/``.

    Builds an in-process charm tree carrying a standard four-file
    Terraform module and exercises the verifier's happy path plus
    every failure mode.  No real ``terraform`` runs.
    """

    RECIPE = COOKBOOK_ROOT / "generate-a-terraform-module"

    _CHARMCRAFT = "name: my-charm\ntype: charm\nbase: ubuntu@24.04\n"
    _MAIN_TF = textwrap.dedent("""\
        resource "juju_application" "my_charm" {
          name  = var.app_name
          model = var.model_uuid
          charm {
            name    = "my-charm"
            channel = var.channel
          }
          units  = var.units
          config = var.config
        }
        """)
    _VARIABLES_TF = textwrap.dedent("""\
        variable "app_name" {
          type    = string
          default = "my-charm"
        }
        variable "model_uuid" {
          type = string
        }
        variable "channel" {
          type    = string
          default = "latest/stable"
        }
        variable "units" {
          type    = number
          default = 1
        }
        variable "config" {
          type    = map(string)
          default = {}
        }
        """)
    _OUTPUTS_TF = textwrap.dedent("""\
        output "app_name" {
          value = juju_application.my_charm.name
        }
        """)
    _TERRAFORM_TF = textwrap.dedent("""\
        terraform {
          required_version = ">= 1.6"
          required_providers {
            juju = {
              source  = "juju/juju"
              version = "~> 0.14"
            }
          }
        }
        """)

    @pytest.fixture
    def verifier(self):
        return _load_verifier(self.RECIPE / "verify.py")

    @staticmethod
    def _write_module_charm(
        root: pathlib.Path,
        *,
        charmcraft_yaml: str | None = None,
        tf_files: dict[str, str] | None = None,
        write_charmcraft: bool = True,
        write_module: bool = True,
    ) -> pathlib.Path:
        """Write a charm tree with a Terraform module into *root*."""
        cls = TestTerraformModuleVerifier
        if write_charmcraft:
            (root / "charmcraft.yaml").write_text(
                charmcraft_yaml if charmcraft_yaml is not None else cls._CHARMCRAFT,
                encoding="utf-8",
            )
        if write_module:
            files = (
                tf_files
                if tf_files is not None
                else {
                    "main.tf": cls._MAIN_TF,
                    "variables.tf": cls._VARIABLES_TF,
                    "outputs.tf": cls._OUTPUTS_TF,
                    "terraform.tf": cls._TERRAFORM_TF,
                }
            )
            (root / "terraform").mkdir(parents=True, exist_ok=True)
            for name, body in files.items():
                (root / "terraform" / name).write_text(body, encoding="utf-8")
        return root

    def test_happy_path(self, tmp_path: pathlib.Path, verifier) -> None:
        verifier.verify(self._write_module_charm(tmp_path))

    def test_missing_charmcraft_yaml_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_module_charm(tmp_path, write_charmcraft=False)
        with pytest.raises(verifier.VerifyError, match=r"charmcraft.yaml"):
            verifier.verify(tmp_path)

    def test_charmcraft_without_name_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_module_charm(tmp_path, charmcraft_yaml="type: charm\n")
        with pytest.raises(verifier.VerifyError, match="no 'name'"):
            verifier.verify(tmp_path)

    def test_missing_terraform_dir_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_module_charm(tmp_path, write_module=False)
        with pytest.raises(verifier.VerifyError, match="terraform/ directory"):
            verifier.verify(tmp_path)

    def test_missing_required_file_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_module_charm(
            tmp_path,
            tf_files={
                "main.tf": self._MAIN_TF,
                "variables.tf": self._VARIABLES_TF,
                "outputs.tf": self._OUTPUTS_TF,
                # terraform.tf deliberately omitted
            },
        )
        with pytest.raises(verifier.VerifyError, match="missing required file"):
            verifier.verify(tmp_path)

    def test_no_juju_application_resource_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_module_charm(
            tmp_path,
            tf_files={
                "main.tf": 'resource "juju_model" "dev" {\n  name = "dev"\n}\n',
                "variables.tf": self._VARIABLES_TF,
                "outputs.tf": self._OUTPUTS_TF,
                "terraform.tf": self._TERRAFORM_TF,
            },
        )
        with pytest.raises(verifier.VerifyError, match="juju_application"):
            verifier.verify(tmp_path)

    def test_no_charm_block_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_module_charm(
            tmp_path,
            tf_files={
                "main.tf": 'resource "juju_application" "x" {\n  name  = var.app_name\n  units = 1\n}\n',
                "variables.tf": self._VARIABLES_TF,
                "outputs.tf": self._OUTPUTS_TF,
                "terraform.tf": self._TERRAFORM_TF,
            },
        )
        with pytest.raises(verifier.VerifyError, match="Charmhub charm and channel"):
            verifier.verify(tmp_path)

    def test_charm_name_mismatch_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        wrong = self._MAIN_TF.replace('"my-charm"', '"some-other-charm"')
        self._write_module_charm(
            tmp_path,
            tf_files={
                "main.tf": wrong,
                "variables.tf": self._VARIABLES_TF,
                "outputs.tf": self._OUTPUTS_TF,
                "terraform.tf": self._TERRAFORM_TF,
            },
        )
        with pytest.raises(verifier.VerifyError, match="not a placeholder"):
            verifier.verify(tmp_path)

    def test_no_variable_blocks_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_module_charm(
            tmp_path,
            tf_files={
                "main.tf": self._MAIN_TF,
                "variables.tf": "# no variables yet\n",
                "outputs.tf": self._OUTPUTS_TF,
                "terraform.tf": self._TERRAFORM_TF,
            },
        )
        with pytest.raises(verifier.VerifyError, match=r"variables.tf"):
            verifier.verify(tmp_path)

    def test_no_output_blocks_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_module_charm(
            tmp_path,
            tf_files={
                "main.tf": self._MAIN_TF,
                "variables.tf": self._VARIABLES_TF,
                "outputs.tf": "# nothing exported\n",
                "terraform.tf": self._TERRAFORM_TF,
            },
        )
        with pytest.raises(verifier.VerifyError, match=r"outputs.tf"):
            verifier.verify(tmp_path)

    def test_no_terraform_block_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_module_charm(
            tmp_path,
            tf_files={
                "main.tf": self._MAIN_TF,
                "variables.tf": self._VARIABLES_TF,
                "outputs.tf": self._OUTPUTS_TF,
                "terraform.tf": "# placeholder\n",
            },
        )
        with pytest.raises(verifier.VerifyError, match=r"no .terraform \{"):
            verifier.verify(tmp_path)

    def test_no_required_providers_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_module_charm(
            tmp_path,
            tf_files={
                "main.tf": self._MAIN_TF,
                "variables.tf": self._VARIABLES_TF,
                "outputs.tf": self._OUTPUTS_TF,
                "terraform.tf": 'terraform {\n  required_version = ">= 1.6"\n}\n',
            },
        )
        with pytest.raises(verifier.VerifyError, match="required_providers"):
            verifier.verify(tmp_path)

    def test_juju_provider_not_pinned_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        no_juju = textwrap.dedent("""\
            terraform {
              required_providers {
                random = {
                  source = "hashicorp/random"
                }
              }
            }
            """)
        self._write_module_charm(
            tmp_path,
            tf_files={
                "main.tf": self._MAIN_TF,
                "variables.tf": self._VARIABLES_TF,
                "outputs.tf": self._OUTPUTS_TF,
                "terraform.tf": no_juju,
            },
        )
        with pytest.raises(verifier.VerifyError, match="juju/juju"):
            verifier.verify(tmp_path)

    def test_verifier_cli_returns_0_on_success(
        self, tmp_path: pathlib.Path, verifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = verifier.main([str(self._write_module_charm(tmp_path))])
        assert code == 0
        assert "OK" in capsys.readouterr().out

    def test_verifier_cli_returns_1_on_failure(
        self, tmp_path: pathlib.Path, verifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = verifier.main([str(tmp_path)])  # Empty dir → missing charmcraft.yaml.
        assert code == 1
        assert "FAIL" in capsys.readouterr().err

    def test_verifier_cli_returns_2_on_wrong_argv(
        self, verifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = verifier.main(["x", "y", "z"])
        assert code == 2
        assert "Usage" in capsys.readouterr().err


class TestAddObservabilityVerifier:
    """Verifier for ``cookbook/add-observability/``.

    Builds an in-process charm tree that's been wired into COS and
    exercises the verifier's happy path (both the K8s three-relation
    layout and the machine ``cos-agent`` layout) plus every failure
    mode.  No real charmcraft / juju runs.
    """

    RECIPE = COOKBOOK_ROOT / "add-observability"

    _CHARMCRAFT = textwrap.dedent("""\
        name: my-charm
        type: charm
        base: ubuntu@24.04
        requires:
          tracing:
            interface: tracing
            limit: 1
          logging:
            interface: loki_push_api
        provides:
          metrics-endpoint:
            interface: prometheus_scrape
          grafana-dashboard:
            interface: grafana_dashboard
        """)
    _CHARM_PY = textwrap.dedent("""\
        import ops
        import ops_tracing
        from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
        from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
        from charms.loki_k8s.v1.loki_push_api import LogForwarder


        class MyCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self._tracing = ops_tracing.Tracing(self, "tracing")
                self._metrics = MetricsEndpointProvider(self, relation_name="metrics-endpoint")
                self._dashboards = GrafanaDashboardProvider(self)
                self._logs = LogForwarder(self)
        """)
    _PYPROJECT = textwrap.dedent("""\
        [project]
        name = "my-charm"
        version = "0.1.0"
        dependencies = ["ops>=3,<4", "ops-tracing", "cosl"]
        """)

    _COS_AGENT_CHARMCRAFT = textwrap.dedent("""\
        name: my-machine-charm
        type: charm
        base: ubuntu@24.04
        requires:
          tracing:
            interface: tracing
        provides:
          cos-agent:
            interface: cos_agent
        """)
    _COS_AGENT_CHARM_PY = textwrap.dedent("""\
        import ops
        import ops_tracing
        from charms.grafana_agent.v0.cos_agent import COSAgentProvider


        class MyMachineCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self._tracing = ops_tracing.Tracing(self, "tracing")
                self._cos = COSAgentProvider(self)
        """)

    @pytest.fixture
    def verifier(self):
        return _load_verifier(self.RECIPE / "verify.py")

    @staticmethod
    def _write_observable_charm(
        root: pathlib.Path,
        *,
        charmcraft_yaml: str | None = None,
        charm_py: str | None = None,
        pyproject_toml: str | None = None,
        dashboards: bool = True,
        write_charmcraft: bool = True,
        write_charm_py: bool = True,
    ) -> pathlib.Path:
        """Write a COS-instrumented charm tree into *root*."""
        cls = TestAddObservabilityVerifier
        if write_charmcraft:
            (root / "charmcraft.yaml").write_text(
                charmcraft_yaml if charmcraft_yaml is not None else cls._CHARMCRAFT,
                encoding="utf-8",
            )
        (root / "pyproject.toml").write_text(
            pyproject_toml if pyproject_toml is not None else cls._PYPROJECT, encoding="utf-8"
        )
        if write_charm_py:
            (root / "src").mkdir(exist_ok=True)
            (root / "src" / "charm.py").write_text(
                charm_py if charm_py is not None else cls._CHARM_PY, encoding="utf-8"
            )
        if dashboards:
            (root / "src" / "grafana_dashboards").mkdir(parents=True, exist_ok=True)
            (root / "src" / "grafana_dashboards" / "overview.json").write_text(
                "{}\n", encoding="utf-8"
            )
        return root

    def test_happy_path_k8s_layout(self, tmp_path: pathlib.Path, verifier) -> None:
        verifier.verify(self._write_observable_charm(tmp_path))

    def test_happy_path_cos_agent_layout(self, tmp_path: pathlib.Path, verifier) -> None:
        charm_dir = self._write_observable_charm(
            tmp_path,
            charmcraft_yaml=self._COS_AGENT_CHARMCRAFT,
            charm_py=self._COS_AGENT_CHARM_PY,
        )
        verifier.verify(charm_dir)

    def test_missing_charmcraft_yaml_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_observable_charm(tmp_path, write_charmcraft=False)
        with pytest.raises(verifier.VerifyError, match=r"charmcraft.yaml"):
            verifier.verify(tmp_path)

    def test_charmcraft_without_name_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_observable_charm(tmp_path, charmcraft_yaml="type: charm\n")
        with pytest.raises(verifier.VerifyError, match="no 'name'"):
            verifier.verify(tmp_path)

    def test_missing_src_charm_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_observable_charm(tmp_path, write_charm_py=False)
        with pytest.raises(verifier.VerifyError, match=r"src/charm.py"):
            verifier.verify(tmp_path)

    def test_no_ops_tracing_dep_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_observable_charm(
            tmp_path, pyproject_toml='[project]\nname = "x"\ndependencies = ["ops>=3,<4"]\n'
        )
        with pytest.raises(verifier.VerifyError, match="ops-tracing dependency"):
            verifier.verify(tmp_path)

    def test_charm_py_without_ops_tracing_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_observable_charm(
            tmp_path, charm_py="import ops\n\nclass C(ops.CharmBase):\n    pass\n"
        )
        with pytest.raises(verifier.VerifyError, match="ops_tracing module"):
            verifier.verify(tmp_path)

    def test_no_tracing_relation_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        no_tracing = textwrap.dedent("""\
            name: x
            type: charm
            base: ubuntu@24.04
            requires:
              logging:
                interface: loki_push_api
            provides:
              metrics-endpoint:
                interface: prometheus_scrape
              grafana-dashboard:
                interface: grafana_dashboard
            """)
        self._write_observable_charm(tmp_path, charmcraft_yaml=no_tracing)
        with pytest.raises(verifier.VerifyError, match="tracing relation"):
            verifier.verify(tmp_path)

    def test_missing_one_cos_pillar_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        # tracing + metrics + dashboards present, logging missing.
        no_logging = textwrap.dedent("""\
            name: x
            type: charm
            base: ubuntu@24.04
            requires:
              tracing:
                interface: tracing
            provides:
              metrics-endpoint:
                interface: prometheus_scrape
              grafana-dashboard:
                interface: grafana_dashboard
            """)
        self._write_observable_charm(tmp_path, charmcraft_yaml=no_logging)
        with pytest.raises(verifier.VerifyError, match=r"missing COS relation.*logs"):
            verifier.verify(tmp_path)

    def test_no_dashboard_assets_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        self._write_observable_charm(tmp_path, dashboards=False)
        with pytest.raises(verifier.VerifyError, match="src/grafana_dashboards"):
            verifier.verify(tmp_path)

    def test_providers_not_wired_fails(self, tmp_path: pathlib.Path, verifier) -> None:
        bare = textwrap.dedent("""\
            import ops
            import ops_tracing


            class MyCharm(ops.CharmBase):
                def __init__(self, framework: ops.Framework):
                    super().__init__(framework)
                    self._tracing = ops_tracing.Tracing(self, "tracing")
            """)
        self._write_observable_charm(tmp_path, charm_py=bare)
        with pytest.raises(verifier.VerifyError, match="references none of"):
            verifier.verify(tmp_path)

    def test_verifier_cli_returns_0_on_success(
        self, tmp_path: pathlib.Path, verifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = verifier.main([str(self._write_observable_charm(tmp_path))])
        assert code == 0
        assert "OK" in capsys.readouterr().out

    def test_verifier_cli_returns_1_on_failure(
        self, tmp_path: pathlib.Path, verifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = verifier.main([str(tmp_path)])  # Empty dir → missing charmcraft.yaml.
        assert code == 1
        assert "FAIL" in capsys.readouterr().err

    def test_verifier_cli_returns_2_on_wrong_argv(
        self, verifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = verifier.main(["one", "two"])
        assert code == 2
        assert "Usage" in capsys.readouterr().err
