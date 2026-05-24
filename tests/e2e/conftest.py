"""End-to-end test configuration."""

import pytest


@pytest.fixture
def fast_executor(monkeypatch: pytest.MonkeyPatch):
    """Collapse executor polling / task-timeout for scripted e2e runs.

    Mirrors the integration-suite fixture of the same name so executor-
    driven e2e scenarios (Phase 93.6) don't pay the 1-second poll
    interval just to observe a queue-state transition.
    """
    from cantrip.agent.executor import core as executor_mod

    monkeypatch.setattr(executor_mod, "_POLL_INTERVAL", 0.01)
    monkeypatch.setattr(executor_mod, "_DEFAULT_TASK_TIMEOUT", 5)
