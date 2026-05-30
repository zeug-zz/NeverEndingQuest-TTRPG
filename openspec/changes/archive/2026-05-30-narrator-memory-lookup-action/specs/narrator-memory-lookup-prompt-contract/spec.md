## ADDED Requirements

### Requirement: @ACTIONS Entry
The compressed system prompt SHALL include `lookupMemory` in the `@ACTIONS` directive.

#### Scenario: lookupMemory in @ACTIONS
- **WHEN** the system prompt is loaded
- **THEN** `@ACTIONS` contains `lookupMemory: Request campaign history for entities when unsure about past events.`

### Requirement: @PARAMS Entry
The compressed system prompt SHALL include `lookupMemory` parameter specification in `@PARAMS`.

#### Scenario: lookupMemory params defined
- **WHEN** the system prompt is loaded
- **THEN** `@PARAMS` contains `lookupMemory` with `entities` (array) and `query` (string) keys

### Requirement: @MEMORY_LOOKUP Directive
The compressed system prompt SHALL include a `@MEMORY_LOOKUP` directive block.

#### Scenario: Directive present with all fields
- **WHEN** the system prompt is loaded
- **THEN** `@MEMORY_LOOKUP` contains `when`, `how`, `format`, `response`, `rule`, and `limit` fields

### Requirement: @EXAMPLES Entry
The compressed system prompt SHALL include a `lookupMemory` example in `@EXAMPLES`.

#### Scenario: Example shows correct JSON format
- **WHEN** the system prompt is loaded
- **THEN** `@EXAMPLES` contains a `lookupMemory` action with `entities` and `query` parameters

### Requirement: Uncompressed Parity
The uncompressed system prompt (`system_prompt.txt`) SHALL contain identical `lookupMemory` additions.

#### Scenario: Uncompressed prompt matches
- **WHEN** both prompts are loaded
- **THEN** `system_prompt.txt` contains the same `lookupMemory` entries in `@ACTIONS`, `@PARAMS`, `@MEMORY_LOOKUP`, and `@EXAMPLES`

### Requirement: Validation Prompt Rule
The compressed validation prompt SHALL include a `lookupMemory` validation rule.

#### Scenario: lookupMemory always valid
- **WHEN** the validation prompt is loaded
- **THEN** it contains `lookupMemory: ALWAYS VALID` with entity name validation guidance

### Requirement: Validation Prompt Uncompressed Parity
The uncompressed validation prompt SHALL contain the same `lookupMemory` validation rule.

#### Scenario: Uncompressed validation matches
- **WHEN** both validation prompts are loaded
- **THEN** `validation_prompt.txt` contains the same `lookupMemory` rule as `validation_prompt_compressed.txt`

### Requirement: ASCII-Only Content
All prompt additions SHALL be ASCII-only (no unicode characters).

#### Scenario: No unicode in prompt additions
- **WHEN** the prompt files are scanned for non-ASCII characters
- **THEN** the `lookupMemory` sections contain zero unicode characters
