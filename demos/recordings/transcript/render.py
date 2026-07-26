"""Render a sample Cantrip transcript and screenshot it headlessly.

Builds a realistic-looking ``TranscriptData`` (charm build session),
renders it via the production Jinja template, then drives Playwright /
Chromium to capture light- and dark-mode PNGs at a docs-friendly width.
"""

from __future__ import annotations

import pathlib
import sys

# Make the in-repo cantrip package importable without installing.
sys.path.insert(0, "/home/ubuntu/cantrip/src")

from cantrip.transcript.export import TranscriptData
from cantrip.transcript.html import render_html

OUT_DIR = pathlib.Path("/tmp/cantrip-transcript-demo")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def sample_data() -> TranscriptData:
    """Return a plausible mid-sized 'build a Redis charm' session."""
    return TranscriptData(
        charm_name="redis-k8s-operator",
        charm_path="/home/alex/charms/redis-k8s-operator",
        token_usage={"prompt_tokens": 184_320, "completion_tokens": 27_904},
        tasks=[
            {
                "id": "t-research",
                "title": "Research the Redis workload and its operational shape",
                "status": "done",
                "category": "research",
                "description": "Confirm Redis variant, persistence model, and Path-A fit.",
                "result": "Redis 7.2 on Kubernetes, RDB+AOF persistence, Path A (12-Factor).",
            },
            {
                "id": "t-scaffold",
                "title": "Scaffold the charm with charmcraft init",
                "status": "done",
                "category": "build",
                "description": "Create the charm skeleton, add ops-tracing and COS relations.",
                "result": "Skeleton landed, ops-tracing wired, charmcraft.yaml validated.",
            },
            {
                "id": "t-charm-code",
                "title": "Write the charm code (workload, relations, status)",
                "status": "done",
                "category": "build",
                "description": "Implement the Pebble layer, relation handlers, and status logic.",
                "result": "All Scenario unit tests green; ops 2.x patterns throughout.",
            },
            {
                "id": "t-pack",
                "title": "Pack the charm with quickpack",
                "status": "done",
                "category": "build",
                "description": "Produce a .charm artefact suitable for juju deploy.",
                "result": "redis-k8s-operator_amd64.charm — 4.2 MB, packed in 11s.",
            },
            {
                "id": "t-deploy",
                "title": "Deploy to the test model on k8s",
                "status": "active",
                "category": "deploy",
                "description": "juju deploy ./redis-k8s-operator_amd64.charm with COS + tracing relations.",
                "result": "",
            },
            {
                "id": "t-debug",
                "title": "Investigate intermittent BlockedStatus on first hook",
                "status": "blocked",
                "category": "debug",
                "description": "Workload reports 'waiting for storage' for ~20s on the first install hook.",
                "result": "",
            },
            {
                "id": "t-future",
                "title": "Add jubilant integration tests",
                "status": "pending",
                "category": "test",
                "description": "Cover deploy, relate-to-grafana-agent-k8s, and scale-out=3.",
                "result": "",
            },
        ],
        subagent_messages={
            "t-charm-code": [
                {
                    "role": "user",
                    "content": (
                        "Implement the Pebble layer for redis-server with persistence "
                        "configurable via the 'persistence' charm config option."
                    ),
                    "timestamp": "2026-05-04T09:42:11",
                },
                {
                    "role": "assistant",
                    "content": (
                        "I'll add a Pebble layer that mounts the data volume, configures "
                        "redis-server to use RDB+AOF when persistence=full, and emits a "
                        "tracing span around the layer-replan."
                    ),
                    "timestamp": "2026-05-04T09:42:24",
                    "tool_calls": [
                        {
                            "id": "tc-write-charm",
                            "name": "write_file",
                            "arguments": {
                                "path": "src/charm.py",
                                "summary": "RedisCharm: Pebble layer + persistence config + tracing",
                            },
                        },
                    ],
                    "tool_results": [],
                },
                {
                    "role": "tool",
                    "content": "",
                    "timestamp": "2026-05-04T09:42:25",
                    "tool_calls": [],
                    "tool_results": [
                        {
                            "tool_call_id": "tc-write-charm",
                            "content": "Wrote 184 lines to src/charm.py.",
                            "is_error": False,
                        },
                    ],
                },
            ],
        },
        messages=[
            {
                "role": "user",
                "content": (
                    "I want to operate Redis on k8s. Build me a charm — single-leader for now, "
                    "persistence on, and please wire up COS and ops-tracing."
                ),
                "timestamp": "2026-05-04T09:38:02",
                "tool_calls": [],
                "tool_results": [],
            },
            {
                "role": "assistant",
                "content": (
                    "Got it. This looks like Path A (12-Factor PaaS): a single-leader Redis "
                    "with stable on-disk state. I'll research the workload first, then scaffold, "
                    "pack, and deploy. I'll relate to grafana-agent-k8s and tempo automatically."
                ),
                "timestamp": "2026-05-04T09:38:14",
                "tool_calls": [
                    {
                        "id": "tc-docs",
                        "name": "docs_search",
                        "arguments": {
                            "query": "redis on kubernetes persistence RDB AOF",
                            "k": 6,
                        },
                    },
                ],
                "tool_results": [],
            },
            {
                "role": "tool",
                "content": "",
                "timestamp": "2026-05-04T09:38:15",
                "tool_calls": [],
                "tool_results": [
                    {
                        "tool_call_id": "tc-docs",
                        "content": (
                            "6 hits across redis.io and charmhub.io.\n"
                            "- redis.io/persistence — RDB snapshots vs AOF append-only file (durability tradeoffs)\n"
                            "- charmhub.io/redis-k8s — operator pattern for Path-A workloads on k8s\n"
                            "- charmhub.io/grafana-agent-k8s — COS scrape relation interface\n"
                            "- canonical/operator-framework — ops 2.x Pebble layer recipes\n"
                            "- canonical/ops-tracing — span emission around hook entry/exit\n"
                            "- redis.io/security — protected-mode and AUTH for non-localhost "
                            "listeners"
                        ),
                        "is_error": False,
                    },
                ],
            },
            {
                "role": "assistant",
                "content": (
                    "Path A confirmed: stateful single-leader with RDB+AOF persistence. I'll "
                    "scaffold now, then write the charm code with a Pebble layer for "
                    "redis-server, COS scrape, and ops-tracing spans on every hook."
                ),
                "timestamp": "2026-05-04T09:39:01",
                "tool_calls": [
                    {
                        "id": "tc-scaffold",
                        "name": "run_command",
                        "arguments": {
                            "command": "charmcraft init --name redis-k8s-operator --profile machine",
                            "cwd": "/home/alex/charms/",
                        },
                    },
                ],
                "tool_results": [],
            },
            {
                "role": "tool",
                "content": "",
                "timestamp": "2026-05-04T09:39:08",
                "tool_calls": [],
                "tool_results": [
                    {
                        "tool_call_id": "tc-scaffold",
                        "content": (
                            "Charmed operator package initialised in "
                            "/home/alex/charms/redis-k8s-operator\n"
                            "Created: charmcraft.yaml, src/charm.py, requirements.txt, "
                            "tests/, README.md (10 files)."
                        ),
                        "is_error": False,
                    },
                ],
            },
            {
                "role": "assistant",
                "content": (
                    "Scaffold landed. I delegated the charm-code task to a subagent — see the "
                    "Tasks section above for the conversation. All Scenario unit tests pass; "
                    "I'll pack next."
                ),
                "timestamp": "2026-05-04T09:42:55",
                "tool_calls": [
                    {
                        "id": "tc-pack",
                        "name": "quickpack",
                        "arguments": {
                            "charm_path": "/home/alex/charms/redis-k8s-operator",
                        },
                    },
                ],
                "tool_results": [],
            },
            {
                "role": "tool",
                "content": "",
                "timestamp": "2026-05-04T09:43:06",
                "tool_calls": [],
                "tool_results": [
                    {
                        "tool_call_id": "tc-pack",
                        "content": (
                            "Packed redis-k8s-operator_amd64.charm (4.2 MB) in 10.8s.\n"
                            "Skipped charmcraft (used quickpack venv with matching CPython "
                            "3.12.3)."
                        ),
                        "is_error": False,
                    },
                ],
            },
            {
                "role": "user",
                "content": "Looks good. Try the deploy?",
                "timestamp": "2026-05-04T09:43:40",
                "tool_calls": [],
                "tool_results": [],
            },
            {
                "role": "assistant",
                "content": (
                    "Deploying to model 'redis-test' on the canonical/k8s substrate. I'll relate "
                    "to grafana-agent-k8s and tempo once the unit settles."
                ),
                "timestamp": "2026-05-04T09:43:55",
                "tool_calls": [
                    {
                        "id": "tc-deploy",
                        "name": "run_command",
                        "arguments": {
                            "command": "juju deploy ./redis-k8s-operator_amd64.charm --resource redis-image=redis:7.2",
                        },
                    },
                ],
                "tool_results": [],
            },
            {
                "role": "tool",
                "content": "",
                "timestamp": "2026-05-04T09:44:13",
                "tool_calls": [],
                "tool_results": [
                    {
                        "tool_call_id": "tc-deploy",
                        "content": (
                            "Deployed redis-k8s-operator (1 unit) to model redis-test.\n"
                            "Status (after 18s): blocked  message='waiting for storage'."
                        ),
                        "is_error": False,
                    },
                ],
            },
            {
                "role": "assistant",
                "content": (
                    "Status flipped to BlockedStatus 'waiting for storage'. That's the install "
                    "hook racing the storage-attached event — happens on first deploy. Watching "
                    "for ~30s before I escalate."
                ),
                "timestamp": "2026-05-04T09:44:14",
                "tool_calls": [],
                "tool_results": [],
            },
        ],
        events=[
            {
                "event_type": "design_confirmed",
                "detail": {"path": "A", "workload": "redis", "topology": "single-leader"},
                "timestamp": "2026-05-04T09:38:55",
            },
            {
                "event_type": "skill_loaded",
                "detail": {"skill": "ops-tracing", "reason": "wiring tracing relation"},
                "timestamp": "2026-05-04T09:40:11",
            },
            {
                "event_type": "checkpoint_hit",
                "detail": {
                    "task_id": "t-charm-code",
                    "step": "charm_skeleton_v2",
                    "savings": {"prompt_tokens": 12_400, "completion_tokens": 2_800},
                },
                "timestamp": "2026-05-04T09:41:02",
            },
            {
                "event_type": "phase_advanced",
                "detail": {"from": "build", "to": "deploy"},
                "timestamp": "2026-05-04T09:43:30",
            },
        ],
    )


