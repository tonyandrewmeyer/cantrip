"""Workflow engines layered over the agent.

These modules implement the repeatable, multi-step execution surfaces the
agent and its slash commands drive:

* :mod:`checks` — prompt-based review checks run against a charm.
* :mod:`flows` — Mermaid decision-tree walkthroughs.
* :mod:`recipes` — parameterised, retryable recipe execution.
* :mod:`ralph` — the bounded iterate-until-green refinement loop.

The user-facing ``/review``, ``/flow``, ``/recipe`` and ``/ralph`` command
glue lives in :mod:`cantrip.agent.commands`; these are the engines behind it.
"""
