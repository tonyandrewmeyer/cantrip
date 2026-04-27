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
from cantrip.agent.tools import charmhub as charmhub_tools
from cantrip.agent.tools import web as web_tools
from cantrip.llm import roles as llm_roles

log = logging.getLogger(__name__)


# Provider-specific char budgets (token estimates × 4).  Conservative
# defaults — large enough that the typical use case fits, small enough
# that one mention does not dominate the prompt.
_FILE_MAX_CHARS = chars_for_tokens(4000)  # ~16k chars
_DIFF_MAX_CHARS = chars_for_tokens(4000)
_TREE_MAX_CHARS = chars_for_tokens(2000)  # ~8k chars
_PROBLEMS_MAX_CHARS = lint_context.DEFAULT_MAX_CHARS  # 6000 chars
_URL_MAX_CHARS = chars_for_tokens(3000)
_CHARM_MAX_CHARS = chars_for_tokens(2000)
_JUJU_MAX_CHARS = chars_for_tokens(2000)
_DOCS_MAX_CHARS = chars_for_tokens(3000)

_GIT_TIMEOUT_SECONDS = 10.0
_JUJU_TIMEOUT_SECONDS = 30.0
_TREE_MAX_FILES = 600

# ``@juju`` accepts only read-only subcommands.  Sticking to a hard
# allowlist keeps a stray mention from running ``juju destroy-model``
# or anything else that mutates state.  Mirrors the read-only
# verbs Cantrip already exposes as typed tools (status, show-unit,
# config) plus a couple of obvious diagnostic verbs.
_JUJU_READONLY_VERBS: frozenset[str] = frozenset(
    {
        "status",
        "show-unit",
        "show-application",
        "show-model",
        "config",
        "list-secrets",
        "show-relation",
        "list-models",
    }
)


def _juju_config_is_readonly(rest: list[str]) -> bool:
    """Return ``True`` when ``juju config <rest>`` doesn't mutate state.

    ``juju config <app>`` and ``juju config <app> <key>`` are
    read-only, but the same verb mutates runtime state when given
    ``--reset <key>``, ``--file <path>``, or any positional
    ``key=value`` form.  The verb-only allowlist on its own would let
    a stray ``@juju config myapp --reset secret`` blow away an app's
    configuration; this helper rejects every destructive shape so the
    read-only allowlist actually means read-only.
    """
    for arg in rest:
        if "=" in arg:
            return False
        if arg in {"--reset", "--reset-from-file", "--file"}:
            return False
        if arg.startswith(("--reset=", "--reset-from-file=", "--file=")):
            return False
    return True


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


# ---------------------------------------------------------------------------
# @url <url>
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class UrlProvider:
    """``@url <url>`` — fetch *url* via :class:`web_tools.WebFetchTool`.

    Reuses the shared web-fetch implementation so the private-IP
    block, llms.txt probing, and HTML-to-text extraction stay in
    one place.  Failures surface as inline error blocks; a
    rate-limited fetch does not abort the rest of the message.
    """

    info: ProviderInfo = ProviderInfo(
        name="url",
        summary="Fetch a URL (markdownified)",
        arg_style=ArgStyle.TOKEN,
        args_hint="<url>",
    )

    async def expand(self, args: str, ctx: ExpansionContext) -> ContextBlock:  # noqa: ARG002 — protocol shape
        """Fetch *args* and return its text body."""
        raw = f"@url {args}".rstrip()
        if not args:
            return ContextBlock(raw=raw, rendered="[@url: missing URL]", error="missing url")
        tool = web_tools.WebFetchTool()
        result = await tool.execute(url=args)
        if not result.success:
            return ContextBlock(
                raw=raw,
                rendered=f"[@url {args}: {result.error}]",
                error=result.error or "fetch failed",
            )
        return truncate(raw=raw, rendered=result.output, max_chars=_URL_MAX_CHARS)


# ---------------------------------------------------------------------------
# @charm <name>
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class CharmProvider:
    """``@charm <name>`` — Charmhub metadata for *name*.

    Wraps :class:`charmhub_tools.CharmhubInfoTool` so the user can
    pull a charm's relations, config, and revision info inline.
    Source-tree fetching is intentionally out of scope here — that's
    a heavier operation belonging on the typed-tool surface.
    """

    info: ProviderInfo = ProviderInfo(
        name="charm",
        summary="Charmhub metadata for a charm",
        arg_style=ArgStyle.TOKEN,
        args_hint="<name>",
    )

    async def expand(self, args: str, ctx: ExpansionContext) -> ContextBlock:  # noqa: ARG002 — protocol shape
        """Fetch metadata for the charm called *args*."""
        raw = f"@charm {args}".rstrip()
        if not args:
            return ContextBlock(
                raw=raw, rendered="[@charm: missing charm name]", error="missing name"
            )
        tool = charmhub_tools.CharmhubInfoTool()
        result = await tool.execute(name=args)
        if not result.success:
            return ContextBlock(
                raw=raw,
                rendered=f"[@charm {args}: {result.error}]",
                error=result.error or "lookup failed",
            )
        return truncate(raw=raw, rendered=result.output, max_chars=_CHARM_MAX_CHARS)


