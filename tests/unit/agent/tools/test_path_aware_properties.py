"""Property-based tests for :meth:`PathAwareTool._resolve_path`.

The example-based tests in ``test_file_tools.py`` cover the named cases
(relative-into-base, absolute-into-base, ``..``-traversal blocked,
absolute-outside-base blocked, symlink-escape blocked).  These property
tests exercise the *space* between those examples: random path strings
with varying numbers of separators, dot segments, parent segments,
trailing slashes, and mixed absolute/relative forms.  Together they
pin the resolver's contract — within base, never above base, ValueError
when the user tries to escape — across the messy strings users
actually pass.

Invariants under test:

* *Resolved path is absolute.*  ``_resolve_path`` always returns an
  absolute :class:`pathlib.Path`, regardless of how the input was
  spelled.
* *Containment.*  With ``base_path`` set, the result either is
  ``is_relative_to(base_path.resolve())`` or the call raised
  ``ValueError``.  No third outcome is possible.
* *Safe relative paths land under base.*  A relative path made of
  non-empty components, none of which is ``..``, resolves to
  ``base_path / candidate`` (after both are resolved).
* *Escape via ``..`` is rejected.*  Any path whose final resolved form
  would lie outside ``base_path`` raises ``ValueError``.  This holds
  whether the escape is spelled as a relative path (``../../etc``), as
  an absolute path outside base (``/etc/passwd``), or as a longer
  sequence with intermediate ``..`` (``a/b/../../../etc``).
* *Idempotence on safe paths.*  Resolving a safe path twice produces
  the same result (the resolved path passed back through is identical
  to the first resolution).
* *None base_path is permissive.*  With ``base_path=None``, absolute
  paths pass through unchanged and relative paths resolve against
  ``Path.cwd()`` without raising.
"""

from __future__ import annotations

import pathlib

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from cantrip.agent.tools.files import ReadFileTool

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def _safe_component() -> st.SearchStrategy[str]:
    """A path component that is neither empty, nor ``.``, nor ``..``.

    Restricted to a small alphabet so Hypothesis can shrink to readable
    failing inputs; the resolver doesn't care which characters appear,
    only how segments are joined.
    """
    return st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_",
        min_size=1,
        max_size=8,
    ).filter(lambda s: s not in (".", ".."))


def _safe_relative_path() -> st.SearchStrategy[str]:
    """A relative path made entirely of safe components."""
    return st.lists(_safe_component(), min_size=1, max_size=5).map("/".join)


def _path_with_dotdot() -> st.SearchStrategy[str]:
    """A relative path that contains at least one ``..`` segment."""
    return (
        st.lists(
            st.one_of(_safe_component(), st.just("..")),
            min_size=2,
            max_size=6,
        )
        .filter(lambda parts: ".." in parts)
        .map("/".join)
    )


def _absolute_outside_base() -> st.SearchStrategy[str]:
    """An absolute path that does not start under any sane tmp dir.

    ``/etc/...``, ``/usr/...``, ``/var/...`` all qualify; the resolver
    must reject these regardless of what ``base_path`` happens to be.
    """
    roots = st.sampled_from(["/etc", "/usr/local", "/var/run", "/root", "/srv"])
    suffix = st.lists(_safe_component(), min_size=0, max_size=3).map("/".join)
    return st.tuples(roots, suffix).map(lambda t: t[0] + ("/" + t[1] if t[1] else ""))


# ---------------------------------------------------------------------------
# Invariants on the resolver's return shape
# ---------------------------------------------------------------------------


# ``tmp_path`` is per-call, so we tell Hypothesis not to complain about reusing
# the same fixture across many examples — we never write into it.
_NO_FUNCTION_SCOPE_WARNING = settings(suppress_health_check=[HealthCheck.function_scoped_fixture])


class TestResolutionShape:
    """Whatever happens, the result is an absolute Path."""

    @given(rel=_safe_relative_path())
    @_NO_FUNCTION_SCOPE_WARNING
    def test_safe_relative_returns_absolute(self, tmp_path: pathlib.Path, rel: str) -> None:
        tool = ReadFileTool(base_path=tmp_path)
        resolved = tool._resolve_path(rel)
        assert resolved.is_absolute()

    @given(rel=_safe_relative_path())
    @_NO_FUNCTION_SCOPE_WARNING
    def test_safe_relative_stays_under_base(self, tmp_path: pathlib.Path, rel: str) -> None:
        tool = ReadFileTool(base_path=tmp_path)
        resolved = tool._resolve_path(rel)
        assert resolved.is_relative_to(tmp_path.resolve())

    @given(rel=_safe_relative_path())
    @_NO_FUNCTION_SCOPE_WARNING
    def test_safe_relative_equals_base_joined(self, tmp_path: pathlib.Path, rel: str) -> None:
        # The contract for safe inputs: anchor under base, then resolve.
        tool = ReadFileTool(base_path=tmp_path)
        resolved = tool._resolve_path(rel)
        expected = (tmp_path / rel).resolve()
        assert resolved == expected

    @given(rel=_safe_relative_path())
    @_NO_FUNCTION_SCOPE_WARNING
    def test_resolution_is_idempotent_on_safe_paths(
        self, tmp_path: pathlib.Path, rel: str
    ) -> None:
        tool = ReadFileTool(base_path=tmp_path)
        first = tool._resolve_path(rel)
        # Feed the resolved path back in as a string; the tool must
        # treat it as an absolute path that happens to live under base.
        second = tool._resolve_path(str(first))
        assert second == first


