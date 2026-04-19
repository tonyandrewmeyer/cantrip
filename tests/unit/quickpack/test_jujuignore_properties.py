"""Property-based tests for ``quickpack.jujuignore.JujuIgnore``.

The pattern matcher is a small, pure, string-only API: the example
tests in ``test_jujuignore.py::TestJujuignore`` cover the canonical
cases; these property tests pin down invariants that should hold for
any mix of patterns and paths.  The previous bug fixed during Phase
58.1 (``Matcher.match`` using unanchored ``is_match`` instead of
anchored ``match``) is exactly the kind of regression property
testing is good at catching, so this suite leans into the semantics
the anchored match guarantees.

Invariants under test:

* *Determinism.*  Calling ``.match`` twice on the same inputs
  returns the same answer.
* *Robust construction.*  ``JujuIgnore(patterns)`` does not raise
  for arbitrary string patterns — even malformed ones — and the
  resulting object still answers ``.match`` for arbitrary paths
  without raising.
* *Defaults always bite.*  Canonical VCS directories (``.git``,
  ``.hg``, etc.) are ignored regardless of the user patterns, so
  long as the user hasn't explicitly un-ignored them.
* *No-op patterns are no-ops.*  Comments and blank lines in the
  pattern list don't change matching behaviour.
* *Negation composition.*  For a pattern ``P`` that matches a path,
  appending ``!P`` afterwards un-ignores the path — matching the
  later-rule-wins semantics documented in ``JujuIgnore.match``.
* *Negation is authoritative.*  Once ``!P`` has force-kept a path,
  a later rule spelled the same way as ``P`` does *not* re-ignore —
  matching the early-break semantics of ``JujuIgnore.match``, which
  differs from gitignore's "latest rule wins" model.
"""

from __future__ import annotations

import string

from hypothesis import given
from hypothesis import strategies as st

from quickpack.jujuignore import DEFAULT_IGNORES, JujuIgnore

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


# Path-safe alphabet: lower-case ASCII letters, digits, and the handful of
# punctuation the matcher treats specially (dot, hyphen, underscore).  Space
# characters get trimmed by ``_unescape`` so they don't help probe behaviour.
_PATH_CHAR = st.text(alphabet=string.ascii_lowercase + "0123456789._-", min_size=1, max_size=5)


def _path() -> st.SearchStrategy[str]:
    """A relative filesystem path with 1..4 components."""
    return st.lists(_PATH_CHAR, min_size=1, max_size=4).map("/".join)


# Pattern-safe alphabet: same base plus the wildcard/character-class metachars
# the matcher supports.  Random punctuation gets escaped verbatim by
# ``_rule_to_regex``, so a wider alphabet mostly wastes shrink budget.
_PATTERN_CHAR = st.text(
    alphabet=string.ascii_lowercase + "0123456789._-*?/!",
    min_size=1,
    max_size=8,
)

