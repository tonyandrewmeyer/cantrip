"""Regression test pinning the ``ops-tracing>=4`` API the system prompt teaches.

Phase 101: the system prompt and ``_inject_ops_tracing`` injection helper used to
emit ``ops_tracing.setup(self)`` — a shorthand that hasn't existed in
``ops-tracing`` for several releases.  Charms that hit production carried a
load-time ``AttributeError`` on the first hook.  This test imports the live
PyPI ``ops-tracing`` and instantiates ``Tracing`` exactly the way the recipe
teaches; if the recipe drifts back to ``setup``, or the upstream API changes
shape again, the test fails before a bad recipe reaches a charm.

The test skips gracefully when ``ops-tracing`` isn't installed (e.g. stripped
CI images).  ``ops-tracing`` is *not* a hard project dependency for the same
reason ``ops-scenario`` isn't — Cantrip generates charms that depend on it,
but the tooling itself does not.
"""

import pathlib
import sys
import textwrap

import pytest

from cantrip.agent.tools.charm import _inject_ops_tracing_into_charm_py

ops = pytest.importorskip("ops")
ops_tracing = pytest.importorskip("ops_tracing")
testing = pytest.importorskip("ops.testing")

# ``ops.testing.Context`` only exists once ``ops-scenario`` is installed.  When
# it isn't, treat the Scenario portion of the test as missing infrastructure
# rather than a recipe failure.
if not hasattr(testing, "Context"):
    pytest.skip("ops-scenario not installed", allow_module_level=True)


class TestOpsTracingRecipe:
    """Pin the live ``ops_tracing.Tracing(charm, "<rel>")`` constructor recipe.

    The system prompt and ``_inject_ops_tracing`` helper both teach this
    exact shape; either drifting away from it would cause every cantrip-built
    charm to fail at module import.
    """

    def test_modern_constructor_exists(self):
        """``ops_tracing.Tracing`` is the public constructor we teach."""
        assert hasattr(ops_tracing, "Tracing"), (
            "ops-tracing has dropped Tracing — the system prompt and "
            "_inject_ops_tracing helper need to point at the new API."
        )

    def test_legacy_setup_shorthand_is_gone(self):
        """Guard against the resurrected ``ops_tracing.setup`` shorthand.

        Earlier versions of cantrip taught ``ops_tracing.setup(self)`` from
        the system prompt and via the injection helper.  ``setup`` was
        removed upstream several releases back; if it ever returns, we want
        a deliberate decision before re-adopting it because the constructor
        shape carries the relation name explicitly.
        """
        assert not hasattr(ops_tracing, "setup"), (
            "ops_tracing.setup has reappeared — pick a recipe explicitly, "
            "don't silently fall back to the legacy shorthand."
        )

    def test_constructor_accepts_charm_and_relation_name(self, tmp_path: pathlib.Path):
        """Build a minimal charm and instantiate ``Tracing`` end-to-end.

        Mirrors the snippet in ``src/cantrip/agent/prompts/system.md.j2``.
        Runs a ``start`` event so the framework reaches the charm
        constructor exactly the way Juju would on a real unit, catching any
        contract drift that escapes attribute-level checks.
        """

        class TinyCharm(ops.CharmBase):
            def __init__(self, framework):
                super().__init__(framework)
                self._tracing = ops_tracing.Tracing(self, "tracing")

        ctx = testing.Context(
            TinyCharm,
            meta={
                "name": "tiny",
                "requires": {"tracing": {"interface": "tracing", "limit": 1}},
            },
        )
        # Reaching ``state_out`` proves the constructor and a hook dispatch
        # both succeed under ``ops-tracing>=4`` — exactly what the agent
        # needs to be true for every charm it writes.
        state_out = ctx.run(ctx.on.start(), testing.State())
        assert state_out is not None

    def test_injection_output_imports_under_real_ops_tracing(
        self, tmp_path: pathlib.Path, monkeypatch
    ):
        """Patched output from ``_inject_ops_tracing_into_charm_py`` imports cleanly.

        The previous helper emitted ``ops_tracing.setup(self)``; importing the
        produced ``charm.py`` against ``ops-tracing>=4`` raised
        ``AttributeError`` at module load.  The current helper emits
        ``Tracing(self, "tracing")`` and the import path stays clean.
        """
        scaffolded = textwrap.dedent("""\
            #!/usr/bin/env python3
            import ops


            class PinnedCharm(ops.CharmBase):
                def __init__(self, framework: ops.Framework):
                    super().__init__(framework)
        """)
        patched = _inject_ops_tracing_into_charm_py(scaffolded)
        assert patched is not None, "scaffold should match the helper anchors"
        assert 'ops_tracing.Tracing(self, "tracing")' in patched
        assert "ops_tracing.setup" not in patched

        module_path = tmp_path / "charm.py"
        module_path.write_text(patched)

        # Loading the module exercises the import-time failure mode that the
        # legacy ``setup`` recipe hit on every charm.  ``Tracing`` is only
        # *referenced*, not invoked, until the charm constructor runs — so
        # this catches the import-side regression specifically.
        monkeypatch.syspath_prepend(str(tmp_path))
        sys.modules.pop("charm", None)
        try:
            import importlib

            importlib.import_module("charm")
        finally:
            sys.modules.pop("charm", None)
