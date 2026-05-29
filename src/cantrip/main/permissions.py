"""``cantrip permissions {test,list}`` handlers."""

from __future__ import annotations

import argparse
import pathlib


def _permissions_test(args: argparse.Namespace) -> int:
    """Evaluate one hypothetical tool call against the active ruleset.

    Mirrors the runtime gate (:func:`cantrip.agent.safety.permissions.evaluate`)
    so the verdict the user sees here is the one the agent will see at
    call time.  Useful while authoring ``permissions.yaml``: try
    ``cantrip permissions test run_command --command 'rm -rf /tmp/x'``
    and see whether the built-in ``rm -rf *`` deny still fires after
    your local override.
    """
    from cantrip.agent.safety import permissions as perms

    ruleset = _load_permissions_for_cli(args)

    arguments: dict[str, object] = {}
    if args.bash_command is not None:
        arguments["command"] = args.bash_command
    if args.path_arg is not None:
        arguments["path"] = args.path_arg

    decision = perms.evaluate(
        ruleset,
        args.tool,
        arguments,
        agent_name=args.agent_name,
    )

    print(f"Tool:    {args.tool}")
    if args.bash_command is not None:
        print(f"Command: {args.bash_command}")
    if args.path_arg is not None:
        print(f"Path:    {args.path_arg}")
    if args.agent_name is not None:
        print(f"Agent:   {args.agent_name}")
    print(f"Outcome: {decision.outcome.value.upper()}")
    print(f"Reason:  {decision.reason}")
    if decision.matched_rule is not None:
        rule = decision.matched_rule
        print(f"Rule:    {rule.source} → {rule.pattern!r} ⇒ {rule.outcome.value}")
    else:
        print("Rule:    (no rule matched; default allow)")

    if args.show_rules:
        print()
        _print_ruleset(ruleset)
    return 0


def _permissions_list(args: argparse.Namespace) -> int:
    """Print every loaded permission rule grouped by section and source."""
    ruleset = _load_permissions_for_cli(args)
    _print_ruleset(ruleset)
    return 0


def _load_permissions_for_cli(args: argparse.Namespace) -> object:
    """Shared discovery for the ``permissions`` subcommands.

    Honours ``--charm-path`` / ``--user-config`` / ``--no-builtin`` so
    the CLI can probe a config without standing up the full agent.
    """
    from cantrip.agent.safety import permissions as perms

    charm_path: pathlib.Path | None = args.charm_path or pathlib.Path.cwd()
    return perms.discover_permissions(
        charm_path=charm_path,
        user_config_dir=args.user_config_dir,
        include_builtin=not args.no_builtin,
    )


def _print_ruleset(ruleset: object) -> None:
    """Render a :class:`PermissionRuleset` as a grouped, source-attributed list."""
    from cantrip.agent.safety import permissions as perms

    assert isinstance(ruleset, perms.PermissionRuleset)
    sections: tuple[tuple[str, tuple[perms.PermissionRule, ...]], ...] = (
        ("tools", ruleset.tools),
        ("bash", ruleset.bash),
        ("paths", ruleset.paths),
    )
    any_rule = any(rules for _, rules in sections) or bool(ruleset.agents)
    if not any_rule:
        print("No permission rules loaded.")
        return

    print(f"Loaded ruleset: {ruleset.name}")
    for section_name, rules in sections:
        if not rules:
            continue
        print(f"  [{section_name}]")
        for rule in rules:
            print(f"    {rule.pattern!r:<32} ⇒ {rule.outcome.value:<5}  ({rule.source})")
    if ruleset.agents:
        for agent_name in sorted(ruleset.agents):
            overlay = ruleset.agents[agent_name]
            print(f"  [agents:{agent_name}]")
            for section_name, rules in (
                ("tools", overlay.tools),
                ("bash", overlay.bash),
                ("paths", overlay.paths),
            ):
                for rule in rules:
                    print(
                        f"    {section_name}: {rule.pattern!r:<24} "
                        f"⇒ {rule.outcome.value:<5}  ({rule.source})"
                    )
    if ruleset.bash_tools != perms.DEFAULT_BASH_TOOLS:
        names = ", ".join(sorted(ruleset.bash_tools))
        print(f"  bash_tools override: {{{names}}}")
