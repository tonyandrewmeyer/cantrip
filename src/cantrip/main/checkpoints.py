"""``cantrip checkpoints {list,show,delete}`` handlers (Phase 52.5)."""

from __future__ import annotations

import sqlite3
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    import pathlib

    from cantrip.agent import durability as durability_mod
    from cantrip.agent import store as store_mod


def _checkpoints(args: argparse.Namespace) -> int:
    """Dispatch ``cantrip checkpoints {list,show,delete}`` (Phase 52.5)."""
    from cantrip.agent import durability as durability_mod
    from cantrip.agent import store as store_mod

    db_path: pathlib.Path = args.db
    if not db_path.exists():
        print(f"Error: {db_path} does not exist.", file=sys.stderr)
        return 2

    session_store = store_mod.SessionStore(db_path)
    try:
        session_store.open()
    except sqlite3.DatabaseError as exc:
        print(
            f"Error: {db_path} is not a valid Cantrip session file ({exc}).",
            file=sys.stderr,
        )
        return 2
    cps = durability_mod.CheckpointStore(session_store)
    try:
        if args.checkpoints_command == "list":
            return _checkpoints_list(session_store, cps, args.task_id)
        if args.checkpoints_command == "show":
            return _checkpoints_show(cps, args.task_id, args.step_name, args.ordinal)
        if args.checkpoints_command == "delete":
            return _checkpoints_delete(cps, args.task_id, args.yes)
        print(f"Unknown checkpoints subcommand: {args.checkpoints_command}", file=sys.stderr)
        return 2
    finally:
        session_store.close()


def _checkpoints_list(
    session_store: store_mod.SessionStore,
    cps: durability_mod.CheckpointStore,
    task_id: str | None,
) -> int:
    """Print a compact table of checkpoint rows for one or every task."""
    if task_id is None:
        tasks = session_store.load_tasks()
        task_ids = [t.id for t in tasks if cps.count_for_task(t.id) > 0]
        titles = {t.id: t.title for t in tasks}
    else:
        task_ids = [task_id]
        titles = {task_id: ""}

    if not task_ids:
        print("No tasks with checkpoints.")
        return 0

    for tid in task_ids:
        records = cps.list_for_task(tid)
        if not records:
            if task_id is not None:
                print(f"No checkpoints for task {tid!r}.")
            continue
        header = f"{titles.get(tid, '')}  ({tid}, {len(records)} step(s))".strip()
        print(header)
        print("-" * len(header))
        for r in records:
            hash_prefix = (r.input_hash or "(none)")[:12]
            print(f"  {r.step_name}#{r.ordinal}  {r.kind:<13} {hash_prefix:<12} {r.created_at}")
        print()
    return 0


def _checkpoints_show(
    cps: durability_mod.CheckpointStore,
    task_id: str,
    step_name: str,
    ordinal: int,
) -> int:
    """Pretty-print one stored blob as JSON (or base64 for KIND_BYTES)."""
    import base64
    import json

    from cantrip.agent.durability import KIND_BYTES

    record = cps.get(task_id, step_name, ordinal)
    if record is None:
        print(
            f"Error: no checkpoint for ({task_id!r}, {step_name!r}, {ordinal}).",
            file=sys.stderr,
        )
        return 1

    print(
        f"Task:       {record.task_id}\n"
        f"Step:       {record.step_name}#{record.ordinal}\n"
        f"Kind:       {record.kind}\n"
        f"Input hash: {record.input_hash or '(none)'}\n"
        f"Created:    {record.created_at}"
    )
    print("-" * 40)
    if record.kind == KIND_BYTES:
        print(f"(bytes, {len(record.blob)} bytes; base64):")
        print(base64.b64encode(record.blob).decode("ascii"))
        return 0
    try:
        decoded = record.decode()
    except json.JSONDecodeError as exc:
        print(f"Error: stored blob is not valid JSON: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(decoded, indent=2, sort_keys=True, default=str))
    return 0


def _checkpoints_delete(
    cps: durability_mod.CheckpointStore,
    task_id: str,
    yes: bool,
) -> int:
    """Purge every checkpoint row for *task_id* after confirmation."""
    count = cps.count_for_task(task_id)
    if count == 0:
        print(f"No checkpoints to delete for task {task_id!r}.")
        return 0
    if not yes:
        reply = input(f"Delete {count} checkpoint(s) for task {task_id!r}? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("Aborted.")
            return 1
    removed = cps.purge_task(task_id)
    print(f"Removed {removed} checkpoint(s) for task {task_id!r}.")
    return 0
