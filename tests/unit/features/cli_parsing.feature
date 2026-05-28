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

  Rule: Explicit subcommands route to their own parser
    Scenario Outline: A named subcommand is preserved, not normalised to run
      Given the command line "<argv>"
      When the CLI arguments are parsed
      Then the selected command is "<command>"

      Examples:
        | argv                       | command           |
        | export-transcript ./charm  | export-transcript |
        | compare ./left ./right     | compare           |
        | audit list                 | audit             |
        | permissions list           | permissions       |

  Rule: Run options bind to the run command
    Scenario: An explicit provider choice is recorded
      Given the command line "--provider claude"
      When the CLI arguments are parsed
      Then the selected command is "run"
      And the "provider" option equals "claude"

    Scenario: The print goal is captured
      Given the command line "--print deploy-postgres"
      When the CLI arguments are parsed
      Then the selected command is "run"
      And the "print_goal" option equals "deploy-postgres"

    Scenario: A custom web port is parsed as an integer
      Given the command line "--web --web-port 9000"
      When the CLI arguments are parsed
      Then the "web" option is enabled
      And the "web_port" option equals "9000"

    Scenario Outline: Boolean run flags toggle on
      Given the command line "<argv>"
      When the CLI arguments are parsed
      Then the selected command is "run"
      And the "<option>" option is enabled

      Examples:
        | argv        | option      |
        | --web       | web         |
        | --yolo      | yolo        |
        | --architect | architect   |
        | --json      | json_output |

  Rule: Export options map onto their parser destinations
    Scenario: A phase and format filter are parsed onto the export command
      Given the command line "export-transcript ./charm --phase build --format markdown"
      When the CLI arguments are parsed
      Then the selected command is "export-transcript"
      And the "filter_phase" option equals "build"
      And the "fmt" option equals "markdown"

    Scenario: A task filter binds to filter_task
      Given the command line "export-transcript ./charm --task scaffold-charm"
      When the CLI arguments are parsed
      Then the "filter_task" option equals "scaffold-charm"
