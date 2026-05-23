"""Differential / metamorphic property tests for the permission policy.

The example-based tests in ``test_permissions.py`` cover the named
verdicts (deny / ask / allow with a single matching rule per section).
These property tests pin the cross-cutting invariants the policy must
hold across *any* shape of ruleset and tool call:

* *Determinism.*  ``evaluate(R, tool, args)`` returns the same
  ``PermissionDecision`` for byte-identical inputs.  The decision is
  pure of the ruleset, tool name, and arguments.
* *Non-mutation.*  Neither the input ruleset nor the arguments dict
  is ever modified by an evaluate call.
* *Empty ruleset is permissive.*  An empty :class:`PermissionRuleset`
  always returns ``ALLOW`` regardless of tool name or arguments — the
  Phase 68.2 "nothing matched ⇒ default allow" guarantee.
* *Catch-all DENY is absorbing.*  Appending ``("*", deny)`` to the
  ``tools`` section guarantees DENY for every tool, regardless of
  what other rules say.  Composing a catch-all-DENY ruleset with any
  other ruleset (DENY rule last) yields the same guarantee.  Note
  that monotonicity in general does **not** hold — last-match-wins
  inside a section means appending an ALLOW rule for the same subject
  intentionally loosens that section's candidate (agent overlays
  exploit this to relax global rules).
* *Unmatched rule is inert.*  Appending a rule whose pattern matches
  no subject the call would test leaves the decision unchanged.
* *Most-restrictive-wins across sections.*  When ``tools`` and
  ``bash`` produce different outcomes for the same call, the more
  restrictive of the two is what the caller sees.
* *bash_tools gate.*  Tools whose name is *not* in ``bash_tools``
  never consult the ``bash`` section — even when the arguments carry
  a ``command`` key that would otherwise match a bash rule.
* *Argument-free evaluation only consults ``tools``.*  Calling
  ``evaluate`` with no arguments skips both ``bash`` and ``paths``
  matching; the only candidate is whatever the ``tools`` section
  produces.
* *Compose with identity.*  ``compose_rulesets(empty, R)`` and
  ``compose_rulesets(R)`` yield rulesets that evaluate to the same
  decision as ``R`` itself.
* *Compose preserves concatenation order.*  For any two rulesets A
  and B, ``compose_rulesets(A, B).tools == A.tools + B.tools`` (and
  similarly for ``bash`` and ``paths``).
"""

from __future__ import annotations

import copy

from hypothesis import given
from hypothesis import strategies as st

from cantrip.agent.permissions import (
    PermissionOutcome,
    PermissionRule,
    PermissionRuleset,
    compose_rulesets,
    evaluate,
)

# Mirror of the internal ``_RESTRICTIVENESS`` table — restated here so
# the tests don't reach into private state to assert their invariant.
_OUTCOME_ORDINAL: dict[PermissionOutcome, int] = {
    PermissionOutcome.ALLOW: 0,
    PermissionOutcome.ASK: 1,
    PermissionOutcome.DENY: 2,
}


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def _tool_name() -> st.SearchStrategy[str]:
    """Plausible tool name — alphanumeric + underscore."""
    return st.text(alphabet="abcdefghij_", min_size=1, max_size=12)


def _outcome() -> st.SearchStrategy[PermissionOutcome]:
    return st.sampled_from(list(PermissionOutcome))


def _glob_pattern() -> st.SearchStrategy[str]:
    """A small set of glob shapes the evaluator should match cleanly.

    The patterns deliberately include ``*`` (catch-all) and prefix
    globs so monotonicity tests can construct rulesets where the new
    rule is guaranteed to match the chosen tool.
    """
    return st.one_of(
        st.just("*"),
        _tool_name(),
        _tool_name().map(lambda s: s + "*"),
        _tool_name().map(lambda s: "*" + s),
    )


def _rule(section_name: str = "tools") -> st.SearchStrategy[PermissionRule]:
    return st.builds(
        PermissionRule,
        pattern=_glob_pattern(),
        outcome=_outcome(),
        source=st.just(f"hypothesis:{section_name}"),
    )


