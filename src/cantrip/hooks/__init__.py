"""User-configurable hooks (Phase 46.1+).

Users can declare small scripts in ``~/.config/cantrip/hooks.yaml``
(user scope) or ``./cantrip.hooks.yaml`` (repo scope) that run at
lifecycle points — before/after every tool call, before/after
compaction, around subagent invocations.  Hooks run as subprocesses
with a JSON payload on stdin so they can observe (and eventually
influence) agent behaviour without forking Cantrip.

The config pair mirrors the MCP config convention
(``cantrip.mcp.yaml``) so users don't have to learn two layouts.

Schema
------

.. code-block:: yaml

    hooks:
      - name: log-git-push
        event: pre_tool_call
        if: tool == "git_push"
        run: logger -t cantrip "pushing $(jq -r .arguments.branch)"
        timeout: 5
        continue_on_error: true

Each hook declares:

* ``name`` (string, optional) — a label used in logs and the future
  ``/hooks`` slash command.  Defaults to the first word of ``run``.
* ``event`` (string, required) — one of the :class:`HookEvent` values.
  (Deliberately not called ``on`` — unquoted ``on:`` in YAML 1.1
  parses as a boolean ``True`` key, which would silently break
  user configs.)
* ``run`` (string, required) — the command line to invoke.  Passed to
  ``/bin/sh -c`` so shell features (pipes, redirection, env-var
  expansion) work out of the box.
* ``if`` (string, optional) — a boolean expression evaluated against
  the event payload before the hook runs; the hook fires only when
  the expression is truthy.  Supports comparisons (``==``, ``!=``,
  ``<``, ``<=``, ``>``, ``>=``, ``in``, ``not in``), boolean
  combinators (``and`` / ``or`` / ``not``), nested field access
  (``task.category``, ``arguments.branch``), and string / number /
  list literals.  Missing payload fields evaluate to a sentinel so
  a filter that references an absent field simply skips the hook
  rather than raising.  Python function calls, imports, lambdas
  etc. are rejected at config-load time.
* ``timeout`` (number, optional) — seconds before the hook is killed.
  Defaults to 30 s — long enough for a ``curl`` or a ``jq`` pipeline,
  short enough that a misbehaving hook can't freeze the agent.
* ``continue_on_error`` (bool, optional, default ``true``) — when
  ``false``, a hook that exits non-zero logs at ``WARNING`` rather
  than ``DEBUG``.  (True veto semantics — where a pre-hook refuses
  the operation — land in Phase 46.4.)

Repo scope overrides user scope on name collision: a ``.yaml`` in
the charm directory is authoritative for the charm, and the user
config acts as a fallback for every charm the user works on.

Mutation envelope (``pre_tool_call`` only, Phase 46.4b)
-------------------------------------------------------

A ``pre_tool_call`` hook can rewrite the pending tool arguments by
printing a JSON envelope to **stdout** with the shape::

    {"mutate": {"arguments": {"branch": "main", "token": "[REDACTED]"}}}

The ``mutate.arguments`` object — if present and an object — wholly
replaces the tool's arguments before it runs.  Typical uses:

* strip secrets from a command line before they hit ``run_shell``
* canonicalise a filename a user wrote relative to a worktree
* normalise a branch name pattern before ``git_push``

Rules:

* Only ``pre_tool_call`` events honour the envelope; other events
  parse and discard.
* Hooks run sequentially for one tool call, so a later hook sees the
  previous hook's mutation on stdin and can refine it further.
* A hook that fails (``continue_on_error: false`` + non-zero exit)
  vetoes the tool call; its envelope is ignored because the call
  will not run.
* Non-JSON stdout, or JSON without a ``mutate`` key, is treated as
  a non-mutating log line — existing hooks keep working unchanged.
* Invalid envelope shapes log a warning and are ignored; they do
  not break the tool call.
"""

from __future__ import annotations

# Re-exports.  The redundant ``as`` aliases mark these as intentional
# re-exports for ruff (private symbols are kept available to tests).
from cantrip.hooks.config import _candidate_paths as _candidate_paths
from cantrip.hooks.config import _parse_hook as _parse_hook
from cantrip.hooks.config import _parse_yaml as _parse_yaml
from cantrip.hooks.config import _user_config_path as _user_config_path
from cantrip.hooks.config import load_hooks as load_hooks
from cantrip.hooks.filter import _ALLOWED_AST_NODES as _ALLOWED_AST_NODES
from cantrip.hooks.filter import _MISSING as _MISSING
from cantrip.hooks.filter import _apply_comparison as _apply_comparison
from cantrip.hooks.filter import _eval_node as _eval_node
from cantrip.hooks.filter import _FilterExpr as _FilterExpr
from cantrip.hooks.filter import _Missing as _Missing
from cantrip.hooks.filter import _validate_ast as _validate_ast
from cantrip.hooks.runner import _OPERATOR_UNSET as _OPERATOR_UNSET
from cantrip.hooks.runner import HookRunner as HookRunner
from cantrip.hooks.runner import HookStats as HookStats
from cantrip.hooks.runner import _HookHistory as _HookHistory
from cantrip.hooks.runner import _OperatorUnset as _OperatorUnset
from cantrip.hooks.runner import _parse_mutation_envelope as _parse_mutation_envelope
from cantrip.hooks.runner import _read_git_config as _read_git_config
from cantrip.hooks.runner import _resolve_operator as _resolve_operator
from cantrip.hooks.types import DEFAULT_HOOK_TIMEOUT as DEFAULT_HOOK_TIMEOUT
from cantrip.hooks.types import REPO_CONFIG_FILENAME as REPO_CONFIG_FILENAME
from cantrip.hooks.types import USER_CONFIG_PATH as USER_CONFIG_PATH
from cantrip.hooks.types import HookConfig as HookConfig
from cantrip.hooks.types import HookConfigError as HookConfigError
from cantrip.hooks.types import HookEvent as HookEvent
from cantrip.hooks.types import HookResult as HookResult
from cantrip.hooks.types import HookResultListener as HookResultListener
from cantrip.hooks.types import final_arguments as final_arguments
from cantrip.hooks.types import first_veto as first_veto

__all__ = [
    "DEFAULT_HOOK_TIMEOUT",
    "REPO_CONFIG_FILENAME",
    "USER_CONFIG_PATH",
    "HookConfig",
    "HookConfigError",
    "HookEvent",
    "HookResult",
    "HookResultListener",
    "HookRunner",
    "HookStats",
    "final_arguments",
    "first_veto",
    "load_hooks",
]
