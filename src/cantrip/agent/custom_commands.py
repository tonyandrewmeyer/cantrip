"""User-defined slash commands from markdown files.

Phase 68.3.  A charm team drops ``.cantrip/commands/<name>.md``
into the repo (or ``~/.config/cantrip/commands/<name>.md`` for
a personal one) and ``/<name>`` becomes a new slash verb that
expands a prompt template before it reaches the agent.  Behind
the scenes each command has:

* YAML frontmatter describing how the prompt should be dispatched
  (``description``, ``agent``, ``model``, ``subtask``).
* A markdown body that is the prompt text with four placeholders:

  * ``$ARGUMENTS`` — every token after the verb, verbatim.
  * ``$1``, ``$2`` … — positional args split via :mod:`shlex`.
  * ``@path`` — the contents of a repo-local file.
  * ``` !`cmd` ``` — stdout of a shell command, gated through
    the Phase 68.2 permission layer so an unsafe expansion
    blocks or asks for approval.

The module owns three things: the :class:`CustomCommand` data
class, a discovery helper that walks both dirs, and an async
:func:`expand` function that produces the final prompt string
the slash dispatcher feeds into the agent.  Dispatch itself
lives in :mod:`cantrip.agent.slash_commands` — we stay
dispatch-agnostic here so tests can round-trip expansion
without constructing a full agent.
"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
import re
import shlex
import subprocess
from collections.abc import Mapping

import yaml

from cantrip.agent.permissions import (
    PermissionManager,
    PermissionOutcome,
    PermissionRuleset,
)
from cantrip.agent.permissions import (
    evaluate as evaluate_permissions,
)

log = logging.getLogger(__name__)

#: Default agent name for commands that omit the frontmatter field.
#: ``primary`` means "feed the expanded prompt to the conversation
#: loop just like a normal user message."  Any other value is the
#: task-category name Cantrip will dispatch a subagent under.
DEFAULT_AGENT: str = "primary"


#: Frontmatter delimiter — matches the ``SKILL.md`` shape so users
#: already familiar with Cantrip skills pick up the same pattern.
_FRONTMATTER_DELIMITER = "---"


#: Permitted frontmatter keys.  Unknown keys raise so a typo doesn't
#: silently fall back to a default — mirrors the permissions loader.
_FRONTMATTER_KEYS: frozenset[str] = frozenset({"description", "agent", "model", "subtask", "name"})


#: Hard limit on ``!`cmd` `` shell expansion output.  Keeps a runaway
#: command from blowing up the prompt that feeds into the model.
_SHELL_STDOUT_MAX_CHARS = 10_000


#: Default timeout for ``!`cmd` `` shell expansion, in seconds.
_SHELL_TIMEOUT_SECONDS: float = 10.0


#: Canonical discovery roots.  Exposed as module constants so the
#: docs and tests can reference the same strings without duplication.
USER_CONFIG_COMMANDS_DIR = pathlib.Path(".config") / "cantrip" / "commands"
REPO_COMMANDS_DIR = pathlib.Path(".cantrip") / "commands"


class CustomCommandError(ValueError):
    """Raised for bad frontmatter, filename, or expansion."""


@dataclasses.dataclass(frozen=True, slots=True)
class CustomCommand:
    """One user-defined slash command loaded from disk.

    ``verb`` carries the leading slash (``/relation-check``) so it
    drops straight into :data:`~cantrip.agent.slash_commands
    .COMMAND_CATALOGUE`.  ``body`` is the raw prompt template with
    placeholders unsubstituted; expansion happens at dispatch time
    via :func:`expand` so the same template can be used multiple
    times with different arguments.
    """

    verb: str
    description: str
    body: str
    agent: str = DEFAULT_AGENT
    model: str | None = None
    subtask: bool = False
    source: pathlib.Path | None = None


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


_VALID_VERB_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _verb_from_filename(path: pathlib.Path) -> str:
    """Return ``/<stem>`` after validating the filename is safe.

    Filenames turn directly into verbs, so we reject anything that
    would produce an ambiguous or unusable command (empty stems,
    stems with uppercase letters, stems that look like path
    traversals).  The regex is intentionally narrow — a typo in a
    filename should fail fast with a clear message.
    """
    stem = path.stem.lower()
    if not _VALID_VERB_RE.fullmatch(stem):
        raise CustomCommandError(
            f"{path}: invalid command name {stem!r}; must match "
            "[a-z0-9][a-z0-9_-]* — letters, digits, hyphens, underscores"
        )
    return f"/{stem}"


def _parse_frontmatter(path: pathlib.Path) -> tuple[dict[str, object], str]:
    """Split a command file into (frontmatter dict, body string).

    A file without frontmatter is accepted and yields an empty dict,
    so a bare prompt template can stand on its own for commands that
    only need a description and no agent/model override.
    """
    raw = path.read_text(encoding="utf-8")
    lines = raw.split("\n")
    if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
        return {}, raw

    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == _FRONTMATTER_DELIMITER:
            end = i
            break

    if end is None:
        raise CustomCommandError(f"{path}: opening frontmatter delimiter has no closing ``---``")
    frontmatter_text = "\n".join(lines[1:end])
    try:
        data = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        raise CustomCommandError(f"{path}: invalid YAML frontmatter: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise CustomCommandError(f"{path}: frontmatter must be a YAML mapping")

    body = "\n".join(lines[end + 1 :]).strip()
    return data, body


def load_command_file(path: pathlib.Path) -> CustomCommand:
    """Load one command file into a :class:`CustomCommand`.

    Raises :class:`CustomCommandError` with a path-prefixed message
    on any problem — filename, frontmatter type, unknown key.  Callers
    that prefer "log + skip" semantics should catch and log rather
    than letting a malformed file halt the session.
    """
    verb = _verb_from_filename(path)
    frontmatter, body = _parse_frontmatter(path)

    unknown = set(frontmatter.keys()) - _FRONTMATTER_KEYS
    if unknown:
        raise CustomCommandError(
            f"{path}: unknown frontmatter keys {sorted(unknown)}; "
            f"expected subset of {sorted(_FRONTMATTER_KEYS)}"
        )

    description_obj = frontmatter.get("description") or ""
    if not isinstance(description_obj, str):
        raise CustomCommandError(
            f"{path}: 'description' must be a string, got {type(description_obj).__name__}"
        )
    description = description_obj.strip()

    agent_obj = frontmatter.get("agent", DEFAULT_AGENT)
    if not isinstance(agent_obj, str) or not agent_obj:
        raise CustomCommandError(f"{path}: 'agent' must be a non-empty string, got {agent_obj!r}")

    model_obj = frontmatter.get("model")
    if model_obj is not None and not isinstance(model_obj, str):
        raise CustomCommandError(
            f"{path}: 'model' must be a string or null, got {type(model_obj).__name__}"
        )

    subtask_obj = frontmatter.get("subtask", False)
    if not isinstance(subtask_obj, bool):
        raise CustomCommandError(
            f"{path}: 'subtask' must be a boolean, got {type(subtask_obj).__name__}"
        )

    if not body.strip():
        raise CustomCommandError(f"{path}: command body is empty; a prompt template is required")

    return CustomCommand(
        verb=verb,
        description=description or f"User command from {path.name}",
        body=body,
        agent=agent_obj,
        model=model_obj,
        subtask=subtask_obj,
        source=path,
    )


def _collect_commands(directory: pathlib.Path) -> dict[str, CustomCommand]:
    """Walk *directory* for ``*.md`` files and load each one.

    Uses a mapping keyed by verb so repo rules can overwrite user
    rules at the caller.  Malformed files log a warning and are
    skipped — one bad command shouldn't break the others.
    """
    found: dict[str, CustomCommand] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() != ".md" or not path.is_file():
            continue
        try:
            command = load_command_file(path)
        except CustomCommandError as exc:
            log.warning("Skipping malformed command file %s: %s", path, exc)
            continue
        found[command.verb] = command
    return found


def discover_custom_commands(
    *,
    charm_path: pathlib.Path | None = None,
    user_config_dir: pathlib.Path | None = None,
) -> list[CustomCommand]:
    """Discover commands from the user and repo directories.

    Returns a list in ``verb`` order.  Repo commands override user
    commands when the verbs collide, matching the precedence rule
    the permissions loader uses.  ``user_config_dir`` defaults to
    ``~/.config/cantrip/`` — override for tests.
    """
    if user_config_dir is None:
        user_config_dir = pathlib.Path.home() / ".config" / "cantrip"
    user_dir = user_config_dir / "commands"
    merged: dict[str, CustomCommand] = dict(_collect_commands(user_dir))
    if charm_path is not None:
        repo_dir = charm_path / REPO_COMMANDS_DIR
        for verb, command in _collect_commands(repo_dir).items():
            merged[verb] = command
    return sorted(merged.values(), key=lambda cmd: cmd.verb)


# ---------------------------------------------------------------------------
# Expansion
# ---------------------------------------------------------------------------


_FILE_REF_RE = re.compile(r"@([^\s@`]+)")
_SHELL_REF_RE = re.compile(r"!`([^`]+)`")
_POSITIONAL_RE = re.compile(r"\$([0-9]+)")


def _expand_arguments(template: str, args: str) -> str:
    """Substitute ``$ARGUMENTS`` and ``$1``/``$2``/… in *template*."""
    result = template.replace("$ARGUMENTS", args)
    try:
        tokens = shlex.split(args)
    except ValueError:
        # Mismatched quotes — fall back to whitespace split so the
        # command still runs with best-effort positional args.
        tokens = args.split()

    def replace_positional(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        if idx == 0 or idx > len(tokens):
            # ``$0`` and unresolved indexes expand to an empty string
            # — matches bash shell semantics for unset positionals.
            return ""
        return tokens[idx - 1]

    return _POSITIONAL_RE.sub(replace_positional, result)


def _resolve_file_reference(raw_path: str, *, repo_root: pathlib.Path | None) -> str:
    """Return the contents of ``@path`` or raise.

    Safety rules: no absolute paths, no ``..`` traversal outside the
    repo root.  If *repo_root* is ``None`` we fall back to the
    current working directory — tests drive this branch.
    """
    if not raw_path:
        raise CustomCommandError("empty @ reference in command body")
    candidate = pathlib.Path(raw_path)
    if candidate.is_absolute():
        raise CustomCommandError(f"@{raw_path}: absolute paths are not permitted in commands")
    base = repo_root if repo_root is not None else pathlib.Path.cwd()
    try:
        resolved = (base / candidate).resolve(strict=False)
        base_resolved = base.resolve(strict=False)
        resolved.relative_to(base_resolved)
    except (OSError, ValueError) as exc:
        raise CustomCommandError(f"@{raw_path}: path must stay within the repo root") from exc
    if not resolved.is_file():
        raise CustomCommandError(f"@{raw_path}: no such file (resolved to {resolved})")
    try:
        return resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise CustomCommandError(f"@{raw_path}: read failed: {exc}") from exc


async def _resolve_shell_reference(
    command: str,
    *,
    repo_root: pathlib.Path | None,
    permissions: PermissionRuleset | None,
    permission_manager: PermissionManager | None,
    agent_name: str,
) -> str:
    """Run ``!`cmd` `` through the permission gate and return stdout.

    Strategy:

    * Evaluate the Phase 68.2 permission policy against a synthetic
      ``run_command`` call with the command string.  DENY refuses
      immediately.  ASK parks on the :class:`PermissionManager` (if
      one is wired) and either approves or denies.  ALLOW proceeds.
    * Execute via :func:`subprocess.run` in the repo root with a
      bounded timeout.  Stderr is appended to stdout so the
      expanded prompt carries the full picture.
    * Stdout is truncated to :data:`_SHELL_STDOUT_MAX_CHARS` so a
      chatty command doesn't flood the model context; the
      truncation marker is part of the substituted text.
    """
    if permissions is not None:
        decision = evaluate_permissions(
            permissions,
            "run_command",
            {"command": command},
            agent_name=agent_name,
        )
        if decision.outcome is PermissionOutcome.DENY:
            raise CustomCommandError(
                f"!`{command}` refused by permissions policy: {decision.reason}. "
                "Edit .cantrip/permissions.yaml to allow or ask."
            )
        if decision.outcome is PermissionOutcome.ASK:
            if permission_manager is None:
                raise CustomCommandError(
                    f"!`{command}` needs approval but this session has no "
                    "interactive permission surface; update "
                    ".cantrip/permissions.yaml."
                )
            approved = await permission_manager.request(
                tool_name="run_command",
                reason=decision.reason,
                arguments={"command": command},
            )
            if not approved:
                raise CustomCommandError(
                    f"!`{command}` refused: user declined the permission prompt."
                )

    cwd = repo_root if repo_root is not None else pathlib.Path.cwd()
    try:
        completed = subprocess.run(
            ["sh", "-c", command],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=_SHELL_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CustomCommandError(
            f"!`{command}` timed out after {_SHELL_TIMEOUT_SECONDS:.0f}s"
        ) from exc
    except (OSError, FileNotFoundError) as exc:
        raise CustomCommandError(f"!`{command}` failed to launch: {exc}") from exc

    combined = completed.stdout
    if completed.stderr:
        # Always label stderr so the LLM sees it as diagnostic output
        # rather than interpreting it as the main response.
        combined = (
            f"{combined}\n[stderr]\n{completed.stderr}"
            if combined
            else f"[stderr]\n{completed.stderr}"
        )
    if completed.returncode != 0:
        combined = f"[exit {completed.returncode}]\n{combined}"
    if len(combined) > _SHELL_STDOUT_MAX_CHARS:
        omitted = len(combined) - _SHELL_STDOUT_MAX_CHARS
        combined = (
            combined[:_SHELL_STDOUT_MAX_CHARS] + f"\n[... truncated {omitted} characters ...]"
        )
    return combined.rstrip()


async def expand(
    command: CustomCommand,
    args: str,
    *,
    repo_root: pathlib.Path | None = None,
    permissions: PermissionRuleset | None = None,
    permission_manager: PermissionManager | None = None,
) -> str:
    """Expand a custom command body into the final prompt text.

    Evaluation order is deliberate:

    1. ``$ARGUMENTS`` / ``$N`` — plain string substitution, zero
       side effects, always runs first so subsequent ``@`` and
       ``!`` references can themselves carry arguments.
    2. ``@path`` — file content interpolation, gated on path safety
       (no absolute paths, no traversal out of the repo root).
    3. ``!`cmd` `` — shell command expansion, gated through the
       Phase 68.2 permission policy.  Async because the ``ask`` path
       waits on a :class:`PermissionManager` future.

    A failed expansion raises :class:`CustomCommandError` naming
    the offending reference — the dispatcher renders it as the
    slash command's error output.
    """
    text = _expand_arguments(command.body, args)

    def _file_sub(match: re.Match[str]) -> str:
        return _resolve_file_reference(match.group(1), repo_root=repo_root)

    text = _FILE_REF_RE.sub(_file_sub, text)

    # Shell substitutions are async because the permission gate may
    # park on a future.  ``re.sub`` itself is sync, so we walk the
    # matches, expand them one by one, and stitch the result.
    parts: list[str] = []
    last_end = 0
    for match in _SHELL_REF_RE.finditer(text):
        parts.append(text[last_end : match.start()])
        replacement = await _resolve_shell_reference(
            match.group(1),
            repo_root=repo_root,
            permissions=permissions,
            permission_manager=permission_manager,
            agent_name=command.agent,
        )
        parts.append(replacement)
        last_end = match.end()
    parts.append(text[last_end:])
    return "".join(parts)


# ---------------------------------------------------------------------------
# Registry (built at agent construction, queried by the dispatcher)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class CustomCommandRegistry:
    """Immutable view over the loaded commands.

    Wraps the list so surfaces (TUI autocomplete, Web UI, CLI) can
    share a single read-only object without worrying about the
    underlying list mutating underneath them.  A new registry is
    built each time the agent reloads commands.
    """

    commands: tuple[CustomCommand, ...] = ()

    @property
    def verbs(self) -> tuple[str, ...]:
        """Verbs of every loaded command, in catalogue order."""
        return tuple(c.verb for c in self.commands)

    def get(self, verb: str) -> CustomCommand | None:
        """Look up a command by verb; returns ``None`` on miss."""
        for command in self.commands:
            if command.verb == verb:
                return command
        return None

    def to_mapping(self) -> Mapping[str, CustomCommand]:
        """Eager dict view — convenient for hot-path dispatchers."""
        return {command.verb: command for command in self.commands}
