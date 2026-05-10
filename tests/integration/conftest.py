"""Integration test configuration — shared fixtures and helpers."""

import json

import pytest

from cantrip.agent.tools import base as tools_base
from tests.support.providers import CallbackProvider as CallbackProvider
from tests.support.providers import MultiRoleProvider as MultiRoleProvider
from tests.support.tools import make_stub_tool as _make_stub_tool
from tests.support.wait import wait_for_queue_state as wait_for_queue_state

# Re-exported above so existing integration tests keep importing from
# ``tests.integration.conftest``.  New tests should import directly from
# ``tests.support.wait`` and ``tests.support.providers``.


# ---------------------------------------------------------------------------
# Stub tools
# ---------------------------------------------------------------------------


def make_stub_tool(name: str, result: str | None = None) -> tools_base.Tool:
    """Create a minimal stub tool that returns a fixed result.

    Thin wrapper around :func:`tests.support.tools.make_stub_tool` that
    keeps the integration-tests-style signature (``result`` defaults to
    ``"<name> executed"`` rather than ``"ok"``).
    """
    return _make_stub_tool(
        name,
        description=f"Stub tool: {name}",
        output=result or f"{name} executed",
    )


# ---------------------------------------------------------------------------
# JSON fixtures — canned planner outputs
#
# Planner LLM calls go through ``complete_structured`` against the
# ``PLANNER_BRIEFING`` schema (Phase 73.3), which expects a top-level
# ``{"tasks": [...]}`` object — not a bare array.  Keep these matching
# the live wire shape so the fixtures don't drift back into "passes a
# value the real planner would reject".
# ---------------------------------------------------------------------------


RESEARCH_PLAN_JSON = json.dumps(
    {
        "tasks": [
            {
                "id": "source-analysis",
                "title": "Analyse the source repository",
                "category": "research",
                "description": "Clone the repo and explore the codebase.",
                "dependencies": [],
            },
            {
                "id": "web-research",
                "title": "Research workload documentation",
                "category": "research",
                "description": "Fetch external docs and deployment guides.",
                "dependencies": [],
            },
            {
                "id": "operational-discovery",
                "title": "Synthesise design proposal",
                "category": "research",
                "description": "Combine all research into a design proposal.",
                "dependencies": ["source-analysis", "web-research"],
            },
            {
                "id": "confirm-design",
                "title": "Confirm design with user",
                "category": "confirm",
                "description": "Present the design proposal for user approval.",
                "dependencies": ["operational-discovery"],
            },
        ]
    }
)


BUILD_PLAN_JSON = json.dumps(
    {
        "tasks": [
            {
                "id": "scaffold-charm",
                "title": "Scaffold the charm project",
                "category": "build",
                "description": "Initialise the charm directory structure.",
                "dependencies": [],
            },
            {
                "id": "write-charm-code",
                "title": "Write charm code",
                "category": "build",
                "description": "Implement the charm in src/charm.py.",
                "dependencies": ["scaffold-charm"],
            },
            {
                "id": "write-tests",
                "title": "Write unit tests",
                "category": "build",
                "description": "Write Scenario-based unit tests.",
                "dependencies": ["write-charm-code"],
            },
        ]
    }
)


SAMPLE_DESIGN_MD = """\
# Redis

## Substrate

Kubernetes — Redis is commonly deployed as a containerised service.

## Substrate reasoning

K8s provides easy scaling and Pebble-based workload management.

## Charm path

Custom — Redis has specific operational patterns that require a full ops charm.

## Charm path reasoning

Redis needs custom relation handling for replication and sentinel.

## Charmhub

Build new — no well-maintained Redis charm exists for k8s.

## Integrations

- redis-client (provides)
- cos-agent (requires)
- certificates (requires)

## Config

- port: Redis listening port (default 6379)
- maxmemory: Maximum memory limit
- maxmemory-policy: Eviction policy

## Actions

- backup: Create an RDB snapshot
- restore: Restore from a backup

## Scaling

Horizontal scaling via Redis Sentinel for high availability.

## Operational patterns

Redis uses RDB snapshots and AOF logging for persistence. Health is checked
via the PING command. Clustering is handled through Redis Sentinel.

## Questions

- Should we support Redis Cluster mode?
- What TLS configuration is needed?

## Sources

- https://redis.io/docs/
- https://hub.docker.com/_/redis
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fast_executor(monkeypatch: pytest.MonkeyPatch):
    """Speed up executor polling and reduce task timeout for tests."""
    from cantrip.agent.executor import core as executor_mod

    monkeypatch.setattr(executor_mod, "_POLL_INTERVAL", 0.01)
    monkeypatch.setattr(executor_mod, "_DEFAULT_TASK_TIMEOUT", 5)


@pytest.fixture
def fast_retry(monkeypatch: pytest.MonkeyPatch):
    """Collapse the transient-error backoff so retry paths run instantly.

    :func:`cantrip.agent.retry.complete_with_retry` bakes
    ``TRANSIENT_RETRIES`` into its default argument, so the retry
    *count* can't be changed after import — but the backoff *delays*
    are read at call time, so zeroing them is enough to keep a
    three-attempt retry loop fast.  ``_PROVIDER_BASE_DELAY`` is emptied
    so per-provider overrides (``claude``) don't reintroduce a wait.
    """
    from cantrip.agent import retry as retry_mod

    monkeypatch.setattr(retry_mod, "TRANSIENT_BASE_DELAY", 0)
    monkeypatch.setattr(retry_mod, "_CONNECTION_BASE_DELAY", 0)
    monkeypatch.setattr(retry_mod, "_PROVIDER_BASE_DELAY", {})
