"""Task planner — LLM-powered decomposition of user intent into agent tasks.

For the common "build a charm for X" flow, the research phase (Phase 1 + 2)
uses deterministic task templates — no LLM call needed.  LLM planning is
reserved for replanning (scope changes) and the build phase (which depends
on the approved design).
"""

import json
import logging
import platform
import re
from dataclasses import dataclass, field
from uuid import uuid4

from cantrip.agent.queue import AgentTask, ModelHint, TaskCategory, TaskStatus
from cantrip.llm import base as llm

log = logging.getLogger(__name__)

# Temperature used for planning calls — low to encourage structured output.
_PLANNING_TEMPERATURE = 0.3

# Valid task categories for validation.
_VALID_CATEGORIES = {c.value for c in TaskCategory}


@dataclass
class PlanningContext:
    """Bundles context for a planning or replanning call."""

    intent: str
    charm_name: str | None = None
    charm_type: str | None = None
    framework: str | None = None
    dev_model: str | None = None
    cos_model: str | None = None
    environment_ready: bool = False
    existing_tasks: list[AgentTask] = field(default_factory=list)
    new_context: str | None = None
    source_url: str | None = None
    existing_charm_path: str | None = None


# ---------------------------------------------------------------------------
# Deterministic task templates
# ---------------------------------------------------------------------------

# Frameworks with well-understood 12-factor PaaS charm paths — skip research.
_FAST_PATH_FRAMEWORKS = frozenset(
    {
        "flask",
        "django",
        "fastapi",
        "go",
        "express",
        "spring-boot",
    }
)


def _unique_id(base: str) -> str:
    """Return *base* with a random suffix to avoid collisions across plans."""
    return f"{base}-{uuid4().hex[:8]}"


def is_fast_path(context: PlanningContext) -> bool:
    """Return whether the context qualifies for the fast (no-research) path.

    Fast path applies when the framework is a known 12-factor type and
    no source URL needs deep analysis.
    """
    return (
        context.framework is not None
        and context.framework.lower() in _FAST_PATH_FRAMEWORKS
        and context.source_url is None
    )


def is_sprint(context: PlanningContext) -> bool:
    """Return whether the context qualifies for the sprint (instant deploy) path.

    Sprint applies for well-known frameworks (12-factor PaaS) or when a
    charm type is explicitly set with no source URL.  Skips research,
    confirmation, and tests — goes straight to scaffold + pack + deploy.
    """
    if context.source_url is not None:
        return False
    # 12-factor PaaS frameworks.
    if context.framework and context.framework.lower() in _FAST_PATH_FRAMEWORKS:
        return True
    # Explicit charm type with a name — user knows what they want.
    return bool(context.charm_type and context.charm_name)


# Title prefixes used to identify sprint tasks in follow-up logic.
SPRINT_BUILD_PREFIX = "Sprint build:"
SPRINT_DEPLOY_PREFIX = "Sprint deploy:"


def _host_ubuntu_version() -> str:
    """Return the host Ubuntu version (e.g. '24.04') for destructive-mode packing."""
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("VERSION_ID="):
                    return line.split("=")[1].strip().strip('"')
    except OSError:
        pass
    # Fallback to platform.
    return platform.freedesktop_os_release().get("VERSION_ID", "24.04")


def _sprint_design_paas(workload: str, framework: str) -> str:
    """Generate a deterministic design for a 12-factor PaaS charm."""
    profile = f"{framework}-framework"
    return (
        f"# Design: {workload}\n\n"
        f"## Summary\n"
        f"Minimal 12-factor PaaS charm for {workload} using the `{profile}` profile.\n\n"
        f"## Substrate\nKubernetes\n\n"
        f"## Charm path\n12-factor PaaS (paas-charm base)\n\n"
        f"## Profile\n`{profile}`\n\n"
        f"## Integrations\nNone for initial deploy — add after verifying the base works.\n\n"
        f"## Notes\n"
        f"Sprint deploy — minimal viable charm. Tests, COS, and integrations "
        f"will be added in follow-up tasks after the charm is deployed and active."
    )


def _sprint_design_custom(workload: str, charm_type: str) -> str:
    """Generate a deterministic design for a simple custom charm."""
    profile = "kubernetes" if charm_type == "k8s" else "machine"
    return (
        f"# Design: {workload}\n\n"
        f"## Summary\n"
        f"Minimal {profile} charm for {workload}.\n\n"
        f"## Substrate\n{profile.title()}\n\n"
        f"## Charm path\nCustom ({profile})\n\n"
        f"## Profile\n`{profile}`\n\n"
        f"## Integrations\nNone for initial deploy.\n\n"
        f"## Notes\n"
        f"Sprint deploy — the scaffolded charm from `charmcraft init` is "
        f"almost sufficient. Make only minimal adjustments to get deployed."
    )


def plan_sprint_deploy(context: PlanningContext) -> list[AgentTask]:
    """Generate a minimal BUILD + DEPLOY sequence for instant deployment.

    Skips research, design confirmation, tests, and validation entirely.
    Gets a working charm packed and deployed as fast as possible.  The
    design is generated deterministically — no LLM call needed.

    After sprint deployment succeeds, the user can iterate with the full
    research/build/test flow to add integrations, COS, and tests.
    """
    workload = context.charm_name or context.framework or "the workload"
    framework = context.framework
    ubuntu_version = _host_ubuntu_version()

    if framework and framework.lower() in _FAST_PATH_FRAMEWORKS:
        profile = f"{framework}-framework"
        design = _sprint_design_paas(workload, framework.lower())
    else:
        charm_type = context.charm_type or "k8s"
        profile = "kubernetes" if charm_type == "k8s" else "machine"
        design = _sprint_design_custom(workload, charm_type)

    build_id = _unique_id("sprint-build")
    deploy_id = _unique_id("sprint-deploy")

    return [
        AgentTask(
            id=build_id,
            title=f"{SPRINT_BUILD_PREFIX} {workload}",
            category=TaskCategory.BUILD,
            model_hint=ModelHint.PRIMARY,
            description=(
                f"Build a minimal charm and pack it as fast as possible.\n\n"
                f"**Goal:** Produce a deployable .charm file with the bare minimum.\n"
                f"Do NOT write tests. Do NOT run charm_validate. Do NOT add "
                f"COS/observability integrations.\n\n"
                f"Steps:\n"
                f"1. Run charmcraft_init with name='{workload}' and "
                f"profile='{profile}'\n"
                f"2. Edit charmcraft.yaml with these changes for fast packing:\n"
                f"   - Change `base: ubuntu@22.04` to `base: ubuntu@{ubuntu_version}`\n"
                f"   - Change the parts plugin from `uv` to `charm`\n"
                f"   - Remove the `build-snaps` section (the `astral-uv` line)\n"
                f"3. Overwrite `requirements.txt` with ONLY `ops>=3,<4` on one "
                f"line — remove any other dependencies like ops-tracing "
                f"(they slow down packing enormously)\n"
                f"4. Edit src/charm.py: remove any `import ops_tracing` line "
                f"and any `ops_tracing.setup(self)` call (since ops-tracing "
                f"is not in requirements.txt). Leave everything else as-is.\n"
                f"5. **CRITICAL**: Run charmcraft_pack with destructive_mode=true — "
                f"this MUST happen, the task is not done without a .charm file\n"
                f"6. Use git_init, git_add, and git_commit to save the work\n\n"
                f"**Important:** Keep changes minimal. The scaffolded charm from "
                f"charmcraft init is designed to work out of the box. "
                f"You MUST call charmcraft_pack before finishing.\n\n"
                f"Design:\n{design}"
            ),
            dependencies=[],
        ),
        AgentTask(
            id=deploy_id,
            title=f"{SPRINT_DEPLOY_PREFIX} {workload}",
            category=TaskCategory.DEPLOY,
            description=(
                "Deploy the freshly packed charm and verify it reaches active/idle.\n\n"
                "1. Find the .charm file in the charm directory\n"
                "2. Deploy with juju_deploy\n"
                "3. Run juju_wait to confirm the application reaches active/idle\n"
                "4. Report the final status"
            ),
            dependencies=[build_id],
        ),
    ]


