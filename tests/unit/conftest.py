"""Unit-test fixtures and Hypothesis profile configuration.

Two profiles are registered and activated automatically at import time:

* ``ci`` — ``max_examples=500``; the deep sweep that runs in GitHub
  Actions.  Opt in by setting ``CANTRIP_HYPOTHESIS_PROFILE=ci``.
* ``dev`` — ``max_examples=100`` (the Hypothesis default).  Used for
  local iteration where feedback latency matters more than the breadth
  of the search.

The profile is selected once at import time from the ``CANTRIP_HYPOTHESIS_PROFILE``
environment variable so ``pytest -q`` in a shell respects it without any
pytest flag.  Tests don't have to import this module — Hypothesis picks
up the loaded profile globally.
"""

from __future__ import annotations

import os

import pytest
from hypothesis import HealthCheck, settings

# ``max_examples`` is the lever that matters: the CI profile runs a
# deeper sweep that catches rare corner cases, the dev profile keeps
# the local feedback loop snappy.  Both disable the ``too_slow`` health
# check because the planner-graph tests build a few hundred AgentTask
# objects each and that can briefly trip Hypothesis's default budget
# on a cold interpreter.
settings.register_profile(
    "dev",
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "ci",
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

settings.load_profile(os.environ.get("CANTRIP_HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture(autouse=True)
def _isolate_global_memory_dir(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redirect ``GlobalMemoryStore`` at the user's real ``~/.config/cantrip/memory``.

    ``MemoryManager`` falls back to a default-constructed
    ``GlobalMemoryStore`` whenever a test doesn't inject one, and that
    default reads/writes the real user directory — leaking real memories
    into exports, counts, and assertions.  Pointing ``CANTRIP_MEMORY_DIR``
    at a per-test scratch directory keeps every test hermetic without
    forcing each one to wire a store by hand.
    """
    scratch = tmp_path_factory.mktemp("global-mem")
    monkeypatch.setenv("CANTRIP_MEMORY_DIR", str(scratch))
