"""Planner tests: tool."""

import json
import pathlib
import subprocess

import pytest

from cantrip.agent.queue import WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.tools import planning as planning_module
from cantrip.agent.tools.planning import (
    PlanTasksTool,
    detect_current_juju_model,
    juju_model_substrate,
)
from cantrip.llm.base import Response
from tests.conftest import FakeProvider


def _juju_models_payload(
    *,
    current: str | None,
    models: list[tuple[str, str, bool]],
) -> str:
    """Build a ``juju models --format=json`` payload.

    ``models`` entries are ``(short_name, model_type, is_controller)`` —
    ``model_type`` is ``"caas"`` or ``"iaas"`` (or ``""`` for legacy/unknown).
    """
    return json.dumps(
        {
            "current-model": current,
            "models": [
                {
                    "short-name": short,
                    "model-type": mtype,
                    "is-controller": is_ctrl,
                }
                for short, mtype, is_ctrl in models
            ],
        }
    )


def _patch_juju(monkeypatch: pytest.MonkeyPatch, payload: str | None) -> None:
    """Patch ``shutil.which`` and ``subprocess.run`` for the planning module.

    ``payload`` of ``None`` simulates Juju not being installed.
    """
    if payload is None:
        monkeypatch.setattr(planning_module.shutil, "which", lambda _name: None)
        return
    monkeypatch.setattr(planning_module.shutil, "which", lambda _name: "/usr/bin/juju")

    def fake_run(*_args, **_kwargs):  # noqa: ANN002, ANN003 — match subprocess signature
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=payload, stderr="")

    monkeypatch.setattr(planning_module.subprocess, "run", fake_run)


# ===================================================================
# TestPlanTasksTool
# ===================================================================


class TestPlanTasksTool:
    """Tests for the PlanTasksTool conversation wrapper."""

    @pytest.mark.asyncio
    async def test_populates_work_queue(self) -> None:
        provider = FakeProvider()
        state = AgentState()
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        result = await tool.execute(intent="Build a charm for Redis")

        assert result.success
        # 4 deterministic tasks: web-research, charmhub-survey, operational-discovery, confirm.
        assert queue.pending_count == 4
        assert result.data["task_count"] == 4

    @pytest.mark.asyncio
    async def test_returns_formatted_summary(self) -> None:
        provider = FakeProvider()
        state = AgentState()
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        result = await tool.execute(intent="Build a charm for Redis")

        assert "Task plan" in result.output
        assert "research" in result.output.lower()
        # The trailer tells the conversation LLM to hand off to the
        # work queue rather than re-implement the steps itself — the
        # behaviour that motivated dropping the per-task description
        # blocks (which carried imperative "Do NOT…" directives small
        # models picked up as their own instructions).
        assert "work queue will run these tasks autonomously" in result.output

    @pytest.mark.asyncio
    async def test_rejects_empty_intent(self) -> None:
        provider = FakeProvider()
        state = AgentState()
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        result = await tool.execute(intent="")

        assert not result.success
        assert "empty" in result.error.lower()

    @pytest.mark.asyncio
    async def test_rejects_whitespace_intent(self) -> None:
        provider = FakeProvider()
        state = AgentState()
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        result = await tool.execute(intent="   ")

        assert not result.success

    @pytest.mark.asyncio
    async def test_fresh_plan_always_succeeds(self) -> None:
        """Deterministic planning cannot fail (no LLM parsing involved)."""
        provider = FakeProvider()
        state = AgentState()
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        result = await tool.execute(intent="Build something")

        assert result.success
        assert queue.pending_count > 0

    @pytest.mark.asyncio
    async def test_uses_state_context(self) -> None:
        provider = FakeProvider()
        state = AgentState(
            charm_name="my-charm",
            charm_type="k8s",
            framework="flask",
        )
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        result = await tool.execute(intent="Build the charm")

        assert result.success
        # Charm name from state should appear in task titles.
        assert any("my-charm" in t.title for t in queue.all_tasks())

    @pytest.mark.asyncio
    async def test_improve_mode_routes_to_improvement(self) -> None:
        """When state.mode is 'improve', PlanTasksTool generates improvement tasks."""
        provider = FakeProvider()
        state = AgentState(
            mode="improve",
            charm_name="my-charm",
            charm_path=pathlib.Path("/tmp/my-charm"),
        )
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        result = await tool.execute(intent="Improve this charm")

        assert result.success
        task_ids = [t.id for t in queue.all_tasks()]
        assert any(tid.startswith("audit-charm-") for tid in task_ids)
        assert any(tid.startswith("confirm-improvements-") for tid in task_ids)
        # No LLM call — improvement planning is deterministic.
        assert provider._call_count == 0

    @pytest.mark.asyncio
    async def test_replans_when_tasks_exist(self) -> None:
        """When the queue already has tasks, the tool should replan via the LLM."""
        replan_json = json.dumps(
            [
                {"id": "new", "title": "New task", "category": "build"},
            ]
        )
        provider = FakeProvider(
            responses=[Response(content=replan_json)],
        )
        state = AgentState()
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        # First plan (deterministic).
        await tool.execute(intent="Build a charm for Redis")
        first_count = queue.pending_count
        assert first_count == 4

        # Second plan (replanning via LLM) — should call the provider.
        result = await tool.execute(intent="Actually, target machine")
        assert result.success
        assert provider._call_count == 1  # LLM called for replan