# ---------------------------------------------------------------------------
# Escape detection
# ---------------------------------------------------------------------------


class TestEscapeRejection:
    """Anything that would resolve outside ``base_path`` must raise."""

    @given(escape=_path_with_dotdot())
    @_NO_FUNCTION_SCOPE_WARNING
    def test_dotdot_escape_either_stays_in_base_or_raises(
        self, tmp_path: pathlib.Path, escape: str
    ) -> None:
        # A ``..``-bearing path may or may not actually escape — e.g.
        # ``foo/../bar`` is fine because it collapses to ``bar``.  The
        # invariant is: either it stays under base, or it raises.
        tool = ReadFileTool(base_path=tmp_path)
        try:
            resolved = tool._resolve_path(escape)
        except ValueError as exc:
            assert "outside allowed directory" in str(exc)
        else:
            assert resolved.is_relative_to(tmp_path.resolve()), (
                f"Path {escape!r} resolved to {resolved!r}, which is outside "
                f"{tmp_path!r}; the resolver should have raised."
            )

    @given(outside=_absolute_outside_base())
    @_NO_FUNCTION_SCOPE_WARNING
    def test_absolute_path_outside_base_raises(self, tmp_path: pathlib.Path, outside: str) -> None:
        # Hypothesis could in principle pick an outside-root path that
        # happens to lie under ``tmp_path``.  Filter that case out so the
        # assertion is unambiguous.
        outside_resolved = pathlib.Path(outside).resolve()
        assume(not outside_resolved.is_relative_to(tmp_path.resolve()))

        tool = ReadFileTool(base_path=tmp_path)
        with pytest.raises(ValueError, match="outside allowed directory"):
            tool._resolve_path(outside)

    @given(prefix_depth=st.integers(min_value=1, max_value=6))
    @_NO_FUNCTION_SCOPE_WARNING
    def test_repeated_dotdot_eventually_escapes(
        self, tmp_path: pathlib.Path, prefix_depth: int
    ) -> None:
        # ``../../...``  with enough hops always escapes any base.
        path = "/".join([".."] * prefix_depth) + "/escape-target"
        tool = ReadFileTool(base_path=tmp_path)
        with pytest.raises(ValueError, match="outside allowed directory"):
            tool._resolve_path(path)


# ---------------------------------------------------------------------------
# Absolute path under base
# ---------------------------------------------------------------------------


class TestAbsoluteInsideBase:
    """Absolute paths *under* base resolve through cleanly."""

    @given(rel=_safe_relative_path())
    @_NO_FUNCTION_SCOPE_WARNING
    def test_absolute_under_base_returns_same_path(self, tmp_path: pathlib.Path, rel: str) -> None:
        # Spell the same target both ways — once relative, once
        # absolute — and assert the resolver agrees.
        tool = ReadFileTool(base_path=tmp_path)
        absolute = str((tmp_path / rel).resolve())
        relative = rel
        assert tool._resolve_path(absolute) == tool._resolve_path(relative)


# ---------------------------------------------------------------------------
# None base_path is permissive
# ---------------------------------------------------------------------------


class TestNoBasePathIsPermissive:
    """With no ``base_path``, the resolver does not gate on location."""

    @given(rel=_safe_relative_path())
    def test_relative_paths_resolve_against_cwd(self, rel: str) -> None:
        tool = ReadFileTool(base_path=None)
        resolved = tool._resolve_path(rel)
        assert resolved.is_absolute()
        assert resolved == (pathlib.Path.cwd() / rel).resolve()

    @given(outside=_absolute_outside_base())
    def test_absolute_paths_pass_through(self, outside: str) -> None:
        tool = ReadFileTool(base_path=None)
        resolved = tool._resolve_path(outside)
        # The resolver returns the absolute path unchanged when no base
        # is set — it does *not* call ``.resolve()``.  The caller is
        # trusted at this layer; the sandbox is the actual gate.
        assert resolved == pathlib.Path(outside).expanduser()
