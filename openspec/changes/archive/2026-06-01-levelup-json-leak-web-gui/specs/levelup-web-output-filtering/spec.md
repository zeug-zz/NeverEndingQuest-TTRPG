## ADDED Requirements

### Requirement: Level-up JSON response parsing in web game loop
The web game loop level-up sub-loop (`main.py:8476-8554`) SHALL parse the level-up LLM response as JSON when it starts with `{` and ends with `}`, and extract the `narration` field for display.

#### Scenario: Final JSON response displays narration only
- **WHEN** the level-up LLM returns a JSON response containing `{"narration": "...", "actions": [...]}`
- **THEN** only the `narration` field value SHALL be displayed in the web GUI chat
- **THEN** the raw JSON SHALL NOT appear in the web GUI chat

#### Scenario: Intermediate plain-text response displays as-is
- **WHEN** the level-up LLM returns a plain-text response (not valid JSON)
- **THEN** the full text response SHALL be displayed in the web GUI chat unchanged

#### Scenario: JSON response without narration field
- **WHEN** the level-up LLM returns valid JSON without a `narration` field
- **THEN** the system SHALL display "Level up complete!" as fallback text

#### Scenario: Malformed JSON response
- **WHEN** the level-up LLM returns text that starts with `{` but is not valid JSON
- **THEN** the system SHALL display the raw text as-is (fail-open behavior)

### Requirement: Raw JSON suppression in WebOutputCapture
The level-up web game loop SHALL NOT emit raw JSON action responses through `WebOutputCapture` to the web GUI chat.

#### Scenario: WebOutputCapture receives narration only
- **WHEN** the level-up finalization response is parsed successfully
- **THEN** `WebOutputCapture` SHALL receive only the extracted narration text
- **THEN** the raw JSON string SHALL NOT be written to `sys.stdout` or `WebOutputCapture`

### Requirement: Terminal level-up path parity
The terminal-only level-up path (`main.py:6764-6907`) SHALL use the same JSON parsing and narration extraction logic as the web game loop path.

#### Scenario: Terminal path displays narration only
- **WHEN** the level-up LLM returns a JSON response in terminal mode
- **THEN** only the `narration` field value SHALL be printed to the terminal
