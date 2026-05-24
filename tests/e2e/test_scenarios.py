"""End-to-end scenario tests.

Multi-turn conversation scenarios using FakeProvider with scripted
responses. These exercise the full loop: user message → system prompt
→ tool execution → state mutation → response.
"""

import json
import pathlib

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.llm.base import Response, ToolCall
from tests.conftest import FakeProvider
from tests.support.providers import CallbackProvider, MultiRoleProvider
from tests.support.wait import wait_for_queue_state


@pytest.mark.e2e
class TestScenarios:
    """Full agent-loop scenarios."""

    @pytest.mark.asyncio
    async def test_scaffold_flask_charm(self, tmp_path: pathlib.Path):
        """Simulate scaffolding a Flask charm: analyse → write → respond."""
        # Seed the project with a requirements.txt so analyse_framework has
        # something to detect.
        (tmp_path / "requirements.txt").write_text("flask>=3.0\n")

        provider = FakeProvider(
            [
                # First turn: agent calls analyse_framework.
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="analyse_framework",
                            name="analyse_framework",
                            arguments={"path": "."},
                        ),
                    ],
                ),
                # Second turn: agent writes a charm.py file.
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="write_file",
                            name="write_file",
                            arguments={
                                "path": "src/charm.py",
                                "content": "# Flask charm\nimport ops\n",
                            },
                        ),
                    ],
                ),
                # Final text response.
                Response(content="Your Flask charm is ready!"),
            ]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        result = await agent.process_message("Build a charm for my Flask app")

        assert result == "Your Flask charm is ready!"
        assert (tmp_path / "src" / "charm.py").exists()
        # user + assistant(tool) + tool + assistant(tool) + tool + assistant(final) = 6
        assert len(agent.state.messages) == 6

    @pytest.mark.asyncio
    async def test_multi_turn_with_state(self, tmp_path: pathlib.Path):
        """Two user messages; second turn writes a file."""
        provider = FakeProvider(
            [
                # First turn: simple text response.
                Response(content="Sure, I can help."),
                # Second turn: write a file then respond.
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="write_file",
                            name="write_file",
                            arguments={
                                "path": "metadata.yaml",
                                "content": "name: my-charm\n",
                            },
                        ),
                    ],
                ),
                Response(content="Created metadata.yaml."),
            ]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        await agent.process_message("Help me build a charm")
        await agent.process_message("Create the metadata file")

        # First turn: user + assistant = 2
        # Second turn: user + assistant(tool) + tool + assistant(final) = 4
        # Total: 6
        assert len(agent.state.messages) == 6
        assert (tmp_path / "metadata.yaml").exists()

    @pytest.mark.asyncio
    async def test_tool_failure_recovery(self, tmp_path: pathlib.Path):
        """A tool returning an error should not raise; the agent recovers."""
        provider = FakeProvider(
            [
                # Agent tries to read a non-existent file.
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="read_file",
                            name="read_file",
                            arguments={"path": "does_not_exist.txt"},
                        ),
                    ],
                ),
                # Agent recovers gracefully.
                Response(content="That file doesn't exist. Let me create it instead."),
            ]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        result = await agent.process_message("Read my config file")

        assert "doesn't exist" in result
        # The tool result should be marked as an error.
        tool_messages = [m for m in agent.state.messages if m.role.value == "tool"]
        assert len(tool_messages) == 1
        assert tool_messages[0].tool_results[0].is_error

    @pytest.mark.asyncio
    async def test_state_round_trip_across_sessions(self, tmp_path: pathlib.Path):
        """State persists across two separate agent sessions."""
        # Session 1: process a message, set state, save.
        provider1 = FakeProvider([Response(content="Got it.")])
        agent1 = CantripAgent(provider=provider1, charm_path=tmp_path)
        await agent1.process_message("Hello")
        agent1.state.charm_name = "my-flask-charm"
        agent1.state.charm_type = "k8s"
        agent1.save_state()

        # Session 2: new agent, load state, process another message.
        provider2 = FakeProvider([Response(content="Welcome back!")])
        agent2 = CantripAgent(provider=provider2, charm_path=tmp_path)
        loaded = agent2.load_state()

        assert loaded is True
        assert agent2.state.charm_name == "my-flask-charm"
        assert agent2.state.charm_type == "k8s"

        result = await agent2.process_message("Continue")
        assert result == "Welcome back!"


