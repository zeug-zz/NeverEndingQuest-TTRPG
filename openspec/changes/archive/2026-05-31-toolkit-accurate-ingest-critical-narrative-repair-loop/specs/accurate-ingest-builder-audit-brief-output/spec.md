## MODIFIED Requirements

### Requirement: Builder Brief Includes Critical Narrative Repair Section

Builder audit briefs SHALL include a critical narrative repair section when source-fidelity blockers identify missing critical actors, puzzles, or plot beats.

#### Scenario: Brief generated for Numillian blocker
- **GIVEN** source-fidelity reports missing Kobe or `skull_riddle`
- **WHEN** `builder_brief.json` and markdown prompt context are generated
- **THEN** they SHALL include missing critical item summaries
- **AND** source excerpts or evidence refs sufficient for Builder repair.

## SHOULD Guidance

Keep the markdown context readable for a Builder model while retaining machine-readable JSON fields for tests.