def plan_fast_path(context: PlanningContext) -> list[AgentTask]:
    """Generate a compressed task list for well-known 12-factor frameworks.

    Skips the full research phase — produces a single synthesis task that
    generates a template-based design, then goes straight to confirm.
    """
    workload = context.charm_name or context.framework or "the workload"
    framework = context.framework or "unknown"

    design_id = _unique_id("fast-design")
    confirm_id = _unique_id("confirm-design")

    return [
        AgentTask(
            id=design_id,
            title=f"operational-discovery: design 12-factor charm for {workload}",
            category=TaskCategory.RESEARCH,
            description=(
                f"Generate a design proposal for a {framework} 12-factor PaaS charm. "
                f"This is a well-understood framework — use the paas-charm base with "
                f"the {framework}-framework profile. Include standard integrations "
                f"(ingress, database if applicable, COS). Search Charmhub briefly "
                f"to check for existing charms."
            ),
            dependencies=[],
        ),
        AgentTask(
            id=confirm_id,
            title="Confirm design with user",
            category=TaskCategory.CONFIRM,
            description="Present the design proposal for user approval.",
            dependencies=[design_id],
        ),
    ]


def is_one_shot_build(context: PlanningContext) -> bool:
    """Return whether the build phase can be collapsed into a single task.

    One-shot build applies when the framework is a known 12-factor type —
    the scaffold + write + pack sequence is predictable enough for one
    subagent invocation.
    """
    return context.framework is not None and context.framework.lower() in _FAST_PATH_FRAMEWORKS


def plan_one_shot_build(context: PlanningContext, design_content: str) -> list[AgentTask]:
    """Generate a single BUILD task that scaffolds, writes, and packs.

    For well-understood 12-factor frameworks the typical 3–5 build tasks
    (scaffold, write charm, write tests, pack) can be handled in a single
    subagent pass because the structure is predictable.
    """
    workload = context.charm_name or context.framework or "the workload"
    framework = context.framework or "unknown"

    return [
        AgentTask(
            id=_unique_id("one-shot-build"),
            title=f"Build {framework} charm for {workload}",
            category=TaskCategory.BUILD,
            model_hint=ModelHint.PRIMARY,
            description=(
                f"Build a complete {framework} 12-factor PaaS charm for {workload} in a "
                f"single pass using a red/green cycle. Steps:\n"
                f"1. Run charmcraft init to scaffold the charm\n"
                f"2. Write metadata (charmcraft.yaml) with correct name, bases, containers, "
                f"and integrations from the approved design\n"
                f"3. Write rockcraft.yaml if needed for the {framework} workload\n"
                f"4. Write integration tests from the design — deploy, relate, config, "
                f"actions (these are the 'red' tests that define the external contract)\n"
                f"5. Write src/charm.py with Pebble layer, integrations, and config "
                f"handling to make the integration tests pass ('green')\n"
                f"6. Write unit tests using Scenario (ops.testing) for edge cases and "
                f"error paths\n"
                f"7. Pack the charm with charmcraft pack\n\n"
                f"If the design lists companion charms, include them in integration "
                f"tests (deploy + relate each companion before asserting status).\n\n"
                f"Approved design:\n{design_content}"
            ),
            dependencies=[],
        ),
    ]


def is_improvement(context: PlanningContext) -> bool:
    """Return whether the context describes an improvement request.

    An improvement request targets an existing charm directory rather than
    building a new charm from scratch.
    """
    return context.existing_charm_path is not None


def plan_improvement_phase(context: PlanningContext) -> list[AgentTask]:
    """Generate the audit → confirm → fix task sequence for improving an existing charm.

    Deterministic template — no LLM call needed.  The audit task runs the
    ``charm_audit`` tool and produces a structured report.  After the user
    confirms which areas to address, conditional fix tasks are generated
    by ``plan_improvement_fixes``.
    """
    charm_path = context.existing_charm_path or "."
    charm_name = context.charm_name or "the charm"

    audit_id = _unique_id("audit-charm")
    confirm_id = _unique_id("confirm-improvements")

    return [
        AgentTask(
            id=audit_id,
            title=f"Audit existing charm: {charm_name}",
            category=TaskCategory.RESEARCH,
            model_hint=ModelHint.PRIMARY,
            description=(
                f"Audit the existing charm at {charm_path} against best practices.\n\n"
                "1. Run `charm_audit` to get a structured report of issues.\n"
                "2. Read key files (`charmcraft.yaml`, `src/charm.py`, `README.md`, "
                "tests) to understand the current state.\n"
                "3. Produce a comprehensive AUDIT.md covering: COS integration gaps, "
                "test coverage, deprecated APIs, metadata completeness, and listing "
                "readiness.\n"
                "4. Categorise findings as must-fix, should-fix, and nice-to-have."
            ),
            dependencies=[],
        ),
        AgentTask(
            id=confirm_id,
            title="Confirm improvement plan with user",
            category=TaskCategory.CONFIRM,
            description=(
                "Present the audit findings to the user and confirm which "
                "improvement areas to address (observability, tests, code "
                "modernisation, listing readiness)."
            ),
            dependencies=[audit_id],
        ),
    ]


