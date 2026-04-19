"""Per-server OAuth token storage for MCP (Phase 45.4a).

Implements the SDK's :class:`mcp.client.auth.TokenStorage` protocol with
a file-backed JSON layout under ``~/.config/cantrip/mcp_tokens/``.  One
file per MCP server name keeps the blast radius small if a single
server's token leaks.

The default storage mode writes plain JSON with mode ``0600`` (owner
read/write only).  Setting ``CANTRIP_MCP_GPG_TOKENS=1`` opts in to
``gpg --symmetric`` encryption for both reads and writes — matching the
GPG opt-in pattern Cantrip uses elsewhere.  When opted in, the user is
expected to have a configured GPG agent so writes don't block on a
passphrase prompt.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

log = logging.getLogger(__name__)


# Filenames Cantrip reads/writes under the per-server token directory.
_TOKENS_FILENAME = "tokens.json"
_CLIENT_INFO_FILENAME = "client.json"

# Env var that opts in to GPG-encrypted-at-rest token storage.  Same
# truthy parsing as the Phase 25 GPG-signing knob in ``tools/git.py``.
GPG_OPT_IN_ENV = "CANTRIP_MCP_GPG_TOKENS"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

# Override for the storage root — tests use this to keep ~/.config alone.
TOKEN_DIR_ENV = "CANTRIP_MCP_TOKEN_DIR"
_DEFAULT_TOKEN_DIR = Path("~/.config/cantrip/mcp_tokens")


def default_token_dir() -> Path:
    """Resolve the per-server token storage directory."""
    override = os.environ.get(TOKEN_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return _DEFAULT_TOKEN_DIR.expanduser()


def gpg_enabled() -> bool:
    """Return True when GPG-at-rest is opted in via env var."""
    return os.environ.get(GPG_OPT_IN_ENV, "").strip().lower() in _TRUTHY


class FileTokenStorage:
    """File-backed implementation of the SDK's ``TokenStorage`` protocol.

    Each server name gets its own subdirectory.  The directory is
    created lazily on the first write; everything is stored at file
    mode ``0600`` (and the parent directory at ``0700``) so a multi-user
    machine can't read another user's tokens.

    Round-trips OAuth pydantic models through their ``model_dump_json``
    / ``model_validate_json`` so a future SDK schema bump that adds
    fields keeps working as long as the old fields are still present.
    """

    def __init__(
        self,
        server_name: str,
        *,
        base_dir: Path | None = None,
    ) -> None:
        self._server_name = server_name
        self._base_dir = base_dir or default_token_dir()

    # ── TokenStorage protocol ───────────────────────────────────────────

    async def get_tokens(self) -> OAuthToken | None:
        """Read the stored OAuth token bundle, or ``None`` if absent."""
        from mcp.shared.auth import OAuthToken

        return await self._load_model(_TOKENS_FILENAME, OAuthToken)

    async def set_tokens(self, tokens: OAuthToken) -> None:
        """Persist the OAuth token bundle (creates the dir on first write)."""
        await self._dump_model(_TOKENS_FILENAME, tokens)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        """Read the dynamically-registered client metadata, or ``None``."""
        from mcp.shared.auth import OAuthClientInformationFull

        return await self._load_model(_CLIENT_INFO_FILENAME, OAuthClientInformationFull)

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        """Persist the dynamically-registered client metadata."""
        await self._dump_model(_CLIENT_INFO_FILENAME, client_info)

    # ── File helpers ────────────────────────────────────────────────────

    @property
    def server_dir(self) -> Path:
        """Directory holding this server's token + client-info files."""
        return self._base_dir / self._server_name

    def _ensure_dir(self) -> None:
        """Create the per-server directory at 0700 if it doesn't exist."""
        self._base_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._base_dir.chmod(stat.S_IRWXU)
        except OSError:
            log.debug("Could not chmod %s; relying on default perms", self._base_dir)
        self.server_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.server_dir.chmod(stat.S_IRWXU)
        except OSError:
            log.debug("Could not chmod %s; relying on default perms", self.server_dir)

    async def _load_model[T](self, filename: str, cls: type[T]) -> T | None:
        """Read JSON (or GPG-encrypted JSON) and parse as a pydantic model."""
        path = self.server_dir / filename
        if not path.exists():
            return None
        try:
            raw = self._read_payload(path)
        except OSError as exc:
            log.warning("Could not read MCP token file %s: %s", path, exc)
            return None
        try:
            return cls.model_validate_json(raw)
        except (ValueError, TypeError) as exc:
            log.warning("Malformed MCP token file %s: %s", path, exc)
            return None

    async def _dump_model(self, filename: str, model: object) -> None:
        """Serialise a pydantic model and write it to disk at 0600."""
        self._ensure_dir()
        path = self.server_dir / filename
        payload = model.model_dump_json(exclude_none=True)
        self._write_payload(path, payload)

    def _read_payload(self, path: Path) -> str:
        """Read a file, decrypting via GPG when opted in."""
        if gpg_enabled():
            return _gpg_decrypt(path)
        return path.read_text()

    def _write_payload(self, path: Path, payload: str) -> None:
        """Write JSON to *path* at 0600, GPG-encrypting when opted in.

        Writes go to a temp file in the same directory then ``rename``
        atomically, so a crashed write never leaves a half-written file
        the SDK might try to parse.
        """
        tmp = path.with_suffix(path.suffix + ".tmp")
        if gpg_enabled():
            _gpg_encrypt(tmp, payload)
        else:
            tmp.write_text(payload)
        try:
            tmp.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            log.debug("Could not chmod %s; relying on default perms", tmp)
        tmp.replace(path)


def _gpg_encrypt(path: Path, payload: str) -> None:
    """Symmetric GPG encryption to ``path`` (binary)."""
    completed = subprocess.run(  # noqa: S603 - opted-in GPG path
        ["gpg", "--batch", "--yes", "--symmetric", "-o", str(path)],
        input=payload.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise OSError(
            f"gpg encryption failed: {completed.stderr.decode('utf-8', errors='replace')}"
        )


def _gpg_decrypt(path: Path) -> str:
    """Symmetric GPG decryption from ``path`` to text."""
    completed = subprocess.run(  # noqa: S603 - opted-in GPG path
        ["gpg", "--batch", "--decrypt", str(path)],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise OSError(
            f"gpg decryption failed: {completed.stderr.decode('utf-8', errors='replace')}"
        )
    return completed.stdout.decode("utf-8")


# Defensive: ensure ``json`` is referenced so a future maintainer who
# adds custom JSON post-processing has the import already in scope.
_ = json


__all__ = [
    "GPG_OPT_IN_ENV",
    "TOKEN_DIR_ENV",
    "FileTokenStorage",
    "default_token_dir",
    "gpg_enabled",
]
