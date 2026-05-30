## ADDED Requirements

### Requirement: @CAMPAIGN_MILESTONES_USAGE directive in compressed prompt
The system SHALL add a `@CAMPAIGN_MILESTONES_USAGE` directive to `prompts/system_prompt_compressed.txt` near the `@CHRONICLE_RULES` section.

#### Scenario: Directive presence
- **WHEN** `prompts/system_prompt_compressed.txt` is loaded
- **THEN** the file SHALL contain a `@CAMPAIGN_MILESTONES_USAGE={...}` block

### Requirement: Milestone authority statement
The directive SHALL state that milestone events are authoritative and WIN over conversation history contradictions.

#### Scenario: Authority hierarchy
- **WHEN** the narrator receives both milestone timeline and conversation history
- **AND** conversation history contradicts a milestone event
- **THEN** the narrator SHALL treat the milestone as authoritative

#### Scenario: Directive content
- **WHEN** the `@CAMPAIGN_MILESTONES_USAGE` directive is present
- **THEN** it SHALL include:
  - `recognition`: "A @CAMPAIGN_MILESTONES block in conversation contains authoritative campaign timeline."
  - `rule`: "These events HAPPENED. When characters or narration refer to past campaign events, use this timeline as the authoritative record."
  - `priority`: "Same authority as DM Note for historical events. If conversation history contradicts milestone timeline, milestone timeline WINS."

### Requirement: Uncompressed prompt parity
The system SHALL add the same `@CAMPAIGN_MILESTONES_USAGE` directive to `prompts/system_prompt.txt` (uncompressed variant).

#### Scenario: Both prompts updated
- **WHEN** both `system_prompt_compressed.txt` and `system_prompt.txt` are loaded
- **THEN** both SHALL contain identical `@CAMPAIGN_MILESTONES_USAGE` directive content

### Requirement: ASCII-only directive text
The directive text SHALL contain only ASCII characters.

#### Scenario: No Unicode in directive
- **WHEN** the `@CAMPAIGN_MILESTONES_USAGE` directive is written
- **THEN** all characters SHALL be ASCII (no smart quotes, em-dashes, or special symbols)

### Requirement: Directive placement
The directive SHALL be placed near `@CHRONICLE_RULES` for logical grouping of history-related guidance.

#### Scenario: Proximity to chronicle rules
- **WHEN** the system prompt is structured with multiple directives
- **THEN** `@CAMPAIGN_MILESTONES_USAGE` SHALL appear within 20 lines of `@CHRONICLE_RULES`