def plan_improvement_fixes(
    context: PlanningContext,
    gaps: dict[str, bool],
    confirm_task_id: str = "confirm-improvements",
) -> list[AgentTask]:
    """Generate fix tasks based on audit findings.

    Called after the user confirms which improvements to make.  Each gap
    area becomes a BUILD task; all depend on *confirm_task_id*.
    A final validation task depends on all fix tasks.
    """
    charm_path = context.existing_charm_path or "."
    tasks: list[AgentTask] = []
    fix_ids: list[str] = []

    # Observability gaps.
    cos_gaps = [
        k
        for k in ("cos_tracing", "cos_metrics", "cos_logging", "cos_dashboards", "ops_tracing")
        if gaps.get(k)
    ]
    if cos_gaps:
        obs_id = _unique_id("fill-observability")
        tasks.append(
            AgentTask(
                id=obs_id,
                title="Fill observability gaps",
                category=TaskCategory.BUILD,
                model_hint=ModelHint.PRIMARY,
                description=(
                    f"Add missing COS integration to the charm at {charm_path}.\n\n"
                    f"Missing: {', '.join(cos_gaps)}\n\n"
                    "1. Load the `observability` and `charm-improvement` skills.\n"
                    "2. Add missing COS relations to charmcraft.yaml (tracing, "
                    "metrics-endpoint, logging, grafana-dashboard).\n"
                    "3. Add ops-tracing if missing — install dependency and add "
                    "`ops_tracing.setup(self)` in `__init__`.\n"
                    "4. Add a Prometheus metrics endpoint if missing — expose "
                    "workload metrics via the `metrics-endpoint` relation.\n"
                    "5. Add Loki log forwarding if missing — add the `logging` "
                    "relation and ensure structured logging is used.\n"
                    "6. Generate a basic Grafana dashboard JSON in "
                    "`src/grafana_dashboards/` covering key operational metrics "
                    "(unit status, hook durations, relation counts).\n"
                    "7. Generate basic Prometheus alert rules in "
                    "`src/prometheus_alert_rules/` for common failure conditions "
                    "(unit blocked, hook failures, resource exhaustion).\n"
                    "8. Commit changes with a descriptive message."
                ),
                dependencies=[confirm_task_id],
            )
        )
        fix_ids.append(obs_id)

    # Test gaps.
    test_gaps = [k for k in ("unit_tests", "integration_tests") if gaps.get(k)]
    if test_gaps:
        test_id = _unique_id("fill-tests")
        tasks.append(
            AgentTask(
                id=test_id,
                title="Fill test gaps",
                category=TaskCategory.BUILD,
                model_hint=ModelHint.PRIMARY,
                description=(
                    f"Add missing tests to the charm at {charm_path}.\n\n"
                    f"Missing: {', '.join(test_gaps)}\n\n"
                    "1. Load the `charm-improvement` skill for test patterns.\n"
                    "2. Read the existing charm code to understand events, relations, "
                    "config, and actions.\n"
                    "3. If unit tests are missing, write Scenario-based unit tests "
                    "in `tests/unit/test_charm.py` covering all observed events, "
                    "happy paths, and error cases. Do NOT use the deprecated "
                    "Harness. Cover: missing relations → BlockedStatus, invalid "
                    "config → error handling, Pebble not ready → WaitingStatus.\n"
                    "4. If integration tests are missing, write Jubilant integration "
                    "tests in `tests/integration/test_charm.py` covering:\n"
                    "   - Deploy and reach active/idle\n"
                    "   - Each relation endpoint (deploy + relate + verify)\n"
                    "   - Each action (run + check result)\n"
                    "   - Config changes (set + verify)\n"
                    "5. Run `run_charm_tests` for each test type and fix any "
                    "failures. Iterate until green.\n"
                    "6. Commit changes with a descriptive message."
                ),
                dependencies=[confirm_task_id],
            )
        )
        fix_ids.append(test_id)

    # Code modernisation (deprecated APIs, type annotations, modern patterns).
    needs_modernise = (
        gaps.get("deprecated_apis") or gaps.get("type_annotations") or gaps.get("modern_patterns")
    )
    if needs_modernise:
        steps = []
        if gaps.get("deprecated_apis"):
            steps.append(
                "- Replace StoredState with instance attributes or Juju secrets.\n"
                "- Replace Harness test imports with Scenario.\n"
                "- Replace charmcraft fetch-libs imports with PyPI equivalents "
                "where available."
            )
        if gaps.get("type_annotations"):
            steps.append(
                "- Add return-type annotations to all public functions and methods.\n"
                "- Add parameter type hints where missing."
            )
        if gaps.get("modern_patterns"):
            steps.append(
                "- Implement a `_reconcile()` method as the single source of truth "
                "for unit status (holistic status handling).\n"
                "- Use the config-changed reconciliation pattern: config-changed "
                "calls `_reconcile()` which validates and applies config.\n"
                "- Handle relation-created / relation-changed events properly: "
                "validate relation data, set status, and reconcile.\n"
                "- Add Pebble readiness checks: handle pebble-ready event, guard "
                "container operations with `can_connect()`."
            )
        step_text = "\n".join(steps)
        mod_id = _unique_id("modernise-code")
        tasks.append(
            AgentTask(
                id=mod_id,
                title="Modernise charm code",
                category=TaskCategory.BUILD,
                model_hint=ModelHint.PRIMARY,
                description=(
                    f"Modernise the charm code at {charm_path}.\n\n"
                    f"{step_text}\n\n"
                    "Run tests after each change to verify nothing breaks.\n"
                    "Commit changes with a descriptive message."
                ),
                dependencies=[confirm_task_id],
            )
        )
        fix_ids.append(mod_id)

    # Listing readiness (README, metadata, licence).
    listing_gaps = [k for k in ("readme", "licence", "icon") if gaps.get(k)]
    if listing_gaps or gaps.get("listing_metadata"):
        listing_id = _unique_id("listing-readiness")
        tasks.append(
            AgentTask(
                id=listing_id,
                title="Prepare for Charmhub listing",
                category=TaskCategory.BUILD,
                model_hint=ModelHint.PRIMARY,
                description=(
                    f"Prepare the charm at {charm_path} for Charmhub listing.\n\n"
                    "1. Generate or update README.md with standard sections "
                    "(description, deployment, configuration, integrations).\n"
                    "2. Fill in missing charmcraft.yaml metadata fields "
                    "(display-name, summary, description, docs, issues, source).\n"
                    "3. Check for LICENSE file — suggest Apache-2.0 if missing.\n"
                    "4. If icon.svg is missing, run `generate_icon` to create a "
                    "placeholder icon (coloured circle with the charm's initial).\n"
                    "5. If no docs/ directory exists, run `generate_docs` to "
                    "create Diátaxis-structured documentation (tutorial, how-to, "
                    "reference, explanation) with the Canonical starter pack.\n"
                    "6. Commit changes with a descriptive message."
                ),
                dependencies=[confirm_task_id],
            )
        )
        fix_ids.append(listing_id)

    # Validation task depends on all fixes.
    if fix_ids:
        validate_id = _unique_id("validate-improvements")
        tasks.append(
            AgentTask(
                id=validate_id,
                title="Validate all improvements",
                category=TaskCategory.TEST,
                description=(
                    f"Validate the improved charm at {charm_path}.\n\n"
                    "1. Run `charm_validate` to verify the charm packs cleanly.\n"
                    "2. Run unit tests with `run_charm_tests`.\n"
                    "3. Run integration tests with `run_charm_tests` if present.\n"
                    "4. Report pass/fail counts for each."
                ),
                dependencies=fix_ids,
            )
        )

        # Deploy and verify the improved charm reaches active/idle.
        deploy_id = _unique_id("deploy-verify-improvements")
        tasks.append(
            AgentTask(
                id=deploy_id,
                title="Deploy and verify improved charm",
                category=TaskCategory.DEPLOY,
                description=(
                    f"Deploy the improved charm at {charm_path} and verify it works.\n\n"
                    "1. Pack the charm with `charmcraft_pack`.\n"
                    "2. Deploy or refresh with `juju_deploy` / `juju_refresh`.\n"
                    "3. Establish all relations.\n"
                    "4. Run `juju_wait` to confirm active/idle.\n"
                    "5. If COS relations were added, verify they are established."
                ),
                dependencies=[validate_id],
            )
        )

        # Diff review — summarise all changes for the user.
        tasks.append(
            AgentTask(
                id=_unique_id("diff-review"),
                title="Review improvement changes",
                category=TaskCategory.RESEARCH,
                model_hint=ModelHint.PRIMARY,
                description=(
                    f"Summarise all changes made to the charm at {charm_path}.\n\n"
                    "1. Run `git_log` to see all commits made during improvement.\n"
                    "2. Run `git_diff` against the initial state to see the full diff.\n"
                    "3. Group changes by category (observability, tests, code "
                    "modernisation, listing readiness).\n"
                    "4. Present a clear summary with: what was changed, why, and "
                    "how many files were affected in each category.\n"
                    "5. Note any issues that were flagged but not addressed."
                ),
                dependencies=[deploy_id],
            )
        )

        # Operability assessment — runs in parallel with diff review.
        tasks.append(
            AgentTask(
                id=_unique_id("assess-operational-readiness"),
                title=f"{OPERABILITY_PREFIX} Assess operational readiness",
                category=TaskCategory.RESEARCH,
                model_hint=ModelHint.PRIMARY,
                description=(
                    f"Evaluate the improved charm at {charm_path} against "
                    "Canonical's Operational Readiness Metrics.\n\n"
                    "1. Run `operational_readiness` on the charm directory.\n"
                    "2. Review OPERATIONAL_READINESS.md.\n"
                    "3. Summarise per-pillar scores and must-fix items."
                ),
                dependencies=[deploy_id],
            )
        )

    return tasks


