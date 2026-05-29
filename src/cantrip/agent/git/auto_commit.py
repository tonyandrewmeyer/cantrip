"""Phase 71.3 — auto-commit-per-turn.

Every conversation-loop turn that mutates files (``write_file`` /
``edit_file`` / ``multi_edit`` and friends) lands as a discrete,
attributed git commit in the user's charm repo:

* **Pre-cantrip commit.**  If the working tree was already dirty
  when the user typed, those changes commit first as
  ``chore(pre-cantrip): save in-progress work`` so the user's
  hand-edits stay distinct from the agent's edits in
  ``git log``.
* **Agent commit.**  Whatever the agent touched in the turn lands
  as a separate commit with a Cantrip co-author trailer.

Both are gated by :attr:`AgentState.git_auto_commit` (default
``True``; flip via ``--no-auto-commit`` or ``/auto-commit off``).
The module never runs ``git push`` — pushing is the user's call.

The interface here is two functions, both safe to call at every
turn boundary:

* :func:`pre_turn_commit_dirty` — runs at the start of a turn
  before the agent does anything; commits any pre-existing dirty
  work so the agent's edits land on a clean base.
* :func:`post_turn_commit_agent_edits` — runs at the end of a
  turn after the final assistant message lands; collects the
  files touched by tool calls, stages them, and commits.

Failures are non-fatal — a missing git binary or a non-repo
charm directory just skips the commit and logs at DEBUG.  The
agent loop never raises out because of an auto-commit hiccup.
"""

from __future__ import annotations

import logging
import pathlib
import shutil
import subprocess
from collections.abc import Iterable

from cantrip.llm.base import Message, Role

log = logging.getLogger(__name__)

# Co-author trailer.  Matches the convention already used in
# ``CHANGELOG.md`` entries authored by Cantrip.
_CANTRIP_NAME = "Cantrip"
_CANTRIP_EMAIL = "noreply@aotearoa.dev"
_CANTRIP_TRAILER = f"Co-Authored-By: {_CANTRIP_NAME} <{_CANTRIP_EMAIL}>"

# Tool names whose successful invocation indicates the agent
# touched a file we should include in the auto-commit.  Mirrors
# the set Phase 71.4 uses for post-edit lint, plus snapshots'
# fingerprint.  Update both lists in lockstep when adding a new
# file-mutating tool.
_FILE_MUTATING_TOOLS = frozenset(
    {
        "write_file",
        "edit_file",
        "multi_edit",
        "fs_write",
        "fs_edit",
        "edit",
        "create_file",
    }
)

# Default subject when no summariser is available.  Truncates
# the user's prompt at 60 characters so even a long question
# doesn't blow the 72-char convention.
_FALLBACK_SUBJECT_PREFIX = "agent:"
_FALLBACK_SUBJECT_LIMIT = 60

_PRE_CANTRIP_MESSAGE = "chore(pre-cantrip): save in-progress work"

# Conservative subprocess timeout — local git ops on a charm-sized
# repo finish well under a second, but a slow snap install or a
# busy worktree can stretch.
_GIT_TIMEOUT_SECONDS = 30


def _have_git() -> bool:
    """Return whether ``git`` is on ``$PATH``."""
    return shutil.which("git") is not None


