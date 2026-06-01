## ADDED Requirements

### Requirement: Critical Prose Actors Are Detected When Missing

Accurate-ingest diagnostics SHALL detect named actors in critical objective or failure-condition prose when those actors are absent from final module NPC/scene surfaces.

#### Scenario: Kobe is missing from Numillian module JSON
- **GIVEN** the source text describes Kobe as the young girl to protect in the final no-win trial
- **AND** final module JSON does not include Kobe in NPC or scene objective surfaces
- **WHEN** critical omission detection runs
- **THEN** it SHALL report Kobe as a critical missing prose actor
- **AND** it SHALL include bounded source excerpts showing why Kobe is critical.

### Requirement: Explicit Trial And Puzzle Structures Are Detected When Missing

Accurate-ingest diagnostics SHALL detect explicit trial, riddle, and puzzle structures when absent from final module plot/puzzle surfaces.

#### Scenario: skull_riddle is missing from Numillian plot data
- **GIVEN** the source text contains The First Trial with skull clues, receptacles, failure mechanics, and a solution table
- **AND** final module JSON does not represent `skull_riddle` as plot or puzzle content
- **WHEN** critical omission detection runs
- **THEN** it SHALL report `skull_riddle` as a critical missing puzzle
- **AND** it SHALL include source excerpts for the riddle, components, solution, and failure consequence.

### Requirement: Puzzle Components Are Not Treated As Complete NPC Preservation

Puzzle components SHALL NOT satisfy puzzle preservation merely because they appear as NPC-like atoms.

#### Scenario: Colored skulls are extracted as NPC-like atoms
- **GIVEN** Red Skull, Blue Skull, and Yellow Skull appear as speaking puzzle components
- **WHEN** source preservation is evaluated
- **THEN** their presence as NPC-like records SHALL NOT count as preserving `skull_riddle`
- **AND** diagnostics SHALL identify the missing puzzle structure.

## SHOULD Guidance

Prefer source excerpts that include surrounding headings and mechanical consequence text so the Builder can reason from the source without receiving the full document.
