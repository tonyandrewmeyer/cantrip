"""Tests for Phase 110 phase-aware tool curation.

Covers the :class:`WorkflowPhase` enum + category mapping, the
``CANTRIP_TOOL_PHASE`` operator override, and ``CantripAgent``'s
per-turn curated tool slice (``_tools_for_llm`` / ``workflow_phase`` /
``tool_phase_badge``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cantrip.agent.core import CantripAgent
from cantrip.agent.queue import AgentTask, TaskCategory, WorkflowPhase
from tests.conftest import FakeProvider

if TYPE_CHECKING:
    import pytest


class _ShortSessionProvider(FakeProvider):
    """A FakeProvider whose tiny context window flips short-session mode on."""

    @property
    def short_session_mode(self) -> bool:
        return True


class _CappedProvider(FakeProvider):
    """A roomy provider that nonetheless caps the tool array (inference-snap style)."""

    @property
    def max_tools(self) -> int | None:
        return 12


# ---------------------------------------------------------------------------
# 110.1 — WorkflowPhase + category mapping
# ---------------------------------------------------------------------------


class TestWorkflowPhaseMapping:
    def test_direct_categories(self) -> None:
        assert WorkflowPhase.from_category(TaskCategory.RESEARCH) is WorkflowPhase.RESEARCH
        assert WorkflowPhase.from_category(TaskCategory.BUILD) is WorkflowPhase.BUILD
        assert WorkflowPhase.from_category(TaskCategory.DEBUG) is WorkflowPhase.DEBUG
        assert WorkflowPhase.from_category(TaskCategory.DEPLOY) is WorkflowPhase.DEPLOY

    def test_test_is_debug_shaped(self) -> None:
        assert WorkflowPhase.from_category(TaskCategory.TEST) is WorkflowPhase.DEBUG

    def test_infra_is_deploy_shaped(self) -> None:
        assert WorkflowPhase.from_category(TaskCategory.INFRA) is WorkflowPhase.DEPLOY

    def test_bookkeeping_categories_default_to_build(self) -> None:
        assert WorkflowPhase.from_category(TaskCategory.CONFIRM) is WorkflowPhase.BUILD

    def test_librarian_is_research_shaped(self) -> None:
        assert WorkflowPhase.from_category(TaskCategory.LIBRARIAN) is WorkflowPhase.RESEARCH

    def test_none_defaults_to_build(self) -> None:
        assert WorkflowPhase.from_category(None) is WorkflowPhase.BUILD

    def test_every_category_maps(self) -> None:
        for category in TaskCategory:
            assert isinstance(WorkflowPhase.from_category(category), WorkflowPhase)


# ---------------------------------------------------------------------------
# 110.1 — the per-phase tool tables
# ---------------------------------------------------------------------------


class TestCoreToolsByPhase:
    def test_every_phase_has_a_table(self) -> None:
        for phase in WorkflowPhase:
            assert phase in CantripAgent._CORE_TOOLS_BY_PHASE

    def test_tables_fit_the_inference_snap_budget(self) -> None:
        # ≤ 11 names so the 12-tool cap can still fit one MCP tool / extension.
        for phase, names in CantripAgent._CORE_TOOLS_BY_PHASE.items():
            assert len(names) <= 11, f"{phase} table has {len(names)} tools"

    def test_build_set_carries_the_demo_dry_run_fixers(self) -> None:
        build = CantripAgent._CORE_TOOLS_BY_PHASE[WorkflowPhase.BUILD]
        # ``charmlint`` lets the model see YAML structure errors instead of
        # oscillating on pack-fail / guess; ``quick_pack`` is the LXD-free
        # packer the sprint recipe explicitly prefers.
        assert {"charmlint", "quick_pack"} <= build

    def test_research_set_is_navigation_and_inquiry(self) -> None:
        research = CantripAgent._CORE_TOOLS_BY_PHASE[WorkflowPhase.RESEARCH]
        assert {"web_search", "analyse_framework", "oracle_consult"} <= research
        # Packing / juju tools have no business in a research turn.
        assert "charmcraft_pack" not in research
        assert "juju" not in research


# ---------------------------------------------------------------------------
# 110.2 — the curator hooked into _tools_for_llm
# ---------------------------------------------------------------------------


def _names(agent: CantripAgent) -> set[str]:
    return {t.name for t in agent._tools_for_llm()}


class TestCuratedToolSlice:
    def test_roomy_provider_gets_everything(self) -> None:
        agent = CantripAgent(provider=FakeProvider())
        assert _names(agent) == {t.name for t in agent._tools}
        assert agent.tool_phase_badge() == ""

    def test_idle_short_session_defaults_to_build(self) -> None:
        agent = CantripAgent(provider=_ShortSessionProvider())
        assert agent.workflow_phase is WorkflowPhase.BUILD
        assert _names(agent) == CantripAgent._CORE_TOOLS_BY_PHASE[WorkflowPhase.BUILD]

    def test_build_category_active_task_picks_build_set(self) -> None:
        agent = CantripAgent(provider=_ShortSessionProvider())
        agent.work_queue.add_task(
            AgentTask(id="t1", title="Scaffold", category=TaskCategory.BUILD)
        )
        agent.work_queue.set_active("t1")
        assert agent.workflow_phase is WorkflowPhase.BUILD
        assert _names(agent) == CantripAgent._CORE_TOOLS_BY_PHASE[WorkflowPhase.BUILD]

    def test_deploy_category_active_task_picks_deploy_set(self) -> None:
        agent = CantripAgent(provider=_ShortSessionProvider())
        agent.work_queue.add_task(AgentTask(id="t1", title="Deploy", category=TaskCategory.DEPLOY))
        agent.work_queue.set_active("t1")
        assert agent.workflow_phase is WorkflowPhase.DEPLOY
        names = _names(agent)
        assert "juju" in names and "concierge_prepare" in names
        assert "charmlint" not in names

    def test_capped_provider_curates_without_short_session(self) -> None:
        # Roomy context, but the API caps the tool array — same curation
        # path, no short-session flag in play.
        agent = CantripAgent(provider=_CappedProvider())
        assert agent.context_manager.short_session_mode is False
        assert len(agent._tools) > 12
        assert _names(agent) <= CantripAgent._CORE_TOOLS_BY_PHASE[WorkflowPhase.BUILD]
        assert agent.tool_phase_badge().startswith("build · ")

    def test_transition_reshapes_the_next_slice(self) -> None:
        agent = CantripAgent(provider=_ShortSessionProvider())
        agent.work_queue.add_task(AgentTask(id="b", title="Build", category=TaskCategory.BUILD))
        agent.work_queue.set_active("b")
        assert _names(agent) == CantripAgent._CORE_TOOLS_BY_PHASE[WorkflowPhase.BUILD]
        # A test failed — the queue flips to a debug task.
        agent.work_queue.set_done("b")
        agent.work_queue.add_task(AgentTask(id="d", title="Fix", category=TaskCategory.DEBUG))
        agent.work_queue.set_active("d")
        assert agent.workflow_phase is WorkflowPhase.DEBUG
        assert _names(agent) == CantripAgent._CORE_TOOLS_BY_PHASE[WorkflowPhase.DEBUG]


# ---------------------------------------------------------------------------
# 110.3 — CANTRIP_TOOL_PHASE operator override
# ---------------------------------------------------------------------------


class TestToolPhaseOverride:
    def test_override_wins_over_active_task(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = CantripAgent(provider=_ShortSessionProvider())
        agent.work_queue.add_task(AgentTask(id="t1", title="Build", category=TaskCategory.BUILD))
        agent.work_queue.set_active("t1")
        monkeypatch.setenv("CANTRIP_TOOL_PHASE", "research")
        assert agent.workflow_phase is WorkflowPhase.RESEARCH
        assert _names(agent) == CantripAgent._CORE_TOOLS_BY_PHASE[WorkflowPhase.RESEARCH]

    def test_override_is_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = CantripAgent(provider=_ShortSessionProvider())
        monkeypatch.setenv("CANTRIP_TOOL_PHASE", "  DEPLOY ")
        assert agent.workflow_phase is WorkflowPhase.DEPLOY

    def test_invalid_override_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = CantripAgent(provider=_ShortSessionProvider())
        monkeypatch.setenv("CANTRIP_TOOL_PHASE", "definitely-not-a-phase")
        assert agent.workflow_phase is WorkflowPhase.BUILD

    def test_empty_override_falls_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = CantripAgent(provider=_ShortSessionProvider())
        agent.work_queue.add_task(AgentTask(id="t1", title="Deploy", category=TaskCategory.DEPLOY))
        agent.work_queue.set_active("t1")
        monkeypatch.setenv("CANTRIP_TOOL_PHASE", "")
        assert agent.workflow_phase is WorkflowPhase.DEPLOY


# ---------------------------------------------------------------------------
# 110.3 — tool_phase_badge for status surfaces
# ---------------------------------------------------------------------------


class TestToolPhaseBadge:
    def test_quiet_when_uncurated(self) -> None:
        assert CantripAgent(provider=FakeProvider()).tool_phase_badge() == ""

    def test_shows_phase_and_count_when_curated(self) -> None:
        agent = CantripAgent(provider=_ShortSessionProvider())
        badge = agent.tool_phase_badge()
        assert badge.startswith("build · ")
        assert int(badge.rsplit(" ", 1)[1]) == len(agent._tools_for_llm())

    def test_badge_tracks_the_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = CantripAgent(provider=_ShortSessionProvider())
        monkeypatch.setenv("CANTRIP_TOOL_PHASE", "research")
        assert agent.tool_phase_badge().startswith("research · ")