# ---------------------------------------------------------------------------
# Operational Readiness (Phase 19)
# ---------------------------------------------------------------------------

# Prefix for operability assessment tasks — used to identify them in
# the autodeploy follow-up logic and prevent duplicate assessments.
OPERABILITY_PREFIX = "[Operability]"


def plan_operability_assessment(
    context: PlanningContext,
    depends_on: str | None = None,
) -> list[AgentTask]:
    """Generate the operability assessment → confirm → fix pipeline.

    Creates three initial tasks:
    1. RESEARCH — run ``operational_readiness`` tool on the charm.
    2. CONFIRM — present findings to the user for approval.
    3. (Conditional) BUILD tasks are generated after confirmation via
       ``plan_operability_fixes()``.

    If *depends_on* is provided, the assessment task depends on it (e.g.
    the acceptance test task ID).
    """
    charm_path = context.existing_charm_path or "."
    charm_name = context.charm_name or "the charm"

    deps = [depends_on] if depends_on else []

    assess_id = _unique_id("assess-operational-readiness")
    confirm_id = _unique_id("confirm-operability")

    return [
        AgentTask(
            id=assess_id,
            title=f"{OPERABILITY_PREFIX} Assess operational readiness of {charm_name}",
            category=TaskCategory.RESEARCH,
            model_hint=ModelHint.PRIMARY,
            description=(
                f"Evaluate the charm at {charm_path} against Canonical's "
                "Operational Readiness Metrics.\n\n"
                "1. Run `operational_readiness` tool on the charm directory.\n"
                "2. Review the OPERATIONAL_READINESS.md report.\n"
                "3. Summarise the per-pillar scores and must-fix items."
            ),
            dependencies=deps,
        ),
        AgentTask(
            id=confirm_id,
            title=f"{OPERABILITY_PREFIX} Confirm operational readiness gaps",
            category=TaskCategory.CONFIRM,
            description=(
                f"Present operational readiness findings for {charm_name}.\n\n"
                "The assessment identified gaps across Best Practices, "
                "Documentation, Reliability, Maintainability, and Security "
                "pillars. Confirm which gaps to address and which to defer."
            ),
            dependencies=[assess_id],
        ),
    ]