# Non-empty alphabet without the special meta-characters so we can generate
# patterns that are guaranteed to appear literally in a matching path.
_LITERAL_CHAR = st.text(alphabet=string.ascii_lowercase + "0123456789_", min_size=1, max_size=5)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestJujuignoreProperties:
    """Invariants over arbitrary pattern and path inputs."""

    @given(pattern=_PATTERN_CHAR, path=_path(), is_dir=st.booleans())
    def test_match_is_deterministic(self, pattern: str, path: str, is_dir: bool) -> None:
        """Two calls with the same inputs must agree."""
        ignore = JujuIgnore([pattern])
        assert ignore.match(path, is_dir=is_dir) == ignore.match(path, is_dir=is_dir)

    @given(patterns=st.lists(_PATTERN_CHAR, max_size=6), path=_path(), is_dir=st.booleans())
    def test_arbitrary_patterns_never_raise(
        self, patterns: list[str], path: str, is_dir: bool
    ) -> None:
        """Construction and matching must not raise on arbitrary input.

        This is the property that would have caught the Phase 58.1
        regex-anchoring regression: the bug produced *wrong* answers
        rather than exceptions, but any future refactor that, say,
        passes a malformed rule straight to ``re.compile`` without
        massaging it first would show up here."""
        ignore = JujuIgnore(patterns)
        ignore.match(path, is_dir=is_dir)

    @given(
        patterns=st.lists(_PATTERN_CHAR, max_size=6),
        default=st.sampled_from(
            # Only the un-anchored, un-suffixed defaults — anchored entries
            # like ``/build/`` and ``/revision`` only match at the repo root,
            # so their ``match`` answer depends on how the path is spelled,
            # and that's orthogonal to "do the defaults still apply?"
            [d for d in DEFAULT_IGNORES if not d.startswith("/") and not d.endswith("/")]
        ),
    )
    def test_defaults_still_bite(self, patterns: list[str], default: str) -> None:
        """User patterns don't disable the built-in default ignores.

        A user pattern that explicitly negates the default (e.g.
        ``!.git``) would break this; the strategy filter below drops
        any such pattern so the invariant is tested against orthogonal
        user input only.
        """
        safe = [
            p for p in patterns if not (p.startswith("!") and p.strip("!").strip("/") == default)
        ]
        ignore = JujuIgnore(safe)
        # Most defaults are directories (.git, .tox, …); the handful that
        # aren't (.jujuignore) still ignore when is_dir=False.
        assert ignore.match(default, is_dir=True) or ignore.match(default, is_dir=False)

    @given(
        base=st.lists(_PATTERN_CHAR, max_size=4),
        noise=st.lists(
            st.sampled_from(["", "   ", "# a comment", "   # indented comment", "\t"]),
            max_size=4,
        ),
        path=_path(),
        is_dir=st.booleans(),
    )
    def test_comments_and_blanks_are_noops(
        self,
        base: list[str],
        noise: list[str],
        path: str,
        is_dir: bool,
    ) -> None:
        """Comments and blank lines should not change matching behaviour."""
        pure = JujuIgnore(base)
        mixed = JujuIgnore(base + noise)
        assert pure.match(path, is_dir=is_dir) == mixed.match(path, is_dir=is_dir)

    @given(pattern=_LITERAL_CHAR, is_dir=st.booleans())
    def test_negation_un_ignores(self, pattern: str, is_dir: bool) -> None:
        """``[P, !P]`` must un-ignore the path that ``[P]`` alone would ignore.

        Uses a literal pattern so we know ``P`` matches a path spelled
        exactly ``/{pattern}`` — the matcher prepends ``**/`` to bare
        rules, then anchors with ``\\Z``.
        """
        path = pattern
        ignored_once = JujuIgnore([pattern]).match(path, is_dir=is_dir)
        ignored_with_negation = JujuIgnore([pattern, f"!{pattern}"]).match(path, is_dir=is_dir)
        # Only assert the symmetry when the base pattern actually ignored
        # the path — a literal like ``_`` might not match for reasons
        # unrelated to negation, and then the property is vacuous.
        if ignored_once:
            assert not ignored_with_negation

    @given(pattern=_LITERAL_CHAR, is_dir=st.booleans())
    def test_negation_is_authoritative(self, pattern: str, is_dir: bool) -> None:
        """Once ``!P`` force-keeps a path, a later plain ``P`` does **not**
        re-ignore it.

        ``JujuIgnore.match`` breaks out of the rule loop on the first
        ``forcekeep`` result, so the third rule in ``[P, !P, P]`` is
        ineffectual — unlike gitignore, where the latest-matching rule
        wins.  Pinning this down keeps a future "make it more
        gitignore-like" refactor from changing behaviour silently.
        """
        path = pattern
        ignored_once_then_negated = JujuIgnore([pattern, f"!{pattern}"]).match(path, is_dir=is_dir)
        ignored_triple = JujuIgnore([pattern, f"!{pattern}", pattern]).match(path, is_dir=is_dir)
        # Add a third rule spelled the same as the first — it must not
        # flip the answer, because the middle ``!P`` already short-
        # circuited the decision.
        assert ignored_once_then_negated == ignored_triple
