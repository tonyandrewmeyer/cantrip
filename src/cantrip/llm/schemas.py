"""Built-in JSON schemas for structured LLM responses (Phase 73.3).

Each schema is a plain ``dict`` matching JSON Schema draft 2020-12 —
the same surface every supported provider already accepts.  Pass them
to :func:`cantrip.llm.structured.complete_structured` (or directly to
``provider.complete(response_schema=…)``) when you want a parseable
return shape rather than free text.

Schemas are deliberately *narrow*: they describe what Cantrip will
parse back out, not every field a model might want to volunteer.
Each ``required`` set lists only the fields we actually consume.
"""

from __future__ import annotations

from typing import Any

# The planner returns a list of work-queue tasks.  Mirrors
# :class:`cantrip.agent.queue.AgentTask` — the fields the planner
# is allowed to populate are ``title``, ``category``,
# ``description``, and ``dependencies``; ``id`` is generated post-
# hoc, the rest are runtime state.  Categories track the
# :class:`cantrip.agent.queue.TaskCategory` enum.
PLANNER_BRIEFING: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "PlannerBriefing",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string", "minLength": 1},
                    "category": {
                        "type": "string",
                        "enum": [
                            "research",
                            "build",
                            "deploy",
                            "test",
                            "debug",
                            "infra",
                            "confirm",
                        ],
                    },
                    "description": {"type": "string"},
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["title", "category"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["tasks"],
    "additionalProperties": False,
}


# Shape of a Phase 70.2 oracle reply when the caller wants more than
# free-form prose — the answer plus optional confidence and caveats
# the agent can surface to the user.
ORACLE_ANSWER: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "OracleAnswer",
    "properties": {
        "answer": {"type": "string", "minLength": 1},
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
        "caveats": {
            "type": "array",
            "items": {"type": "string"},
        },
        "references": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["answer"],
    "additionalProperties": False,
}


# Output of a Phase 70.4 prompt-based "Check" — the LLM evaluates a
# named rule against the active charm and returns a structured
# pass/fail.  ``severity`` defaults to the rule's declared severity
# when omitted by the model; ``evidence`` should quote the smallest
# surface that justifies the verdict.
CHECK_RESULT: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "CheckResult",
    "properties": {
        "status": {"type": "string", "enum": ["pass", "fail"]},
        "severity": {
            "type": "string",
            "enum": ["error", "warning", "info"],
        },
        "message": {"type": "string"},
        "evidence": {"type": "string"},
        "suggested_fix": {"type": "string"},
    },
    "required": ["status", "message"],
    "additionalProperties": False,
}


# Phase 17 acceptance-test report — what the agent produces after
# exercising a deployed charm.  ``coverage`` records which areas
# were exercised; ``findings`` is a list of issues to surface to
# the user; ``overall_status`` is the gate the work loop reads.
ACCEPTANCE_REPORT: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "AcceptanceReport",
    "properties": {
        "app": {"type": "string", "minLength": 1},
        "model": {"type": "string"},
        "summary": {"type": "string"},
        "overall_status": {
            "type": "string",
            "enum": ["pass", "fail", "partial"],
        },
        "coverage": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "actions",
                    "relations",
                    "endpoints",
                    "config",
                    "lifecycle",
                ],
            },
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["error", "warning", "info"],
                    },
                    "area": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["severity", "description"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["app", "overall_status"],
    "additionalProperties": False,
}


# Lookup table — callers that resolve schemas by name (recipes,
# CLI hooks, future settings) read from here so the set of built-
# ins is discoverable in one place.
BUILTIN_SCHEMAS: dict[str, dict[str, Any]] = {
    "planner_briefing": PLANNER_BRIEFING,
    "oracle_answer": ORACLE_ANSWER,
    "check_result": CHECK_RESULT,
    "acceptance_report": ACCEPTANCE_REPORT,
}


__all__ = [
    "ACCEPTANCE_REPORT",
    "BUILTIN_SCHEMAS",
    "CHECK_RESULT",
    "ORACLE_ANSWER",
    "PLANNER_BRIEFING",
]