# ---------------------------------------------------------------------------
# @juju <subcmd>
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class JujuProvider:
    """``@juju <subcmd>`` — output of a read-only ``juju`` command.

    The first token of *args* must be in :data:`_JUJU_READONLY_VERBS`.
    Anything else is rejected so a typo cannot accidentally invoke
    a destructive verb (``juju destroy-model`` & friends).
    """

    info: ProviderInfo = ProviderInfo(
        name="juju",
        summary="Read-only juju output (status, show-unit, config, …)",
        arg_style=ArgStyle.REST_OF_LINE,
        args_hint="<subcmd>",
    )

    async def expand(self, args: str, ctx: ExpansionContext) -> ContextBlock:  # noqa: ARG002 — protocol shape
        """Run ``juju <args>`` if the verb is in the read-only allowlist."""
        raw = f"@juju {args}".rstrip()
        if not args:
            return ContextBlock(
                raw=raw, rendered="[@juju: missing subcommand]", error="missing subcommand"
            )
        verb, *rest = args.split()
        if verb not in _JUJU_READONLY_VERBS:
            allowed = ", ".join(sorted(_JUJU_READONLY_VERBS))
            return ContextBlock(
                raw=raw,
                rendered=f"[@juju {verb}: not a read-only verb. Allowed: {allowed}]",
                error="not read-only",
            )
        if verb == "config" and not _juju_config_is_readonly(rest):
            return ContextBlock(
                raw=raw,
                rendered=(
                    "[@juju config: read-only form only. Drop "
                    "key=value, --reset, --reset-from-file, and --file.]"
                ),
                error="not read-only",
            )
        if shutil.which("juju") is None:
            return ContextBlock(raw=raw, rendered="[@juju: juju not installed]", error="no juju")
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["juju", verb, *rest],
                capture_output=True,
                text=True,
                timeout=_JUJU_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ContextBlock(raw=raw, rendered="[@juju: timed out]", error="timeout")
        except OSError as exc:
            return ContextBlock(raw=raw, rendered=f"[@juju: {exc}]", error=str(exc))
        if result.returncode != 0:
            stderr = result.stderr.strip() or "command failed"
            return ContextBlock(
                raw=raw,
                rendered=f"[@juju {verb}: {stderr}]",
                error="juju error",
            )
        return truncate(raw=raw, rendered=result.stdout, max_chars=_JUJU_MAX_CHARS)


# ---------------------------------------------------------------------------
# @docs <site> <query>
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class DocsProvider:
    """``@docs <site> <query>`` — search the indexed Canonical docs.

    Phase 72.1.  Wraps :class:`~cantrip.agent.tools.docs_search.DocsSearchTool`
    so a user can lookup canonical reference passages mid-message
    without a tool round-trip.  The first whitespace-delimited token
    of the args is the site name (juju/ops/charmcraft/…), the rest
    is the free-text query.

    The provider needs an embed-capable role router; build it with
    ``DocsProvider(role_router=agent.role_router)`` from the agent
    layer.  Sessions without a configured embed provider surface a
    clean error inline rather than crashing.
    """

    info: ProviderInfo = ProviderInfo(
        name="docs",
        summary="Search indexed Canonical documentation",
        arg_style=ArgStyle.REST_OF_LINE,
        args_hint="<site> <query>",
    )
    role_router: llm_roles.RoleRouter | None = None
    cache_root: pathlib.Path | None = None

    async def expand(self, args: str, ctx: ExpansionContext) -> ContextBlock:  # noqa: ARG002 — protocol shape
        """Run a docs_search and render the top hits as a block."""
        raw = f"@docs {args}".rstrip()
        if not args.strip():
            return ContextBlock(
                raw=raw,
                rendered="[@docs: usage `@docs <site> <query>` — try `@docs ops secrets`]",
                error="missing args",
            )
        first, _, rest = args.strip().partition(" ")
        site = first.lower()
        query = rest.strip()
        if not query:
            return ContextBlock(
                raw=raw,
                rendered=f"[@docs {site}: missing query — `@docs {site} <query>`]",
                error="missing query",
            )
        if self.role_router is None:
            return ContextBlock(
                raw=raw,
                rendered="[@docs: no role router available in this session]",
                error="no router",
            )
        from cantrip.agent.tools.docs_search import DocsSearchTool

        tool = DocsSearchTool(self.role_router, cache_root=self.cache_root)
        result = await tool.execute(query=query, site=site, top_k=4)
        if not result.success:
            return ContextBlock(
                raw=raw,
                rendered=f"[@docs {site}: {result.error}]",
                error=result.error or "search failed",
            )
        return truncate(raw=raw, rendered=result.output, max_chars=_DOCS_MAX_CHARS)


# ---------------------------------------------------------------------------
# Default registry
# ---------------------------------------------------------------------------


def build_default_registry(
    *,
    role_router: llm_roles.RoleRouter | None = None,
) -> ProviderRegistry:
    """Return a :class:`ProviderRegistry` with the baseline ``@`` providers.

    Includes both light-touch wrappers (``@file``, ``@diff``, ``@tree``,
    ``@problems``) and the network-touching set (``@url``, ``@charm``,
    ``@juju``).  Network providers are lazy — they only call out when
    the user types the mention, so unit tests that never trigger them
    incur no I/O.

    *role_router*, when supplied, enables the Phase 72.1 ``@docs``
    provider on top of the indexed-docs store.  Sessions without an
    embed-capable router skip ``@docs`` registration entirely so a
    user typing ``@docs ...`` gets the regular "unknown provider"
    pass-through rather than a runtime error.
    """
    registry = ProviderRegistry()
    providers: list[object] = [
        FileProvider(),
        DiffProvider(),
        TreeProvider(),
        ProblemsProvider(),
        UrlProvider(),
        CharmProvider(),
        JujuProvider(),
    ]
    if role_router is not None:
        providers.append(DocsProvider(role_router=role_router))
    for provider in providers:
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
