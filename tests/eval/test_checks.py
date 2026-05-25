"""Regression tests for individual rubric checker functions in
:mod:`tests.eval.checks`.

``test_gold_standards.py`` only proves the full gold standards score
100 %; it does not catch substring-matching blind spots that show up
when a real-world charm uses an idiom the rubric did not expect.
This file pins the explicit positive and negative cases for the
checks where we have hit such a blind spot.
"""

import pathlib

from tests.eval.checks import uses_scenario_tests


def _write(charm_dir: pathlib.Path, body: str) -> None:
    """Write a single ``tests/unit/test_charm.py`` with *body*."""
    test_dir = charm_dir / "tests" / "unit"
    test_dir.mkdir(parents=True, exist_ok=True)
    (test_dir / "test_charm.py").write_text(body)


class TestUsesScenarioTests:
    """Cover each Scenario import idiom the rubric needs to recognise."""

    def test_explicit_dotted_import_passes(self, tmp_path: pathlib.Path):
        # The canonical idiom — what gold-claude ships with.
        _write(
            tmp_path,
            "import ops\nimport ops.testing\n\n"
            "def test_x():\n    ctx = ops.testing.Context(MyCharm)\n",
        )
        ok, _ = uses_scenario_tests(tmp_path)
        assert ok

    def test_aliased_dotted_import_passes(self, tmp_path: pathlib.Path):
        # gold-fireworks idiom.
        _write(
            tmp_path,
            "import ops.testing as testing\n\ndef test_x():\n    ctx = testing.Context(MyCharm)\n",
        )
        ok, _ = uses_scenario_tests(tmp_path)
        assert ok

    def test_from_ops_import_testing_passes(self, tmp_path: pathlib.Path):
        # The idiom GLM-4.7 reached for naturally — `from ops import …,
        # testing` then `testing.Context(...)`.  Semantically valid
        # Scenario usage; previously failed because the file contains
        # neither the dotted ``ops.testing`` substring nor the word
        # ``scenario``.
        _write(
            tmp_path,
            "from ops import pebble, testing\n\n"
            "def test_x():\n"
            "    ctx = testing.Context(MyCharm)\n"
            "    state = testing.State()\n",
        )
        ok, msg = uses_scenario_tests(tmp_path)
        assert ok, f"expected pass, got {msg!r}"

    def test_scenario_alias_passes(self, tmp_path: pathlib.Path):
        # ``import ops.testing as scenario`` — covered by both the
        # ``ops.testing`` substring and the ``scenario`` fallback.
        _write(
            tmp_path,
            "import ops.testing as scenario\n\n"
            "def test_x():\n    ctx = scenario.Context(MyCharm)\n",
        )
        ok, _ = uses_scenario_tests(tmp_path)
        assert ok

    def test_harness_fails_even_with_testing_in_imports(self, tmp_path: pathlib.Path):
        # If Harness is in the file we must fail regardless of how
        # ``testing`` is imported.
        _write(
            tmp_path,
            "from ops.testing import Harness\n\ndef test_x():\n    h = Harness(MyCharm)\n",
        )
        ok, msg = uses_scenario_tests(tmp_path)
        assert not ok and "Harness" in msg

    def test_no_testing_idiom_fails(self, tmp_path: pathlib.Path):
        # A file that doesn't use any Scenario API at all.
        _write(tmp_path, "def test_x():\n    assert True\n")
        ok, _ = uses_scenario_tests(tmp_path)
        assert not ok

    def test_missing_test_dir_fails(self, tmp_path: pathlib.Path):
        ok, msg = uses_scenario_tests(tmp_path)
        assert not ok and "tests/unit/" in msg
