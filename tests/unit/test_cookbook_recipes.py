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