def plan_operability_fixes(
    context: PlanningContext,
    findings: dict[str, list[str]],
    confirm_task_id: str = "confirm-operability",
) -> list[AgentTask]:
    """Generate BUILD tasks to close confirmed operability gaps.

    Called after the user confirms which gaps to address.  Each fix area
    becomes a BUILD task depending on *confirm_task_id*.  A re-assessment
    task at the end verifies the score improved.
    """
    charm_path = context.existing_charm_path or "."
    tasks: list[AgentTask] = []
    fix_ids: list[str] = []

    must_fix = findings.get("must_fix", [])
    should_fix = findings.get("should_fix", [])
    all_gaps = must_fix + should_fix

    # Group gaps into implementation categories.
    status_gaps = [g for g in all_gaps if "status" in g.lower()]
    action_gaps = [
        g
        for g in all_gaps
        if any(k in g.lower() for k in ("action", "health", "pause", "resume", "diagnostics"))
    ]
    backup_gaps = [g for g in all_gaps if "backup" in g.lower() or "restore" in g.lower()]
    upgrade_gaps = [g for g in all_gaps if "upgrade" in g.lower()]
    cos_gaps = [g for g in all_gaps if "cos" in g.lower() or "observability" in g.lower()]
    security_gaps = [
        g for g in all_gaps if any(k in g.lower() for k in ("tls", "encrypt", "secret", "cert"))
    ]
    doc_gaps = [g for g in all_gaps if "documentation" in g.lower() or "doc" in g.lower()]

    if status_gaps:
        task_id = _unique_id("implement-status-reporting")
        tasks.append(
            AgentTask(
                id=task_id,
                title=f"{OPERABILITY_PREFIX} Implement comprehensive status reporting",
                category=TaskCategory.BUILD,
                model_hint=ModelHint.PRIMARY,
                description=(
                    f"Add comprehensive status reporting to the charm at {charm_path}.\n\n"
                    "1. Load the `operational-readiness` skill.\n"
                    "2. Implement a `_reconcile()` method that checks all conditions "
                    "and sets appropriate status (BlockedStatus, WaitingStatus, "
                    "MaintenanceStatus, ActiveStatus).\n"
                    "3. Call `_reconcile()` from every event handler.\n"
                    "4. Run tests and commit."
                ),
                dependencies=[confirm_task_id],
            )
        )
        fix_ids.append(task_id)

    if action_gaps:
        task_id = _unique_id("implement-operational-actions")
        tasks.append(
            AgentTask(
                id=task_id,
                title=f"{OPERABILITY_PREFIX} Add operational actions",
                category=TaskCategory.BUILD,
                model_hint=ModelHint.PRIMARY,
                description=(
                    f"Add operational actions to the charm at {charm_path}.\n\n"
                    "1. Load the `operational-readiness` skill.\n"
                    "2. Add `get-health` action with comprehensive checks.\n"
                    "3. Add `pause` and `resume` actions for workload control.\n"
                    "4. Add `collect-diagnostics` action for troubleshooting.\n"
                    "5. Update actions.yaml or charmcraft.yaml with descriptions "
                    "and parameter schemas.\n"
                    "6. Run tests and commit."
                ),
                dependencies=[confirm_task_id],
            )
        )
        fix_ids.append(task_id)

    if backup_gaps:
        task_id = _unique_id("implement-backup-restore")
        tasks.append(
            AgentTask(
                id=task_id,
                title=f"{OPERABILITY_PREFIX} Add backup and restore actions",
                category=TaskCategory.BUILD,
                model_hint=ModelHint.PRIMARY,
                description=(
                    f"Add backup and restore capabilities to the charm at {charm_path}.\n\n"
                    "1. Load the `operational-readiness` skill.\n"
                    "2. Add `create-backup`, `list-backups`, and `restore-backup` "
                    "actions using workload-native tools.\n"
                    "3. Run tests and commit."
                ),
                dependencies=[confirm_task_id],
            )
        )
        fix_ids.append(task_id)

    if upgrade_gaps:
        task_id = _unique_id("implement-upgrade-procedures")
        tasks.append(
            AgentTask(
                id=task_id,
                title=f"{OPERABILITY_PREFIX} Add upgrade pre-flight checks",
                category=TaskCategory.BUILD,
                model_hint=ModelHint.PRIMARY,
                description=(
                    f"Add upgrade support to the charm at {charm_path}.\n\n"
                    "1. Load the `operational-readiness` skill.\n"
                    "2. Add `pre-upgrade-check` action that validates version "
                    "compatibility, cluster health, and backup freshness.\n"
                    "3. Handle upgrade events gracefully.\n"
                    "4. Run tests and commit."
                ),
                dependencies=[confirm_task_id],
            )
        )
        fix_ids.append(task_id)

    if cos_gaps:
        task_id = _unique_id("improve-observability-completeness")
        tasks.append(
            AgentTask(
                id=task_id,
                title=f"{OPERABILITY_PREFIX} Complete COS observability",
                category=TaskCategory.BUILD,
                model_hint=ModelHint.PRIMARY,
                description=(
                    f"Fill remaining COS gaps in the charm at {charm_path}.\n\n"
                    "1. Load the `observability` and `operational-readiness` skills.\n"
                    "2. Add any missing COS relations (tracing, metrics, logging, "
                    "grafana-dashboard).\n"
                    "3. Add alert rules and dashboard panels beyond basic integration.\n"
                    "4. Run tests and commit."
                ),
                dependencies=[confirm_task_id],
            )
        )
        fix_ids.append(task_id)

    if security_gaps:
        task_id = _unique_id("improve-security-posture")
        tasks.append(
            AgentTask(
                id=task_id,
                title=f"{OPERABILITY_PREFIX} Improve security posture",
                category=TaskCategory.BUILD,
                model_hint=ModelHint.PRIMARY,
                description=(
                    f"Improve the security posture of the charm at {charm_path}.\n\n"
                    "1. Load the `operational-readiness` skill.\n"
                    "2. Migrate any plain-text secret config to Juju secrets.\n"
                    "3. Add TLS support if missing.\n"
                    "4. Add certificate management actions if relevant.\n"
                    "5. Run tests and commit."
                ),
                dependencies=[confirm_task_id],
            )
        )
        fix_ids.append(task_id)

    if doc_gaps:
        task_id = _unique_id("improve-operational-docs")
        tasks.append(
            AgentTask(
                id=task_id,
                title=f"{OPERABILITY_PREFIX} Improve operational documentation",
                category=TaskCategory.BUILD,
                model_hint=ModelHint.PRIMARY,
                description=(
                    f"Add missing operational documentation for the charm at {charm_path}.\n\n"
                    "1. Add installation/setup guide if missing.\n"
                    "2. Add configuration reference.\n"
                    "3. Add troubleshooting, upgrade, and backup/restore docs.\n"
                    "4. Commit."
                ),
                dependencies=[confirm_task_id],
            )
        )
        fix_ids.append(task_id)

    # Re-assessment after fixes.
    if fix_ids:
        tasks.append(
            AgentTask(
                id=_unique_id("reassess-operational-readiness"),
                title=f"{OPERABILITY_PREFIX} Re-assess operational readiness",
                category=TaskCategory.RESEARCH,
                model_hint=ModelHint.PRIMARY,
                description=(
                    f"Re-run operational readiness assessment on {charm_path}.\n\n"
                    "1. Run `operational_readiness` tool.\n"
                    "2. Compare before/after scores.\n"
                    "3. Present the improvement summary to the user."
                ),
                dependencies=fix_ids,
            )
        )

    return tasks


def plan_research_phase(context: PlanningContext) -> list[AgentTask]:
    """Generate the standard research → synthesis → confirm task sequence.

    These tasks are always the same structure for a "build a charm" request.
    Skips source-analysis if no source URL is provided.  Returns 4 or 5
    tasks depending on whether source analysis is needed.
    """
    workload = context.charm_name or "the workload"
    tasks: list[AgentTask] = []
    research_ids: list[str] = []

    if context.source_url:
        source_id = _unique_id("source-analysis")
        tasks.append(
            AgentTask(
                id=source_id,
                title=f"Analyse source repository for {workload}",
                category=TaskCategory.RESEARCH,
                description=(
                    f"Clone {context.source_url}, explore README, dependency files, "
                    "Dockerfiles, config files, and entry points. Run analyse_framework. "
                    "Write findings into WORKLOAD.md."
                ),
                dependencies=[],
            )
        )
        research_ids.append(source_id)

    web_id = _unique_id("web-research")
    tasks.append(
        AgentTask(
            id=web_id,
            title=f"Research {workload} documentation and operations",
            category=TaskCategory.RESEARCH,
            description=(
                f"Fetch official docs, project website, and deployment guides for {workload}. "
                "Focus on operational patterns: deployment, configuration, monitoring, scaling."
            ),
            dependencies=[],
        )
    )
    research_ids.append(web_id)

    hub_id = _unique_id("charmhub-survey")
    tasks.append(
        AgentTask(
            id=hub_id,
            title=f"Survey Charmhub for existing {workload} charms",
            category=TaskCategory.RESEARCH,
            description=(
                f"Search Charmhub for existing charms covering {workload}. "
                "Evaluate candidates: relations, config, storage, maintenance status."
            ),
            dependencies=[],
        )
    )
    research_ids.append(hub_id)

    synthesis_id = _unique_id("operational-discovery")
    tasks.append(
        AgentTask(
            id=synthesis_id,
            title=f"operational-discovery: synthesise design for {workload}",
            category=TaskCategory.RESEARCH,
            description=(
                "Synthesise all research into a structured design proposal (DESIGN.md). "
                "Cover: substrate, charm path, Charmhub recommendation, integrations, "
                "config, actions, scaling, operational patterns, security surface "
                "assessment, and open questions."
            ),
            dependencies=list(research_ids),
        )
    )

    tasks.append(
        AgentTask(
            id=_unique_id("confirm-design"),
            title="Confirm design with user",
            category=TaskCategory.CONFIRM,
            description="Present the design proposal for user approval.",
            dependencies=[synthesis_id],
        )
    )

    return tasks


