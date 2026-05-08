"""``cantrip hooks test`` handler (Phase 46.5)."""

from __future__ import annotations

import argparse
import pathlib
import sys


def _hooks_test(args: argparse.Namespace) -> int:
    """Fire a synthetic event against the user's configured hooks.

    Useful when authoring a hook config: ``cantrip hooks test
    pre_tool_call --payload '{"tool": "git_push"}'`` tells you at a
    glance whether the ``if:`` filter would match, whether the hook
    exits cleanly, and how long it takes — no need to stand up a live
    agent session.
    """
    import asyncio
    import json

    from cantrip.hooks import HookEvent, HookRunner

    try:
        event = HookEvent(args.event)
    except ValueError:
        valid = ", ".join(sorted(e.value for e in HookEvent))
        print(f"Unknown event {args.event!r}. Valid events: {valid}", file=sys.stderr)
        return 2

    # Validate --payload up front — it's a CLI-argument error that's
    # independent of config state, and we don't want it hidden behind
    # the "no hooks configured" early return.
    payload: dict[str, object] = {}
    if args.payload:
        try:
            parsed = json.loads(args.payload)
        except json.JSONDecodeError as exc:
            print(f"--payload must be valid JSON: {exc}", file=sys.stderr)
            return 2
        if not isinstance(parsed, dict):
            print("--payload must parse to a JSON object", file=sys.stderr)
            return 2
        payload.update(parsed)

    repo_root = args.charm_path or pathlib.Path.cwd()
    runner = HookRunner.from_disk(repo_root=repo_root)

    if runner.hook_count == 0:
        print("No hooks are configured.")
        print("  - user config: ~/.config/cantrip/hooks.yaml (or $CANTRIP_HOOKS_USER_CONFIG)")
        print(f"  - repo config: {repo_root / 'cantrip.hooks.yaml'}")
        return 0

    matching = runner.hooks_for(event)
    print(f"Firing `{event.value}` against {len(matching)} matching hook(s).")
    if not matching:
        print("No hooks registered for that event — nothing to do.")
        return 0

    results = asyncio.run(runner.fire(event, payload))

    if not results:
        print("Every matching hook was filtered out by its `if:` expression.")
        return 0

    for result in results:
        mark = "✓" if result.succeeded else ("∅" if result.vetoed else "✗")
        print(
            f"  {mark} {result.name} — exit {result.exit_code} "
            f"in {result.duration_seconds * 1000:.0f}ms"
            + (" (timed out)" if result.timed_out else "")
            + (" (VETO)" if result.vetoed else "")
        )
        if result.stdout.strip():
            for line in result.stdout.strip().splitlines():
                print(f"      stdout: {line}")
        if result.stderr.strip():
            for line in result.stderr.strip().splitlines():
                print(f"      stderr: {line}")
    return 0
