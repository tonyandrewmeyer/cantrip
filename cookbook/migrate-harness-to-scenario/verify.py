#!/usr/bin/env python3

"""Verifier for the ``migrate-harness-to-scenario`` cookbook recipe.

Asserts that a charm directory whose unit tests have been migrated
off the deprecated ``ops.testing.Harness`` matches the shape the
recipe teaches:

- A ``tests/`` directory with at least one ``*.py`` test file.
- No test file under ``tests/`` still references ``Harness`` —
  ``testing.Harness``, ``ops.testing.Harness``, or a bare
  ``Harness(...)`` call.
- At least one test file uses a state-transition (Scenario)
  construct — ``testing.Context``, ``testing.State``,
  ``ctx.run(...)``, or the legacy ``Scenario(...)`` — so the suite
  was *migrated*, not merely deleted.
- ``pyproject.toml`` exists, is valid TOML, declares ``ops[testing]``,
  and does **not** reference the standalone ``ops-scenario`` package
  (folded into ``ops[testing]``).

The Harness / Scenario detector regexes mirror the ones in
``cantrip.agent.tools.harness_inventory`` (and the upstream
``migrate-harness-tests-to-state-transition-test`` skill) so a
recipe run and the in-agent inventory tool agree on what counts.

Exit codes:
- ``0`` — every assertion passed.
- ``1`` — at least one assertion failed; reason printed to stderr.
- ``2`` — the supplied path isn't a directory, or argv is wrong.

Usage:
    python verify.py /path/to/migrated/charm/dir
"""

from __future__ import annotations

import pathlib
import re
import sys
import tomllib

# Mirrors ``cantrip.agent.tools.harness_inventory`` — keep in sync if
# the upstream detector changes.
_HARNESS_RE = re.compile(r"\btesting\.Harness\b|\bops\.testing\.Harness\b|\bHarness\(")
_SCENARIO_RE = re.compile(
    r"\btesting\.Scenario\b|\bScenario\(|\btesting\.Context\b|\bops\.testing\.Context\b"
    r"|\btesting\.State\b|\bctx\.run\("
)

# The standalone ``ops-scenario`` distribution as a package token,
# anywhere in ``pyproject.toml`` (inline TOML arrays put deps mid-line).
# ``ops[testing]`` supersedes it, so its presence means the migration
# is incomplete.
_OPS_SCENARIO_RE = re.compile(r"(?<![\w-])ops-scenario(?![\w-])", re.IGNORECASE)


class VerifyError(Exception):
    """Raised when a migration invariant is violated."""


def _read(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise VerifyError(f"cannot read {path}: {exc}") from exc


def _test_files(charm_dir: pathlib.Path) -> list[pathlib.Path]:
    """Return every ``*.py`` file under ``charm_dir/tests`` (sorted).

    Raises :class:`VerifyError` if there is no ``tests/`` directory —
    this recipe migrates an *existing* suite, so one must exist.
    """
    tests_root = charm_dir / "tests"
    if not tests_root.is_dir():
        raise VerifyError(
            f"no tests/ directory in {charm_dir} — the recipe migrates an "
            "existing unit-test suite, so there must be one to migrate"
        )
    return sorted(tests_root.rglob("*.py"))


def check_tests_present(charm_dir: pathlib.Path) -> list[pathlib.Path]:
    """Assert there is at least one Python test file to inspect."""
    files = _test_files(charm_dir)
    if not files:
        raise VerifyError(f"tests/ under {charm_dir} contains no .py files — nothing to verify")
    return files


def check_no_harness(charm_dir: pathlib.Path, test_files: list[pathlib.Path]) -> None:
    """Assert no test file still references ``ops.testing.Harness``."""
    offenders = [
        str(path.relative_to(charm_dir)) for path in test_files if _HARNESS_RE.search(_read(path))
    ]
    if offenders:
        raise VerifyError(
            f"these test files still use ops.testing.Harness: {offenders!r} — the "
            "migration is incomplete (run the harness_inventory tool for per-file counts)"
        )


def check_scenario_present(test_files: list[pathlib.Path]) -> None:
    """Assert at least one test file uses a Scenario construct."""
    if any(_SCENARIO_RE.search(_read(path)) for path in test_files):
        return
    raise VerifyError(
        "no test file uses a state-transition construct "
        "(testing.Context / testing.State / ctx.run(...) / Scenario(...)). "
        "The recipe rewrites Harness tests as Scenario tests — deleting them "
        "without replacement doesn't count."
    )


def check_pyproject(charm_dir: pathlib.Path) -> None:
    """Assert ``pyproject.toml`` declares ``ops[testing]`` and not ``ops-scenario``."""
    path = charm_dir / "pyproject.toml"
    if not path.exists():
        raise VerifyError(
            f"no pyproject.toml in {charm_dir} — the recipe puts ops[testing] in "
            "the unit-test dependency group, which lives in pyproject.toml"
        )
    raw = _read(path)
    try:
        tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise VerifyError(f"pyproject.toml is not valid TOML: {exc}") from exc

    if "ops[testing]" not in raw.replace(" ", "").lower():
        raise VerifyError(
            "pyproject.toml does not declare ops[testing] — Scenario's Context "
            "lives in the testing extra; add ops[testing] to the unit-test "
            "dependency group"
        )

    if _OPS_SCENARIO_RE.search(raw):
        raise VerifyError(
            "pyproject.toml still references the standalone ops-scenario package "
            "— it has been folded into ops[testing]; remove the separate pin"
        )


def verify(charm_dir: pathlib.Path) -> None:
    """Run every migration check against *charm_dir*."""
    if not charm_dir.is_dir():
        raise VerifyError(f"{charm_dir} is not a directory")
    test_files = check_tests_present(charm_dir)
    check_no_harness(charm_dir, test_files)
    check_scenario_present(test_files)
    check_pyproject(charm_dir)


def main(argv: list[str]) -> int:
    """Verify the cookbook recipe's output and report the result."""
    if len(argv) != 1:
        sys.stderr.write(
            "Usage: verify.py <charm-dir>\n"
            "  <charm-dir>: path to the charm whose tests Cantrip migrated\n"
        )
        return 2
    charm_dir = pathlib.Path(argv[0]).resolve()
    try:
        verify(charm_dir)
    except VerifyError as exc:
        sys.stderr.write(f"FAIL: {exc}\n")
        return 1
    print("OK — Harness→Scenario migration shape verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
