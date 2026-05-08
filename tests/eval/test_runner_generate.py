"""Tests for the ``generate`` / ``run`` subcommands of the eval runner.

Phase 79.4 turned ``score --provider X`` from a metadata-only label
into a real generation step.  The runner shells out to ``cantrip run
--print``; these tests use a fake subprocess runner that lays down a
synthetic charm tree so the suite never has to spend tokens on a real
LLM call.
"""

from __future__ import annotations

import datetime
import pathlib
import subprocess
from typing import TYPE_CHECKING

import pytest

from tests.eval import generator, runner
from tests.eval.spec import (
    CharmPath,
    Criterion,
    EvalSpec,
    Rubric,
    Severity,
    Substrate,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


def _make_spec() -> EvalSpec:
    return EvalSpec(
        name="dummy",
        description="dummy spec for runner tests",
        charm_path_type=CharmPath.CUSTOM,
        substrate=Substrate.K8S,
        prompt="Build a charm for the dummy workload.",
        rubric=Rubric(
            (
                Criterion(
                    name="charmcraft-yaml",
                    description="Primary project file exists",
                    category="structure",
                    severity=Severity.CRITICAL,
                    check="file_exists",
                    args={"path": "charmcraft.yaml"},
                ),
                Criterion(
                    name="charm-source",
                    description="Main charm source file",
                    category="structure",
                    severity=Severity.MAJOR,
                    check="file_exists",
                    args={"path": "src/charm.py"},
                ),
            )
        ),
    )


def _fake_runner_factory(
    *,
    files: dict[str, str] | None = None,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
):
    """Return a stub :func:`subprocess.run` that lays down *files*.

    ``files`` keys are relative paths inside ``cwd`` (the charm dir).
    ``cwd`` is the per-run charm directory the generator picked, so the
    fake runner mimics what print-mode would write.
    """
    captured: dict[str, object] = {}

    def fake(
        args: Sequence[str],
        *,
        cwd: pathlib.Path | str | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
        check: bool = False,  # noqa: ARG001
        capture_output: bool = False,  # noqa: ARG001
        text: bool = False,  # noqa: ARG001
    ) -> subprocess.CompletedProcess:
        captured["args"] = tuple(args)
        captured["cwd"] = cwd
        captured["env"] = env
        captured["timeout"] = timeout
        if files and cwd is not None:
            base = pathlib.Path(cwd)
            for rel, content in files.items():
                target = base / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
        return subprocess.CompletedProcess(
            args=list(args),
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return fake, captured


def test_slugify_model_handles_paths_and_punct():
    assert generator.slugify_model(None) == "default"
    assert generator.slugify_model("") == "default"
    assert generator.slugify_model("Opus 4.7") == "opus-4.7"
    assert generator.slugify_model("openai/gpt-4o-mini") == "openai-gpt-4o-mini"
    assert generator.slugify_model("!!!") == "default"


def test_make_charm_dir_includes_provider_model_and_timestamp(tmp_path: pathlib.Path):
    ts = datetime.datetime(2026, 5, 9, 12, 30, 45, tzinfo=datetime.UTC)
    out = generator.make_charm_dir(tmp_path, provider="claude", model="opus-4.7", timestamp=ts)
    assert out == tmp_path / "cantrip-claude-opus-4.7-20260509-123045"


def test_build_command_includes_yolo_and_path():
    spec = _make_spec()
    cmd = generator.build_command(
        spec,
        pathlib.Path("/tmp/charm"),
        provider="claude",
        model="opus-4.7",
    )
    assert cmd[0] == "cantrip"
    assert "--print" in cmd
    assert spec.prompt in cmd
    assert "--provider" in cmd and "claude" in cmd
    assert "--model" in cmd and "opus-4.7" in cmd
    assert "--yolo" in cmd
    assert cmd[-1] == "/tmp/charm"


def test_build_command_omits_model_when_none():
    spec = _make_spec()
    cmd = generator.build_command(spec, pathlib.Path("/tmp/charm"), provider="gemini", model=None)
    assert "--model" not in cmd


def test_build_command_yolo_optional():
    spec = _make_spec()
    cmd = generator.build_command(
        spec, pathlib.Path("/tmp/charm"), provider="gemini", model=None, yolo=False
    )
    assert "--yolo" not in cmd


def test_generate_charm_creates_dir_and_passes_argv(tmp_path: pathlib.Path):
    spec = _make_spec()
    fake, captured = _fake_runner_factory(
        files={"charmcraft.yaml": "name: dummy\n", "src/charm.py": "# generated\n"},
    )
    result = generator.generate_charm(
        spec,
        tmp_path,
        provider="claude",
        model="opus-4.7",
        runner=fake,
    )
    assert result.success
    assert result.charm_dir.parent == tmp_path
    assert (result.charm_dir / "charmcraft.yaml").exists()
    assert (result.charm_dir / "src/charm.py").exists()

    args = list(captured["args"])
    assert args[:3] == ["cantrip", "run", "--print"]
    assert "claude" in args and "opus-4.7" in args
    assert args[-1] == str(result.charm_dir)
    assert captured["cwd"] == result.charm_dir


def test_generate_charm_propagates_failure(tmp_path: pathlib.Path):
    spec = _make_spec()
    fake, _ = _fake_runner_factory(
        returncode=2,
        stderr="provider error: bad key\n",
    )
    result = generator.generate_charm(spec, tmp_path, provider="claude", runner=fake)
    assert not result.success
    assert result.returncode == 2
    assert "provider error" in result.stderr
    # The directory still exists — the caller decides whether to drop it.
    assert result.charm_dir.is_dir()


def test_generate_and_score_chains_outputs(tmp_path: pathlib.Path):
    spec = _make_spec()
    fake, _ = _fake_runner_factory(
        files={"charmcraft.yaml": "name: dummy\n", "src/charm.py": "# generated\n"},
    )

    generation, result = runner.generate_and_score(
        spec, tmp_path, provider="claude", model="opus-4.7", runner=fake
    )
    assert generation.success
    assert result is not None
    assert result.score == result.max_score
    assert result.provider == "claude"
    assert result.model == "opus-4.7"


def test_generate_and_score_skips_score_on_empty_failure(tmp_path: pathlib.Path):
    spec = _make_spec()
    fake, _ = _fake_runner_factory(returncode=1, stderr="boom\n")

    generation, result = runner.generate_and_score(
        spec, tmp_path, provider="claude", model=None, runner=fake
    )
    assert not generation.success
    assert result is None


def test_generate_and_score_scores_partial_artefacts(tmp_path: pathlib.Path):
    """A non-zero exit with partial files still gets scored.

    The rubric is the most useful signal we have for "did the failed
    run produce *anything* worth keeping?", so the runner should not
    discard a half-finished charm just because print-mode bailed.
    """
    spec = _make_spec()
    fake, _ = _fake_runner_factory(
        returncode=1,
        stderr="timed out\n",
        files={"charmcraft.yaml": "name: dummy\n"},  # src/charm.py missing
    )

    generation, result = runner.generate_and_score(
        spec, tmp_path, provider="claude", model=None, runner=fake
    )
    assert not generation.success
    assert result is not None
    # charmcraft.yaml is critical and present; src/charm.py is missing.
    detail = {cr.criterion.name: cr.passed for cr in result.results}
    assert detail["charmcraft-yaml"] is True
    assert detail["charm-source"] is False


def test_runner_cli_generate_invokes_generator(
    tmp_path: pathlib.Path, monkeypatch, capsys: pytest.CaptureFixture[str]
):
    """End-to-end test of the ``generate`` CLI subcommand.

    Patches :func:`subprocess.run` directly so the CLI path (which
    has no ``runner`` kwarg) hits the same fake the unit tests use.
    """
    spec_dir = tmp_path / "dummy"
    spec_dir.mkdir()
    spec_file = spec_dir / "spec.yaml"
    spec_file.write_text(
        """
name: dummy
description: dummy spec for runner tests
charm_path: custom
substrate: k8s
prompt: Build a charm for the dummy workload.
rubric:
  - name: charmcraft-yaml
    description: Primary project file exists
    category: structure
    severity: critical
    check: file_exists
    args: {path: charmcraft.yaml}
""".lstrip()
    )
    fake, captured = _fake_runner_factory(files={"charmcraft.yaml": "name: dummy\n"})
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(
        "sys.argv",
        ["runner", "generate", str(spec_dir), "--provider", "claude", "--model", "opus-4.7"],
    )

    runner.main()

    out = capsys.readouterr().out
    assert "Charm directory:" in out
    assert "Command:" in out
    args = list(captured["args"])
    assert "--provider" in args and "claude" in args
