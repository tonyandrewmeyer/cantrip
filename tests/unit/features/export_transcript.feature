Feature: Exporting a recorded transcript
  Cantrip can turn a saved session into shareable transcript files.

  Rule: Recorded sessions can be exported in supported formats
    Scenario Outline: Exporting a session with the default filename
      Given a charm project with a recorded session
      When I export the transcript as "<format>"
      Then the export succeeds
      And the file "<filename>" is created
      And the file "<filename>" contains "<snippet>"

      Examples:
        | format   | filename         | snippet               |
        | html     | transcript.html  | cli-test-charm        |
        | markdown | transcript.md    | # Cantrip Transcript  |
        | jsonl    | transcript.jsonl | "type": "message"     |

    Scenario: Exporting to a custom output file
      Given a charm project with a recorded session
      When I export the transcript as "markdown" to "custom-session.md"
      Then the export succeeds
      And the file "custom-session.md" is created
      And the file "custom-session.md" contains "cli-test-charm"

  Rule: Missing session data is reported clearly
    Scenario: Exporting without a .cantrip database fails
      Given a charm project without session data
      When I export the transcript as "html"
      Then the export fails
      And the export output contains "Error: no .cantrip file found"
