"""Session-management slash commands.

Extracted from :mod:`cantrip.agent.commands.slash` (Phase 113.5).  Groups the
commands that operate on the session itself: turn history (``/undo`` and
``/redo``), transcript navigation (``/branch`` and ``/tree``, with the shared
:class:`TreeNode` rendering the TUI picker reuses), and the PyPI version check
(``/update``).  Handlers return plain text except ``/update``, which returns a
:class:`~cantrip.agent.commands.slash.SlashResult`.
"""

from __future__ import annotations

import dataclasses
import logging
import typing

from cantrip import update as update_module
from cantrip.llm.base import Role

if typing.TYPE_CHECKING:
    from cantrip.agent.commands.slash import SlashResult
    from cantrip.agent.core import CantripAgent

log = logging.getLogger(__name__)


def _handle_update(args: str) -> SlashResult:
    """Dispatch the ``/update`` slash command.

    ``/update`` forces a cache-bypassing PyPI check and renders the
    result in the chat.  ``--no-check`` / ``--check`` toggle the
    persistent opt-out in ``~/.config/cantrip/settings.json``.
    """
    from cantrip.agent.commands.slash import SlashResult

    tokens = args.split()
    if not tokens:
        return SlashResult(
            text="Checking PyPI for a newer Cantrip…",
            followup=_run_update_slash_check(),
        )

    flag = tokens[0].lower()
    if len(tokens) != 1 or flag not in {"--check", "--no-check"}:
        return SlashResult(
            text=(
                "Usage: `/update` (check PyPI now), "
                "`/update --no-check` (disable auto-check), "
                "or `/update --check` (re-enable)."
            )
        )
    try:
        path = update_module.set_update_check_disabled(flag == "--no-check")
    except OSError as exc:
        return SlashResult(text=f"_Failed to update {_SETTINGS_LABEL}: {exc}._")
    verb_label = "disabled" if flag == "--no-check" else "re-enabled"
    return SlashResult(text=f"Auto-update check {verb_label} — wrote `{path}`.")


_SETTINGS_LABEL = "~/.config/cantrip/settings.json"