# ---------------------------------------------------------------------------
# Phase 93.6 — stateful e2e scenarios
#
# Multi-turn / multi-session flows that drive the *whole* CantripAgent —
# conversation loop + persistence + work queue + executor + auto-follow-ups
# + confirmation handlers — through realistic stateful sequences.  The
# existing integration suites cover each seam (autodeploy chain,
# durability/resume, design/day-2/improvement confirmations) individually;
# these scenarios exercise the same flows but assembled through the
# top-level agent API the TUI / CLI actually use.
# ---------------------------------------------------------------------------


_VERIFY_TITLE_FRAGMENT = "Verify deployment:"


def _diagnostic_provider() -> CallbackProvider:
    """Provider that succeeds on every subagent call except verify, which fails.

    Mirrors the integration-suite pattern (``CallbackProvider`` keyed on
    a system-prompt fragment) so the auto-follow-up chain
    BUILD → DEPLOY → Verify → DEBUG is exercised end-to-end without
    LLM stubs that have to know about turn order.
    """

    def respond(messages, tools):  # noqa: ARG001
        for msg in messages:
            if msg.role.value == "system" and _VERIFY_TITLE_FRAGMENT in msg.content:
                raise RuntimeError("Verification failed")
        return Response(content="Task done.")

    return CallbackProvider(respond)


_OVERRIDE_DESIGN_MD = """\
# Redis

## Substrate

Kubernetes — Redis is commonly deployed as a containerised service.

## Charm path

Custom — Redis needs custom relation handling.

## Integrations

- redis-client (provides)
"""


_OVERRIDE_PLAN_JSON = json.dumps(
    {
        "tasks": [
            {
                "id": "scaffold-machine-charm",
                "title": "Scaffold machine charm",
                "category": "build",
                "description": "Initialise a machine-substrate charm directory.",
                "dependencies": [],
            },
            {
                "id": "write-machine-charm-code",
                "title": "Write machine charm code",
                "category": "build",
                "description": "Implement the charm against the machine substrate.",
                "dependencies": ["scaffold-machine-charm"],
            },
        ]
    }
)


_AUDIT_REPORT = (
    "## Audit Results\n\n"
    "- Tracing is missing from the charm — no ops-tracing integration.\n"
    "- No unit tests found. Unit test coverage is missing.\n"
)