def _ruleset() -> st.SearchStrategy[PermissionRuleset]:
    """A small random ruleset over the three sections."""
    return st.builds(
        PermissionRuleset,
        tools=st.lists(_rule("tools"), max_size=4).map(tuple),
        bash=st.lists(_rule("bash"), max_size=3).map(tuple),
        paths=st.lists(_rule("paths"), max_size=3).map(tuple),
        name=st.just("hypothesis"),
    )


def _arguments() -> st.SearchStrategy[dict]:
    """A small bundle of argument keys the evaluator inspects."""
    return st.fixed_dictionaries(
        {},
        optional={
            "path": st.text(alphabet="abc/_-", min_size=1, max_size=8),
            "command": st.text(alphabet="abcdef _-", min_size=1, max_size=12),
        },
    )


# ---------------------------------------------------------------------------
# Identity / determinism / non-mutation
# ---------------------------------------------------------------------------


class TestEvaluateIdentity:
    """``evaluate`` is pure."""

    @given(ruleset=_ruleset(), tool=_tool_name(), args=_arguments())
    def test_is_deterministic(self, ruleset: PermissionRuleset, tool: str, args: dict) -> None:
        first = evaluate(ruleset, tool, args)
        second = evaluate(ruleset, tool, args)
        assert first == second

    @given(ruleset=_ruleset(), tool=_tool_name(), args=_arguments())
    def test_does_not_mutate_arguments(
        self, ruleset: PermissionRuleset, tool: str, args: dict
    ) -> None:
        snapshot = copy.deepcopy(args)
        evaluate(ruleset, tool, args)
        assert args == snapshot

    @given(ruleset=_ruleset(), tool=_tool_name(), args=_arguments())
    def test_does_not_mutate_ruleset(
        self, ruleset: PermissionRuleset, tool: str, args: dict
    ) -> None:
        snapshot = copy.deepcopy(ruleset)
        evaluate(ruleset, tool, args)
        assert ruleset == snapshot


# ---------------------------------------------------------------------------
# Empty ruleset is permissive
# ---------------------------------------------------------------------------


class TestEmptyIsPermissive:
    """An empty ruleset is always ``ALLOW``."""

    @given(tool=_tool_name(), args=_arguments())
    def test_empty_returns_default_allow(self, tool: str, args: dict) -> None:
        decision = evaluate(PermissionRuleset(), tool, args)
        assert decision.outcome is PermissionOutcome.ALLOW
        assert decision.matched_rule is None

    @given(tool=_tool_name())
    def test_empty_returns_default_allow_with_no_arguments(self, tool: str) -> None:
        decision = evaluate(PermissionRuleset(), tool)
        assert decision.outcome is PermissionOutcome.ALLOW


# ---------------------------------------------------------------------------
# Catch-all DENY is absorbing
# ---------------------------------------------------------------------------


class TestCatchAllDenyIsAbsorbing:
    """A ``("*", deny)`` rule in ``tools`` forces DENY everywhere."""

    @given(ruleset=_ruleset(), tool=_tool_name(), args=_arguments())
    def test_append_star_deny_in_tools_forces_deny(
        self, ruleset: PermissionRuleset, tool: str, args: dict
    ) -> None:
        # Add a catch-all DENY to the *end* of the tools section.  The
        # tools section's last match becomes the DENY rule (it matches
        # every subject), and DENY beats every other section's outcome.
        with_deny = PermissionRuleset(
            tools=ruleset.tools
            + (PermissionRule(pattern="*", outcome=PermissionOutcome.DENY, source="hypothesis"),),
            bash=ruleset.bash,
            paths=ruleset.paths,
            agents=ruleset.agents,
            bash_tools=ruleset.bash_tools,
            name=ruleset.name,
        )
        decision = evaluate(with_deny, tool, args)
        assert decision.outcome is PermissionOutcome.DENY

    @given(ruleset=_ruleset(), tool=_tool_name(), args=_arguments())
    def test_compose_with_trailing_star_deny_forces_deny(
        self, ruleset: PermissionRuleset, tool: str, args: dict
    ) -> None:
        # Same property, expressed through ``compose_rulesets``: layering
        # a strictly-DENY catch-all on top of anything yields DENY.
        catchall = PermissionRuleset(
            tools=(
                PermissionRule(pattern="*", outcome=PermissionOutcome.DENY, source="catchall"),
            ),
        )
        composed = compose_rulesets(ruleset, catchall)
        decision = evaluate(composed, tool, args)
        assert decision.outcome is PermissionOutcome.DENY