# ---------------------------------------------------------------------------
# Day-2 operations research phase
# ---------------------------------------------------------------------------

# Title prefix for day-2 tasks — used by the subagent prompt builder
# to overlay day-2 guidance.
DAY2_RESEARCH_PREFIX = "Day 2:"


def plan_day2_ops_phase(
    context: PlanningContext,
    depends_on: str,
) -> list[AgentTask]:
    """Generate the day-2 operations research phase.

    Produces research tasks that investigate backup/restore, scaling,
    HA, upgrades, monitoring, security hardening, and disaster recovery
    for the workload.  The phase depends on *depends_on* (typically the
    last deploy or test task from the build phase).

    After the user confirms the day-2 plan, ``handle_day2_confirmation``
    generates implementation tasks from the findings.
    """
    workload = context.charm_name or "the workload"

    research_id = _unique_id("day2-research")
    synthesis_id = _unique_id("day2-synthesis")
    confirm_id = _unique_id("confirm-day2")

    return [
        AgentTask(
            id=research_id,
            title=f"{DAY2_RESEARCH_PREFIX} research operations for {workload}",
            category=TaskCategory.RESEARCH,
            model_hint=ModelHint.PRIMARY,
            description=(
                f"Research day-2 operational concerns for {workload}.\n\n"
                "Use web_search and web_fetch to find documentation on:\n"
                "- Backup and restore procedures\n"
                "- Horizontal and vertical scaling\n"
                "- High availability and clustering\n"
                "- Upgrade and migration paths\n"
                "- Security hardening and credential rotation\n"
                "- Monitoring, alerting, and observability best practices\n"
                "- Disaster recovery runbooks\n\n"
                "Also check Charmhub for how existing charms handle these "
                "operations (actions, config, relations).\n\n"
                "Write findings into DAY2.md with clear headings per topic."
            ),
            dependencies=[depends_on],
        ),
        AgentTask(
            id=synthesis_id,
            title=f"{DAY2_RESEARCH_PREFIX} synthesise day-2 plan for {workload}",
            category=TaskCategory.RESEARCH,
            model_hint=ModelHint.PRIMARY,
            description=(
                "Synthesise day-2 research into a structured plan proposing "
                "specific charm features for each operational area.\n\n"
                "For each area, propose concrete charm features:\n"
                "- Actions (backup, restore, rotate-credentials, promote-standby)\n"
                "- Config options (backup-schedule, ha-mode, tls-enabled)\n"
                "- Relations (s3-credentials for backup, peer for HA)\n"
                "- Operational patterns (leader election, rolling upgrades)\n\n"
                "Write output as DAY2-PLAN.md with structured questions using the "
                "standard format (bold key, indented suggestions). Questions should "
                "focus on areas where the user's operational expertise is most "
                "valuable — deployment topology, backup policies, security needs."
            ),
            dependencies=[research_id],
        ),
        AgentTask(
            id=confirm_id,
            title="Discuss day-2 operations with user",
            category=TaskCategory.CONFIRM,
            description=(
                "Present the day-2 operations plan for user discussion. "
                "The user may approve areas, skip areas, provide additional "
                "operational context, or indicate they are unsure (in which "
                "case the research findings serve as the default)."
            ),
            dependencies=[synthesis_id],
        ),
    ]


def find_day2_anchor(tasks: list[AgentTask]) -> str | None:
    """Find the task ID to use as the dependency anchor for day-2 tasks.

    Scans *tasks* in reverse for the last DEPLOY or TEST category task.
    Falls back to the last task overall if no deploy/test task is found.
    Returns ``None`` only when *tasks* is empty.
    """
    # Prefer the last deploy or test task.
    for task in reversed(tasks):
        if task.category in (TaskCategory.DEPLOY, TaskCategory.TEST):
            return task.id
    # Fallback to the very last task.
    return tasks[-1].id if tasks else None


class TaskPlanner:
    """Stateless planner that decomposes intent into ordered agent tasks.

    For fresh "build a charm" requests, uses deterministic templates for
    the research phase (no LLM call).  Falls back to the LLM for
    replanning and for generating build-phase tasks from an approved design.
    """

    def __init__(self, provider: llm.LLMProvider) -> None:
        self._provider = provider

    async def plan(self, context: PlanningContext) -> list[AgentTask]:
        """Decompose *context.intent* into an ordered list of tasks.

        Uses deterministic templates — no LLM call.  For well-known
        12-factor frameworks or explicit charm types, the sprint path
        goes straight to build + deploy.  For improvement requests,
        generates the audit → confirm flow.
        """
        if is_improvement(context):
            return plan_improvement_phase(context)
        if is_sprint(context):
            return plan_sprint_deploy(context)
        if is_fast_path(context):
            return plan_fast_path(context)
        return plan_research_phase(context)

    async def plan_from_design(
        self,
        design_content: str,
        context: PlanningContext,
        overrides: str | None = None,
    ) -> list[AgentTask]:
        """Generate build/deploy/test tasks from an approved design.

        Called after the user confirms the design proposal.  Uses a
        dedicated prompt that focuses on the implementation phase.
        """
        prompt = _build_design_to_build_prompt(context)
        user_msg = f"## Approved design\n\n{design_content}"
        if overrides:
            user_msg += f"\n\n## User overrides\n\n{overrides}"
        messages = [
            llm.Message(role=llm.Role.SYSTEM, content=prompt),
            llm.Message(role=llm.Role.USER, content=user_msg),
        ]
        response = await self._provider.complete(
            messages=messages,
            tools=None,
            temperature=_PLANNING_TEMPERATURE,
        )
        return _parse_task_list(response.content)

    async def replan(self, context: PlanningContext) -> list[AgentTask]:
        """Adapt existing tasks given new context or changed scope.

        Completed and active tasks are preserved; pending tasks are
        replaced by the new plan.
        """
        prompt = _build_replanning_prompt(context)
        messages = [
            llm.Message(role=llm.Role.SYSTEM, content=prompt),
            llm.Message(
                role=llm.Role.USER,
                content=context.new_context or context.intent,
            ),
        ]
        response = await self._provider.complete(
            messages=messages,
            tools=None,
            temperature=_PLANNING_TEMPERATURE,
        )
        new_tasks = _parse_task_list(response.content)
        return _merge_tasks(context.existing_tasks, new_tasks)

    async def plan_from_day2_findings(
        self,
        findings: str,
        context: PlanningContext,
        overrides: str | None = None,
    ) -> list[AgentTask]:
        """Generate implementation tasks from confirmed day-2 findings.

        Called after the user discusses and approves the day-2 operations
        plan.  Uses a dedicated prompt focused on adding operational
        features to an existing charm.
        """
        prompt = _build_day2_to_build_prompt(context)
        user_msg = f"## Approved day-2 operations plan\n\n{findings}"
        if overrides:
            user_msg += f"\n\n## User overrides\n\n{overrides}"
        messages = [
            llm.Message(role=llm.Role.SYSTEM, content=prompt),
            llm.Message(role=llm.Role.USER, content=user_msg),
        ]
        response = await self._provider.complete(
            messages=messages,
            tools=None,
            temperature=_PLANNING_TEMPERATURE,
        )
        return _parse_task_list(response.content)


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

