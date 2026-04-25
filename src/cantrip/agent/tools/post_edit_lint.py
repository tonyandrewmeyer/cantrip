"""Per-edit lint feedback for ``write_file`` / ``edit_file`` / ``multi_edit``.

After a successful file edit the dispatcher invokes
:func:`run_post_edit_diagnostics` with the touched paths.  Python
files run through ``ruff`` and ``ty``; charm-shaped YAML files
(``metadata.yaml``, ``charmcraft.yaml``, ``actions.yaml``,
``config.yaml``) trigger a single ``charmlint`` invocation against
the charm directory.  Anything reported is folded into the tool
result so the agent reacts in the same turn instead of waiting for
``make check`` to surface the issue much later.

Diagnostics are advisory: missing binaries, timeouts, and parse
failures degrade silently rather than failing the edit.  Phase 71.4.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Files that look like part of a charm and merit a ``charmlint`` pass.
# Charmlint expects a charm directory rather than individual files, so
# touching any of these triggers exactly one lint of the whole charm.
_CHARM_YAML_NAMES: frozenset[str] = frozenset(
    {
        "metadata.yaml",
        "charmcraft.yaml",
        "actions.yaml",
        "config.yaml",
        "manifest.yaml",
    }
)

# Cap each external lint at 10 s.  Ruff is sub-second on a single file,
# ``ty`` and ``charmlint`` typically a couple of seconds; the cap is the
# escape hatch for a hung subprocess, not a perf budget.
_DEFAULT_TIMEOUT_SECONDS: float = 10.0


@dataclass
class FileDiagnostic:
    """One diagnostic from a per-edit lint pass."""

    tool: str  # "ruff", "ty", "charmlint"
    file: str
    severity: str  # "error", "warning", "info"
    code: str
    message: str
    line: int | None = None
    column: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "file": self.file,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "line": self.line,
            "column": self.column,
        }

    def format_line(self) -> str:
        """Render a single diagnostic as one line of text."""
        loc = self.file
        if self.line is not None:
            loc = f"{loc}:{self.line}"
            if self.column is not None:
                loc = f"{loc}:{self.column}"
        prefix = f"[{self.tool}] {loc}: " if loc else f"[{self.tool}] "
        code = f"{self.code} " if self.code else ""
        return f"{prefix}{self.severity}: {code}{self.message}".rstrip()


@dataclass
class DiagnosticsReport:
    """Aggregate result of a per-edit lint run."""

    diagnostics: list[FileDiagnostic] = field(default_factory=list)
    # Tools that were requested but skipped (missing binary, timeout,
    # parse failure).  Surfaced in the text output so the agent knows
    # the absence of diagnostics is not the same as "all clear".
    skipped: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.diagnostics and not self.skipped

    def to_text(self) -> str:
        """Render the report as a self-contained text block."""
        if self.is_empty():
            return ""
        lines: list[str] = ["Lint diagnostics (post-edit):"]
        if self.diagnostics:
            for d in self.diagnostics:
                lines.append(f"  {d.format_line()}")
        else:
            lines.append("  (no issues found)")
        for note in self.skipped:
            lines.append(f"  [skipped] {note}")
        return "\n".join(lines)

    def to_data(self) -> dict[str, Any]:
        """Render the report as JSON-friendly structured data."""
        return {
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "skipped": list(self.skipped),
            "counts": {
                "total": len(self.diagnostics),
                "errors": sum(1 for d in self.diagnostics if d.severity == "error"),
                "warnings": sum(1 for d in self.diagnostics if d.severity == "warning"),
                "info": sum(1 for d in self.diagnostics if d.severity == "info"),
            },
        }


async def run_post_edit_diagnostics(
    paths: list[Path],
    *,
    charm_path: Path | None = None,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
) -> DiagnosticsReport:
    """Lint *paths* and return a report.

    Python files (``.py``) run through ``ruff`` and ``ty``.  Charm-
    shaped YAML files (``metadata.yaml`` etc.) trigger a single
    ``charmlint`` pass against *charm_path*.  Files outside both
    categories are ignored — the dispatcher pays nothing for editing
    a README.

    Returning an empty report means "nothing relevant touched, or all
    clean".  Errors from the underlying tools (missing binary,
    timeout, malformed JSON) become entries in
    :attr:`DiagnosticsReport.skipped` so the agent sees an explicit
    "I tried, here's why I have nothing".
    """
    report = DiagnosticsReport()

    py_files = [p for p in paths if p.suffix == ".py" and p.is_file()]
    yaml_files = [p for p in paths if p.name in _CHARM_YAML_NAMES and p.is_file()]

    coros: list[Any] = []
    if py_files:
        coros.append(_run_ruff(py_files, timeout=timeout))
        coros.append(_run_ty(py_files, timeout=timeout))
    if yaml_files and charm_path is not None and charm_path.is_dir():
        coros.append(_run_charmlint(charm_path, timeout=timeout))

    if not coros:
        return report

    results = await asyncio.gather(*coros, return_exceptions=True)
    for outcome in results:
        if isinstance(outcome, BaseException):
            log.warning("Post-edit diagnostics task failed: %s", outcome)
            report.skipped.append(f"diagnostics task crashed: {outcome}")
            continue
        sub_report: DiagnosticsReport = outcome
        report.diagnostics.extend(sub_report.diagnostics)
        report.skipped.extend(sub_report.skipped)

    return report


async def _run_ruff(files: list[Path], *, timeout: float) -> DiagnosticsReport:
    """Run ``ruff check --output-format json`` on *files*."""
    binary = shutil.which("ruff")
    if binary is None:
        return DiagnosticsReport(skipped=["ruff: binary not found on PATH"])

    cmd = [binary, "check", "--output-format", "json", "--force-exclude", *(str(f) for f in files)]
    stdout, _stderr, error = await _run_subprocess(cmd, timeout=timeout)
    if error is not None:
        return DiagnosticsReport(skipped=[f"ruff: {error}"])

    try:
        payload = json.loads(stdout or "[]")
    except json.JSONDecodeError as exc:
        return DiagnosticsReport(skipped=[f"ruff: malformed JSON output ({exc})"])

    diagnostics: list[FileDiagnostic] = []
    for item in payload:
        location = item.get("location") or {}
        diagnostics.append(
            FileDiagnostic(
                tool="ruff",
                file=str(item.get("filename", "")),
                severity=item.get("severity", "warning"),
                code=str(item.get("code") or ""),
                message=str(item.get("message", "")),
                line=location.get("row"),
                column=location.get("column"),
            )
        )
    return DiagnosticsReport(diagnostics=diagnostics)


async def _run_ty(files: list[Path], *, timeout: float) -> DiagnosticsReport:
    """Run ``ty check --output-format=concise`` on *files*.

    ``ty`` does not emit JSON yet (only ``full`` / ``concise`` /
    ``gitlab`` / ``github``) so we parse the concise human format
    instead.  Each diagnostic is one line:
    ``<path>:<line>:<col>: <severity>[<rule>] <message>``.
    """
    binary = shutil.which("ty")
    if binary is None:
        return DiagnosticsReport(skipped=["ty: binary not found on PATH"])

    cmd = [binary, "check", "--output-format=concise", *(str(f) for f in files)]
    stdout, stderr, error = await _run_subprocess(cmd, timeout=timeout)
    if error is not None:
        return DiagnosticsReport(skipped=[f"ty: {error}"])

    diagnostics: list[FileDiagnostic] = []
    for raw_line in (stdout or "").splitlines():
        parsed = _parse_ty_line(raw_line)
        if parsed is not None:
            diagnostics.append(parsed)

    # ``ty`` writes the "All checks passed!" / "Found N diagnostic"
    # summary to stdout; the parser ignores those lines because they
    # don't match the diagnostic shape.  Surface stderr only when we
    # got nothing parseable and ty actually complained.
    if not diagnostics and stderr and "error" in stderr.lower():
        return DiagnosticsReport(skipped=[f"ty: {stderr.splitlines()[0][:200]}"])

    return DiagnosticsReport(diagnostics=diagnostics)


def _parse_ty_line(line: str) -> FileDiagnostic | None:
    """Parse one ``ty`` concise output line into a diagnostic.

    Format: ``<path>:<line>:<col>: <severity>[<rule>] <message>``.
    Lines that don't match are returned as ``None`` so summary lines
    like ``Found 1 diagnostic`` get filtered out.
    """
    # Quick reject for non-diagnostic lines.
    if ": " not in line or line.startswith("Found ") or line == "All checks passed!":
        return None

    # Split on the first three ":" to peel off path / line / col.
    parts = line.split(":", 3)
    if len(parts) < 4:
        return None
    path, line_str, col_str, rest = parts
    if not (line_str.isdigit() and col_str.isdigit()):
        return None

    rest = rest.strip()
    severity = "error"
    code = ""
    for marker in ("error", "warning", "info"):
        if rest.startswith(marker):
            severity = marker
            rest = rest[len(marker) :].lstrip()
            break

    if rest.startswith("[") and "]" in rest:
        end = rest.index("]")
        code = rest[1:end]
        rest = rest[end + 1 :].lstrip()

    return FileDiagnostic(
        tool="ty",
        file=path,
        severity=severity,
        code=code,
        message=rest,
        line=int(line_str),
        column=int(col_str),
    )


async def _run_charmlint(charm_dir: Path, *, timeout: float) -> DiagnosticsReport:
    """Run charmlint against *charm_dir*.

    Prefers the Rust binary when available — same probe as
    :class:`cantrip.agent.tools.charmlint_tool.CharmlintTool` — and
    falls back to the Python library on any failure.  We do not call
    the agent tool directly because it returns a ``ToolResult``
    shaped for the LLM; the structured ``data`` is enough for our
    purposes.
    """
    binary = _find_charmlint_binary()
    if binary is not None:
        cmd = [binary, str(charm_dir), "--format", "json"]
        stdout, _stderr, error = await _run_subprocess(cmd, timeout=timeout)
        if error is None:
            try:
                payload = json.loads(stdout or "{}")
            except json.JSONDecodeError as exc:
                log.debug("charmlint Rust output unparseable, falling back: %s", exc)
                return await asyncio.to_thread(_charmlint_python, charm_dir)
            return _charmlint_report_from_payload(payload)
        log.debug("charmlint Rust binary failed (%s); falling back to Python", error)

    return await asyncio.to_thread(_charmlint_python, charm_dir)


def _find_charmlint_binary() -> str | None:
    """Return the Rust charmlint binary path, mirroring the agent tool."""
    rust_bin = shutil.which("charmlint-rs")
    if rust_bin:
        return rust_bin
    import cantrip

    pkg_dir = Path(cantrip.__file__).resolve().parent
    candidate = pkg_dir.parent.parent / "charmlint-rs" / "target" / "release" / "charmlint"
    if candidate.is_file():
        return str(candidate)
    return None


def _charmlint_python(charm_dir: Path) -> DiagnosticsReport:
    """Run the Python charmlint library and convert its report."""
    try:
        from charmlint import LintConfig, lint
    except ImportError:
        return DiagnosticsReport(skipped=["charmlint: library not installed"])

    try:
        report = lint(charm_dir, LintConfig())
    except (OSError, ValueError, RuntimeError) as exc:
        return DiagnosticsReport(skipped=[f"charmlint: {exc}"])

    diagnostics: list[FileDiagnostic] = []
    for d in report.diagnostics:
        diagnostics.append(
            FileDiagnostic(
                tool="charmlint",
                file=str(getattr(d, "path", "")),
                severity=str(getattr(d, "severity", "warning")),
                code=str(getattr(d, "rule_id", "")),
                message=str(getattr(d, "message", "")),
                line=getattr(d, "line", None),
            )
        )
    return DiagnosticsReport(diagnostics=diagnostics)


def _charmlint_report_from_payload(payload: dict[str, Any]) -> DiagnosticsReport:
    """Convert the Rust binary's JSON payload into a diagnostics report."""
    diagnostics: list[FileDiagnostic] = []
    for item in payload.get("diagnostics", []):
        diagnostics.append(
            FileDiagnostic(
                tool="charmlint",
                file=str(item.get("path", "")),
                severity=str(item.get("severity", "warning")),
                code=str(item.get("rule_id", "")),
                message=str(item.get("message", "")),
                line=item.get("line"),
            )
        )
    return DiagnosticsReport(diagnostics=diagnostics)


