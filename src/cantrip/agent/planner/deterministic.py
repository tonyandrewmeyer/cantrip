"""Deterministic task generators — no LLM call required.

For the common "build a charm for X" flow, path classifiers
(``is_fast_path``, ``is_sprint``, ``is_one_shot_build``,
``is_improvement``) decide which deterministic template applies, and a
matching ``plan_*`` function returns the task list.  All guidance text
lives in ``.md.j2`` templates under ``cantrip.agent.prompts.tasks`` —
this module contains only the control flow that threads runtime context
(workload, charm_path, gap sets) into those templates.
"""

from __future__ import annotations

import platform
from uuid import uuid4

from cantrip.agent.planner.context import PlanningContext
from cantrip.agent.prompts import tasks as task_prompts
from cantrip.agent.queue import AgentTask, ModelHint, TaskCategory

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


# Base task IDs for CONFIRM tasks.  ``_unique_id`` appends a random
# suffix in normal planning flows, but the bare value is also used as a
# stable fallback (e.g. default ``confirm_task_id`` arguments and tests).
# ``task_id.startswith(BASE)`` matches both forms.
DESIGN_CONFIRM_BASE = "confirm-design"
DAY2_CONFIRM_BASE = "confirm-day2"
IMPROVEMENT_CONFIRM_BASE = "confirm-improvements"
OPERABILITY_CONFIRM_BASE = "confirm-operability"


# Title prefixes used to identify sprint tasks in follow-up logic.
SPRINT_BUILD_PREFIX = "Sprint build:"
SPRINT_DEPLOY_PREFIX = "Sprint deploy:"


# Prefix for operability assessment tasks — used to identify them in
# the autodeploy follow-up logic and prevent duplicate assessments.
OPERABILITY_PREFIX = "[Operability]"


# Title prefix for day-2 tasks — used by the subagent prompt builder
# to overlay day-2 guidance.
DAY2_RESEARCH_PREFIX = "Day 2:"


def _unique_id(base: str) -> str:
    """Return *base* with a random suffix to avoid collisions across plans."""
    return f"{base}-{uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Path classifiers
# ---------------------------------------------------------------------------


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


def is_one_shot_build(context: PlanningContext) -> bool:
    """Return whether the build phase can be collapsed into a single task.

    One-shot build applies when the framework is a known 12-factor type —
    the scaffold + write + pack sequence is predictable enough for one
    subagent invocation.
    """
    return context.framework is not None and context.framework.lower() in _FAST_PATH_FRAMEWORKS


def is_improvement(context: PlanningContext) -> bool:
    """Return whether the context describes an improvement request.

    An improvement request targets an existing charm directory rather than
    building a new charm from scratch.
    """
    return context.existing_charm_path is not None


# ---------------------------------------------------------------------------
# Sprint path helpers
# ---------------------------------------------------------------------------


def _host_ubuntu_version() -> str:
    """Return the host Ubuntu version (e.g. '24.04') for destructive-mode packing."""
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("VERSION_ID="):
                    return line.split("=")[1].strip().strip('"')
    except OSError:
        pass
    try:
        version = platform.freedesktop_os_release().get("VERSION_ID")
    except OSError:
        return "24.04"
    return version or "24.04"


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