def _is_git_repo(path: pathlib.Path) -> bool:
    """Return whether *path* sits inside a git working tree.

    Uses ``git rev-parse --is-inside-work-tree`` so submodules and
    nested checkouts resolve correctly; the bare existence of a
    ``.git`` directory isn't enough.
    """
    if not path or not path.exists():
        return False
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _has_dirty_tree(path: pathlib.Path) -> bool:
    """Return whether *path* has uncommitted modifications or untracked files.

    Treats both modified-but-unstaged and staged-but-uncommitted as
    dirty — both should be preserved as a discrete commit before
    the agent edits.  Untracked files count too, since the user
    might be mid-creation of a file the agent will then edit.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def _commit(path: pathlib.Path, message: str, *, stage_all: bool = False) -> str | None:
    """Run ``git commit`` and return the new HEAD SHA, or ``None`` on failure.

    When *stage_all* is ``True`` we run ``git add -A`` first so untracked
    files participate; the pre-cantrip path uses this.  Agent edits go
    through explicit ``git add -- <files>`` so we never sweep up
    something the user is mid-edit on.
    """
    try:
        if stage_all:
            stage = subprocess.run(
                ["git", "add", "-A"],
                cwd=str(path),
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
            if stage.returncode != 0:
                log.debug("auto_commit: git add -A failed: %s", stage.stderr.strip())
                return None

        commit = subprocess.run(
            ["git", "commit", "--no-gpg-sign", "-m", message],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        log.debug("auto_commit: subprocess error during commit: %s", exc)
        return None

    if commit.returncode != 0:
        # An empty-tree commit returns non-zero with a clear stderr;
        # we treat that as "nothing to commit" — log + skip.
        log.debug(
            "auto_commit: git commit returned %d: %s", commit.returncode, commit.stderr.strip()
        )
        return None

    try:
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if rev.returncode != 0:
        return None
    return rev.stdout.strip() or None


def _add_paths(path: pathlib.Path, paths: list[str]) -> bool:
    """Stage *paths* via ``git add -- <paths>``.

    Returns ``True`` on success.  Empty *paths* short-circuits to
    ``False`` so callers don't accidentally commit an empty index.
    """
    if not paths:
        return False
    try:
        result = subprocess.run(
            ["git", "add", "--", *paths],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _staged_diff_empty(path: pathlib.Path) -> bool:
    """Return whether ``git diff --cached`` shows no staged changes.

    Used to skip the agent commit when ``git add`` resolved to a
    no-op (the agent ran but every touched path either matched the
    HEAD content or didn't exist).  Without this guard the agent
    commit would fail with a "nothing to commit" error.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return True
    # ``--quiet`` exits 0 when there's no diff, 1 when there is.
    return result.returncode == 0


def collect_touched_files(turn_messages: Iterable[Message]) -> list[str]:
    """Return paths the agent touched in the given turn slice.

    Walks the messages added during the turn, picks ASSISTANT
    messages with tool calls in :data:`_FILE_MUTATING_TOOLS`, and
    extracts the ``path`` / ``file_path`` argument.  ``multi_edit``
    carries a list of edit dicts — we extract the ``path`` of each.

    Duplicates collapse (a file edited twice in one turn lands as a
    single entry).  Order is the order tool calls appeared so the
    commit's staged file list is deterministic.
    """
    seen: list[str] = []
    seen_set: set[str] = set()
    for msg in turn_messages:
        if msg.role is not Role.ASSISTANT:
            continue
        for tc in msg.tool_calls:
            if tc.name not in _FILE_MUTATING_TOOLS:
                continue
            args = tc.arguments or {}
            for key in ("path", "file_path", "filepath", "file"):
                value = args.get(key)
                if isinstance(value, str) and value:
                    if value not in seen_set:
                        seen.append(value)
                        seen_set.add(value)
                    break
            edits = args.get("edits")
            if isinstance(edits, list):
                for edit in edits:
                    if not isinstance(edit, dict):
                        continue
                    for key in ("path", "file_path", "filepath", "file"):
                        v = edit.get(key)
                        if isinstance(v, str) and v and v not in seen_set:
                            seen.append(v)
                            seen_set.add(v)
                            break
    return seen


def _human_coauthor_trailer(path: pathlib.Path) -> str | None:
    """Return a ``Co-Authored-By:`` line for the local git user, or ``None``.

    Reads ``git config user.name`` / ``user.email`` resolved at *path*
    (so a per-repo identity overrides the global one).  Returns
    ``None`` when git is missing, either field is unset, or the
    configured identity matches Cantrip's canonical — in that case
    the existing :data:`_CANTRIP_TRAILER` already covers it and a
    second line would be a duplicate.

    The comparison is case-insensitive to mirror how Git and GitHub
    treat author emails.
    """
    if not _have_git():
        return None
    try:
        name_proc = subprocess.run(
            ["git", "config", "--get", "user.name"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        email_proc = subprocess.run(
            ["git", "config", "--get", "user.email"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    name = name_proc.stdout.strip() if name_proc.returncode == 0 else ""
    email = email_proc.stdout.strip() if email_proc.returncode == 0 else ""
    if not name or not email:
        return None
    if name.lower() == _CANTRIP_NAME.lower() or email.lower() == _CANTRIP_EMAIL.lower():
        return None
    return f"Co-Authored-By: {name} <{email}>"


def _summarise_user_message(user_message: str) -> str:
    """Build the fallback commit subject from the user's request.

    The light-provider summariser is preferred when configured; this
    is the safety-net when no summariser is wired or it returns
    empty text.  Strips newlines, collapses whitespace, and clips
    to :data:`_FALLBACK_SUBJECT_LIMIT` characters with an ellipsis.
    """
    cleaned = " ".join(user_message.split())
    if not cleaned:
        return f"{_FALLBACK_SUBJECT_PREFIX} edits"
    if len(cleaned) > _FALLBACK_SUBJECT_LIMIT:
        cleaned = cleaned[: _FALLBACK_SUBJECT_LIMIT - 1].rstrip() + "…"
    return f"{_FALLBACK_SUBJECT_PREFIX} {cleaned}"


def build_commit_message(
    user_message: str,
    *,
    summary: str | None = None,
    files: list[str] | None = None,
    human_trailer: str | None = None,
) -> str:
    """Compose the agent's commit message body.

    *summary* is an optional one-line subject from the light
    provider; fallback derives one from *user_message*.  *files*
    is a non-binding list of touched paths mentioned in the body
    so reviewers see the scope at a glance without running
    ``git show --stat``.  *human_trailer* is an optional second
    ``Co-Authored-By:`` line attributing the human operator who
    drove the session — see :func:`_human_coauthor_trailer`.
    """
    # ``splitlines()`` on a whitespace-only string returns ``[]``, so guard the
    # ``[0]`` index after stripping.
    summary_lines = (summary or "").strip().splitlines()
    subject = summary_lines[0] if summary_lines else ""
    if not subject:
        subject = _summarise_user_message(user_message)
    if len(subject) > 72:
        subject = subject[:71].rstrip() + "…"

    body_lines: list[str] = [subject, ""]
    if user_message.strip():
        prompt = user_message.strip()
        if len(prompt) > 280:
            prompt = prompt[:279].rstrip() + "…"
        body_lines.append(f"Prompt: {prompt}")
        body_lines.append("")
    if files:
        body_lines.append("Touched:")
        for path in files[:20]:
            body_lines.append(f"  - {path}")
        if len(files) > 20:
            body_lines.append(f"  - … and {len(files) - 20} more")
        body_lines.append("")
    body_lines.append(_CANTRIP_TRAILER)
    if human_trailer:
        body_lines.append(human_trailer)
    return "\n".join(body_lines)


def pre_turn_commit_dirty(charm_path: pathlib.Path | None) -> str | None:
    """Commit any pre-existing dirty work before the agent runs.

    Returns the new HEAD SHA on success, ``None`` when nothing was
    committed (clean tree, missing git, non-repo, etc.).  Uses
    ``git add -A`` so untracked files participate.

    The caller is responsible for gating on
    ``state.git_auto_commit`` — this function is a no-op when
    given an unset *charm_path* but doesn't itself read any state.
    """
    if charm_path is None or not _have_git():
        return None
    if not _is_git_repo(charm_path):
        return None
    if not _has_dirty_tree(charm_path):
        return None
    sha = _commit(charm_path, _PRE_CANTRIP_MESSAGE, stage_all=True)
    if sha:
        log.info("auto_commit: pre-cantrip commit %s", sha[:8])
    return sha


def post_turn_commit_agent_edits(
    charm_path: pathlib.Path | None,
    turn_messages: Iterable[Message],
    user_message: str,
    *,
    summary: str | None = None,
) -> str | None:
    """Commit files the agent touched in this turn.

    Walks *turn_messages* (typically ``state.messages[user_idx:]``)
    to find the touched paths, stages them, and commits with a
    Cantrip co-author trailer.  Returns the new HEAD SHA on
    success or ``None`` when nothing was committed.

    The commit message subject prefers *summary* when given; the
    caller can pre-compute it via the light provider.  The body
    embeds the user prompt and a list of touched files for audit.
    """
    if charm_path is None or not _have_git():
        return None
    if not _is_git_repo(charm_path):
        return None
    paths = collect_touched_files(turn_messages)
    if not paths:
        return None
    if not _add_paths(charm_path, paths):
        log.debug("auto_commit: git add -- %s failed", paths)
        return None
    if _staged_diff_empty(charm_path):
        log.debug("auto_commit: staged diff empty; skipping agent commit")
        return None
    human_trailer = _human_coauthor_trailer(charm_path)
    message = build_commit_message(
        user_message, summary=summary, files=paths, human_trailer=human_trailer
    )
    sha = _commit(charm_path, message)
    if sha:
        log.info("auto_commit: agent commit %s (%d file(s))", sha[:8], len(paths))
    return sha
