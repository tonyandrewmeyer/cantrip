"""Public datatypes for the update-check pipeline."""

from __future__ import annotations

import dataclasses
import enum


@dataclasses.dataclass(frozen=True)
class UpdateInfo:
    """A newer release of Cantrip is available on PyPI.

    ``release_timestamp`` is an ISO-8601 string when PyPI supplied
    one (it usually does), or ``None`` when the JSON payload omitted
    the ``releases`` map — the rest of the helper still works
    without it.

    ``release_notes_markdown`` is the concatenated ``## <version>``
    sections from the project's published ``CHANGELOG.md``, newest
    first, covering everything strictly between *current* and
    *latest*.  ``None`` when the changelog couldn't be fetched
    (untagged release, network failure) or no release notes were
    found between the two versions — the upgrade prompt should
    still surface the version number even when notes are absent.

    ``installed_yanked`` is True when PyPI has marked one or more
    files of the *currently installed* version as yanked.  The UI
    layer uses this to switch the prompt's tone from "an upgrade is
    available" to "your installed version has been yanked;
    upgrading is recommended".
    """

    current: str
    latest: str
    pypi_url: str
    release_timestamp: str | None
    release_notes_markdown: str | None = None
    installed_yanked: bool = False


class InstallMethod(enum.StrEnum):
    """How the running Cantrip was installed.

    Used to surface a copy-pasteable upgrade command tailored to the
    installer.  :attr:`UNKNOWN` is returned when nothing matches —
    callers should fall back to "visit the PyPI URL" rather than
    guessing, because the wrong upgrade command is worse than no
    command at all.
    """

    UV_TOOL = "uv-tool"
    PIPX = "pipx"
    PIP_USER = "pip-user"
    PIP_VENV = "pip-venv"
    SNAP = "snap"
    UNKNOWN = "unknown"
