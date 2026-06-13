"""Composition helpers for :class:`cantrip.agent.core.CantripAgent`.

These modules were carved out of the ``core.py`` god-class (Phase 113.1):
each holds a focused slice of the agent's behaviour behind an
``self._agent`` back-reference, leaving ``core.py`` to wire them together.
``CantripAgent`` keeps thin delegating wrappers so the public API and the
test surface are unchanged.
"""
