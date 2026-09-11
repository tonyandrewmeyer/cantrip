"""Tests for ``share_to_gist`` — the ``/share`` upload helper (Phase 114.1).

``share_to_gist`` is a promise never to raise: whatever goes wrong —
an unreadable session file, a full ``/tmp``, a missing or unauthenticated
``gh`` — the user gets a sentence they can act on and the session keeps
going.  Every branch here exists to prove that promise holds, and that
the fallbacks always hand back the local HTML path so nothing the user
wanted to share is lost.

The dispatcher-level ``/share`` tests (charm-path short-circuits, the
"Uploading…" prelude) live in ``test_slash.py`` with the rest of the
dispatch contract.
"""

from __future__ import annotations

import contextlib
import pathlib
from typing import TYPE_CHECKING, Any
from unittest import mock

from cantrip.agent.commands import share as share_commands

if TYPE_CHECKING:
    from collections.abc import Iterator


def _fake_gh(*, returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> mock.MagicMock:
    """Build a process double whose ``communicate`` returns fixed bytes."""
    proc = mock.MagicMock()
    proc.returncode = returncode

    async def _communicate() -> tuple[bytes, bytes]:
        return stdout, stderr

    proc.communicate = _communicate
    return proc


@contextlib.contextmanager
def _transcript_renders(content: str = "<html/>") -> Iterator[None]:
    """Patch the lazily-imported transcript pipeline to a fixed payload."""
    with (
        mock.patch("cantrip.transcript.export.load_transcript", return_value={}),
        mock.patch("cantrip.transcript.html.render_html", return_value=content),
    ):
        yield


@contextlib.contextmanager
def _gh_available(proc: mock.MagicMock | None, *, launch_error: Exception | None = None):
    """Pretend ``gh`` is on PATH and control what launching it does."""
    with (
        mock.patch("cantrip.agent.commands.share.shutil.which", return_value="/usr/bin/gh"),
        mock.patch("cantrip.agent.commands.share.asyncio.create_subprocess_exec") as exec_mock,
    ):

        async def _spawn(*_args: Any, **_kwargs: Any) -> mock.MagicMock:
            if launch_error is not None:
                raise launch_error
            assert proc is not None
            return proc

        exec_mock.side_effect = _spawn
        yield


def _charm(tmp_path: pathlib.Path) -> pathlib.Path:
    charm_path = tmp_path / "charm"
    charm_path.mkdir()
    (charm_path / ".cantrip").write_bytes(b"sqlite-placeholder")
    return charm_path


class TestHappyPath:
    async def test_returns_the_gist_url(self, tmp_path: pathlib.Path) -> None:
        charm_path = _charm(tmp_path)
        proc = _fake_gh(returncode=0, stdout=b"https://gist.github.com/user/abc123\n")
        with _transcript_renders(), _gh_available(proc):
            result = await share_commands.share_to_gist(charm_path / ".cantrip", charm_path)
        assert "https://gist.github.com/user/abc123" in result

    async def test_url_is_taken_from_the_last_http_line(self, tmp_path: pathlib.Path) -> None:
        """Older ``gh`` releases print a progress preamble before the URL."""
        charm_path = _charm(tmp_path)
        proc = _fake_gh(
            returncode=0,
            stdout=b"- Creating secret gist...\nhttps://gist.github.com/user/zzz\n",
        )
        with _transcript_renders(), _gh_available(proc):
            result = await share_commands.share_to_gist(charm_path / ".cantrip", charm_path)
        assert "https://gist.github.com/user/zzz" in result

    async def test_tempfile_is_cleaned_up_after_a_successful_upload(
        self, tmp_path: pathlib.Path
    ) -> None:
        charm_path = _charm(tmp_path)
        proc = _fake_gh(returncode=0, stdout=b"https://gist.github.com/user/abc\n")
        with (
            _transcript_renders(),
            _gh_available(proc),
            mock.patch.object(pathlib.Path, "unlink", autospec=True) as unlink,
        ):
            await share_commands.share_to_gist(charm_path / ".cantrip", charm_path)
        assert unlink.call_count == 1

    async def test_unlink_failure_does_not_lose_the_url(self, tmp_path: pathlib.Path) -> None:
        """A leaked tempfile is a tidiness problem, not a user-facing one."""
        charm_path = _charm(tmp_path)
        proc = _fake_gh(returncode=0, stdout=b"https://gist.github.com/user/abc\n")
        with (
            _transcript_renders(),
            _gh_available(proc),
            mock.patch.object(
                pathlib.Path, "unlink", autospec=True, side_effect=OSError("read-only fs")
            ),
        ):
            result = await share_commands.share_to_gist(charm_path / ".cantrip", charm_path)
        assert "https://gist.github.com/user/abc" in result


class TestFailurePaths:
    async def test_render_failure_is_reported_not_raised(self, tmp_path: pathlib.Path) -> None:
        charm_path = _charm(tmp_path)
        with mock.patch(
            "cantrip.transcript.export.load_transcript",
            side_effect=ValueError("not a cantrip database"),
        ):
            result = await share_commands.share_to_gist(charm_path / ".cantrip", charm_path)
        assert "Failed to render transcript" in result
        assert "not a cantrip database" in result

    async def test_tempfile_write_failure_is_reported(self, tmp_path: pathlib.Path) -> None:
        charm_path = _charm(tmp_path)
        with (
            _transcript_renders(),
            mock.patch(
                "cantrip.agent.commands.share.tempfile.NamedTemporaryFile",
                side_effect=OSError("No space left on device"),
            ),
        ):
            result = await share_commands.share_to_gist(charm_path / ".cantrip", charm_path)
        assert "Failed to write temp transcript" in result
        assert "No space left on device" in result

    async def test_gh_missing_falls_back_to_a_local_path(self, tmp_path: pathlib.Path) -> None:
        charm_path = _charm(tmp_path)
        with (
            _transcript_renders(),
            mock.patch("cantrip.agent.commands.share.shutil.which", return_value=None),
        ):
            result = await share_commands.share_to_gist(charm_path / ".cantrip", charm_path)
        assert "`gh` is not installed" in result
        assert "gh gist create" in result
        assert "cantrip-session-charm-" in result

    async def test_gh_launch_failure_keeps_the_local_path(self, tmp_path: pathlib.Path) -> None:
        """``which`` found it, then ``exec`` failed — a race or a bad shim."""
        charm_path = _charm(tmp_path)
        with (
            _transcript_renders(),
            _gh_available(None, launch_error=OSError("Exec format error")),
        ):
            result = await share_commands.share_to_gist(charm_path / ".cantrip", charm_path)
        assert "Failed to launch `gh`" in result
        assert "Exec format error" in result
        assert "cantrip-session-charm-" in result

    async def test_auth_failure_surfaces_stderr_and_the_retry_command(
        self, tmp_path: pathlib.Path
    ) -> None:
        charm_path = _charm(tmp_path)
        proc = _fake_gh(
            returncode=4,
            stderr=b"You are not logged into any GitHub hosts. Run gh auth login\n",
        )
        with _transcript_renders(), _gh_available(proc):
            result = await share_commands.share_to_gist(charm_path / ".cantrip", charm_path)
        assert "Failed to upload gist" in result
        assert "gh auth login" in result
        assert "gh gist create" in result

    async def test_silent_nonzero_exit_reports_the_code(self, tmp_path: pathlib.Path) -> None:
        charm_path = _charm(tmp_path)
        with _transcript_renders(), _gh_available(_fake_gh(returncode=7)):
            result = await share_commands.share_to_gist(charm_path / ".cantrip", charm_path)
        assert "`gh` exited with code 7" in result

    async def test_unparseable_success_output_shows_the_raw_text(
        self, tmp_path: pathlib.Path
    ) -> None:
        charm_path = _charm(tmp_path)
        proc = _fake_gh(returncode=0, stdout=b"created gist abc123\n")
        with _transcript_renders(), _gh_available(proc):
            result = await share_commands.share_to_gist(charm_path / ".cantrip", charm_path)
        assert "could not parse a URL" in result
        assert "created gist abc123" in result


class TestGistDescription:
    async def test_description_names_the_charm_directory(self, tmp_path: pathlib.Path) -> None:
        charm_path = _charm(tmp_path)
        with (
            _transcript_renders(),
            mock.patch("cantrip.agent.commands.share.shutil.which", return_value=None),
        ):
            result = await share_commands.share_to_gist(charm_path / ".cantrip", charm_path)
        assert "Cantrip session — charm — " in result

    async def test_root_path_falls_back_to_the_project_name(self, tmp_path: pathlib.Path) -> None:
        """``pathlib.Path("/").name`` is empty — the gist still needs a label."""
        with (
            _transcript_renders(),
            mock.patch("cantrip.agent.commands.share.shutil.which", return_value=None),
        ):
            result = await share_commands.share_to_gist(tmp_path / ".cantrip", pathlib.Path("/"))
        assert "Cantrip session — cantrip — " in result