def main() -> None:
    """Render the demo transcript to disk."""
    html = render_html(sample_data())
    html_path = OUT_DIR / "transcript.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"Wrote {html_path} ({len(html):,} bytes)")

    from playwright.sync_api import sync_playwright

    url = html_path.as_uri()
    width, height = 1280, 1700  # docs-friendly viewport, plenty of vertical room

    chromium_bin = (
        "/home/ubuntu/.cache/ms-playwright/chromium_headless_shell-1217/"
        "chrome-headless-shell-linux64/chrome-headless-shell"
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium_bin)
        for scheme in ("light", "dark"):
            ctx = browser.new_context(
                viewport={"width": width, "height": height},
                color_scheme=scheme,
                device_scale_factor=2,  # crisp on retina-style displays
            )
            page = ctx.new_page()
            page.goto(url, wait_until="load")
            # Full-page screenshot — captures the whole transcript end-to-end.
            full_path = OUT_DIR / f"transcript-{scheme}-full.png"
            page.screenshot(path=str(full_path), full_page=True)
            # Above-the-fold screenshot — what a docs reader sees first.
            fold_path = OUT_DIR / f"transcript-{scheme}-fold.png"
            page.screenshot(path=str(fold_path), full_page=False)
            print(f"Wrote {full_path}")
            print(f"Wrote {fold_path}")
            ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