# ===================================================================
# TestDetectCurrentJujuModel — substrate-aware auto-detection
# ===================================================================


class TestDetectCurrentJujuModel:
    """Tests for substrate-aware ``detect_current_juju_model``.

    The bug this guards against: a host with both an LXD model (the
    current one) and a k8s model would always return the LXD model,
    even when the charm under development is Kubernetes.
    """

    def test_returns_none_when_juju_missing(self, monkeypatch):
        _patch_juju(monkeypatch, None)
        assert detect_current_juju_model() is None
        assert detect_current_juju_model(prefer_substrate="k8s") is None

    def test_no_substrate_preference_keeps_legacy_behaviour(self, monkeypatch):
        """Without ``prefer_substrate``, return the current non-skip model."""
        payload = _juju_models_payload(
            current="dev",
            models=[
                ("controller", "iaas", True),
                ("dev", "iaas", False),
                ("cos", "caas", False),
            ],
        )
        _patch_juju(monkeypatch, payload)
        assert detect_current_juju_model() == "dev"

    def test_prefers_matching_substrate_over_current(self, monkeypatch):
        """The crux: current LXD + non-current k8s, asking for k8s, picks k8s."""
        payload = _juju_models_payload(
            current="lxd-model",
            models=[
                ("controller", "iaas", True),
                ("lxd-model", "iaas", False),
                ("k8s-model", "caas", False),
            ],
        )
        _patch_juju(monkeypatch, payload)

        assert detect_current_juju_model(prefer_substrate="k8s") == "k8s-model"
        assert detect_current_juju_model(prefer_substrate="machine") == "lxd-model"

    def test_returns_current_when_it_matches_substrate(self, monkeypatch):
        """If the current model already matches, prefer it over other matches."""
        payload = _juju_models_payload(
            current="prod-k8s",
            models=[
                ("controller", "caas", True),
                ("staging-k8s", "caas", False),
                ("prod-k8s", "caas", False),
            ],
        )
        _patch_juju(monkeypatch, payload)
        assert detect_current_juju_model(prefer_substrate="k8s") == "prod-k8s"

    def test_skips_controller_and_cos(self, monkeypatch):
        """``controller`` and ``cos`` must never be selected, even if current."""
        payload = _juju_models_payload(
            current="cos",
            models=[
                ("controller", "iaas", True),
                ("cos", "caas", False),
                ("dev", "caas", False),
            ],
        )
        _patch_juju(monkeypatch, payload)
        assert detect_current_juju_model(prefer_substrate="k8s") == "dev"

    def test_falls_back_when_no_match_for_substrate(self, monkeypatch):
        """If nothing matches the requested substrate, return *something* usable.

        This keeps behaviour against older Juju (no ``model-type`` field)
        or one-substrate hosts the same as before — the caller can't
        deploy a k8s charm there anyway, but auto-detection shouldn't
        leave ``dev_model`` empty.
        """
        payload = _juju_models_payload(
            current="dev",
            models=[
                ("controller", "iaas", True),
                ("dev", "iaas", False),
            ],
        )
        _patch_juju(monkeypatch, payload)
        assert detect_current_juju_model(prefer_substrate="k8s") == "dev"

    def test_no_eligible_models_returns_none(self, monkeypatch):
        payload = _juju_models_payload(
            current=None,
            models=[("controller", "iaas", True), ("cos", "caas", False)],
        )
        _patch_juju(monkeypatch, payload)
        assert detect_current_juju_model() is None
        assert detect_current_juju_model(prefer_substrate="k8s") is None