@pytest.mark.e2e
class TestStatefulFlows:
    """Phase 93.6 stateful e2e flows driven through the top-level agent."""

    @pytest.mark.asyncio
    async def test_interrupted_session_resumes_and_finishes_pending_deploy(
        self,
        tmp_path: pathlib.Path,
        fast_executor,  # noqa: ARG002
    ):
        """A session saved mid-flow resumes with state + queue intact and
        the executor of a *fresh* agent completes the previously-pending
        DEPLOY task without re-running the already-DONE BUILD."""
        # --- Session 1: do some build work, persist mid-deploy. ---
        provider1 = FakeProvider(
            responses=[
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="write-meta",
                            name="write_file",
                            arguments={
                                "path": "metadata.yaml",
                                "content": "name: redis-k8s\n",
                            },
                        ),
                    ],
                ),
                Response(content="Scaffold complete; deploy is queued."),
            ]
        )
        agent1 = CantripAgent(provider=provider1, charm_path=tmp_path)
        agent1.state.charm_name = "redis-k8s"
        agent1.state.charm_type = "kubernetes"
        agent1.state.framework = "custom"
        agent1.state.dev_model = "dev-model"
        agent1.state.add_decision("substrate", "Kubernetes", "User chose k8s")

        await agent1.process_message("Build a Redis charm")

        # Pre-seed the queue with a completed BUILD and a still-pending DEPLOY
        # — the user closed the lid while the deploy was queued but not yet
        # running.
        build = AgentTask(
            id="build-redis",
            title="Build Redis charm",
            category=TaskCategory.BUILD,
            status=TaskStatus.DONE,
            result="Charm scaffolded.",
        )
        deploy = AgentTask(
            id="deploy-redis",
            title="Deploy Redis charm",
            category=TaskCategory.DEPLOY,
            status=TaskStatus.PENDING,
            dependencies=["build-redis"],
        )
        agent1.work_queue.add_tasks([build, deploy])
        agent1.save_state()

        # --- Session 2: brand-new agent, same charm_path. ---
        provider2 = FakeProvider(
            responses=[Response(content="Deploy complete; verify finished.")] * 3
        )
        agent2 = CantripAgent(provider=provider2, charm_path=tmp_path)

        assert agent2.load_state() is True

        # State round-trip: identity, framework, decisions, prior turn.
        assert agent2.state.charm_name == "redis-k8s"
        assert agent2.state.charm_type == "kubernetes"
        assert agent2.state.framework == "custom"
        assert agent2.state.dev_model == "dev-model"
        decision_types = [d.type for d in agent2.state.decisions]
        assert "substrate" in decision_types
        # Conversation history from session 1 is replayed.
        assert any(
            m.role.value == "user" and "Build a Redis charm" in (m.content or "")
            for m in agent2.state.messages
        )
        # Queue round-trip: BUILD remained DONE, DEPLOY remained PENDING.
        loaded = {t.id: t for t in agent2.work_queue.all_tasks()}
        assert loaded["build-redis"].status == TaskStatus.DONE
        assert loaded["deploy-redis"].status == TaskStatus.PENDING

        # The fresh agent's executor picks up the pending deploy and
        # drives the auto-follow-up chain (Verify) to completion — without
        # re-running the already-DONE build.  Three DONE = BUILD + DEPLOY
        # + Verify.
        agent2.start_executor()
        try:
            await wait_for_queue_state(agent2.work_queue, done_count=3, timeout=10.0)
        finally:
            await agent2.stop_executor()

        final = {t.id: t for t in agent2.work_queue.all_tasks()}
        assert final["build-redis"].status == TaskStatus.DONE
        assert final["build-redis"].result == "Charm scaffolded."  # untouched on resume.
        assert final["deploy-redis"].status == TaskStatus.DONE

    @pytest.mark.asyncio
    async def test_failed_verify_creates_debug_task_through_agent(
        self,
        tmp_path: pathlib.Path,
        fast_executor,  # noqa: ARG002
    ):
        """Driven through ``CantripAgent.start_executor`` (not a raw
        BackgroundExecutor): a failing verify follow-up auto-creates a
        DEBUG task on the agent's own work queue."""
        agent = CantripAgent(provider=_diagnostic_provider(), charm_path=tmp_path)
        agent.state.dev_model = "dev-model"
        agent.state.charm_name = "redis-k8s"

        agent.work_queue.add_task(
            AgentTask(id="build-1", title="Build Redis charm", category=TaskCategory.BUILD)
        )

        agent.start_executor()
        try:
            # BUILD → DEPLOY succeed (2 DONE), Verify FAILS (1 FAILED).
            await wait_for_queue_state(
                agent.work_queue, done_count=2, failed_count=1, timeout=15.0
            )
        finally:
            await agent.stop_executor()

        tasks = agent.work_queue.all_tasks()
        debug_tasks = [t for t in tasks if t.category == TaskCategory.DEBUG]
        verify_tasks = [t for t in tasks if t.title.startswith(_VERIFY_TITLE_FRAGMENT)]
        assert verify_tasks, "auto-deploy did not create a verify follow-up"
        assert all(t.status == TaskStatus.FAILED for t in verify_tasks)
        assert debug_tasks, "failed verify did not create a DEBUG follow-up"
        assert any("Diagnose" in t.title for t in debug_tasks)
        # The DEBUG task remembers what it's diagnosing.
        assert any(verify_tasks[0].id in t.dependencies for t in debug_tasks)

    @pytest.mark.asyncio
    async def test_improvement_flow_audits_existing_charm_and_runs_fixes(
        self,
        tmp_path: pathlib.Path,
        fast_executor,  # noqa: ARG002
    ):
        """Existing charm → audit task DONE → user confirms improvements
        → fix tasks created → executor runs every fix to completion."""
        # Seed a minimal existing charm so the agent sees a real workspace.
        (tmp_path / "metadata.yaml").write_text("name: redis-k8s\n")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "charm.py").write_text("import ops\n\n# stub\n")
        (tmp_path / "requirements.txt").write_text("ops>=2.16\n")

        provider = MultiRoleProvider(subagent_responses=[Response(content="Fix applied.")] * 4)
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.charm_name = "redis-k8s"
        agent.state.charm_type = "kubernetes"
        agent.state.framework = "custom"
        agent.state.dev_model = "dev-model"

        audit = AgentTask(
            id="audit-redis",
            title="Audit redis-k8s for gaps",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            result=_AUDIT_REPORT,
        )
        confirm = AgentTask(
            id="confirm-improve-redis",
            title="Confirm improvements",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
            dependencies=["audit-redis"],
        )
        agent.work_queue.add_tasks([audit, confirm])

        fix_tasks = await agent.handle_improvement_confirmation("confirm-improve-redis")

        assert fix_tasks, "audit findings did not turn into any fix tasks"
        assert agent.state.audit_report == _AUDIT_REPORT
        fix_ids = [t.id for t in fix_tasks]
        assert any(i.startswith("fill-observability") for i in fix_ids)
        assert any(i.startswith("fill-tests") for i in fix_ids)

        # In the real flow the TUI approves the CONFIRM task explicitly
        # — mirrors ``app.py:_handle_improvement_confirm_approve``.
        # Without this the BUILD fix tasks stay BLOCKED on the confirm
        # dependency and the executor can't make progress.
        agent.work_queue.set_done("confirm-improve-redis", "Approved by user")

        agent.start_executor()
        try:
            # audit (DONE) + confirm (DONE) + every fix task should reach
            # DONE.  Downstream tasks (validate / deploy-verify /
            # diff-review / operability) are exercised by separate suites.
            await wait_for_queue_state(
                agent.work_queue,
                done_count=1 + 1 + len(fix_tasks),
                timeout=20.0,
            )
            build_after = [
                t for t in agent.work_queue.all_tasks() if t.category == TaskCategory.BUILD
            ]
            assert build_after, "no BUILD fix tasks materialised in the queue"
            assert all(t.status == TaskStatus.DONE for t in build_after)
        finally:
            await agent.stop_executor()

    @pytest.mark.asyncio
    async def test_user_override_steers_design_to_machine_path(
        self,
        tmp_path: pathlib.Path,
        fast_executor,  # noqa: ARG002
    ):
        """User rejects the synthesised plan with an override; the
        planner is consulted with the override visible, build tasks
        reflect the new direction, and the executor runs *that* plan."""
        seen_planner_messages: list[str] = []

        # MultiRoleProvider routes planner vs subagent by system prompt;
        # we wrap it to capture the planner's USER turn and assert the
        # override actually reached the LLM call.
        class CapturingPlanner(MultiRoleProvider):
            async def complete(
                self,
                messages,
                tools=None,
                temperature=0.7,
                max_tokens=None,
                thinking_budget=None,
                response_schema=None,
            ):
                for msg in messages:
                    if msg.role.value == "user":
                        seen_planner_messages.append(msg.content)
                return await super().complete(
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    thinking_budget=thinking_budget,
                    response_schema=response_schema,
                )

        provider = CapturingPlanner(
            planner_responses=[Response(content=_OVERRIDE_PLAN_JSON)],
            subagent_responses=[Response(content="Override task done.")] * 4,
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.charm_name = "redis"
        agent.state.dev_model = "dev-model"

        synthesis = AgentTask(
            id="operational-discovery",
            title="Synthesise design proposal",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            result=_OVERRIDE_DESIGN_MD,
        )
        confirm = AgentTask(
            id="confirm-design",
            title="Confirm design with user",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
            dependencies=["operational-discovery"],
        )
        agent.work_queue.add_tasks([synthesis, confirm])

        override_text = "Switch to machine substrate using LXD — no k8s."
        build_tasks = await agent.handle_design_confirmation(
            "confirm-design", overrides=override_text
        )

        # The synthesised proposal said k8s, but the user override
        # produced a machine-substrate plan.  Build tasks come from the
        # override JSON, not the deterministic one-shot path.
        assert len(build_tasks) == 2
        titles = [t.title for t in build_tasks]
        assert "Scaffold machine charm" in titles
        assert "Write machine charm code" in titles
        # The override text reached the planner verbatim.
        assert any(override_text in m for m in seen_planner_messages)

        # The synthesised proposal's substrate is still recorded as a
        # decision (the override doesn't rewrite history) — but the *plan*
        # the executor runs is the override plan.
        decision_types = [d.type for d in agent.state.decisions]
        assert "substrate" in decision_types

        agent.start_executor()
        try:
            # synthesis (already DONE) + 2 override build tasks.
            await wait_for_queue_state(agent.work_queue, done_count=3, timeout=15.0)
        finally:
            await agent.stop_executor()

        executed_builds = [
            t
            for t in agent.work_queue.all_tasks()
            if t.category == TaskCategory.BUILD
            and (t.id.startswith("scaffold-machine") or t.id.startswith("write-machine"))
        ]
        assert executed_builds
        assert all(t.status == TaskStatus.DONE for t in executed_builds)
