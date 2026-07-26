"""Drive Cantrip in print-mode to produce a charm directory for scoring.

Phase 79.4 turned ``score --provider X`` from a metadata-only label into
a real generation step: the runner shells out to ``cantrip run --print``
with the spec's prompt against an empty subdirectory of the spec, then
hands the result to the existing rubric scorer.

The generator is a thin wrapper around :func:`subprocess.run` so the
runner can be exercised under unit test without touching a real LLM.
Tests inject a fake ``runner`` callable that lays down a known-shape
charm tree; production callers get the default which actually invokes
Cantrip.
"""

from __future__ import annotations

import dataclasses
import datetime
import os
import re
import shlex
import subprocess
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence

    from .spec import EvalSpec


class _SubprocessRunner(Protocol):
    """Subset of :func:`subprocess.run` the generator depends on.

    The Protocol exists so tests can substitute a callable that records
    invocations and writes a synthetic charm tree without spawning a
    real process.
    """

    def __call__(
        self,
        args: Sequence[str],
        *,
        cwd: pathlib.Path | str | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
    ) -> subprocess.CompletedProcess: ...


@dataclasses.dataclass(frozen=True)
class GenerationResult:
    """Outcome of a single generation run.

    ``charm_dir`` is the directory Cantrip wrote into.  ``stdout`` and
    ``stderr`` are captured for surfacing to the developer when the run
    fails — they are *not* parsed for structured output, since print-
    mode's NDJSON event stream is the structured contract and a future
    iteration of this code may consume it directly.
    """

    charm_dir: pathlib.Path
    returncode: int
    stdout: str
    stderr: str
    command: tuple[str, ...]

    @property
    def success(self) -> bool:
        return self.returncode == 0


def slugify_model(model: str | None) -> str:
    """Reduce a model identifier to a filesystem-safe slug.

    Provider model names range from short (``opus-4.7``) to slash-laden
    (``openai/gpt-4o-mini``); the slug just needs to be unique enough
    that two adjacent runs of different models land in different
    directories without colliding with the gold-standard naming
    convention (``gold-<provider>``).
    """
    if not model:
        return "default"
    return re.sub(r"[^a-z0-9.-]+", "-", model.lower()).strip("-") or "default"


def make_charm_dir(
    spec_dir: pathlib.Path,
    *,
    provider: str,
    model: str | None,
    timestamp: datetime.datetime | None = None,
) -> pathlib.Path:
    """Pick a fresh subdirectory under *spec_dir* for one generation run.

    Naming convention: ``cantrip-<provider>-<model-slug>-<YYYYMMDD-HHMMSS>``.
    Timestamps avoid collisions across re-runs without forcing a clean-
    up step, which matters when comparing two generations of the same
    model side by side.
    """
    ts = timestamp or datetime.datetime.now(tz=datetime.UTC)
    stamp = ts.strftime("%Y%m%d-%H%M%S")
    slug = slugify_model(model)
    return spec_dir / f"cantrip-{provider}-{slug}-{stamp}"


def build_command(
    spec: EvalSpec,
    charm_dir: pathlib.Path,
    *,
    provider: str,
    model: str | None,
    cantrip_executable: str = "cantrip",
    yolo: bool = True,
    extra_args: Sequence[str] = (),
) -> list[str]:
    """Build the ``cantrip run --print …`` argv for one generation.

    ``--yolo`` is the default: print mode refuses to start when there
    are pending CONFIRM tasks, and an unattended eval can't answer
    them.  Callers that want to step through interactively should
    invoke ``cantrip run`` themselves; this helper exists for the
    headless path.
    """
    cmd: list[str] = [
        cantrip_executable,
        "run",
        "--print",
        spec.prompt,
        "--provider",
        provider,
    ]
    if model:
        cmd.extend(["--model", model])
    if yolo:
        cmd.append("--yolo")
    cmd.extend(extra_args)
    cmd.append(str(charm_dir))
    return cmd


def generate_charm(
    spec: EvalSpec,
    spec_dir: pathlib.Path,
    *,
    provider: str,
    model: str | None = None,
    cantrip_executable: str = "cantrip",
    timeout_seconds: float = 30 * 60,
    extra_args: Sequence[str] = (),
    env: dict[str, str] | None = None,
    runner: _SubprocessRunner | None = None,
    timestamp: datetime.datetime | None = None,
) -> GenerationResult:
    """Run Cantrip print-mode against *spec* and return where it landed.

    Creates a fresh subdirectory of *spec_dir* (so the generated charm
    sits next to ``gold-claude`` / ``gold-gemini`` / etc.), invokes
    ``cantrip run --print`` against the spec's prompt, and reports the
    captured stdout/stderr alongside the new directory path.  The
    caller decides whether to score the result, archive it, or discard
    it — this function is deliberately I/O only.
    """
    # Resolve to absolute so the subprocess sees the same path regardless
    # of the caller's cwd.  When ``cwd`` and the positional charm-path
    # argument were both relative, ``cantrip`` re-resolved the positional
    # against its own cwd (the new charm dir) and created a nested copy.
    charm_dir = make_charm_dir(
        spec_dir, provider=provider, model=model, timestamp=timestamp
    ).resolve()
    charm_dir.mkdir(parents=True, exist_ok=False)

    cmd = build_command(
        spec,
        charm_dir,
        provider=provider,
        model=model,
        cantrip_executable=cantrip_executable,
        extra_args=extra_args,
    )

    invoke = runner if runner is not None else subprocess.run
    completed = invoke(
        cmd,
        cwd=charm_dir,
        env=_merge_env(env),
        timeout=timeout_seconds,
        check=False,
        capture_output=True,
        text=True,
    )

    return GenerationResult(
        charm_dir=charm_dir,
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        command=tuple(cmd),
    )


def _merge_env(extra: dict[str, str] | None) -> dict[str, str] | None:
    """Layer extra env vars on top of the current process environment.

    Returning ``None`` when the caller passes nothing lets
    :func:`subprocess.run` inherit the parent env unchanged, which is
    what eval runs typically want (provider keys, ``PATH`` for the
    ``cantrip`` executable, ``UV_*`` for the project venv).
    """
    if not extra:
        return None
    merged = dict(os.environ)
    merged.update(extra)
    return merged


def shell_quote(cmd: Sequence[str]) -> str:
    """Render argv as a copy-pasteable shell command.

    Used in error messages and the howto so a developer can re-run
    exactly what the runner attempted.  ``shlex.join`` handles spaces,
    quotes, and the multi-line prompt strings the eval specs carry.
    """
    return shlex.join(cmd)