# ---------------------------------------------------------------------------
# Plan generators
# ---------------------------------------------------------------------------


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
            description=task_prompts.render(
                "sprint_build",
                workload=workload,
                profile=profile,
                ubuntu_version=ubuntu_version,
                design=design,
            ),
            dependencies=[],
        ),
        AgentTask(
            id=deploy_id,
            title=f"{SPRINT_DEPLOY_PREFIX} {workload}",
            category=TaskCategory.DEPLOY,
            description=task_prompts.render("sprint_deploy"),
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
    confirm_id = _unique_id(DESIGN_CONFIRM_BASE)

    return [
        AgentTask(
            id=design_id,
            title=f"operational-discovery: design 12-factor charm for {workload}",
            category=TaskCategory.RESEARCH,
            description=task_prompts.render("fast_path_design", framework=framework),
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
            description=task_prompts.render(
                "one_shot_build",
                framework=framework,
                workload=workload,
                design_content=design_content,
            ),
            dependencies=[],
        ),
    ]


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
    confirm_id = _unique_id(IMPROVEMENT_CONFIRM_BASE)

    return [
        AgentTask(
            id=audit_id,
            title=f"Audit existing charm: {charm_name}",
            category=TaskCategory.RESEARCH,
            model_hint=ModelHint.PRIMARY,
            description=task_prompts.render("improvement_audit", charm_path=charm_path),
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
    confirm_task_id: str = IMPROVEMENT_CONFIRM_BASE,
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
                description=task_prompts.render(
                    "improvement_fill_observability",
                    charm_path=charm_path,
                    cos_gaps=", ".join(cos_gaps),
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
                description=task_prompts.render(
                    "improvement_fill_tests",
                    charm_path=charm_path,
                    test_gaps=", ".join(test_gaps),
                ),
                dependencies=[confirm_task_id],
            )
        )
        fix_ids.append(test_id)

    # Code modernisation (deprecated APIs, type annotations, modern patterns).
    needs_modernise = (
        gaps.get("deprecated_apis")
        or gaps.get("type_annotations")
        or gaps.get("modern_patterns")
        or gaps.get("reactive_framework")
    )
    if needs_modernise:
        steps = []
        if gaps.get("reactive_framework") or gaps.get("deprecated_apis"):
            steps.append(
                "- Load the `charm-migration` skill first — it covers the "
                "reactive-framework rewrite, StoredState replacement, Harness "
                "→ Scenario test migration, and fetch-libs → PyPI swap as a "
                "single workflow with per-pattern recipes."
            )
        if gaps.get("reactive_framework"):
            steps.append(
                "- Rewrite the reactive layer as an `ops.CharmBase` subclass: "
                "replace `@when`/`@when_not`/`@hook` decorators with "
                "`framework.observe(...)` handlers; drop `charms.reactive` "
                "imports; convert flag state to Juju relation data, config, "
                "or peer relation data as appropriate."
            )
        if gaps.get("deprecated_apis"):
            steps.append(
                "- Replace StoredState with instance attributes, peer relation "
                "data, or Juju secrets (see the charm-migration skill for the "
                "decision tree).\n"
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
                description=task_prompts.render(
                    "improvement_modernise_code",
                    charm_path=charm_path,
                    step_text=step_text,
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
                description=task_prompts.render(
                    "improvement_listing_readiness", charm_path=charm_path
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
                description=task_prompts.render("improvement_validate", charm_path=charm_path),
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
                description=task_prompts.render(
                    "improvement_deploy_verify", charm_path=charm_path
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
                description=task_prompts.render("improvement_diff_review", charm_path=charm_path),
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
                description=task_prompts.render(
                    "improvement_assess_readiness", charm_path=charm_path
                ),
                dependencies=[deploy_id],
            )
        )

    return tasks


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
    confirm_id = _unique_id(OPERABILITY_CONFIRM_BASE)

    return [
        AgentTask(
            id=assess_id,
            title=f"{OPERABILITY_PREFIX} Assess operational readiness of {charm_name}",
            category=TaskCategory.RESEARCH,
            model_hint=ModelHint.PRIMARY,
            description=task_prompts.render("operability_assess", charm_path=charm_path),
            dependencies=deps,
        ),
        AgentTask(
            id=confirm_id,
            title=f"{OPERABILITY_PREFIX} Confirm operational readiness gaps",
            category=TaskCategory.CONFIRM,
            description=task_prompts.render("operability_confirm", charm_name=charm_name),
            dependencies=[assess_id],
        ),
    ]


def plan_operability_fixes(
    context: PlanningContext,
    findings: dict[str, list[str]],
    confirm_task_id: str = OPERABILITY_CONFIRM_BASE,
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
                description=task_prompts.render("operability_status", charm_path=charm_path),
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
                description=task_prompts.render("operability_actions", charm_path=charm_path),
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
                description=task_prompts.render("operability_backup", charm_path=charm_path),
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
                description=task_prompts.render("operability_upgrade", charm_path=charm_path),
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
                description=task_prompts.render("operability_cos", charm_path=charm_path),
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
                description=task_prompts.render("operability_security", charm_path=charm_path),
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
                description=task_prompts.render("operability_docs", charm_path=charm_path),
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
                description=task_prompts.render("operability_reassess", charm_path=charm_path),
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
                description=task_prompts.render("research_source", source_url=context.source_url),
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
            description=task_prompts.render("research_web", workload=workload),
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
            description=task_prompts.render("research_charmhub", workload=workload),
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
            description=task_prompts.render("research_synthesis"),
            dependencies=list(research_ids),
        )
    )

    tasks.append(
        AgentTask(
            id=_unique_id(DESIGN_CONFIRM_BASE),
            title="Confirm design with user",
            category=TaskCategory.CONFIRM,
            description="Present the design proposal for user approval.",
            dependencies=[synthesis_id],
        )
    )

    return tasks


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
    confirm_id = _unique_id(DAY2_CONFIRM_BASE)

    return [
        AgentTask(
            id=research_id,
            title=f"{DAY2_RESEARCH_PREFIX} research operations for {workload}",
            category=TaskCategory.RESEARCH,
            model_hint=ModelHint.PRIMARY,
            description=task_prompts.render("day2_research", workload=workload),
            dependencies=[depends_on],
        ),
        AgentTask(
            id=synthesis_id,
            title=f"{DAY2_RESEARCH_PREFIX} synthesise day-2 plan for {workload}",
            category=TaskCategory.RESEARCH,
            model_hint=ModelHint.PRIMARY,
            description=task_prompts.render("day2_synthesis"),
            dependencies=[research_id],
        ),
        AgentTask(
            id=confirm_id,
            title="Discuss day-2 operations with user",
            category=TaskCategory.CONFIRM,
            description=task_prompts.render("day2_confirm"),
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
