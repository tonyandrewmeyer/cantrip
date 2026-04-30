Feature: CLI command selection
  Cantrip treats bare invocations as the standard run command.

  Rule: Missing subcommands are normalised to run
    Scenario: A flag-only invocation defaults to run
      Given only the "--no-tui" flag was provided
      When the CLI arguments are parsed
      Then the selected command is "run"
      And the "no_tui" option is enabled

    Scenario: A bare project path defaults to run
      Given a bare project path was provided
      When the CLI arguments are parsed
      Then the selected command is "run"
      And the selected path is that project path