class TestJujuModelSubstrate:
    """Tests for ``juju_model_substrate`` lookup helper."""

    def test_returns_k8s_for_caas_model(self, monkeypatch):
        payload = _juju_models_payload(
            current="dev",
            models=[("dev", "caas", False)],
        )
        _patch_juju(monkeypatch, payload)
        assert juju_model_substrate("dev") == "k8s"

    def test_returns_machine_for_iaas_model(self, monkeypatch):
        payload = _juju_models_payload(
            current="dev",
            models=[("dev", "iaas", False)],
        )
        _patch_juju(monkeypatch, payload)
        assert juju_model_substrate("dev") == "machine"

    def test_returns_none_for_unknown_model(self, monkeypatch):
        payload = _juju_models_payload(
            current="dev",
            models=[("dev", "iaas", False)],
        )
        _patch_juju(monkeypatch, payload)
        assert juju_model_substrate("nope") is None

    def test_returns_none_when_juju_missing(self, monkeypatch):
        _patch_juju(monkeypatch, None)
        assert juju_model_substrate("dev") is None

    def test_returns_none_for_empty_name(self, monkeypatch):
        # No subprocess call should be needed.
        _patch_juju(monkeypatch, None)
        assert juju_model_substrate("") is None


# ===================================================================
# TestSprintAutoDetect — substrate-aware sprint auto-detection
# ===================================================================


class TestSprintAutoDetect:
    """Sprint planning auto-detects ``dev_model`` against the charm substrate."""

    @pytest.mark.asyncio
    async def test_sprint_picks_k8s_model_for_k8s_charm(self, monkeypatch):
        payload = _juju_models_payload(
            current="lxd-dev",
            models=[
                ("controller", "iaas", True),
                ("lxd-dev", "iaas", False),
                ("k8s-dev", "caas", False),
            ],
        )
        _patch_juju(monkeypatch, payload)

        provider = FakeProvider()
        state = AgentState(charm_path=pathlib.Path("/tmp/charms"))
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        # Sprint trigger: explicit charm_name + charm_type in the call.
        result = await tool.execute(
            intent="Sprint to deploy",
            charm_name="my-charm",
            charm_type="k8s",
        )
        assert result.success
        assert state.dev_model == "k8s-dev"

    @pytest.mark.asyncio
    async def test_sprint_replaces_stale_wrong_substrate_dev_model(self, monkeypatch):
        """A stale LXD ``dev_model`` is dropped when the charm is k8s."""
        payload = _juju_models_payload(
            current="lxd-dev",
            models=[
                ("lxd-dev", "iaas", False),
                ("k8s-dev", "caas", False),
            ],
        )
        _patch_juju(monkeypatch, payload)

        provider = FakeProvider()
        state = AgentState(
            charm_path=pathlib.Path("/tmp/charms"),
            dev_model="lxd-dev",  # stale: from a prior session/guess
        )
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        await tool.execute(
            intent="Sprint to deploy",
            charm_name="my-charm",
            charm_type="k8s",
        )
        assert state.dev_model == "k8s-dev"