_PLANNING_PROMPT = """\
You are a task planner for Cantrip, an AI agent that builds Juju charms autonomously.

Given the user's intent, decompose it into a concrete, ordered list of tasks. Return
**only** a JSON array — no surrounding text or explanation.

Each task object must have:
- "id": short unique slug (e.g. "source-analysis", "scaffold-charm")
- "title": concise imperative title (e.g. "Analyse the source repository")
- "category": one of {categories}
- "description": one or two sentences explaining what the task does
- "dependencies": list of task IDs that must complete before this one starts (may be empty)

### Category guide

- **research** — fetch documentation, explore source code, query Charmhub/registries
- **build** — scaffold, write charm code, write rockcraft.yaml, write tests
- **deploy** — pack, push images, deploy with Juju, refresh
- **test** — run unit tests, integration tests, validate the charm
- **debug** — investigate failures, query logs/traces, fix issues
- **infra** — set up the development environment, bootstrap controllers
- **confirm** — present a decision to the user and wait for approval

### Research-first decomposition

For a typical charm build, always follow a **research → synthesis → confirm → build** \
pattern. Do NOT generate build tasks upfront — they are created after the user approves \
the design.

**Phase 1 — Research** (multiple parallel tasks, category: research):

- **source-analysis**: Clone the source repository, explore README, dependency files, \
Dockerfiles, configuration files, and entry points. Run `analyse_framework` to detect \
language and framework. Write findings into WORKLOAD.md.

- **web-research**: Fetch external documentation, project website, PyPI/npm pages, and \
deployment guides. Gather operational patterns: how the workload is typically deployed, \
configured, monitored, and scaled.

- **charmhub-survey**: Search Charmhub for existing charms that cover this workload. \
Use `charmhub_search` and `charmhub_info` to evaluate candidates — check relations, \
config, storage, containers, and maintenance status.

These three tasks have no dependencies on each other and can run in parallel.

**Phase 2 — Synthesis** (two tasks):

- **operational-discovery** (category: research, depends on all Phase 1 tasks): \
Synthesise the research findings into a structured design proposal. Cover: substrate \
choice (K8s vs machine) with reasoning, charm path (12-factor / custom / infrastructure), \
Charmhub recommendation (use existing / fork / build new), integrations, config options, \
actions, scaling strategy, operational patterns, and open questions for the user. \
Format the output as a DESIGN.md.

- **confirm-design** (category: confirm, depends on operational-discovery): \
Present the design proposal to the user for approval.

**Phase 3 — Build** is NOT generated at this stage. Build, deploy, and test tasks are \
created dynamically after the user confirms the design.

Adapt the pattern to the specific request — skip research tasks that do not apply (e.g. \
skip source-analysis if no source URL is given, skip charmhub-survey for a clearly novel \
workload). Always include operational-discovery and confirm-design.

### Context
{context_block}

Return a JSON array of task objects. Example:
```json
[
  {{"id": "source-analysis", "title": "Analyse the source repository", "category": \
"research", "description": "Clone the repo and explore the codebase structure, \
dependencies, and framework.", "dependencies": []}},
  {{"id": "web-research", "title": "Research workload documentation", "category": \
"research", "description": "Fetch external docs, deployment guides, and operational \
patterns.", "dependencies": []}},
  {{"id": "charmhub-survey", "title": "Survey Charmhub for existing charms", "category": \
"research", "description": "Search Charmhub and evaluate existing charms for this \
workload.", "dependencies": []}},
  {{"id": "operational-discovery", "title": "Synthesise design proposal", "category": \
"research", "description": "Combine all research into a structured design proposal \
(DESIGN.md).", "dependencies": ["source-analysis", "web-research", "charmhub-survey"]}},
  {{"id": "confirm-design", "title": "Confirm design with user", "category": "confirm", \
"description": "Present the design proposal for user approval.", "dependencies": \
["operational-discovery"]}}
]
```
"""

_DESIGN_TO_BUILD_PROMPT = """\
You are a task planner for Cantrip, an AI agent that builds Juju charms autonomously.

The user has approved a design proposal. Generate the **build, deploy, and test** tasks \
needed to implement it. Return **only** a JSON array — no surrounding text.

Each task object must have:
- "id": short unique slug (e.g. "scaffold-charm", "write-integration-tests")
- "title": concise imperative title
- "category": one of {categories}
- "description": one or two sentences explaining what the task does
- "dependencies": list of task IDs that must complete before this one starts

### Typical build sequence (red/green)

Follow an **integration-tests-first** approach. Write integration tests from the \
design *before* the charm code, then iterate until they pass.

1. Scaffold the charm (charmcraft init, write metadata)
2. Write integration tests from the design — deploy, relate, actions, config \
(these will fail initially — that is expected; this is the "red" phase)
3. Write charm code to make the tests pass (src/charm.py, Pebble layers, \
integrations) — this is the "green" phase
4. Pack and deploy
5. Run integration tests and iterate until green
6. Write unit tests (Scenario-based) for edge cases and error paths
7. Run full validation (unit + integration) and commit

The integration tests encode the **external contract** from the approved design: \
each relation endpoint, action, config option, and COS integration becomes a test. \
The charm code is written to satisfy these tests, not the other way around.

Adapt for the design — add rock-building steps for 12-factor charms, add integration \
wiring for complex workloads, skip steps that do not apply. Honour any user overrides.

### Companion charms

If the design includes a `## Companion charms` section, generate a DEPLOY task for each \
companion charm **before** the primary deploy + relate step. Each companion task should \
deploy the charm from Charmhub and then relate it to the primary charm using the endpoint \
and interface specified in the design.

After all tests pass, include an **"Acceptance test: put the charm through its paces"** \
task (category: test) that exercises the live deployment: running every action, testing \
relations with partner charms, probing workload endpoints, varying config options, and \
testing scaling. This task depends on the final test/validation task.

After acceptance testing, include a **"Generate demo artefacts"** task (category: build) \
that creates DEMO.md, demo.sh, TUTORIAL.md, and a demo/ directory with captured output \
from the live deployment. This task depends on the acceptance test task.

### Context
{context_block}
"""


def _build_planning_prompt(context: PlanningContext) -> str:
    """Build the system prompt for a fresh planning call."""
    return _PLANNING_PROMPT.format(
        categories=", ".join(sorted(_VALID_CATEGORIES)),
        context_block=_format_context_block(context),
    )