# ---------------------------------------------------------------------------
# Unmatched rule is inert
# ---------------------------------------------------------------------------


class TestUnmatchedRuleIsInert:
    """Appending a rule that no subject can match leaves the decision unchanged."""

    @given(
        ruleset=_ruleset(),
        outcome=_outcome(),
        tool=_tool_name(),
        args=_arguments(),
    )
    def test_appending_non_matching_rule_preserves_decision(
        self,
        ruleset: PermissionRuleset,
        outcome: PermissionOutcome,
        tool: str,
        args: dict,
    ) -> None:
        # Use a pattern that can't match any subject the call inspects:
        # a long suffix unique to this test plus a fixed prefix.  The
        # tool / bash / paths subjects all start with letters from the
        # strategy alphabets, so a pattern beginning with ``zzz-`` is
        # guaranteed not to fnmatch any of them.
        inert_pattern = "zzz-unmatchable-sentinel-" + outcome.value
        before = evaluate(ruleset, tool, args)
        with_inert = PermissionRuleset(
            tools=ruleset.tools
            + (PermissionRule(pattern=inert_pattern, outcome=outcome, source="hypothesis"),),
            bash=ruleset.bash
            + (PermissionRule(pattern=inert_pattern, outcome=outcome, source="hypothesis"),),
            paths=ruleset.paths
            + (PermissionRule(pattern=inert_pattern, outcome=outcome, source="hypothesis"),),
            agents=ruleset.agents,
            bash_tools=ruleset.bash_tools,
            name=ruleset.name,
        )
        after = evaluate(with_inert, tool, args)
        assert after.outcome == before.outcome


# ---------------------------------------------------------------------------
# Most-restrictive-wins
# ---------------------------------------------------------------------------


class TestMostRestrictiveWins:
    """When multiple rules match a call, the strictest one wins."""

    @given(
        tool=_tool_name(),
        weaker_outcome=_outcome(),
        stronger_outcome=_outcome(),
    )
    def test_two_matching_tool_rules_pick_stricter(
        self,
        tool: str,
        weaker_outcome: PermissionOutcome,
        stronger_outcome: PermissionOutcome,
    ) -> None:
        # Skip the equal case; the test is about disagreement.
        if weaker_outcome == stronger_outcome:
            return
        # Order outcomes by restrictiveness so the assertion is unambiguous.
        if _OUTCOME_ORDINAL[weaker_outcome] > _OUTCOME_ORDINAL[stronger_outcome]:
            weaker_outcome, stronger_outcome = stronger_outcome, weaker_outcome
        ruleset = PermissionRuleset(
            tools=(
                PermissionRule(pattern="*", outcome=weaker_outcome, source="hypothesis"),
                PermissionRule(pattern=tool, outcome=stronger_outcome, source="hypothesis"),
            ),
        )
        # Hypothesis can pick a glob-active tool name (e.g. starting
        # with ``*``); fnmatch treats ``*`` and ``?`` as wildcards in
        # the *pattern*, not in the subject, so this is fine.
        decision = evaluate(ruleset, tool)
        # The chosen outcome is at least as strict as the stricter rule.
        assert _OUTCOME_ORDINAL[decision.outcome] >= _OUTCOME_ORDINAL[stronger_outcome]

    @given(
        tool=_tool_name(),
        command=st.text(alphabet="abcdef ", min_size=1, max_size=8),
        tools_outcome=_outcome(),
        bash_outcome=_outcome(),
    )
    def test_cross_section_pick_stricter(
        self,
        tool: str,
        command: str,
        tools_outcome: PermissionOutcome,
        bash_outcome: PermissionOutcome,
    ) -> None:
        # tools-section "*"-pattern + bash-section "*"-pattern both
        # match.  ``run_command`` is in the default ``bash_tools`` so
        # the bash section is consulted when ``command`` is supplied.
        ruleset = PermissionRuleset(
            tools=(PermissionRule(pattern="*", outcome=tools_outcome, source="hypothesis"),),
            bash=(PermissionRule(pattern="*", outcome=bash_outcome, source="hypothesis"),),
        )
        decision = evaluate(ruleset, "run_command", {"command": command})
        expected = max(
            _OUTCOME_ORDINAL[tools_outcome],
            _OUTCOME_ORDINAL[bash_outcome],
        )
        assert _OUTCOME_ORDINAL[decision.outcome] == expected


