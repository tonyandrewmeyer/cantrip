"""Per-turn working-tree snapshots feeding ``/undo`` and ``/redo`` (Phase 68.1).

The agent edits user files between every conversation turn.  Without a
recovery affordance, the only escape from a botched edit is ``git
restore`` by hand — and that only works when the user's tree is itself a
git repo.  :class:`SnapshotManager` solves this by taking one git
commit per user turn into a *separate*, hidden snapshot repository,
keyed off the absolute charm path.

Design notes:

* The snapshot repo lives under ``$XDG_STATE_HOME/cantrip/snapshots/<hash>/``
  (falling back to ``~/.local/state/...``) — out of the user's tree so
  ``git status`` and ``git clean`` in the charm don't see it, and so it
  survives ``rm -rf`` of the working dir.
* One snapshot per *user turn*, taken just before the user's message
  enters ``state.messages``.  The commit SHA is stamped onto
  :attr:`Message.metadata` so ``/undo`` can map the last user message
  back to "the state of the tree right before that turn ran".
* ``/undo`` first takes a *pre-restore* snapshot of the current dirt so
  ``git reset --hard <target>`` can cleanly remove files the agent
  added during the turn being undone.  That pre-restore SHA + the
  stripped messages live on an in-memory redo stack.
* The redo stack is *not* persisted — re-applying a stale undo across
  restarts is too easy a footgun to expose by default.

Files outside the charm root (memory writes, the ``.cantrip/`` session
store, Phase 44 ``.cantrip-worktrees/``) are excluded via the snapshot
repo's ``info/exclude`` so they survive a restore unchanged.
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
import os
import pathlib
import shutil
import subprocess
from typing import TYPE_CHECKING

from cantrip.ui import events as ui_events

if TYPE_CHECKING:
    from cantrip.llm.base import Message

log = logging.getLogger(__name__)

#: Environment-variable opt-out for Phase 68.1 snapshots.  Truthy values
#: keep the default (snapshots on); falsy values disable.  Mirrors the
#: ``--no-snapshots`` CLI flag so operators have a single answer to "how
#: do I turn this off in CI / a monorepo".
ENV_SNAPSHOTS = "CANTRIP_SNAPSHOTS"

_FALSY = frozenset({"0", "false", "no", "off"})


def snapshots_enabled(*, no_snapshots_flag: bool = False) -> bool:
    """Resolve the effective snapshot-enabled bool from CLI flag + env.

    The CLI flag wins when set; otherwise ``CANTRIP_SNAPSHOTS=false``
    (and friends) flips the default off.  Anything else — unset env,
    truthy env, ``--no-snapshots`` absent — leaves snapshots on.
    """
    if no_snapshots_flag:
        return False
    raw = os.environ.get(ENV_SNAPSHOTS)
    return not (raw is not None and raw.strip().lower() in _FALSY)


# Same envelope as ``cantrip.agent.tools.git._run_git``: short for local
# git operations, long for any path that might block on disk I/O.  We
# never hit the network from the snapshot repo so one timeout suffices.
_GIT_TIMEOUT = 60

# Identity stamped on every snapshot commit.  Picked so it's obvious in
# ``git log`` of the snapshot repo that these are machine-generated and
# not the user's own commits.
_SNAPSHOT_AUTHOR_NAME = "Cantrip Snapshot"
_SNAPSHOT_AUTHOR_EMAIL = "cantrip@localhost"

# Identity is injected per-invocation via ``-c`` flags rather than
# written into the snapshot repo's ``.git/config``.  Persisting it
# was a footgun: a stray ``git config`` call running in the wrong
# directory could land the snapshot identity in a *user* repo's
# config and silently rewrite the author on subsequent commits.
# Per-invocation ``-c`` keeps the identity scoped to the single
# subprocess and writes nothing to disk.  ``commit.gpgsign=false``
# rides along so users with a global ``commit.gpgsign = true`` don't
# hit a passphrase prompt every snapshot.
_IDENTITY_CONFIG = (
    "-c",
    f"user.name={_SNAPSHOT_AUTHOR_NAME}",
    "-c",
    f"user.email={_SNAPSHOT_AUTHOR_EMAIL}",
    "-c",
    "commit.gpgsign=false",
)

# Files inside the charm root that must never be snapshotted: the
# session store (``.cantrip/`` SQLite + JSONL) and Phase 44 worktrees
# (``.cantrip-worktrees/`` git worktrees for parallel subagents).
# Restoring either would corrupt agent state that lives outside the
# turn-by-turn working-tree contract.
_EXCLUDE_PATTERNS = (
    ".cantrip",
    ".cantrip/",
    ".cantrip-worktrees",
    ".cantrip-worktrees/",
)


@dataclasses.dataclass
class _UndoneTurn:
    """One entry on the in-memory redo stack."""

    # Snapshot SHA the working tree was at the moment ``/undo`` ran.
    # ``/redo`` resets back to this so any agent-side mutations made
    # during the undone turn are restored verbatim.
    redo_sha: str

    # Messages that were sliced off ``state.messages`` and out of the
    # SQLite ``messages`` table.  Restored in order on ``/redo``.
    removed_messages: list[Message]


def _snapshot_root() -> pathlib.Path:
    """Return the parent directory under which per-charm snapshot repos live.

    Honours ``XDG_STATE_HOME`` so users who relocate their state
    directory keep their snapshots there; falls back to the
    XDG-spec default ``~/.local/state/cantrip/snapshots``.
    """
    xdg = os.environ.get("XDG_STATE_HOME")
    base = pathlib.Path(xdg) if xdg else pathlib.Path.home() / ".local" / "state"
    return base / "cantrip" / "snapshots"


def _charm_key(charm_path: pathlib.Path) -> str:
    """Return a short, filesystem-safe key for *charm_path*.

    ``sha256`` of the absolute path, truncated to 16 hex chars.  Two
    charms in different directories never collide; the same charm
    moved to a new path gets a fresh snapshot history (which is the
    correct behaviour — undoing across a relocation would be
    surprising at best, destructive at worst).
    """
    abs_path = str(charm_path.resolve())
    return hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:16]


class SnapshotManager:
    """Per-charm snapshot repository plus undo/redo bookkeeping.

    One instance per :class:`CantripAgent`; constructed when the agent
    has a charm path and ``state.snapshot_enabled`` is true.  Lazily
    initialises the snapshot repo on first :meth:`snapshot_turn` so
    sessions that never type a message don't pay the init cost.
    """

    def __init__(
        self,
        charm_path: pathlib.Path,
        *,
        event_bus: ui_events.EventBus | None = None,
        state_root: pathlib.Path | None = None,
    ):
        self._charm_path = charm_path.resolve()
        self._event_bus = event_bus
        self._repo_path = (state_root or _snapshot_root()) / _charm_key(self._charm_path)
        self._git_dir = self._repo_path / ".git"
        self._initialised = False
        self._redo_stack: list[_UndoneTurn] = []

    # ── Repo lifecycle ───────────────────────────────────────────────

    def _ensure_repo(self) -> bool:
        """Lazily create the snapshot repo if it does not exist.

        Returns True on success, False if git is unavailable or the
        repo could not be created.  Caller treats False as "skip
        snapshotting" — the agent must keep running even when undo
        history is unavailable.
        """
        if self._initialised:
            return True
        if not shutil.which("git"):
            log.info("Snapshot manager disabled: git not found on PATH")
            return False
        try:
            self._repo_path.mkdir(parents=True, exist_ok=True)
            if not self._git_dir.is_dir():
                init = self._run_raw(["init", "--quiet", str(self._repo_path)])
                if init.returncode != 0:
                    log.warning(
                        "Snapshot repo init failed at %s: %s",
                        self._repo_path,
                        init.stderr.strip(),
                    )
                    return False
                # Identity rides on every git invocation via ``-c``
                # (see ``_IDENTITY_CONFIG``) so no ``git config`` call
                # can leak into the surrounding repo.  The exclude
                # file still lives in ``info/exclude`` because the
                # user's own .gitignore is honoured automatically.
                self._write_exclude()
                # Empty initial commit guarantees HEAD exists so every
                # subsequent ``reset --hard`` has something to anchor
                # against.
                self._run(
                    ["commit", "--quiet", "--allow-empty", "-m", "init"],
                )
            self._initialised = True
            return True
        except OSError as exc:
            log.warning("Snapshot repo init failed: %s", exc)
            return False

    def _write_exclude(self) -> None:
        """Seed the snapshot repo's ``info/exclude`` with cantrip-internal paths.

        Charm-author ``.gitignore`` files inside the working tree are
        honoured automatically; this file adds the entries that
        wouldn't make sense for the user to declare themselves.
        """
        exclude_path = self._git_dir / "info" / "exclude"
        try:
            exclude_path.parent.mkdir(parents=True, exist_ok=True)
            exclude_path.write_text(
                "# Cantrip-managed exclusions.\n" + "\n".join(_EXCLUDE_PATTERNS) + "\n",
            )
        except OSError as exc:
            log.warning("Failed to write snapshot exclude file: %s", exc)

    # ── Snapshot / restore primitives ────────────────────────────────

    def snapshot_turn(self, turn_id: str) -> str | None:
        """Capture a snapshot of the current working tree.

        Returns the resulting commit SHA, or ``None`` if snapshotting
        was unavailable / failed (the agent treats either as "no undo
        for this turn" and keeps going).  ``turn_id`` lands in the
        commit message verbatim so ``git log`` of the snapshot repo
        is human-readable.
        """
        if not self._ensure_repo():
            return None
        # ``add -A`` honours .gitignore plus our info/exclude, so the
        # user's checked-in ignore rules cascade automatically.
        add = self._run(["add", "-A"])
        if add.returncode != 0:
            log.warning("Snapshot add failed: %s", add.stderr.strip())
            return None
        commit = self._run(
            [
                "commit",
                "--quiet",
                "--allow-empty",
                "-m",
                f"snapshot: turn {turn_id}",
            ],
        )
        if commit.returncode != 0:
            log.warning("Snapshot commit failed: %s", commit.stderr.strip())
            return None
        sha = self._head_sha()
        if sha is not None and self._event_bus is not None:
            try:
                self._event_bus.publish(ui_events.snapshot_created(turn_id=turn_id, sha=sha))
            except Exception:  # noqa: BLE001 — UI failure must not break snapshots.
                log.debug("Failed to publish snapshot_created event", exc_info=True)
        return sha

    def restore(self, target_sha: str, *, direction: str) -> int | None:
        """Hard-reset the working tree to *target_sha*.

        Returns the count of paths git touched on the way back, or
        ``None`` if the restore could not be performed.  *direction*
        is ``"undo"`` or ``"redo"``; it propagates onto the
        ``snapshot_restored`` UI event so transcripts can label which
        op landed at this SHA.

        The current working tree is staged before the reset so files
        the agent created mid-turn (and that aren't yet snapshotted
        in HEAD) get cleaned up — ``git reset --hard`` only deletes
        *tracked* paths that don't exist in the target tree.
        """
        if not self._ensure_repo():
            return None
        # Stage current state so any post-snapshot dirt is tracked
        # against the snapshot repo's HEAD; reset --hard then has
        # something to remove when the target tree omits those paths.
        self._run(["add", "-A"])
        # Count what will move so the slash command can report
        # "restored N files" without re-running git.
        diff = self._run(["diff", "--name-only", "HEAD", target_sha])
        paths_changed = (
            len([line for line in diff.stdout.splitlines() if line.strip()])
            if diff.returncode == 0
            else 0
        )
        reset = self._run(["reset", "--hard", target_sha])
        if reset.returncode != 0:
            log.warning(
                "Snapshot restore to %s failed: %s",
                target_sha[:8],
                reset.stderr.strip(),
            )
            return None
        if self._event_bus is not None:
            try:
                self._event_bus.publish(
                    ui_events.snapshot_restored(
                        sha=target_sha,
                        paths_changed=paths_changed,
                        direction=direction,
                    )
                )
            except Exception:  # noqa: BLE001 — UI failure must not break restore.
                log.debug("Failed to publish snapshot_restored event", exc_info=True)
        return paths_changed

    def previous_snapshot(self, sha: str) -> str | None:
        """Return the SHA of the snapshot immediately before *sha*.

        Used by ``/undo`` when the user wants to roll back the most
        recent turn — *sha* is the commit taken just before that
        turn started, and we want the one taken before the turn
        *prior to that*.  Returns ``None`` when *sha* is the initial
        commit (nothing earlier to roll back to).
        """
        if not self._ensure_repo():
            return None
        result = self._run(["rev-parse", f"{sha}^"])
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _head_sha(self) -> str | None:
        """Return the snapshot repo's current HEAD SHA, or None on error."""
        result = self._run(["rev-parse", "HEAD"])
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    # ── Redo stack ───────────────────────────────────────────────────

    def push_undone(self, redo_sha: str, removed_messages: list[Message]) -> None:
        """Push a freshly-undone turn onto the redo stack.

        *redo_sha* is the snapshot SHA of "current state at /undo
        time" — restoring it brings back the agent's mid-turn work.
        *removed_messages* is the slice of ``state.messages`` that
        was truncated, in original order.
        """
        self._redo_stack.append(_UndoneTurn(redo_sha=redo_sha, removed_messages=removed_messages))

    def pop_undone(self) -> _UndoneTurn | None:
        """Pop the most recently undone turn, or ``None`` if the stack is empty."""
        if not self._redo_stack:
            return None
        return self._redo_stack.pop()

    def clear_redo(self) -> None:
        """Drop all pending redo entries.

        Called when a new user turn arrives — once the user has spoken
        again, re-applying an old ``/undo`` would land in a context
        that no longer matches the conversation, so the right thing
        is to forget those redo entries entirely.
        """
        self._redo_stack.clear()

    @property
    def redo_depth(self) -> int:
        """Number of pending redo entries — surfaces in ``/undo`` reporting."""
        return len(self._redo_stack)

    # ── Subprocess wrapper ───────────────────────────────────────────

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Run a git command against the snapshot repo's working tree.

        Both ``--git-dir`` and ``--work-tree`` are passed so the
        operation targets the snapshot repo's history but reads /
        writes the user's charm tree.  Used for commit, add, reset,
        diff, rev-parse and friends.  Identity is injected via
        ``_IDENTITY_CONFIG`` so commits never depend on (or write
        to) any persistent ``user.name`` / ``user.email`` config.
        """
        cmd = [
            "git",
            *_IDENTITY_CONFIG,
            f"--git-dir={self._git_dir}",
            f"--work-tree={self._charm_path}",
            *args,
        ]
        return self._invoke(cmd)

    def _run_raw(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Run git with only the identity flags pre-pended (used for ``init``)."""
        return self._invoke(["git", *_IDENTITY_CONFIG, *args])

    def _invoke(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        """Shared subprocess invocation envelope."""
        try:
            return subprocess.run(  # noqa: S603 — args are constants, paths internal.
                cmd,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired:
            log.warning("Snapshot git command timed out: %s", " ".join(cmd))
            return subprocess.CompletedProcess(
                args=cmd, returncode=124, stdout="", stderr="git command timed out"
            )
        except OSError as exc:
            log.warning("Snapshot git command failed to launch: %s", exc)
            return subprocess.CompletedProcess(
                args=cmd, returncode=127, stdout="", stderr=str(exc)
            )


__all__ = ["SnapshotManager"]