async def _run_subprocess(cmd: list[str], *, timeout: float) -> tuple[str, str, str | None]:
    """Run *cmd* and return ``(stdout, stderr, error)``.

    *error* is ``None`` on success (which includes non-zero exit
    codes — linters use exit code to signal "found issues", not
    "broken").  A returned error string indicates the subprocess
    itself failed (missing binary, timeout, OS error) and the caller
    should surface a "skipped" note rather than diagnostics.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        return "", "", str(exc)

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        return "", "", f"timed out after {timeout:.0f}s"

    return stdout_bytes.decode(errors="replace"), stderr_bytes.decode(errors="replace"), None


def collect_touched_paths(
    tool_name: str, arguments: dict[str, Any], base_path: Path | None
) -> list[Path]:
    """Extract resolved file paths from a successful edit-tool call.

    Resolves against *base_path* when the argument is relative — the
    file tools all use ``PathAwareTool`` so the contract matches.
    Returns an empty list for tools that don't shape like an edit
    or for malformed arguments — never raises.
    """
    raw_paths: list[str] = []
    if tool_name in ("write_file", "edit_file"):
        path = arguments.get("path")
        if isinstance(path, str) and path:
            raw_paths.append(path)
    elif tool_name == "multi_edit":
        edits = arguments.get("edits")
        if isinstance(edits, list):
            seen: set[str] = set()
            for edit in edits:
                if not isinstance(edit, dict):
                    continue
                file = edit.get("file")
                if isinstance(file, str) and file and file not in seen:
                    seen.add(file)
                    raw_paths.append(file)

    resolved: list[Path] = []
    for raw in raw_paths:
        candidate = Path(raw)
        if not candidate.is_absolute() and base_path is not None:
            candidate = base_path / raw
        try:
            resolved.append(candidate.resolve())
        except (OSError, RuntimeError):
            # Resolution can raise on symlink loops or unreadable
            # parents; skip rather than crash the post-edit hook.
            continue
    return resolved