async def _run_update_slash_check() -> str:
    """Hit PyPI, bypassing the cache, and format the result for chat.

    Follows the same failure-model as the startup check — any error
    gets translated into a clear user-facing message rather than a
    traceback.  The cache bypass exists precisely for a user who just
    ran their installer's upgrade command and wants to see the new
    version reflected immediately.
    """
    if update_module.update_check_disabled():
        return (
            "_Auto-update check is disabled (env var or settings file). "
            "Re-enable with `/update --check`._"
        )
    try:
        info = await update_module.check_for_update(use_cache=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return f"_Could not reach PyPI: {exc}._"
    if info is None:
        return "You're on the latest Cantrip release."
    return update_module.format_slash_notice(info)


def handle_undo(agent: CantripAgent) -> str:
    """Phase 68.1 ``/undo``: roll back the last user turn.

    Restores the working tree to the snapshot taken just before the
    most recent user message landed, truncates that message and every
    follow-up assistant / tool message from both ``state.messages``
    and the SQLite ``messages`` table, and pushes the discarded
    state onto the snapshot manager's redo stack so ``/redo`` can
    re-apply it.

    Returns a single-paragraph status string suitable for chat.  Each
    failure mode (snapshots disabled, no user turns yet, no snapshot
    recorded for this turn, git restore failed) returns a clear
    one-liner rather than raising.
    """
    mgr = agent.snapshot_manager
    if mgr is None:
        return (
            "_Snapshots are disabled — relaunch without `--no-snapshots` "
            "or set `CANTRIP_SNAPSHOTS=true` to enable `/undo` and `/redo`._"
        )

    state = agent.state
    user_idx: int | None = None
    for i in range(len(state.messages) - 1, -1, -1):
        if state.messages[i].role == Role.USER:
            user_idx = i
            break
    if user_idx is None:
        return "_Nothing to undo — no user turns yet._"

    user_msg = state.messages[user_idx]
    target_sha = user_msg.metadata.get("snapshot_sha") if user_msg.metadata else None
    if not target_sha:
        return (
            "_Cannot undo this turn — no snapshot was recorded for it. "
            "Snapshots may have been disabled or git unavailable when "
            "this turn started._"
        )

    # Snapshot the *current* working tree before resetting so any
    # mid-turn agent edits the user might want back can be redone.
    redo_sha = mgr.snapshot_turn(f"pre-undo-{user_idx}")

    paths_changed = mgr.restore(str(target_sha), direction="undo")
    if paths_changed is None:
        return f"_Failed to restore snapshot `{str(target_sha)[:8]}` — check the logs._"

    removed = list(state.messages[user_idx:])
    del state.messages[user_idx:]
    if redo_sha is not None:
        mgr.push_undone(redo_sha, removed)

    deleted = 0
    db_message_id = user_msg.metadata.get("db_message_id") if user_msg.metadata else None
    store = agent.store
    if db_message_id is not None and store is not None:
        try:
            deleted = store.delete_messages_from(int(db_message_id))
        except (ValueError, TypeError):
            log.warning("Skipping store truncate: bad db_message_id %r", db_message_id)

    parts = [
        f"Undid the last turn — restored **{paths_changed}** file(s), "
        f"removed **{len(removed)}** message(s) from history",
    ]
    if deleted:
        parts.append(f"({deleted} from the session store)")
    redo_note = " · `/redo` re-applies." if redo_sha is not None else ""
    return " ".join(parts) + "." + redo_note


def handle_redo(agent: CantripAgent) -> str:
    """Phase 68.1 ``/redo``: re-apply the most recently undone turn.

    Pops the top of the snapshot manager's redo stack, restores the
    working tree to the SHA captured at ``/undo`` time, re-appends
    the messages that were stripped, and re-records them in the
    session store (with fresh row IDs).

    Returns a single-paragraph status string.  An empty redo stack
    or a failed restore returns a clear one-liner; the redo entry
    is preserved on restore failure so the user can try again.
    """
    mgr = agent.snapshot_manager
    if mgr is None:
        return "_Snapshots are disabled — nothing to redo._"

    entry = mgr.pop_undone()
    if entry is None:
        return (
            "_Nothing to redo — the redo stack is empty.  It clears "
            "whenever a new user turn arrives._"
        )

    paths_changed = mgr.restore(entry.redo_sha, direction="redo")
    if paths_changed is None:
        # Put the entry back so a retry stays available.
        mgr.push_undone(entry.redo_sha, entry.removed_messages)
        return f"_Failed to restore snapshot `{entry.redo_sha[:8]}` — check the logs._"

    agent.state.messages.extend(entry.removed_messages)
    for msg in entry.removed_messages:
        # New IDs land in metadata so a subsequent /undo on this turn
        # finds the right rows to delete.
        agent._record_message(msg)

    return (
        f"Redid the last undo — restored **{paths_changed}** file(s), "
        f"re-added **{len(entry.removed_messages)}** message(s)."
    )


def handle_branch(agent: CantripAgent, args: str) -> str:
    """Phase 67.1 ``/branch``: rewind to a prior turn and start a new branch.

    With a turn id (``/branch 17``), moves the active head to that
    message and rebuilds ``state.messages`` so the next prompt forks
    off it.  Without an argument, picks the turn before the most
    recent user message — handy after a bad steering message: the
    user issues ``/branch`` and types a corrected instruction.

    Off-branch messages stay in the SQLite store; ``/tree`` lists
    them and re-activating any node restores that branch.  Unlike
    ``/undo`` this command never deletes rows and never touches the
    working tree.
    """
    store = agent.store
    if store is None:
        return "_No session store available — `/branch` needs a saved session._"

    target: int | None = None
    args_stripped = args.strip()
    if args_stripped:
        try:
            target = int(args_stripped)
        except ValueError:
            return f"_`/branch` expected an integer turn id, got `{args_stripped}`._"
        # Validate the target exists in this session before moving.
        all_messages = {m["id"]: m for m in store.load_messages()}
        if target not in all_messages:
            return (
                f"_Turn `{target}` not found in this session.  "
                "Run `/tree` to see the turns you can fork from._"
            )
    else:
        # Find the message before the most recent user turn.  Walk
        # the active branch from the leaf back to skip the user
        # message itself, then take its parent.
        branch = store.load_active_branch()
        last_user_idx: int | None = None
        for i in range(len(branch) - 1, -1, -1):
            if branch[i].get("role") == "user":
                last_user_idx = i
                break
        if last_user_idx is None:
            return "_Nothing to fork from — no user turns yet._"
        # When the first message is the user turn, forking before it
        # means an empty conversation; clearing the head matches that.
        target = None if last_user_idx == 0 else int(branch[last_user_idx - 1]["id"])

    previous_head = store.get_active_head()
    store.set_active_head(target)
    rebuilt = agent._rebuild_messages_from_active_branch()

    if target is None:
        return (
            "Forked from before the first user turn — the conversation is now empty.  "
            f"The previous branch (head `{previous_head}`) stays in the store."
        )
    return (
        f"Forked at turn `{target}` — rebuilt **{rebuilt}** message(s) on the active branch.  "
        f"The prior branch (head `{previous_head}`) is still reachable via `/tree`."
    )


@dataclasses.dataclass(frozen=True)
class TreeNode:
    """A turn rendered for the ``/tree`` view.

    ``depth`` is the indent level (root is 0); ``id`` is the message
    db row id used by ``/branch``; ``label`` is the one-line
    description shown on the row; ``on_active_branch`` lets the
    renderer mark live nodes versus historical forks.
    """

    depth: int
    id: int
    role: str
    label: str
    timestamp: str
    on_active_branch: bool


def build_tree_nodes(
    messages: list[dict[str, object]],
    active_branch_ids: set[int],
) -> list[TreeNode]:
    """Render a flat message list as a depth-first tree traversal.

    Pure function so the TUI modal can reuse the rendering rule the
    text ``/tree`` produces.  *messages* is the full row dump from
    ``SessionStore.load_messages``; *active_branch_ids* is the set
    of ids currently on the live branch (so the renderer can mark
    them).  Children are visited in id order, which matches the
    chronological order rows were recorded — newer forks appear
    later under their shared parent.
    """
    by_id: dict[int, dict[str, object]] = {}
    children: dict[int | None, list[int]] = {}
    for msg in messages:
        msg_id = msg.get("id")
        if not isinstance(msg_id, int):
            continue
        by_id[msg_id] = msg
        parent = msg.get("parent_turn_id")
        parent_key = parent if isinstance(parent, int) else None
        children.setdefault(parent_key, []).append(msg_id)
    for kids in children.values():
        kids.sort()

    nodes: list[TreeNode] = []

    def visit(node_id: int, depth: int) -> None:
        msg = by_id[node_id]
        content = str(msg.get("content") or "").splitlines()
        first_line = content[0].strip() if content else ""
        if len(first_line) > 80:
            first_line = first_line[:77] + "…"
        nodes.append(
            TreeNode(
                depth=depth,
                id=node_id,
                role=str(msg.get("role") or ""),
                label=first_line or "(empty)",
                timestamp=str(msg.get("timestamp") or ""),
                on_active_branch=node_id in active_branch_ids,
            )
        )
        for child_id in children.get(node_id, []):
            visit(child_id, depth + 1)

    for root_id in children.get(None, []):
        visit(root_id, 0)

    return nodes


def handle_tree(agent: CantripAgent, _args: str) -> str:
    """Phase 67.1 ``/tree``: render the session as a tree of turns.

    Lists every persisted turn, grouped under its parent in id order.
    Each row shows the turn id, role, a marker (``*``) for nodes on
    the active branch, the first line of the message, and the
    timestamp.  Pair with ``/branch <id>`` to fork from any node.
    The TUI surface replaces this with an interactive picker; CLI
    and Web see the text form.
    """
    store = agent.store
    if store is None:
        return "_No session store available — `/tree` needs a saved session._"

    messages = store.load_messages()
    if not messages:
        return "_No turns yet — `/tree` will populate after the first message._"

    active_ids = {m["id"] for m in store.load_active_branch()}
    nodes = build_tree_nodes(messages, active_ids)

    lines = [
        "**Session tree** — `*` marks the active branch, `/branch <id>` forks from any turn.",
        "",
    ]
    for node in nodes:
        prefix = "  " * node.depth
        marker = "*" if node.on_active_branch else " "
        timestamp = node.timestamp[:19] if node.timestamp else ""
        lines.append(
            f"{prefix}{marker} `{node.id}` **{node.role}** — {node.label}"
            + (f"  _({timestamp})_" if timestamp else "")
        )
    return "\n".join(lines)