# ---------------------------------------------------------------------------
# bash_tools gate
# ---------------------------------------------------------------------------


class TestBashSectionGate:
    """The ``bash`` section is consulted only for tools in ``bash_tools``."""

    @given(
        tool=_tool_name().filter(lambda s: s != "run_command"),
        command=st.text(alphabet="abcdef ", min_size=1, max_size=8),
        bash_outcome=_outcome(),
    )
    def test_non_bash_tool_ignores_bash_section(
        self,
        tool: str,
        command: str,
        bash_outcome: PermissionOutcome,
    ) -> None:
        # Build a ruleset where the bash section would say DENY/ASK,
        # but the tool name isn't a bash tool — the bash section must
        # not contribute a candidate.
        ruleset = PermissionRuleset(
            bash=(PermissionRule(pattern="*", outcome=bash_outcome, source="hypothesis"),),
        )
        decision = evaluate(ruleset, tool, {"command": command})
        # No section produced a candidate → default ALLOW.
        assert decision.outcome is PermissionOutcome.ALLOW

    @given(
        command=st.text(alphabet="abcdef ", min_size=1, max_size=8),
        bash_outcome=_outcome(),
    )
    def test_run_command_does_consult_bash(
        self,
        command: str,
        bash_outcome: PermissionOutcome,
    ) -> None:
        ruleset = PermissionRuleset(
            bash=(PermissionRule(pattern="*", outcome=bash_outcome, source="hypothesis"),),
        )
        decision = evaluate(ruleset, "run_command", {"command": command})
        assert decision.outcome is bash_outcome


# ---------------------------------------------------------------------------
# Argument-free evaluation
# ---------------------------------------------------------------------------


class TestArgumentFreeEvaluation:
    """Without arguments, only ``tools`` matches."""

    @given(
        ruleset=_ruleset(),
        tool=_tool_name(),
    )
    def test_no_arguments_skips_bash_and_paths(
        self, ruleset: PermissionRuleset, tool: str
    ) -> None:
        # Compare against a synthetic ruleset that has *only* the
        # tools section — the decisions must agree because the absent
        # arguments stop the bash/paths sections from contributing.
        tools_only = PermissionRuleset(tools=ruleset.tools, name=ruleset.name)
        assert evaluate(ruleset, tool) == evaluate(tools_only, tool)


# ---------------------------------------------------------------------------
# Compose
# ---------------------------------------------------------------------------


class TestCompose:
    """Composition has the documented section-concatenation shape."""

    @given(ruleset=_ruleset())
    def test_compose_identity_with_empty(self, ruleset: PermissionRuleset) -> None:
        composed = compose_rulesets(PermissionRuleset(), ruleset)
        # Section tuples concatenate, so the composed sections start
        # with the empty ruleset's empty tuples and continue with the
        # input's rules.
        assert composed.tools == ruleset.tools
        assert composed.bash == ruleset.bash
        assert composed.paths == ruleset.paths

    @given(ruleset=_ruleset())
    def test_compose_single_ruleset_is_identity(self, ruleset: PermissionRuleset) -> None:
        assert compose_rulesets(ruleset) is ruleset

    @given(a=_ruleset(), b=_ruleset())
    def test_compose_preserves_section_order(
        self, a: PermissionRuleset, b: PermissionRuleset
    ) -> None:
        composed = compose_rulesets(a, b)
        assert composed.tools == a.tools + b.tools
        assert composed.bash == a.bash + b.bash
        assert composed.paths == a.paths + b.paths

    @given(a=_ruleset(), b=_ruleset(), c=_ruleset())
    def test_compose_is_associative_structurally(
        self,
        a: PermissionRuleset,
        b: PermissionRuleset,
        c: PermissionRuleset,
    ) -> None:
        # compose(a, compose(b, c)) and compose(compose(a, b), c) must
        # share the same section tuples — concatenation is associative.
        left = compose_rulesets(a, compose_rulesets(b, c))
        right = compose_rulesets(compose_rulesets(a, b), c)
        assert left.tools == right.tools
        assert left.bash == right.bash
        assert left.paths == right.paths
