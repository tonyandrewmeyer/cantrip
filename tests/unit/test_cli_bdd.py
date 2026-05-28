"""BDD-style Gherkin coverage for the Cantrip CLI."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import pathlib
import shlex
import types

import pytest
import pytest_bdd

from cantrip import main as cantrip_main
from tests.support import transcript_seed

pytest_bdd.scenarios("features/cli_parsing.feature")
pytest_bdd.scenarios("features/export_transcript.feature")


@dataclasses.dataclass
class CliWorld:
    """Mutable scenario state shared across Given/When/Then steps."""

    argv: list[str] = dataclasses.field(default_factory=list)
    parsed_args: argparse.Namespace | None = None
    charm_path: pathlib.Path | None = None
    expected_path: pathlib.Path | None = None
    export_result: int | None = None
    export_output: str = ""


@pytest.fixture
def cli_world() -> CliWorld:
    """Create a fresh scenario world for each example."""
    return CliWorld()


@pytest_bdd.given(pytest_bdd.parsers.parse('the command line "{argv}"'))
def given_command_line(cli_world: CliWorld, argv: str) -> None:
    """Seed an arbitrary argv from a shell-style command line.

    Lets parsing scenarios spell the exact invocation in the feature
    file (``--provider claude``, ``export-transcript ./charm --phase
    build``) without a per-shape Given step.
    """
    cli_world.argv = shlex.split(argv)


@pytest_bdd.given('only the "--no-tui" flag was provided')
def given_flag_only_invocation(cli_world: CliWorld) -> None:
    """Seed a flag-only CLI invocation."""
    cli_world.argv = ["--no-tui"]


@pytest_bdd.given("a bare project path was provided")
def given_bare_project_path(cli_world: CliWorld, tmp_path: pathlib.Path) -> None:
    """Seed a path-only CLI invocation."""
    cli_world.expected_path = tmp_path / "demo-charm"
    cli_world.argv = [str(cli_world.expected_path)]


@pytest_bdd.when("the CLI arguments are parsed")
def when_cli_arguments_are_parsed(cli_world: CliWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    """Parse the current scenario argv."""
    monkeypatch.setattr("sys.argv", ["cantrip", *cli_world.argv])
    cli_world.parsed_args = cantrip_main.parse_args()


@pytest_bdd.then(pytest_bdd.parsers.parse('the selected command is "{command}"'))
def then_selected_command_is(cli_world: CliWorld, command: str) -> None:
    """Assert the selected subcommand."""
    assert cli_world.parsed_args is not None
    assert cli_world.parsed_args.command == command


@pytest_bdd.then(pytest_bdd.parsers.parse('the "{option_name}" option is enabled'))
def then_option_is_enabled(cli_world: CliWorld, option_name: str) -> None:
    """Assert a boolean CLI option is enabled."""
    assert cli_world.parsed_args is not None
    assert getattr(cli_world.parsed_args, option_name) is True


@pytest_bdd.then(pytest_bdd.parsers.parse('the "{option_name}" option equals "{value}"'))
def then_option_equals(cli_world: CliWorld, option_name: str, value: str) -> None:
    """Assert a CLI option parsed to the expected (stringified) value."""
    assert cli_world.parsed_args is not None
    assert str(getattr(cli_world.parsed_args, option_name)) == value


@pytest_bdd.then("the selected path is that project path")
def then_selected_path_matches(cli_world: CliWorld) -> None:
    """Assert the path-only invocation is preserved."""
    assert cli_world.parsed_args is not None
    assert cli_world.expected_path is not None
    assert cli_world.parsed_args.path == cli_world.expected_path


@pytest_bdd.given("a charm project with a recorded session")
def given_charm_project_with_session(cli_world: CliWorld, tmp_path: pathlib.Path) -> None:
    """Create a project directory whose transcript can be exported."""
    cli_world.charm_path = tmp_path / "my-charm"
    cli_world.charm_path.mkdir()
    transcript_seed.seed_cli_export_session(cli_world.charm_path)


@pytest_bdd.given("a charm project without session data")
def given_charm_project_without_session(cli_world: CliWorld, tmp_path: pathlib.Path) -> None:
    """Create a project directory with no `.cantrip` database."""
    cli_world.charm_path = tmp_path / "empty-charm"
    cli_world.charm_path.mkdir()


@pytest_bdd.when(pytest_bdd.parsers.parse('I export the transcript as "{fmt}"'))
def when_exporting_transcript(cli_world: CliWorld, fmt: str) -> None:
    """Export the transcript to its default path."""
    _run_export(cli_world, fmt=fmt, output=None)


@pytest_bdd.when(
    pytest_bdd.parsers.parse('I export the transcript as "{fmt}" to "{relative_output}"')
)
def when_exporting_transcript_to_output(
    cli_world: CliWorld, fmt: str, relative_output: str
) -> None:
    """Export the transcript to a custom path under the charm project."""
    assert cli_world.charm_path is not None
    _run_export(cli_world, fmt=fmt, output=cli_world.charm_path / relative_output)


@pytest_bdd.when(
    pytest_bdd.parsers.parse('I export the transcript as "{fmt}" filtered to phase "{phase}"')
)
def when_exporting_transcript_for_phase(cli_world: CliWorld, fmt: str, phase: str) -> None:
    """Export only the tasks belonging to a single workflow phase."""
    _run_export(cli_world, fmt=fmt, output=None, filter_phase=phase)


@pytest_bdd.then("the export succeeds")
def then_export_succeeds(cli_world: CliWorld) -> None:
    """Assert the export returned success."""
    assert cli_world.export_result == 0


@pytest_bdd.then("the export fails")
def then_export_fails(cli_world: CliWorld) -> None:
    """Assert the export returned failure."""
    assert cli_world.export_result == 1


@pytest_bdd.then(pytest_bdd.parsers.parse('the file "{relative_path}" is created'))
def then_file_is_created(cli_world: CliWorld, relative_path: str) -> None:
    """Assert an output file was written under the charm project."""
    output_path = _resolve_under_charm(cli_world, relative_path)
    assert output_path.exists()


@pytest_bdd.then(pytest_bdd.parsers.parse('the file "{relative_path}" contains "{expected_text}"'))
def then_file_contains(cli_world: CliWorld, relative_path: str, expected_text: str) -> None:
    """Assert an output file contains the expected user-visible text."""
    output_path = _resolve_under_charm(cli_world, relative_path)
    assert expected_text in output_path.read_text()


@pytest_bdd.then(pytest_bdd.parsers.parse('the export output contains "{expected_text}"'))
def then_export_output_contains(cli_world: CliWorld, expected_text: str) -> None:
    """Assert the command printed the expected status message."""
    assert expected_text in cli_world.export_output


def _run_export(
    cli_world: CliWorld,
    *,
    fmt: str,
    output: pathlib.Path | None,
    filter_phase: str | None = None,
) -> None:
    """Call the export command and capture its printed status."""
    assert cli_world.charm_path is not None
    args = types.SimpleNamespace(
        path=cli_world.charm_path,
        fmt=fmt,
        output=output,
        filter_task=None,
        filter_phase=filter_phase,
        filter_since=None,
        filter_branch=None,
        page_size=None,
    )
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        cli_world.export_result = cantrip_main._export_transcript(args)
    cli_world.export_output = stdout.getvalue()


def _resolve_under_charm(cli_world: CliWorld, relative_path: str) -> pathlib.Path:
    """Resolve a test path relative to the current charm project."""
    assert cli_world.charm_path is not None
    return cli_world.charm_path / relative_path
