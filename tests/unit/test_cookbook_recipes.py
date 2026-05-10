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
        with pytest.raises(verifier.VerifyError, match="charmcraft.yaml"):
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
        with pytest.raises(verifier.VerifyError, match="ubuntu@24.04"):
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
        with pytest.raises(verifier.VerifyError, match="charm plugin|plugin: charm"):
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
        with pytest.raises(verifier.VerifyError, match="src/charm.py"):
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
        with pytest.raises(verifier.VerifyError, match="no .py files"):
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
        with pytest.raises(verifier.VerifyError, match="pyproject.toml"):
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
