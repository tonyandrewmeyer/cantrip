"""Baseline ``@``-mention providers shipped with Cantrip.

Each provider here wraps an existing read-only operation (file read,
``git diff``, lint sweep, …) into the
:class:`~cantrip.agent.context_providers.ContextProvider` protocol.
Heavier providers that depend on external services
(``@url``/``@charm``/``@juju``) live next to this module so the core
parser stays import-light.

Adding a baseline provider:

1. Implement a ``ContextProvider``-shaped object (a frozen dataclass
   with an ``info`` :class:`ProviderInfo` and an async ``expand``
   method is the simplest shape).
2. Register it inside :func:`build_default_registry`.
3. If users surface it from autocomplete, the ``info`` is enough — no
   parallel catalogue list to keep in sync.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import pathlib
import shutil
import subprocess

from cantrip.agent import lint_context
from cantrip.agent.context_providers import (
    ArgStyle,
    ContextBlock,
    ContextProvider,
    ExpansionContext,
    ProviderInfo,
    ProviderRegistry,
    chars_for_tokens,
    truncate,
)

log = logging.getLogger(__name__)


# Provider-specific char budgets (token estimates × 4).  Conservative
# defaults — large enough that the typical use case fits, small enough
# that one mention does not dominate the prompt.
_FILE_MAX_CHARS = chars_for_tokens(4000)  # ~16k chars
_DIFF_MAX_CHARS = chars_for_tokens(4000)
_TREE_MAX_CHARS = chars_for_tokens(2000)  # ~8k chars
_PROBLEMS_MAX_CHARS = lint_context.DEFAULT_MAX_CHARS  # 6000 chars

_GIT_TIMEOUT_SECONDS = 10.0
_TREE_MAX_FILES = 600


def _resolve_within(
    raw: str,
    *,
    base: pathlib.Path,
) -> pathlib.Path:
    """Resolve *raw* under *base*, refusing absolute paths and ``..`` traversal.

    Mirrors the safety contract of
    :func:`cantrip.agent.custom_commands._resolve_file_reference`: a
    user typing ``@file ../../etc/passwd`` is rejected before any I/O.
    """
    candidate = pathlib.Path(raw)
    if candidate.is_absolute():
        raise ValueError(f"absolute paths are not permitted: {raw}")
    resolved = (base / candidate).resolve(strict=False)
    base_resolved = base.resolve(strict=False)
    try:
        resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError(f"path must stay within the repo root: {raw}") from exc
    return resolved


def _root_for(ctx: ExpansionContext) -> pathlib.Path:
    """Pick the directory baseline providers anchor to.

    ``charm_path`` is the most useful default for charm-specific
    operations (``@diff``, ``@tree``, ``@problems``); ``repo_root``
    is the fallback when the agent has not yet anchored on a charm.
    Both fall through to ``cwd()`` so unit tests that build a
    bare :class:`ExpansionContext` still work.
    """
    if ctx.charm_path is not None:
        return ctx.charm_path
    if ctx.repo_root is not None:
        return ctx.repo_root
    return pathlib.Path.cwd()


# ---------------------------------------------------------------------------
# @file <path>
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class FileProvider:
    """``@file <path>`` — inline the contents of a repo-relative file."""

    info: ProviderInfo = ProviderInfo(
        name="file",
        summary="Inline file contents",
        arg_style=ArgStyle.TOKEN,
        args_hint="<path>",
    )

    async def expand(self, args: str, ctx: ExpansionContext) -> ContextBlock:
        """Read *args* relative to the charm/repo root and return its text."""
        raw_form = self._raw_form(args)
        if not args:
            return ContextBlock(
                raw=raw_form,
                rendered="[@file: missing path argument]",
                error="missing path",
            )
        base = _root_for(ctx)
        try:
            resolved = _resolve_within(args, base=base)
        except ValueError as exc:
            return ContextBlock(
                raw=raw_form,
                rendered=f"[@file {args}: {exc}]",
                error=str(exc),
            )
        if not resolved.is_file():
            return ContextBlock(
                raw=raw_form,
                rendered=f"[@file {args}: not a file]",
                error="not a file",
            )
        try:
            text = resolved.read_text(encoding="utf-8")
        except OSError as exc:
            return ContextBlock(
                raw=raw_form,
                rendered=f"[@file {args}: read failed: {exc}]",
                error=str(exc),
            )
        return truncate(
            raw=raw_form,
            rendered=text,
            max_chars=_FILE_MAX_CHARS,
            note="use `@file <path> --full` to override (planned)",
        )

    def _raw_form(self, args: str) -> str:
        """Reconstruct the typed mention for transcript/error messages."""
        return f"@file {args}".rstrip()


# ---------------------------------------------------------------------------
# @diff
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class DiffProvider:
    """``@diff`` — output of ``git diff HEAD`` in the charm/repo."""

    info: ProviderInfo = ProviderInfo(
        name="diff",
        summary="git diff since last commit",
        arg_style=ArgStyle.NONE,
    )

    async def expand(self, args: str, ctx: ExpansionContext) -> ContextBlock:  # noqa: ARG002 — protocol shape
        """Shell out to ``git diff HEAD`` and return the patch text."""
        raw = "@diff"
        if shutil.which("git") is None:
            return ContextBlock(raw=raw, rendered="[@diff: git not installed]", error="no git")
        cwd = _root_for(ctx)
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["git", "diff", "HEAD"],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ContextBlock(raw=raw, rendered="[@diff: git timed out]", error="timeout")
        except OSError as exc:
            return ContextBlock(raw=raw, rendered=f"[@diff: {exc}]", error=str(exc))
        if result.returncode != 0:
            return ContextBlock(
                raw=raw,
                rendered=f"[@diff: git returned {result.returncode}: {result.stderr.strip()}]",
                error="git error",
            )
        body = result.stdout
        if not body.strip():
            return ContextBlock(raw=raw, rendered="[@diff: working tree clean]")
        return truncate(raw=raw, rendered=body, max_chars=_DIFF_MAX_CHARS)


# ---------------------------------------------------------------------------
# @tree [path]
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class TreeProvider:
    """``@tree [path]`` — repo-tracked file tree (respects ``.gitignore``).

    Uses ``git ls-files`` so ignore semantics come for free without
    re-implementing ``.gitignore`` parsing.  Falls back to
    :func:`pathlib.Path.iterdir` when the directory is not a git
    checkout — matches what the user expects when they run ``@tree``
    inside a fresh charm directory.
    """

    info: ProviderInfo = ProviderInfo(
        name="tree",
        summary="Directory tree (respects .gitignore)",
        arg_style=ArgStyle.TOKEN,
        args_hint="[path]",
    )

    async def expand(self, args: str, ctx: ExpansionContext) -> ContextBlock:
        """List files under *args* (or the charm/repo root)."""
        raw = f"@tree {args}".rstrip()
        base = _root_for(ctx)
        target = base
        if args:
            try:
                target = _resolve_within(args, base=base)
            except ValueError as exc:
                return ContextBlock(raw=raw, rendered=f"[@tree {args}: {exc}]", error=str(exc))
            if not target.is_dir():
                return ContextBlock(
                    raw=raw,
                    rendered=f"[@tree {args}: not a directory]",
                    error="not a directory",
                )

        rendered, error = await asyncio.to_thread(_render_tree, target, base)
        if error:
            return ContextBlock(raw=raw, rendered=f"[@tree {args or '.'}: {error}]", error=error)
        return truncate(raw=raw, rendered=rendered, max_chars=_TREE_MAX_CHARS)


def _render_tree(target: pathlib.Path, repo_root: pathlib.Path) -> tuple[str, str]:
    """Return ``(text, error)`` — *error* is ``""`` on success.

    Strategy:

    * If *target* sits inside a git checkout, use ``git -C <root>
      ls-files <relpath>`` so ignored files are skipped.  This also
      catches untracked-but-not-ignored files (``--others
      --exclude-standard``) so a fresh ``foo.py`` shows up before
      the user has staged it.
    * Otherwise fall back to a plain recursive walk capped at
      :data:`_TREE_MAX_FILES`.
    """
    if shutil.which("git") is not None:
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "ls-files",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                ],
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "", str(exc)
        if result.returncode == 0:
            try:
                rel_target = target.resolve().relative_to(repo_root.resolve())
            except ValueError:
                rel_target = pathlib.Path(".")
            prefix = "" if str(rel_target) in {".", ""} else f"{rel_target.as_posix()}/"
            files = sorted(
                line
                for line in result.stdout.splitlines()
                if line and (not prefix or line.startswith(prefix))
            )
            if not files:
                return f"(no tracked files under {rel_target.as_posix() or '.'})", ""
            shown = files[:_TREE_MAX_FILES]
            text = "\n".join(shown)
            if len(files) > _TREE_MAX_FILES:
                text += f"\n… {len(files) - _TREE_MAX_FILES} more files elided"
            return text, ""

    # Fallback: plain walk.
    files: list[str] = []
    try:
        for path in sorted(target.rglob("*")):
            if path.is_dir():
                continue
            files.append(path.relative_to(target).as_posix())
            if len(files) > _TREE_MAX_FILES * 2:
                break
    except OSError as exc:
        return "", str(exc)
    if not files:
        return "(empty)", ""
    shown = files[:_TREE_MAX_FILES]
    text = "\n".join(shown)
    if len(files) > _TREE_MAX_FILES:
        text += f"\n… {len(files) - _TREE_MAX_FILES} more files elided"
    return text, ""


# ---------------------------------------------------------------------------
# @problems
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class ProblemsProvider:
    """``@problems`` — ruff/ty/charmlint diagnostics for the active charm.

    Reuses the Phase 72.4 :class:`~cantrip.agent.lint_context.DiagnosticsCache`
    so a ``/diagnostics`` immediately followed by an ``@problems``
    mention does not pay for the linters twice.
    """

    info: ProviderInfo = ProviderInfo(
        name="problems",
        summary="Current ruff/ty/charmlint diagnostics",
        arg_style=ArgStyle.NONE,
    )
    cache: lint_context.DiagnosticsCache | None = None

    async def expand(self, args: str, ctx: ExpansionContext) -> ContextBlock:  # noqa: ARG002 — protocol shape
        """Run the project-wide lint sweep and render the result."""
        raw = "@problems"
        charm_path = ctx.charm_path or ctx.repo_root or pathlib.Path.cwd()
        cache = self.cache if self.cache is not None else lint_context.default_cache()
        try:
            block = await lint_context.gather_project_diagnostics(
                charm_path,
                max_chars=_PROBLEMS_MAX_CHARS,
                cache=cache,
            )
        except (OSError, RuntimeError) as exc:
            return ContextBlock(raw=raw, rendered=f"[@problems: {exc}]", error=str(exc))
        return ContextBlock(raw=raw, rendered=block.to_text())


# ---------------------------------------------------------------------------
# Default registry
# ---------------------------------------------------------------------------


def build_default_registry() -> ProviderRegistry:
    """Return a :class:`ProviderRegistry` with the baseline ``@`` providers.

    Heavier providers (``@url``, ``@charm``, ``@juju``) are added by
    surfaces that pull in their dependencies — see
    :mod:`cantrip.agent.context_providers_external`.  This split keeps
    unit tests that exercise the parser free of network and Charmhub
    imports.
    """
    registry = ProviderRegistry()
    for provider in (
        FileProvider(),
        DiffProvider(),
        TreeProvider(),
        ProblemsProvider(),
    ):
        registry.register(_as_protocol(provider))
    return registry


def _as_protocol(provider: object) -> ContextProvider:
    """Cast helper.

    Frozen dataclasses with ``info`` and ``expand`` satisfy the
    :class:`ContextProvider` protocol structurally; this helper
    keeps the type checker happy at the registration site without a
    sprinkling of ``cast`` calls in the caller.
    """
    if not isinstance(provider, ContextProvider):
        raise TypeError(f"{type(provider).__name__} does not satisfy ContextProvider")
    return provider
