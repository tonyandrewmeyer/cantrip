"""``/share`` — upload the live session as a secret GitHub gist.

The slash dispatcher constructs the immediate "Uploading…" prelude
itself so this module is free of :class:`SlashResult` and can stay
purely an async helper.  Lifted out of the dispatcher in Phase 85.3.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import pathlib
import shlex
import shutil
import tempfile

log = logging.getLogger(__name__)


async def share_to_gist(db_path: pathlib.Path, charm_path: pathlib.Path) -> str:
    """Export to HTML and upload via ``gh gist create``.

    On ``gh`` absence or auth failure, write the HTML locally and
    return a message containing the path + the exact ``gh`` command
    the user can run manually.  The session is never blocked — every
    error path returns a human-readable string.
    """
    # Import lazily so the slash module stays importable even when the
    # renderer's optional deps are unusual.
    from cantrip.transcript import export as transcript_export
    from cantrip.transcript.html import render_html

    try:
        data = transcript_export.load_transcript(db_path)
        content = render_html(data)
    except (OSError, ValueError, RuntimeError) as exc:
        return f"_Failed to render transcript: {exc}._"

    timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    charm_name = charm_path.name or "cantrip"
    description = f"Cantrip session — {charm_name} — {timestamp}"

    # Write into a tempfile the subprocess call can read.  Use the
    # charm name as a prefix so the gist's default filename is
    # discoverable rather than being a random hex string.
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f"cantrip-session-{charm_name}-",
            suffix=".html",
            delete=False,
        ) as tmp:
            tmp.write(content.encode("utf-8"))
            tmp_path = pathlib.Path(tmp.name)
    except OSError as exc:
        return f"_Failed to write temp transcript: {exc}._"

    if not shutil.which("gh"):
        return (
            f"`gh` is not installed — transcript written to `{tmp_path}`.\n\n"
            f"Install GitHub CLI and run:\n\n"
            f"```\ngh gist create --desc {shlex.quote(description)} {shlex.quote(str(tmp_path))}\n```"
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            "gh",
            "gist",
            "create",
            "--desc",
            description,
            str(tmp_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
    except (OSError, FileNotFoundError) as exc:
        return (
            f"_Failed to launch `gh`: {exc}._ Transcript written to "
            f"`{tmp_path}` — upload manually with the `gh gist create` "
            f"command."
        )

    stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        # gh auth status failure is the common case — the stderr
        # carries the hint, so surface it verbatim.
        hint = stderr or f"`gh` exited with code {proc.returncode}"
        return (
            f"_Failed to upload gist: {hint}._ Transcript written to "
            f"`{tmp_path}` — run `gh auth login` and retry with:\n\n"
            f"```\ngh gist create --desc {shlex.quote(description)} {shlex.quote(str(tmp_path))}\n```"
        )

    # ``gh gist create`` prints the URL on the last non-empty stdout
    # line; older versions include a progress preamble.
    url = next(
        (line for line in reversed(stdout.splitlines()) if line.strip().startswith("http")),
        "",
    )
    if not url:
        return (
            f"Uploaded, but could not parse a URL from `gh` output. "
            f"Raw output:\n\n```\n{stdout}\n```"
        )

    # Clean up the local tempfile now that the gist is live — leaving
    # it behind would gradually fill /tmp and the user has the URL.
    try:
        tmp_path.unlink()
    except OSError:
        log.debug("Failed to unlink temp transcript %s", tmp_path, exc_info=True)

    return f"Shared session as a secret gist: {url}"
