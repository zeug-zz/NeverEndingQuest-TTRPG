## MODIFIED Requirements

### Requirement: Source Contract Distinguishes Critical Prose Actors And Puzzle Components

Generator source contracts SHALL carry critical prose actors and puzzle components distinctly from table-derived NPCs.

#### Scenario: Source contains table NPCs, Kobe, and skull components
- **GIVEN** the source has an NPC table
- **AND** Kobe appears only in critical final trial prose
- **AND** Red, Blue, and Yellow Skull appear as puzzle components
- **WHEN** builder source context is assembled
- **THEN** Kobe SHALL be included as a critical prose actor
- **AND** skulls SHALL be attached to `skull_riddle` puzzle context rather than treated only as NPCs.

## SHOULD Guidance

Prefer compact labels such as `CRITICAL_ACTORS:` and `PUZZLES:` in prompt context so Builder instructions stay bounded but explicit.