def _build_design_to_build_prompt(context: PlanningContext) -> str:
    """Build the system prompt for generating build tasks from a design."""
    return _DESIGN_TO_BUILD_PROMPT.format(
        categories=", ".join(sorted(_VALID_CATEGORIES)),
        context_block=_format_context_block(context),
    )


def _build_replanning_prompt(context: PlanningContext) -> str:
    """Build the system prompt for a replanning call.

    Includes the existing task list so the LLM can see what has already
    been completed and what is still pending.
    """
    existing_json = json.dumps(
        [
            {
                "id": t.id,
                "title": t.title,
                "category": t.category.value,
                "status": t.status.value,
                "description": t.description,
            }
            for t in context.existing_tasks
        ],
        indent=2,
    )
    extra = (
        "\n\n### Existing tasks\n\n"
        "The following tasks already exist. Tasks with status 'done' or 'active' must "
        "NOT be replaced — only produce new tasks for work that is still pending. "
        "You may drop, reorder, or add pending tasks as needed.\n\n"
        f"```json\n{existing_json}\n```"
    )
    base = _build_planning_prompt(context)
    return base + extra


_DAY2_TO_BUILD_PROMPT = """\
You are a task planner for Cantrip, an AI agent that builds Juju charms autonomously.

The user has approved a day-2 operations plan for an existing, deployed charm. Generate \
the **build and test** tasks needed to implement the approved operational features. \
Return **only** a JSON array — no surrounding text.

Each task object must have:
- "id": short unique slug (e.g. "add-backup-action", "add-ha-config")
- "title": concise imperative title
- "category": one of {categories}
- "description": detailed implementation instructions
- "dependencies": list of task IDs that must complete before this one starts

### Day-2 implementation patterns

For each approved operational area, generate a BUILD task that modifies the existing \
charm. Use `edit_file` to modify `src/charm.py`, `charmcraft.yaml`, and test files — \
do NOT rewrite from scratch.

Common patterns:
- **Backup/restore**: Add `backup` and `restore` Juju actions; add an `s3-credentials` \
relation (via the s3-integrator interface) if off-site storage is needed; add \
`backup-schedule` config option for automated backups.
- **Scaling**: Add or enhance the `peer` relation for data sharing; add config options \
for replication mode; handle `relation-joined`/`relation-departed` for cluster membership.
- **HA**: Add leader-election handling in `_on_leader_elected`; add `promote-standby` \
action for manual failover; ensure peer relation shares cluster state.
- **Upgrades**: Handle `upgrade-charm` event; add rolling-restart logic if the workload \
supports it; add a `pre-upgrade-check` action that validates readiness.
- **Security**: Add `rotate-credentials` action; use Juju secrets for sensitive config; \
add TLS config options and certificate relation if applicable.
- **Monitoring**: Add custom Prometheus metrics via the `metrics-endpoint` relation; \
create Grafana dashboard JSON in `src/grafana_dashboards/`; add alert rules in \
`src/prometheus_alert_rules/`.
- **Disaster recovery**: Add `export-state` and `import-state` actions; document RTO/RPO \
in README.

Each task should commit its changes with `git_add` and `git_commit`. Include a final \
validation task (category: test) that runs `charm_validate` and `run_charm_tests` to \
verify nothing is broken.

### Context
{context_block}
"""


def _build_day2_to_build_prompt(context: PlanningContext) -> str:
    """Build the system prompt for generating tasks from day-2 findings."""
    return _DAY2_TO_BUILD_PROMPT.format(
        categories=", ".join(sorted(_VALID_CATEGORIES)),
        context_block=_format_context_block(context),
    )


def _format_context_block(context: PlanningContext) -> str:
    """Format the context variables section of the planning prompt."""
    lines: list[str] = []
    if context.charm_name:
        lines.append(f"- Charm name: {context.charm_name}")
    if context.charm_type:
        lines.append(f"- Charm type: {context.charm_type}")
    if context.framework:
        lines.append(f"- Framework: {context.framework}")
    if context.dev_model:
        lines.append(f"- Dev model: {context.dev_model}")
    if context.cos_model:
        lines.append(f"- COS model: {context.cos_model}")
    if context.source_url:
        lines.append(f"- Source URL: {context.source_url}")
    if context.environment_ready:
        lines.append("- Environment: ready")
    else:
        lines.append("- Environment: not yet provisioned")
    return "\n".join(lines) if lines else "No additional context."


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def _extract_json(content: str) -> str:
    """Strip markdown code fences from LLM output."""
    # Match ```json ... ``` or ``` ... ``` blocks.
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return content.strip()


def _parse_task_list(content: str) -> list[AgentTask]:
    """Parse the LLM response into a list of ``AgentTask`` objects.

    Handles:
    - Raw JSON arrays
    - JSON wrapped in markdown code fences
    - ``{"tasks": [...]}`` wrapper objects
    """
    raw = _extract_json(content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse task list JSON: {exc}") from exc

    # Unwrap {"tasks": [...]} if present.
    if isinstance(data, dict):
        if "tasks" in data and isinstance(data["tasks"], list):
            data = data["tasks"]
        else:
            raise ValueError('Expected a JSON array of tasks or {"tasks": [...]}')

    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of tasks")

    return [_parse_single_task(item, idx) for idx, item in enumerate(data)]


def _parse_single_task(item: dict, index: int) -> AgentTask:
    """Validate and construct a single ``AgentTask`` from parsed JSON."""
    if not isinstance(item, dict):
        raise ValueError(f"Task at index {index} is not an object")

    title = item.get("title")
    if not title:
        raise ValueError(f"Task at index {index} is missing a title")

    raw_category = str(item.get("category", "build")).lower()
    if raw_category not in _VALID_CATEGORIES:
        log.warning("Unknown category %r in task %r — defaulting to 'build'", raw_category, title)
        raw_category = "build"

    dependencies = item.get("dependencies", [])
    if not isinstance(dependencies, list):
        dependencies = []

    return AgentTask(
        id=str(item.get("id", "")),
        title=title,
        category=TaskCategory(raw_category),
        description=str(item.get("description", "")),
        dependencies=[str(d) for d in dependencies],
    )


# ---------------------------------------------------------------------------
# Task merging (for replanning)
# ---------------------------------------------------------------------------


def _merge_tasks(
    existing: list[AgentTask],
    new: list[AgentTask],
) -> list[AgentTask]:
    """Merge new planned tasks with existing ones.

    - Completed and active tasks are preserved (appear first).
    - Pending tasks from the existing list are dropped.
    - New tasks are appended after preserved tasks.
    - If a new task ID collides with a completed/active task, the
      completed/active task wins and the duplicate is discarded.
    """
    preserved: list[AgentTask] = []
    preserved_ids: set[str] = set()

    for task in existing:
        if task.status in (TaskStatus.DONE, TaskStatus.ACTIVE):
            preserved.append(task)
            preserved_ids.add(task.id)

    merged = list(preserved)
    for task in new:
        if task.id not in preserved_ids:
            merged.append(task)

    return merged
